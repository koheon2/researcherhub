"""
OpenAlex S3 스냅샷에서 AI/CS 연구자를 수집하여 DB에 upsert합니다.

필터 조건:
  - topics 중 field = Computer Science (fields/17)
  - cited_by_count >= MIN_CITATIONS
  - works_count >= 2

병렬 스트리밍 (N_WORKERS개 동시), 진행상황 저장 (재시작 가능)

Usage:
    cd backend
    .venv/bin/python -m scripts.sync_researchers_from_s3 [--dry-run] [--workers 4] [--min-citations 5]
"""
import argparse
import asyncio
import gzip
import json
import logging
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/sync_researchers.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────────────────────────────
S3_MANIFEST   = "s3://openalex/data/authors/manifest"
PROGRESS_FILE = Path(__file__).resolve().parent.parent / "data" / "sync_progress.json"
CS_FIELD_ID   = "/fields/17"

SUBFIELD_MAP = {
    "Artificial Intelligence":                   "AI",
    "Computer Vision and Pattern Recognition":   "Computer Vision",
    "Computer Networks and Communications":      "Networks",
    "Computational Theory and Mathematics":      "Theory & Math",
    "Information Systems":                       "Information Systems",
    "Human-Computer Interaction":                "HCI",
    "Signal Processing":                         "Signal Processing",
    "Hardware and Architecture":                 "Hardware",
    "Software":                                  "Theory & Math",
    "Computer Graphics and Computer-Aided Design": "Computer Vision",
    "Computer Science Applications":             "AI",
}

# ── 진행상황 저장/로드 ──────────────────────────────────────────────────────────
def load_progress() -> set[str]:
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()).get("done", []))
    return set()

def save_progress(done: set[str]):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps({"done": sorted(done)}, indent=2))

