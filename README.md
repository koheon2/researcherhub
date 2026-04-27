# ResearcherHub

ResearcherHub는 AI/CS 연구 논문과 연구자 정보를 기반으로 국가, 기관, 세부 연구 토픽의 흐름을 비교하고 시각화하는 연구 탐색 웹앱입니다. 단순 검색창보다 **publication-time affiliation**, **paper facet**, **연도별 성장 추이**, **비교/리더보드/트렌딩**을 한 화면에서 다루는 연구 지식 지도를 목표로 합니다.

## 핵심 컨셉

기존 연구자 DB나 논문 검색 서비스는 보통 현재 소속, coarse topic, citation count 중심으로 정보를 보여줍니다. ResearcherHub는 논문 발표 시점의 저자-기관-국가 관계를 별도 계층으로 만들고, 논문 title/abstract에서 세부 AI facet을 약하게 분류해 다음 질문에 답하는 방향으로 설계했습니다.

- 한국과 미국의 AI 연구 contribution은 연도별로 어떻게 달라졌나?
- MIT와 Stanford는 어떤 분야에서 publication-time 기준 contribution이 많은가?
- Transformer, Diffusion, RAG, LLM은 논문 수와 citation이 어떻게 성장했나?
- 최근 성장률이 높은 method/task/application facet은 무엇인가?
- 자연어 질문을 비교, 트렌딩, 진행 추이, 리더보드 화면으로 바로 연결할 수 있는가?

## 현재 기능

- 연구자 지도 및 검색
- 국가/기관/토픽 비교 패널
- publication-year 기반 progress chart
- 국가/기관/연구자 leaderboard
- paper facet 기반 trending
- Transformer, Diffusion, RAG, LLM 등 세부 AI method facet 비교
- VQA, reasoning, retrieval, code generation 등 task facet
- medical imaging, robotics, autonomous driving 등 application facet
- OpenAI API 기반 자연어 쿼리 파싱 및 화면 라우팅
- OpenAlex snapshot/API 기반 수집 및 백필 스크립트

## 기술 스택

### Frontend

- React 19
- TypeScript
- Vite
- React Router
- Three.js / React Three Fiber
- Cesium

### Backend

- FastAPI
- SQLAlchemy async
- PostgreSQL
- Alembic
- OpenAI API
- OpenAlex API / snapshot utilities

## 데이터 모델 개요

주요 테이블은 다음과 같습니다.

| 테이블 | 역할 |
| --- | --- |
| `researchers` | 연구자 프로필, citation, h-index, 위치, 현재/대표 기관 |
| `papers` | 논문 title, abstract, year, citations, subfield, topic |
| `paper_authors` | 논문-저자 원천 관계 |
| `paper_author_affiliations` | 논문 발표 시점의 paper-author-affiliation contribution |
| `paper_facets` | 논문별 weak-label facet |
| `publication_country_stats` | 국가별 publication-time 요약 |
| `publication_institution_stats` | 기관별 publication-time 요약 |
| `paper_facet_summary` | facet별 전체 count/citation/growth 요약 |
| `paper_facet_year_summary` | facet별 연도별 trend 요약 |

`paper_author_affiliations`는 국가/기관 비교의 기준입니다. 연구자의 현재 소속이 아니라 논문이 발표된 시점의 저자 소속을 contribution 단위로 계산합니다.

`paper_facets`는 논문 title + abstract를 기반으로 aboutness/method/task/application 축을 저장합니다. 현재는 rule/keyword 기반 weak label이며, LLM/embedding 기반 taxonomy는 다음 단계입니다.

## Data Quality

현재 데이터는 OpenAlex 기반 원천 저장소 성격이 강하며, dataset/repository record, 고문헌, future-year metadata, topic mismatch가 일부 섞여 있습니다. 제품 지표에는 원본을 직접 쓰기보다 quality-filtered layer가 필요합니다.

1차 조사 결과와 판단 기준은 [Data Quality Audit](docs/data-quality-audit.md)에 정리했습니다.

## Full DB Dump로 시작하기

전체 데이터를 바로 재현하려면 GitHub repo와 별도로 전달되는 PostgreSQL custom-format dump를 복구합니다. DB dump는 Git에 포함하지 않는 artifact입니다.

