"""Benchmark timeline endpoints — proxy OpenAlex concepts & works."""

import httpx
from fastapi import APIRouter, Query

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

OPENALEX_BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "ResearcherHub/1.0 (mailto:admin@researcherhub.io)"}
TIMEOUT = 15.0


async def _openalex_get(url: str, params: dict | None = None) -> dict | list:
    """Fire a GET to OpenAlex; return JSON or empty dict on failure."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[benchmarks] OpenAlex request failed: {exc}")
        return {}


# ── Search concepts ──────────────────────────────────────────────────────────

@router.get("/search")
async def search_concepts(q: str = Query(..., min_length=1)):
    """Search OpenAlex concepts and return a slim list."""
    data = await _openalex_get(
        f"{OPENALEX_BASE}/concepts",
        params={
            "search": q,
            "per-page": "8",
            "select": "id,display_name,works_count,cited_by_count,level",
        },
    )
    results = data.get("results", []) if isinstance(data, dict) else []
    return [
        {
            "id": c.get("id", ""),
            "name": c.get("display_name", ""),
            "works_count": c.get("works_count", 0),
            "cited_by_count": c.get("cited_by_count", 0),
        }
        for c in results
    ]


# ── Timeline for a concept ──────────────────────────────────────────────────

def _extract_concept_short_id(full_id: str) -> str:
    """'https://openalex.org/C41008148' -> 'C41008148'"""
    return full_id.rsplit("/", 1)[-1] if "/" in full_id else full_id


@router.get("/timeline")
async def concept_timeline(
    concept_id: str = Query(...),
    years: int = Query(10, ge=1, le=30),
):
    """Return yearly paper counts + top papers for a concept."""
    from datetime import datetime

    end_year = datetime.now().year
    start_year = end_year - years + 1
    short_id = _extract_concept_short_id(concept_id)

    # ── yearly aggregation ───────────────────────────────────────────────
    yearly_data = await _openalex_get(
        f"{OPENALEX_BASE}/works",
        params={
            "filter": f"concepts.id:{concept_id},publication_year:{start_year}-{end_year}",
            "group_by": "publication_year",
            "per-page": "200",
        },
    )
    yearly: list[dict] = []
    for g in (yearly_data.get("group_by", []) if isinstance(yearly_data, dict) else []):
        try:
            yearly.append({
                "year": int(g["key"]),
                "paper_count": int(g["count"]),
            })
        except (KeyError, ValueError):
            continue
    yearly.sort(key=lambda x: x["year"])

    # ── top papers ───────────────────────────────────────────────────────
    top_data = await _openalex_get(
        f"{OPENALEX_BASE}/works",
        params={
            "filter": f"concepts.id:{concept_id}",
            "sort": "cited_by_count:desc",
            "per-page": "30",
            "select": "id,title,publication_year,cited_by_count,authorships",
        },
    )
    top_papers: list[dict] = []
    for w in (top_data.get("results", []) if isinstance(top_data, dict) else []):
        authors: list[dict] = []
        for a in (w.get("authorships") or []):
            author_obj = a.get("author") or {}
            aid = author_obj.get("id") or ""
            # extract short id from URL
            aid_short = aid.rsplit("/", 1)[-1] if aid and "/" in aid else aid
            aname = author_obj.get("display_name") or ""
            if aname:
                authors.append({"id": aid_short, "name": aname})
        top_papers.append({
            "id": (w.get("id") or "").rsplit("/", 1)[-1],
            "title": w.get("title") or "(untitled)",
            "year": w.get("publication_year"),
            "citations": w.get("cited_by_count", 0),
            "authors": authors[:5],  # limit to first 5 authors
        })

    return {
        "concept": {
            "id": short_id,
            "name": concept_id,  # caller already has the name; this is a fallback
            "works_count": 0,
        },
        "yearly": yearly,
        "top_papers": top_papers,
    }