# ── S3 스트리밍 ────────────────────────────────────────────────────────────────
def stream_authors(s3_url: str) -> Iterator[dict]:
    proc = subprocess.Popen(
        ["aws", "s3", "cp", s3_url, "-", "--no-sign-request",
         "--cli-read-timeout", "60", "--cli-connect-timeout", "10"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        with gzip.open(proc.stdout, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
    except EOFError:
        logger.warning(f"[{s3_url.split('/')[-1]}] 연결 끊김 — 부분 데이터로 처리 계속")
    finally:
        proc.kill()
        proc.wait()

# ── 연구자 필터 + 변환 ─────────────────────────────────────────────────────────
def is_cs_researcher(author: dict, min_citations: int) -> bool:
    if (author.get("cited_by_count") or 0) < min_citations:
        return False
    if (author.get("works_count") or 0) < 2:
        return False
    topics = author.get("topics") or []
    return any(CS_FIELD_ID in (t.get("field") or {}).get("id", "") for t in topics)

def classify_field(author: dict) -> str:
    topics = author.get("topics") or []
    for t in topics:
        if CS_FIELD_ID not in (t.get("field") or {}).get("id", ""):
            continue
        sf = (t.get("subfield") or {}).get("display_name", "")
        if sf in SUBFIELD_MAP:
            return SUBFIELD_MAP[sf]
    return "AI"

def extract_researcher(author: dict) -> dict:
    insts = author.get("last_known_institutions") or []
    inst  = insts[0] if insts else {}
    topics = author.get("topics") or []
    topic_ids = [t["id"].split("/")[-1] for t in topics[:15] if t.get("id")]

    # recent_papers: counts_by_year에서 최근 2년
    now_year = 2026
    counts = {c["year"]: c["works_count"] for c in (author.get("counts_by_year") or [])}
    recent = counts.get(now_year - 1, 0) + counts.get(now_year - 2, 0)

    inst_id = inst.get("id", "").split("/")[-1] if inst.get("id") else None  # "I12345"

    return {
        "id":             author["id"].split("/")[-1],
        "name":           author.get("display_name", ""),
        "institution":    inst.get("display_name"),
        "institution_id": inst_id,
        "country":        inst.get("country_code"),
        "citations":      author.get("cited_by_count") or 0,
        "h_index":        (author.get("summary_stats") or {}).get("h_index") or 0,
        "works_count":    author.get("works_count") or 0,
        "recent_papers":  recent,
        "field":          classify_field(author),
        "topics":         topic_ids,
        "openalex_url":   author.get("id"),
    }

# ── DB upsert ────────────────────────────────────────────────────────────────
UPSERT_SQL = text("""
INSERT INTO researchers
    (id, name, institution, institution_id, country, citations, h_index, works_count,
     recent_papers, field, topics, openalex_url)
VALUES
    (:id, :name, :institution, :institution_id, :country, :citations, :h_index, :works_count,
     :recent_papers, :field, CAST(:topics AS json), :openalex_url)
ON CONFLICT (id) DO UPDATE SET
    name           = EXCLUDED.name,
    institution    = COALESCE(EXCLUDED.institution,    researchers.institution),
    institution_id = COALESCE(EXCLUDED.institution_id, researchers.institution_id),
    country        = COALESCE(EXCLUDED.country,        researchers.country),
    citations      = EXCLUDED.citations,
    h_index        = EXCLUDED.h_index,
    works_count    = EXCLUDED.works_count,
    recent_papers  = EXCLUDED.recent_papers,
    field          = EXCLUDED.field,
    topics        = COALESCE(EXCLUDED.topics,       researchers.topics),
    openalex_url  = COALESCE(EXCLUDED.openalex_url, researchers.openalex_url)
""")

async def upsert_batch(batch: list[dict]) -> int:
    async with AsyncSessionLocal() as db:
        for row in batch:
            row["topics"] = json.dumps(row["topics"])
        await db.execute(UPSERT_SQL, batch)
        await db.commit()
    return len(batch)

# ── 파일 처리 ─────────────────────────────────────────────────────────────────
def collect_file_sync(s3_url: str, min_citations: int) -> dict:
    """동기 버전 — executor에서 실행. CS 연구자 목록만 반환 (upsert 없음)."""
    file_name = "/".join(s3_url.split("/")[-2:])
    t0 = time.time()
    researchers, total = [], 0

    for author in stream_authors(s3_url):
        total += 1
        if is_cs_researcher(author, min_citations):
            researchers.append(extract_researcher(author))

    elapsed = time.time() - t0
    kept = len(researchers)
    logger.info(
        f"[{file_name}] {total:,} → {kept:,} CS ({kept/max(total,1)*100:.1f}%) "
        f"in {elapsed:.0f}s"
    )
    return {"url": s3_url, "total": total, "kept": kept, "researchers": researchers}


async def process_file(
    s3_url: str,
    min_citations: int,
    dry_run: bool,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, collect_file_sync, s3_url, min_citations
        )
        if not dry_run and result["researchers"]:
            batch = result["researchers"]
            for i in range(0, len(batch), 500):
                await upsert_batch(batch[i:i+500])
        result.pop("researchers")  # 메모리 해제
        return result

# ── 메인 ──────────────────────────────────────────────────────────────────────
async def main(args):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # manifest 로드
    logger.info("Fetching manifest...")
    result = subprocess.run(
        ["aws", "s3", "cp", S3_MANIFEST, "-", "--no-sign-request"],
        capture_output=True, check=True,
    )
    manifest = json.loads(result.stdout)
    all_urls = [e["url"] for e in manifest["entries"]]
    logger.info(f"Total files: {len(all_urls)}")

    # 이미 처리된 파일 건너뜀
    done = load_progress()
    pending = [u for u in all_urls if u not in done]
    logger.info(f"Already done: {len(done)}, Pending: {len(pending)}")

    if not pending:
        logger.info("All files processed.")
        return

    semaphore = asyncio.Semaphore(args.workers)
    grand_total = grand_kept = 0
    t_start = time.time()
    completed = 0

    # 배치 단위로 병렬 실행
    batch_size = args.workers
    for batch_start in range(0, len(pending), batch_size):
        batch_urls = pending[batch_start : batch_start + batch_size]
        tasks = [process_file(u, args.min_citations, args.dry_run, semaphore) for u in batch_urls]
        results = await asyncio.gather(*tasks)

        for result in results:
            grand_total += result["total"]
            grand_kept  += result["kept"]
            done.add(result["url"])
            completed += 1

        if not args.dry_run:
            save_progress(done)

        elapsed = time.time() - t_start
        rate = completed / elapsed if elapsed > 0 else 1
        remaining = (len(pending) - completed) / rate
        logger.info(
            f"Progress: {completed}/{len(pending)} files | "
            f"{grand_kept:,} CS researchers so far | "
            f"ETA: {remaining/60:.0f}min"
        )

    logger.info(
        f"\n=== DONE ===\n"
        f"Files processed : {len(pending)}\n"
        f"Total authors   : {grand_total:,}\n"
        f"CS researchers  : {grand_kept:,}\n"
        f"Elapsed         : {(time.time()-t_start)/60:.1f} min\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",       action="store_true", help="DB 저장 없이 카운트만")
    parser.add_argument("--workers",       type=int, default=3, help="동시 파일 처리 수 (default: 3)")
    parser.add_argument("--min-citations", type=int, default=5, help="최소 인용수 (default: 5)")
    args = parser.parse_args()

    logger.info(
        f"Starting sync | workers={args.workers} "
        f"min_citations={args.min_citations} dry_run={args.dry_run}"
    )
    asyncio.run(main(args))