현재 handoff dump:

| 항목 | 값 |
| --- | --- |
| 파일명 | `researcherhub_codex_full_20260427.dump` |
| checksum 파일 | `researcherhub_codex_full_20260427.dump.sha256` |
| SHA256 | `ef81e3b4eadc0607f353ff271d6e3113505e9796a688239356625c16337d3f44` |
| 크기 | 약 `8.1GB` |
| 원본 DB | `researcherhub_codex` |
| 권장 PostgreSQL | 16 |
| 권장 여유 디스크 | 최소 100GB |

복구 전 준비:

- PostgreSQL 서버가 실행 중이어야 합니다.
- `createdb`, `pg_restore`, `psql` 명령이 PATH에 있어야 합니다.
- `backend/.env`에 들어갈 API key는 별도로 전달받아야 합니다.

dump 파일을 받은 뒤 checksum을 확인합니다.

```bash
shasum -a 256 -c researcherhub_codex_full_20260427.dump.sha256
```

archive가 정상적으로 읽히는지도 확인합니다.

```bash
pg_restore --list researcherhub_codex_full_20260427.dump | head
```

기존에 같은 이름의 DB가 없다면 새 DB를 만들고 복구합니다.

```bash
createdb researcherhub_codex
pg_restore --no-owner --no-acl --jobs 4 -d researcherhub_codex researcherhub_codex_full_20260427.dump
```

이미 같은 이름의 DB가 있으면 덮어쓰기 전에 반드시 백업하거나 다른 DB명을 사용하세요. 예를 들어:

```bash
createdb researcherhub_codex_local
pg_restore --no-owner --no-acl --jobs 4 -d researcherhub_codex_local researcherhub_codex_full_20260427.dump
```

복구한 DB명에 맞춰 `backend/.env`를 설정합니다.

```env
DATABASE_URL=postgresql+asyncpg://<your-postgres-user>@localhost:5432/researcherhub_codex
OPENALEX_EMAIL=your@email.com
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
OPENAI_API_KEY=your-openai-api-key
```

풀 덤프에는 schema, data, index, Alembic version이 포함되어 있습니다. 따라서 풀 덤프 복구 경로에서는 migration을 새로 적용하는 것이 아니라 현재 revision을 확인하는 용도로 실행합니다.

```bash
cd backend
.venv/bin/alembic -c alembic.ini current
```

복구 후 sanity check:

```bash
cd backend
.venv/bin/python -m scripts.validate_metadata_quality
.venv/bin/python -m scripts.validate_publication_affiliations
.venv/bin/python -m scripts.validate_paper_facets
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

프론트까지 확인하려면 별도 터미널에서 실행합니다.

```bash
npm install
npm run dev
```

## 로컬 실행

### 1. Frontend 설치

```bash
npm install
```

### 2. Backend 가상환경 준비

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. 환경변수 설정

```bash
cp backend/.env.example backend/.env
```

`backend/.env` 예시:

```env
DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/researcherhub
OPENALEX_EMAIL=your@email.com
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
OPENAI_API_KEY=your-openai-api-key
```

주의:

- `backend/.env`는 커밋하지 않습니다.
- 자연어 쿼리 파서는 `OPENAI_API_KEY`가 있을 때 동작합니다.
- `DATABASE_URL`에 운영 DB 비밀번호가 들어가면 이 값도 비밀값입니다.

### 4. DB 마이그레이션

```bash
cd backend
.venv/bin/alembic -c alembic.ini upgrade head
```

이 명령은 빈 DB에서 새로 시작하거나 CSV import/backfill 파이프라인을 돌릴 때 사용합니다. 위의 full DB dump를 복구한 경우에는 schema/data/Alembic version이 이미 포함되어 있으므로 `upgrade head` 대신 `alembic current`로 상태만 확인합니다.

### 5. Backend 실행

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 6. Frontend 실행

```bash
npm run dev
```

브라우저에서 `http://localhost:5173`을 엽니다.

## 데이터 적재 파이프라인

OpenAlex snapshot에서 CS 논문 CSV를 생성하고 DB에 적재하는 흐름은 `scripts/collect` 아래에 있습니다.

