#!/bin/bash
# =============================================================================
# import.sh - S3에서 수집된 CS 논문 CSV를 다운로드하고 researcherhub DB에 import
#
# 사용법:
#   ./import.sh BUCKET_NAME
#
# 환경변수:
#   DATABASE_URL - PostgreSQL 연결 URL. 비어 있으면 backend/.env 기준으로 읽음.
# =============================================================================
set -euo pipefail

BUCKET="${1:-}"
if [ -z "$BUCKET" ]; then
    echo "사용법: ./import.sh BUCKET_NAME"
    echo ""
    echo "예시: ./import.sh researcherworld-papers-20260422-120000"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/data"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

ASYNC_DB_URL="${DATABASE_URL:-$(
  cd "${BACKEND_DIR}" &&
  .venv/bin/python - <<'PY'
from app.core.config import settings
print(settings.DATABASE_URL)
PY
)}"
SYNC_DB_URL="${ASYNC_DB_URL/postgresql+asyncpg:/postgresql:}"

mkdir -p "${DATA_DIR}"

echo "=== ResearcherHub Papers Import ==="
echo "Bucket:   ${BUCKET}"
echo "Data dir: ${DATA_DIR}"
echo "DB:       ${SYNC_DB_URL}"
echo ""

# -----------------------------------------------------------
# 1. 완료 확인
# -----------------------------------------------------------
echo "[1/5] 수집 완료 여부 확인..."
if ! aws s3 ls "s3://${BUCKET}/done.txt" > /dev/null 2>&1; then
    echo "  [ERROR] done.txt가 없습니다. 수집이 아직 완료되지 않았을 수 있습니다."
    echo "  확인: aws s3 ls s3://${BUCKET}/"
    exit 1
fi
echo "  -> 수집 완료 확인"
aws s3 cp "s3://${BUCKET}/done.txt" - 2>/dev/null | head -5
echo ""

# -----------------------------------------------------------
# 2. S3에서 다운로드
# -----------------------------------------------------------
echo "[2/5] S3에서 CSV 다운로드..."
aws s3 cp "s3://${BUCKET}/papers.csv.gz" "${DATA_DIR}/papers.csv.gz"
aws s3 cp "s3://${BUCKET}/paper_authors.csv.gz" "${DATA_DIR}/paper_authors.csv.gz"
echo "  -> 다운로드 완료"

# -----------------------------------------------------------
# 3. 압축 해제
# -----------------------------------------------------------
echo "[3/5] 압축 해제..."
gunzip -f "${DATA_DIR}/papers.csv.gz"
gunzip -f "${DATA_DIR}/paper_authors.csv.gz"

PAPERS_COUNT=$(wc -l < "${DATA_DIR}/papers.csv")
AUTHORS_COUNT=$(wc -l < "${DATA_DIR}/paper_authors.csv")
echo "  -> papers.csv: ${PAPERS_COUNT} lines"
echo "  -> paper_authors.csv: ${AUTHORS_COUNT} lines"

# -----------------------------------------------------------
# 4. DB 테이블 생성
# -----------------------------------------------------------
echo "[4/6] Alembic migration 적용..."
(
  cd "${BACKEND_DIR}"
  .venv/bin/alembic -c alembic.ini upgrade head
)
echo "  -> migration 완료"

# -----------------------------------------------------------
# 5. CSV Import
# -----------------------------------------------------------
echo "[5/6] CSV Import..."
psql "${SYNC_DB_URL}" \
  -v papers_file="${DATA_DIR}/papers.csv" \
  -v authors_file="${DATA_DIR}/paper_authors.csv" <<'EOF'
BEGIN;

CREATE TEMP TABLE staging_papers (LIKE papers INCLUDING DEFAULTS);
\COPY staging_papers FROM :'papers_file' CSV HEADER

INSERT INTO papers (
    id, title, doi, year, citations, fwci, subfield, topic, abstract, open_access, type
)
SELECT
    id, title, doi, year, citations, fwci, subfield, topic, abstract, open_access, type
FROM staging_papers
ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title,
    doi = EXCLUDED.doi,
    year = EXCLUDED.year,
    citations = EXCLUDED.citations,
    fwci = EXCLUDED.fwci,
    subfield = EXCLUDED.subfield,
    topic = EXCLUDED.topic,
    abstract = EXCLUDED.abstract,
    open_access = EXCLUDED.open_access,
    type = EXCLUDED.type;

CREATE TEMP TABLE staging_paper_authors (LIKE paper_authors INCLUDING DEFAULTS);
\COPY staging_paper_authors FROM :'authors_file' CSV HEADER

INSERT INTO paper_authors (
    paper_id, author_id, author_name, position, institution_name, country
)
SELECT
    paper_id, author_id, author_name, position, institution_name, country
FROM staging_paper_authors
ON CONFLICT (paper_id, author_id) DO UPDATE SET
    author_name = EXCLUDED.author_name,
    position = EXCLUDED.position,
    institution_name = EXCLUDED.institution_name,
    country = EXCLUDED.country;

COMMIT;
EOF
echo "  -> upsert import 완료"

# -----------------------------------------------------------
# 6. Backfill + Validate
# -----------------------------------------------------------
echo "[6/6] Backfill + validation..."
(
  cd "${BACKEND_DIR}"
  .venv/bin/python -m scripts.backfill_paper_author_affiliations
  .venv/bin/python -m scripts.backfill_paper_facets
  .venv/bin/python -m scripts.backfill_paper_quality_flags
  .venv/bin/python -m scripts.backfill_institution_name_matches
  .venv/bin/python -m scripts.refresh_publication_summaries
  .venv/bin/python -m scripts.validate_publication_affiliations
  .venv/bin/python -m scripts.validate_institution_matches
  .venv/bin/python -m scripts.validate_paper_facets
  .venv/bin/python -m scripts.validate_metadata_quality
)

echo ""
echo "=== Import 결과 ==="
psql "${SYNC_DB_URL}" <<'EOF'
SELECT COUNT(*) AS total_papers FROM papers;
SELECT COUNT(*) AS total_paper_authors FROM paper_authors;
SELECT COUNT(*) AS total_paper_author_affiliations FROM paper_author_affiliations;
SELECT COUNT(*) AS total_paper_facets FROM paper_facets;
SELECT COUNT(*) AS total_paper_quality_flags FROM paper_quality_flags;
SELECT COUNT(*) AS total_institution_name_matches FROM institution_name_matches;
SELECT COUNT(*) AS total_publication_institution_field_stats FROM publication_institution_field_stats;
SELECT subfield, COUNT(*) AS cnt FROM papers GROUP BY subfield ORDER BY cnt DESC LIMIT 10;
SELECT facet_type, facet_value, COUNT(*) AS cnt
FROM paper_facets
GROUP BY facet_type, facet_value
ORDER BY cnt DESC
LIMIT 10;
SELECT status, COUNT(*) AS cnt
FROM institution_name_matches
GROUP BY status
ORDER BY status;
EOF

echo ""
echo "Import 완료!"
