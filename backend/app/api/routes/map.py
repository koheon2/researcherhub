"""Research Map — real-time OpenAlex landscape analysis."""

import httpx
from fastapi import APIRouter, Query
from collections import defaultdict
from datetime import datetime

router = APIRouter(prefix="/map", tags=["map"])
OPENALEX_BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "ResearcherHub/1.0 (mailto:admin@researcherhub.io)"}
TIMEOUT = 20.0


async def _get(url: str, params: dict | None = None):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"[map] OpenAlex error: {e}")
        return {}


@router.get("/search")
async def search_concepts(q: str = Query(..., min_length=1)):
    """Search OpenAlex concepts."""
    data = await _get(f"{OPENALEX_BASE}/concepts", params={
        "search": q, "per-page": "8",
        "select": "id,display_name,works_count,cited_by_count,level",
    })
    results = data.get("results", []) if isinstance(data, dict) else []
    return [
        {"id": c["id"], "name": c["display_name"],
         "works_count": c.get("works_count", 0), "level": c.get("level", 0)}
        for c in results
    ]


@router.get("/analyze")
async def analyze_concept(
    concept_id: str = Query(...),
    years: int = Query(15, ge=3, le=30),
):
    """Full research landscape analysis for a concept."""
    end_year = datetime.now().year
    start_year = end_year - years + 1
    short_id = concept_id.rsplit("/", 1)[-1] if "/" in concept_id else concept_id

    # 1. Concept metadata
    concept_data = await _get(f"{OPENALEX_BASE}/concepts/{short_id}")
    concept_name = concept_data.get("display_name", short_id) if isinstance(concept_data, dict) else short_id
    total_works = concept_data.get("works_count", 0) if isinstance(concept_data, dict) else 0

    # 2. Top 200 papers by citations (with concepts for camp analysis)
    papers_data = await _get(f"{OPENALEX_BASE}/works", params={
        "filter": f"concepts.id:{concept_id},publication_year:{start_year}-{end_year}",
        "sort": "cited_by_count:desc",
        "per-page": "200",
        "select": "id,title,publication_year,cited_by_count,concepts,authorships",
    })
    papers = papers_data.get("results", []) if isinstance(papers_data, dict) else []

    # 3. Yearly paper counts (separate aggregation call — accurate)
    yearly_data = await _get(f"{OPENALEX_BASE}/works", params={
        "filter": f"concepts.id:{concept_id},publication_year:{start_year}-{end_year}",
        "group_by": "publication_year",
        "per-page": "200",
    })
    yearly_counts: dict[int, int] = {}
    for g in (yearly_data.get("group_by", []) if isinstance(yearly_data, dict) else []):
        try:
            yearly_counts[int(g["key"])] = int(g["count"])
        except (KeyError, ValueError):
            pass

    # 4. Camp analysis: group papers by highest-scoring level-2+ sub-concept
    camp_papers: dict[str, list] = defaultdict(list)
    camp_names: dict[str, str] = {}

    for paper in papers:
        concepts = paper.get("concepts") or []
        sub = [
            c for c in concepts
            if c.get("level", 0) >= 2
            and c.get("id", "").rsplit("/", 1)[-1] != short_id
        ]
        if not sub:
            sub = [c for c in concepts if c.get("level", 0) >= 1
                   and c.get("id", "").rsplit("/", 1)[-1] != short_id]
        if not sub:
            continue
        top_c = max(sub, key=lambda c: c.get("score", 0))
        cid = top_c.get("id", "").rsplit("/", 1)[-1]
        cname = top_c.get("display_name", cid)
        camp_papers[cid].append(paper)
        camp_names[cid] = cname

    camps = []
    for cid, cp in sorted(camp_papers.items(), key=lambda x: -len(x[1]))[:8]:
        total_cit = sum(p.get("cited_by_count", 0) for p in cp)
        top_p = sorted(cp, key=lambda p: p.get("cited_by_count", 0), reverse=True)[:3]
        camps.append({
            "id": cid,
            "name": camp_names[cid],
            "paper_count": len(cp),
            "total_citations": total_cit,
            "top_papers": [
                {
                    "id": p.get("id", "").rsplit("/", 1)[-1],
                    "title": p.get("title") or "(untitled)",
                    "year": p.get("publication_year"),
                    "citations": p.get("cited_by_count", 0),
                }
                for p in top_p
            ],
        })

    # 5. Key papers with roles
    all_years = [p.get("publication_year") for p in papers if p.get("publication_year")]
    median_year = sorted(all_years)[len(all_years) // 2] if all_years else end_year
    recent_threshold = end_year - 3

    key_papers = []
    for p in papers[:30]:
        year = p.get("publication_year") or end_year
        cit = p.get("cited_by_count", 0)
        if year <= median_year and cit > 500:
            role = "foundational"
        elif year >= recent_threshold and cit > 100:
            role = "current"
        elif cit > 1000:
            role = "milestone"
        else:
            role = "notable"

        paper_concepts = p.get("concepts") or []
        sub = [c for c in paper_concepts if c.get("level", 0) >= 2
               and c.get("id", "").rsplit("/", 1)[-1] != short_id]
        camp_name = sub[0].get("display_name", "") if sub else ""

        authors = []
        for a in (p.get("authorships") or [])[:3]:
            aobj = a.get("author") or {}
            if aobj.get("display_name"):
                authors.append(aobj["display_name"])

        key_papers.append({
            "id": p.get("id", "").rsplit("/", 1)[-1],
            "title": p.get("title") or "(untitled)",
            "year": year,
            "citations": cit,
            "role": role,
            "camp": camp_name,
            "authors": authors,
        })

    # 6. Timeline enriched with dominant camp per year
    year_camp: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cid, cp in camp_papers.items():
        for paper in cp:
            yr = paper.get("publication_year")
            if yr:
                year_camp[yr][camp_names[cid]] += 1

    timeline = []
    for year in range(start_year, end_year + 1):
        count = yearly_counts.get(year, 0)
        year_papers = [p for p in papers if p.get("publication_year") == year]
        avg_cit = (
            sum(p.get("cited_by_count", 0) for p in year_papers) / len(year_papers)
            if year_papers else 0
        )
        dominant = (max(year_camp[year].items(), key=lambda x: x[1])[0]
                    if year_camp[year] else None)
        timeline.append({
            "year": year,
            "paper_count": count,
            "avg_citations": round(avg_cit, 1),
            "dominant_camp": dominant,
        })

    # 7. Auto-generated narrative
    peak_year_entry = max(timeline, key=lambda t: t["paper_count"]) if timeline else None
    peak_year = peak_year_entry["year"] if peak_year_entry else end_year
    peak_count = peak_year_entry["paper_count"] if peak_year_entry else 0
    top_paper = key_papers[0] if key_papers else None

    parts = []
    if top_paper and top_paper["role"] == "foundational":
        parts.append(
            f'The field was shaped early by "{top_paper["title"][:70]}" '
            f'({top_paper["year"]}, {top_paper["citations"]:,} citations).'
        )
    if peak_count:
        parts.append(
            f"Publication activity peaked in {peak_year} with {peak_count:,} papers."
        )
    if len(camps) >= 2:
        parts.append(
            f'The field spans {len(camps)} active directions, led by '
            f'"{camps[0]["name"]}" ({camps[0]["paper_count"]} papers) '
            f'and "{camps[1]["name"]}" ({camps[1]["paper_count"]} papers).'
        )

    return {
        "concept": {"id": short_id, "name": concept_name, "total_works": total_works},
        "timeline": timeline,
        "camps": camps,
        "key_papers": key_papers,
        "narrative": " ".join(parts),
        "sample_size": len(papers),
    }