일반적인 순서:

1. OpenAlex snapshot에서 `papers.csv.gz`, `paper_authors.csv.gz` 생성
2. Alembic migration 적용
3. `papers`, `paper_authors` import
4. `paper_author_affiliations` backfill
5. `paper_facets` backfill
6. summary table refresh
7. validation/smoke test 실행

Import orchestration:

```bash
scripts/collect/import.sh <S3_BUCKET_NAME>
```

개별 backfill:

```bash
cd backend
.venv/bin/python -m scripts.backfill_paper_author_affiliations
.venv/bin/python -m scripts.backfill_paper_facets --mode aboutness
.venv/bin/python -m scripts.backfill_paper_facets --mode keywords --batch-size 10000
.venv/bin/python -m scripts.refresh_publication_summaries
```

## 검증 명령

Backend smoke:

```bash
cd backend
.venv/bin/python -m scripts.validate_publication_affiliations
.venv/bin/python -m scripts.validate_paper_facets
.venv/bin/python -m scripts.validate_metadata_quality
.venv/bin/python -m scripts.smoke_publication_affiliation_api --base-url http://127.0.0.1:8000/api
.venv/bin/python -m scripts.smoke_paper_facet_api --base-url http://127.0.0.1:8000/api
```

Metadata quality audit:

```bash
cd backend
.venv/bin/python -m scripts.validate_metadata_quality
.venv/bin/python -m scripts.validate_metadata_quality --deep
.venv/bin/python -m scripts.validate_metadata_quality --external-sample 50 --csv /tmp/metadata-audit.csv
```

기본 실행은 빠른 반복 확인을 위해 추정치와 `TABLESAMPLE`을 사용합니다. 정확한 전체 scan이 필요하면 `--deep`을 사용하고, DOI 외부 대조가 필요하면 `--external-sample`을 지정합니다.

Frontend build:

```bash
npm run build
```

## 주요 API

```text
GET /api/compare?type=country&entities=US,KR
GET /api/compare?type=institution&entities=MIT,Stanford
GET /api/compare?type=topic&entities=transformer,diffusion
GET /api/progress?type=country&entity=KR&years=10
GET /api/progress?type=field&entity=transformer&years=10
GET /api/trending?axis=method&limit=20
GET /api/leaderboard?type=country&limit=20
GET /api/search/universal?q=Transformer%20vs%20Diffusion
```

## Git에 포함하지 않는 것

다음 파일과 디렉터리는 로컬 데이터, 캐시, 비밀값이므로 Git에 포함하지 않습니다.

- `backend/.env`
- `scripts/collect/*.pem`
- `scripts/collect/data/`
- `*.dump`
- `*.dump.sha256`
- `*.sql`
- `*.sql.gz`
- `exports/`
- `db-dumps/`
- `backend/.venv/`
- `node_modules/`
- `dist/`
- `.playwright-cli/`
- `backend/data/ror/`
- `backend/data/umap_cache/`
- `backend/data/institutions/`
- `backend/pipeline_state.json`
- `backend/snapshot_state.json`
- `backend/institution_coords_cache.json`
- `LOCAL_AGENT_CONTEXT.md`

`backend/data/paper_facet_seeds.json`과 `backend/data/topic_names.json`은 작고 코드 동작에 필요한 seed/config 성격이라 커밋 대상입니다.

## 현재 한계

- `paper_facets`는 아직 keyword rule 기반 weak label입니다.
- OpenAlex aboutness/topic 품질은 거칠 수 있습니다.
- ROR 기반 기관 정규화는 아직 완성 단계가 아닙니다.
- benchmark score, dataset, metric extraction은 아직 구현하지 않았습니다.
- 대용량 전체 DB를 그대로 배포하는 구조는 비용 효율적이지 않습니다. 배포용으로는 summary table 중심의 slim DB가 필요합니다.

## 다음 단계

1. 배포용 slim DB 생성
2. frontend API base URL 환경변수화
3. Postgres FTS/trgm 기반 검색 개선
4. ROR institution matching
5. facet taxonomy v1
6. result/benchmark extraction
