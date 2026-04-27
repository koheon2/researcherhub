#!/usr/bin/env python3
from __future__ import annotations
"""
collect_papers.py - OpenAlex S3 스냅샷에서 CS 분야 논문을 수집

EC2에서 실행되며, OpenAlex public S3 bucket에서 works 데이터를 스트리밍으로 읽어
CS 논문만 필터링하여 CSV.gz로 저장한 뒤 결과 S3 버킷에 업로드한다.

사용법:
    python3 collect_papers.py --bucket RESULTS_BUCKET
    python3 collect_papers.py --bucket RESULTS_BUCKET --dry-run        # 파일 5개만 처리
    python3 collect_papers.py --bucket RESULTS_BUCKET --start-from 100 # 100번째 파일부터 재개
"""

import argparse
import csv
import gc
import gzip
import io
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import boto3
from botocore import UNSIGNED
from botocore.config import Config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OPENALEX_BUCKET = "openalex"
MANIFEST_PREFIX = "data/works/manifest"
CS_FIELD = "Computer Science"
PROGRESS_INTERVAL = 100  # 진행 상황 출력 간격 (파일 수)
CHUNK_SIZE = 100          # 한 번에 제출할 파일 수 (메모리 제한)

# ---------------------------------------------------------------------------
# S3 clients
# ---------------------------------------------------------------------------
openalex_s3 = boto3.client(
    "s3",
    region_name="us-east-1",
    config=Config(signature_version=UNSIGNED),
)


def get_results_s3():
    return boto3.client("s3", region_name="us-east-1")


# ---------------------------------------------------------------------------
# Paper extraction helpers
# ---------------------------------------------------------------------------
def decode_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    try:
        max_pos = max(pos for positions in inverted_index.values() for pos in positions)
        words = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for pos in positions:
                if pos <= max_pos:
                    words[pos] = word
        return " ".join(w for w in words if w)
    except Exception:
        return ""


def extract_paper(work: dict) -> dict | None:
    primary_topic = work.get("primary_topic") or {}
    field = primary_topic.get("field", {}).get("display_name", "")
    if field != CS_FIELD:
        return None

    wid = (work.get("id") or "").split("/")[-1]
    if not wid:
        return None

    return {
        "id": wid,
        "title": (work.get("title") or "")[:1000],
        "doi": (work.get("doi") or "").replace("https://doi.org/", "")[:200],
        "year": work.get("publication_year"),
        "citations": work.get("cited_by_count", 0),
        "fwci": work.get("fwci"),
        "subfield": primary_topic.get("subfield", {}).get("display_name", "")[:100],
        "topic": primary_topic.get("display_name", "")[:200],
        "abstract": decode_abstract(work.get("abstract_inverted_index")),
        "open_access": (work.get("open_access") or {}).get("is_oa", False),
        "type": (work.get("type") or "")[:50],
    }


def extract_authors(work: dict) -> list[dict]:
    wid = (work.get("id") or "").split("/")[-1]
    authors = []
    for i, auth in enumerate(work.get("authorships", [])):
        author = auth.get("author") or {}
        aid = (author.get("id") or "").split("/")[-1]
        if not aid:
            continue
        insts = auth.get("institutions") or []
        inst = insts[0] if insts else {}
        authors.append({
            "paper_id": wid,
            "author_id": aid,
            "author_name": (author.get("display_name") or "")[:200],
            "position": i,
            "institution_name": (inst.get("display_name") or "")[:300],
            "country": (inst.get("country_code") or "")[:5],
        })
    return authors


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------
def get_entry_keys() -> list[str]:
    resp = openalex_s3.get_object(Bucket=OPENALEX_BUCKET, Key=MANIFEST_PREFIX)
    manifest = json.loads(resp["Body"].read().decode("utf-8"))
    entry_keys = []
    for entry in manifest.get("entries", []):
        url = entry.get("url", "")
        key = url.replace(f"s3://{OPENALEX_BUCKET}/", "")
        if key:
            entry_keys.append(key)
    return entry_keys


# ---------------------------------------------------------------------------
# Single file processor
# ---------------------------------------------------------------------------
def process_entry(key: str) -> tuple[list[dict], list[dict], int]:
    papers = []
    authors = []
    total_works = 0

    try:
        resp = openalex_s3.get_object(Bucket=OPENALEX_BUCKET, Key=key)
        raw_stream = resp["Body"]

        with gzip.GzipFile(fileobj=raw_stream) as gz:
            reader = io.TextIOWrapper(gz, encoding="utf-8")
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                total_works += 1
                try:
                    work = json.loads(line)
                except json.JSONDecodeError:
                    continue

                paper = extract_paper(work)
                if paper is not None:
                    papers.append(paper)
                    authors.extend(extract_authors(work))
    except Exception as e:
        print(f"  [ERROR] {key}: {e}", file=sys.stderr)

    return papers, authors, total_works


# ---------------------------------------------------------------------------
# CSV writers (thread-safe, gzip compressed to save disk space)
# ---------------------------------------------------------------------------
PAPER_FIELDS = [
    "id", "title", "doi", "year", "citations", "fwci",
    "subfield", "topic", "abstract", "open_access", "type",
]
AUTHOR_FIELDS = [
    "paper_id", "author_id", "author_name", "position",
    "institution_name", "country",
]


