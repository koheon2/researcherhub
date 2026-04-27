"""
OpenAlex S3 스냅샷에서 topics 전체를 수집하여
1. backend/data/topic_names.json 갱신
2. DB에 topic 정보 저장 (선택, 현재는 json만)

Usage:
    cd backend
    .venv/bin/python -m scripts.sync_topics_from_s3
"""
import gzip
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "topic_names.json"
S3_MANIFEST = "s3://openalex/data/topics/manifest"


def fetch_manifest() -> list[str]:
    """manifest에서 파일 URL 목록 반환."""
    result = subprocess.run(
        ["aws", "s3", "cp", S3_MANIFEST, "-", "--no-sign-request"],
        capture_output=True, check=True,
    )
    manifest = json.loads(result.stdout)
    return [e["url"] for e in manifest["entries"]]


def stream_topics_from_s3(s3_url: str):
    """S3 gz 파일을 스트리밍으로 읽어 topic dict 생성."""
    proc = subprocess.Popen(
        ["aws", "s3", "cp", s3_url, "-", "--no-sign-request"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    with gzip.open(proc.stdout, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
    proc.wait()


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching topics manifest from S3...")
    urls = fetch_manifest()
    logger.info(f"Found {len(urls)} partition files")

    all_topics: dict[str, dict] = {}  # id → {name, subfield, field, description, keywords}

    for url in urls:
        logger.info(f"Processing {url.split('/')[-2]}/{url.split('/')[-1]} ...")
        for t in stream_topics_from_s3(url):
            tid = t["id"].split("/")[-1]
            all_topics[tid] = {
                "name":        t.get("display_name", tid),
                "description": t.get("description", ""),
                "keywords":    t.get("keywords", [])[:8],
                "subfield":    (t.get("subfield") or {}).get("display_name", ""),
                "field":       (t.get("field") or {}).get("display_name", ""),
                "domain":      (t.get("domain") or {}).get("display_name", ""),
                "field_id":    (t.get("field") or {}).get("id", "").split("/")[-1],
            }

    logger.info(f"Total topics collected: {len(all_topics)}")

    # field 분포
    from collections import Counter
    field_dist = Counter(v["field"] for v in all_topics.values())
    logger.info("Top fields:")
    for f, c in field_dist.most_common(8):
        logger.info(f"  {c:4d}  {f}")

    # topic_names.json: id → display_name (기존 format 유지)
    names_only = {k: v["name"] for k, v in all_topics.items()}
    OUTPUT_PATH.write_text(json.dumps(names_only, ensure_ascii=False, indent=2))
    logger.info(f"Saved {len(names_only)} topic names → {OUTPUT_PATH}")

    # 전체 메타데이터도 저장
    full_path = OUTPUT_PATH.parent / "topics_full.json"
    full_path.write_text(json.dumps(all_topics, ensure_ascii=False, indent=2))
    logger.info(f"Saved full topic metadata → {full_path}")

    # CS topics만 별도 저장
    cs_topics = {k: v for k, v in all_topics.items() if v["field_id"] == "17"}
    cs_path = OUTPUT_PATH.parent / "topics_cs.json"
    cs_path.write_text(json.dumps(cs_topics, ensure_ascii=False, indent=2))
    logger.info(f"Saved {len(cs_topics)} CS topics → {cs_path}")


if __name__ == "__main__":
    main()