class CSVAccumulator:
    """Thread-safe gzip CSV writer."""

    def __init__(self, tmpdir: str):
        self.tmpdir = tmpdir
        self.papers_path = os.path.join(tmpdir, "papers.csv.gz")
        self.authors_path = os.path.join(tmpdir, "paper_authors.csv.gz")
        self.lock = Lock()
        self.cs_count = 0
        self.total_works = 0

        with gzip.open(self.papers_path, "wt", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=PAPER_FIELDS).writeheader()
        with gzip.open(self.authors_path, "wt", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=AUTHOR_FIELDS).writeheader()

    def append(self, papers: list[dict], authors: list[dict], works_count: int):
        with self.lock:
            self.cs_count += len(papers)
            self.total_works += works_count

            if papers:
                with gzip.open(self.papers_path, "at", encoding="utf-8", newline="") as f:
                    csv.DictWriter(f, fieldnames=PAPER_FIELDS).writerows(papers)

            if authors:
                with gzip.open(self.authors_path, "at", encoding="utf-8", newline="") as f:
                    csv.DictWriter(f, fieldnames=AUTHOR_FIELDS).writerows(authors)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_pipeline(bucket: str, dry_run: bool = False, start_from: int = 0):
    start_time = time.time()

    print("=== OpenAlex CS Papers Collection Pipeline ===")
    print(f"Results bucket: {bucket}")
    print(f"Dry run: {dry_run}")
    print(f"Start from: {start_from}")
    print("")

    # 1. Manifest
    print("[1/4] Manifest 파일 목록 조회...")
    entry_keys = get_entry_keys()
    total_entries = len(entry_keys)
    print(f"  -> 총 {total_entries:,}개 데이터 파일 발견")

    if start_from > 0:
        entry_keys = entry_keys[start_from:]
        print(f"  -> {start_from}번째부터 재개 ({len(entry_keys):,}개 남음)")

    if dry_run:
        entry_keys = entry_keys[:5]
        print(f"  -> Dry run: 5개 파일만 처리")

    actual_total = len(entry_keys)

    # 2. 청크 단위 병렬 처리 (메모리 제한)
    print(f"\n[2/4] 데이터 수집 시작 (max_workers=8, chunk={CHUNK_SIZE})...")
    with tempfile.TemporaryDirectory() as tmpdir:
        accumulator = CSVAccumulator(tmpdir)
        done_count = 0

        for chunk_start in range(0, actual_total, CHUNK_SIZE):
            chunk = entry_keys[chunk_start : chunk_start + CHUNK_SIZE]

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {executor.submit(process_entry, key): key for key in chunk}

                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        papers, authors, works_count = future.result()
                        accumulator.append(papers, authors, works_count)
                    except Exception as e:
                        print(f"  [ERROR] {key}: {e}", file=sys.stderr)

                    done_count += 1
                    if done_count % PROGRESS_INTERVAL == 0 or done_count == actual_total:
                        elapsed = time.time() - start_time
                        rate = done_count / elapsed if elapsed > 0 else 0
                        eta = (actual_total - done_count) / rate if rate > 0 else 0
                        print(
                            f"  [{done_count}/{actual_total}] "
                            f"{accumulator.cs_count:,} CS papers found | "
                            f"{accumulator.total_works:,} total works scanned | "
                            f"ETA: {eta/60:.0f}min"
                        )

            # 청크 완료 후 메모리 해제
            gc.collect()

        # 3. S3 업로드 (이미 gzip)
        print(f"\n[3/4] S3 업로드...")
        results_s3 = get_results_s3()

        for s3_name, src_path in [
            ("papers.csv.gz", accumulator.papers_path),
            ("paper_authors.csv.gz", accumulator.authors_path),
        ]:
            file_size = os.path.getsize(src_path) / (1024 * 1024)
            print(f"  -> {s3_name} ({file_size:.1f} MB) 업로드 중...")
            results_s3.upload_file(src_path, bucket, s3_name)
            print(f"     완료")

        # 4. 완료 신호
        print(f"\n[4/4] 완료 신호 전송...")
        elapsed_total = time.time() - start_time
        done_content = (
            f"Collection completed at {time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"CS papers: {accumulator.cs_count:,}\n"
            f"Total works scanned: {accumulator.total_works:,}\n"
            f"Elapsed: {elapsed_total/3600:.1f} hours\n"
            f"Files processed: {done_count}/{actual_total}\n"
            f"Start from: {start_from}\n"
        )
        results_s3.put_object(Bucket=bucket, Key="done.txt", Body=done_content.encode())

    print("")
    print("========================================")
    print(f"  수집 완료!")
    print(f"  CS 논문: {accumulator.cs_count:,}")
    print(f"  총 스캔: {accumulator.total_works:,}")
    print(f"  소요 시간: {elapsed_total/3600:.1f}시간")
    print(f"  결과: s3://{bucket}/")
    print("========================================")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--start-from", type=int, default=0)
    args = parser.parse_args()

    run_pipeline(bucket=args.bucket, dry_run=args.dry_run, start_from=args.start_from)


if __name__ == "__main__":
    main()
