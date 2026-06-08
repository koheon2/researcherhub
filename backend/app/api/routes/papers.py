"""Paper discovery, representative lists, and paper details."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.paper_facets import FACET_TYPES, canonicalize_facet_query, normalize_facet_text

router = APIRouter(prefix="/papers", tags=["papers"])

SPECIFIC_AXIS = "specific"
AXIS_PATTERN = "^(aboutness|method|task|application|specific)$"
PAPER_SEARCH_VECTOR = (
    "to_tsvector('english'::regconfig, "
    "coalesce(p.title, '') || ' ' || coalesce(p.topic, '') || ' ' || coalesce(p.abstract, ''))"
)

QUALITY_PROVENANCE = {
    "quality_filtered": True,
    "quality_policy": "conservative_v0",
}


def _openalex_work_url(paper_id: str) -> str | None:
    if not paper_id:
        return None
    if paper_id.startswith("http://") or paper_id.startswith("https://"):
        return paper_id
    return f"https://openalex.org/{paper_id}"


async def _paper_annotations(db: AsyncSession, paper_ids: list[str]) -> dict[str, dict[str, list[dict]]]:
    if not paper_ids:
        return {}

    annotations = {
        paper_id: {"authors": [], "facets": [], "quality_flags": [], "affiliations": []}
        for paper_id in paper_ids
    }

    author_rows = await db.execute(
        text("""
        SELECT paper_id, author_id, author_name, institution_name, country, position
        FROM paper_authors
        WHERE paper_id = ANY(:ids)
        ORDER BY paper_id, position
        """),
        {"ids": paper_ids},
    )
    for a in author_rows.fetchall():
        annotations.setdefault(a.paper_id, {"authors": [], "facets": [], "quality_flags": [], "affiliations": []})
        annotations[a.paper_id]["authors"].append({
            "author_id": a.author_id,
            "name": a.author_name,
            "institution": a.institution_name,
            "country": a.country,
            "position": a.position,
        })

    facet_rows = await db.execute(
        text("""
        SELECT paper_id, facet_type, facet_value, source, confidence, rank
        FROM paper_facets
        WHERE paper_id = ANY(:ids)
        ORDER BY paper_id, facet_type, rank, confidence DESC
        """),
        {"ids": paper_ids},
    )
    for f in facet_rows.fetchall():
        annotations.setdefault(f.paper_id, {"authors": [], "facets": [], "quality_flags": [], "affiliations": []})
        annotations[f.paper_id]["facets"].append({
            "facet_type": f.facet_type,
            "facet_value": f.facet_value,
            "source": f.source,
            "confidence": float(f.confidence or 0),
            "rank": f.rank,
        })

    flag_rows = await db.execute(
        text("""
        SELECT paper_id, flag_type, severity, reason, source
        FROM paper_quality_flags
        WHERE paper_id = ANY(:ids)
        ORDER BY paper_id, severity, flag_type
        """),
        {"ids": paper_ids},
    )
    for q in flag_rows.fetchall():
        annotations.setdefault(q.paper_id, {"authors": [], "facets": [], "quality_flags": [], "affiliations": []})
        annotations[q.paper_id]["quality_flags"].append({
            "flag_type": q.flag_type,
            "severity": q.severity,
            "reason": q.reason,
            "source": q.source,
        })

    affiliation_rows = await db.execute(
        text("""
        SELECT
            paa.paper_id,
            paa.author_id,
            paa.author_name,
            paa.institution_name,
            COALESCE(inm.canonical_name, paa.institution_name) AS canonical_institution_name,
            inm.institution_ror_id,
            inm.confidence AS institution_match_confidence,
            paa.country_code,
            paa.position,
            paa.confidence
        FROM paper_author_affiliations paa
        LEFT JOIN institution_name_matches inm
          ON inm.raw_institution_name = paa.institution_name
         AND inm.country_code = paa.country_code
         AND inm.status = 'matched'
        WHERE paa.paper_id = ANY(:ids)
        ORDER BY paa.paper_id, paa.position, paa.institution_name
        """),
        {"ids": paper_ids},
    )
    for aff in affiliation_rows.fetchall():
        annotations.setdefault(aff.paper_id, {"authors": [], "facets": [], "quality_flags": [], "affiliations": []})
        annotations[aff.paper_id]["affiliations"].append({
            "author_id": aff.author_id,
            "author_name": aff.author_name,
            "institution_name": aff.institution_name,
            "canonical_institution_name": aff.canonical_institution_name,
            "institution_ror_id": aff.institution_ror_id,
            "institution_match_confidence": (
                float(aff.institution_match_confidence)
                if aff.institution_match_confidence is not None
                else None
            ),
            "country_code": aff.country_code,
            "position": aff.position,
            "confidence": float(aff.confidence or 0),
        })

    return annotations


def _paper_item(row, annotations: dict[str, dict[str, list[dict]]] | None = None) -> dict:
    ann = annotations.get(row.id, {}) if annotations else {}
    doi = row.doi
    return {
        "id": row.id,
        "title": row.title,
        "year": row.year,
        "citations": int(row.citations or 0),
        "fwci": float(row.fwci) if row.fwci is not None else None,
        "doi": doi,
        "doi_url": f"https://doi.org/{doi}" if doi else None,
        "openalex_url": _openalex_work_url(row.id),
        "abstract": row.abstract,
        "abstract_available": bool(row.abstract),
        "open_access": bool(row.open_access),
        "type": row.type,
        "subfield": row.subfield,
        "topic": row.topic,
        "authors": ann.get("authors", []),
        "facets": ann.get("facets", []),
        "quality_flags": ann.get("quality_flags", []),
        "affiliations": ann.get("affiliations", []),
    }


def _axis_filter(axis: str | None = None) -> list[str]:
    if axis and axis != SPECIFIC_AXIS:
        return [axis]
    return list(FACET_TYPES)


async def _specific_topic_option(
    db: AsyncSession,
    query: str,
) -> dict[str, object] | None:
    if len(query.strip()) < 3:
        return None

    result = await db.execute(
        text(f"""
        WITH search_query AS (
            SELECT websearch_to_tsquery('english', :query) AS tsq
        )
        SELECT
            COUNT(*)::bigint AS paper_count,
            COALESCE(SUM(p.citations), 0)::bigint AS total_citations,
            MIN(p.year) AS min_year,
            MAX(p.year) AS max_year
        FROM papers p
        CROSS JOIN search_query sq
        WHERE {PAPER_SEARCH_VECTOR} @@ sq.tsq
          AND p.year IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM paper_quality_flags pqf
              WHERE pqf.paper_id = p.id
                AND pqf.severity = 'exclude'
          )
        """),
        {"query": query},
    )
    row = result.one()
    paper_count = int(row.paper_count or 0)
    if paper_count == 0:
        return None

    return {
        "facet_type": SPECIFIC_AXIS,
        "topic": query.strip(),
        "paper_count": paper_count,
        "total_citations": int(row.total_citations or 0),
        "min_year": row.min_year,
        "max_year": row.max_year,
    }


async def _timeline_response(
    db: AsyncSession,
    *,
    topic: str,
    query: str,
    matched_axes: list[str],
    per_year: int,
    min_fwci: float,
    papers: list,
) -> dict:
    if not papers:
        return {
            "topic": topic,
            "query": query,
            "matched_axes": matched_axes,
            "per_year": per_year,
            "min_fwci": min_fwci,
            "papers": [],
            "by_year": [],
            **QUALITY_PROVENANCE,
        }

    annotations = await _paper_annotations(db, [p.id for p in papers])

    items = [
        {
            "id": p.id,
            "title": p.title,
            "year": p.year,
            "citations": int(p.citations or 0),
            "fwci": float(p.fwci) if p.fwci is not None else None,
            "doi": p.doi,
            "abstract": None,
            "open_access": bool(p.open_access),
            "type": p.type,
            "authors": annotations.get(p.id, {}).get("authors", [])[:3],
        }
        for p in papers
    ]

    by_year: dict[int, list[dict]] = {}
    for it in items:
        by_year.setdefault(it["year"], []).append(it)
    grouped = [
        {"year": y, "papers": by_year[y]}
        for y in sorted(by_year.keys())
    ]

    return {
        "topic": topic,
        "query": query,
        "matched_axes": matched_axes,
        "per_year": per_year,
        "min_fwci": min_fwci,
        "papers": items,
        "by_year": grouped,
        **QUALITY_PROVENANCE,
    }


@router.get("/topics")
async def list_topics(
    q: str | None = Query(None, description="Substring filter on topic name"),
    axis: str | None = Query(None, pattern=AXIS_PATTERN),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return facet topics with paper counts, sorted by match quality and size."""
    query = q.strip() if q and q.strip() else ""
    axes = _axis_filter(axis)
    params: dict[str, object] = {
        "axes": axes,
        "limit": limit,
    }
    where = "WHERE s.facet_type = ANY(:axes) AND s.paper_count > 0"
    order = "s.paper_count DESC, s.facet_value ASC"

    if query:
        canonical, matched_axes = canonicalize_facet_query(query)
        if matched_axes and axis is None:
            axes = matched_axes
            params["axes"] = axes
        params.update(
            {
                "q": query.lower(),
                "canonical": canonical.lower(),
                "q_prefix": f"{query.lower()}%",
                "q_contains": f"%{query.lower()}%",
            }
        )
        where += """
          AND (
            LOWER(s.facet_value) = :canonical
            OR LOWER(s.facet_value) LIKE :q_contains
          )
        """
        order = """
        CASE
            WHEN LOWER(s.facet_value) = :canonical THEN 0
            WHEN LOWER(s.facet_value) = :q THEN 1
            WHEN LOWER(s.facet_value) LIKE :q_prefix THEN 2
            ELSE 3
        END,
        s.paper_count DESC,
        s.facet_value ASC
        """

    rows = []
    if axis != SPECIFIC_AXIS:
        result = await db.execute(
            text(f"""
            WITH years AS (
                SELECT
                    facet_type,
                    facet_value,
                    MIN(year) AS min_year,
                    MAX(year) AS max_year
                FROM paper_facet_year_summary
                WHERE facet_type = ANY(:axes)
                GROUP BY facet_type, facet_value
            )
            SELECT
                s.facet_type,
                s.facet_value AS topic,
                s.paper_count,
                s.total_citations,
                years.min_year,
                years.max_year
            FROM paper_facet_summary s
            LEFT JOIN years
              ON years.facet_type = s.facet_type
             AND years.facet_value = s.facet_value
            {where}
            ORDER BY {order}
            LIMIT :limit
            """),
            params,
        )
        rows = [
            {
                "facet_type": r.facet_type,
                "topic": r.topic,
                "paper_count": int(r.paper_count),
                "total_citations": int(r.total_citations or 0),
                "min_year": r.min_year,
                "max_year": r.max_year,
            }
            for r in result.fetchall()
        ]

    if query:
        exact_curated_match = any(
            normalize_facet_text(str(row["topic"])) == normalize_facet_text(query)
            for row in rows
        )
        should_offer_specific = (
            axis == SPECIFIC_AXIS
            or (not exact_curated_match and (" " in query or "-" in query or not rows))
        )
        if should_offer_specific:
            specific = await _specific_topic_option(db, query)
            if specific:
                rows = [specific, *rows]

    return rows[:limit]


@router.get("/representative")
async def representative_papers(
    topic: str | None = Query(None, description="Facet/topic query. Empty returns globally cited papers."),
    axis: str | None = Query(None, pattern=AXIS_PATTERN),
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("impact", pattern="^(impact|recent|citations)$"),
    db: AsyncSession = Depends(get_db),
):
    """Representative papers for a facet or broad topic."""
    params: dict[str, object] = {"limit": limit}
    year_clause = ""
    if year_from is not None:
        year_clause += " AND p.year >= :year_from"
        params["year_from"] = year_from
    if year_to is not None:
        year_clause += " AND p.year <= :year_to"
        params["year_to"] = year_to

    order_clause = {
        "recent": "p.year DESC NULLS LAST, p.citations DESC NULLS LAST, p.fwci DESC NULLS LAST, p.id",
        "citations": "p.citations DESC NULLS LAST, p.fwci DESC NULLS LAST, p.year DESC NULLS LAST, p.id",
        "impact": "p.citations DESC NULLS LAST, p.fwci DESC NULLS LAST, p.year DESC NULLS LAST, p.id",
    }[sort]

    topic_value = topic.strip() if topic and topic.strip() else ""
    matched_axes: list[str] = []
    resolved_topic = topic_value
    topic_clause = ""
    join_clause = ""
    match_kind = "global"

    if not topic_value:
        global_order_clause = {
            "recent": "p.year DESC NULLS LAST, p.citations DESC NULLS LAST, pes.candidate_score DESC NULLS LAST, p.id",
            "citations": "p.citations DESC NULLS LAST, pes.candidate_score DESC NULLS LAST, p.year DESC NULLS LAST, p.id",
            "impact": "pes.candidate_score DESC NULLS LAST, p.citations DESC NULLS LAST, p.year DESC NULLS LAST, p.id",
        }[sort]
        result = await db.execute(
            text(f"""
            SELECT
                p.id, p.title, p.year, p.citations, p.fwci, p.doi, p.open_access,
                p.type, p.subfield, p.topic, NULL::text AS abstract
            FROM paper_enrichment_status pes
            JOIN papers p ON p.id = pes.paper_id
            WHERE pes.source = 'openalex'
              AND pes.status = 'fetched'
              AND p.year IS NOT NULL
              {year_clause}
              AND NOT EXISTS (
                  SELECT 1
                  FROM paper_quality_flags pqf
                  WHERE pqf.paper_id = p.id
                    AND pqf.severity = 'exclude'
              )
            ORDER BY {global_order_clause}
            LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()
        annotations = await _paper_annotations(db, [r.id for r in rows])
        papers = []
        for row in rows:
            item = _paper_item(row, annotations)
            item["abstract"] = None
            item["affiliations"] = []
            item["quality_flags"] = []
            item["authors"] = item["authors"][:3]
            papers.append(item)

        return {
            "topic": None,
            "query": None,
            "matched_axes": matched_axes,
            "match_kind": match_kind,
            "sort": sort,
            "limit": limit,
            "papers": papers,
            **QUALITY_PROVENANCE,
        }

    if topic_value:
        if axis == SPECIFIC_AXIS:
            params["query"] = topic_value
            join_clause = "CROSS JOIN (SELECT websearch_to_tsquery('english', :query) AS tsq) sq"
            topic_clause = f"AND {PAPER_SEARCH_VECTOR} @@ sq.tsq"
            matched_axes = [SPECIFIC_AXIS]
            match_kind = SPECIFIC_AXIS
        else:
            resolved_topic, matched_axes = canonicalize_facet_query(topic_value)
            axes = _axis_filter(axis) if axis else (matched_axes or list(FACET_TYPES))
            params.update({"topic": resolved_topic, "axes": axes})
            topic_clause = """
            AND EXISTS (
                SELECT 1
                FROM paper_facets pf
                WHERE pf.paper_id = p.id
                  AND pf.facet_value = :topic
                  AND pf.facet_type = ANY(:axes)
            )
            """
            matched_axes = axes
            match_kind = "facet"

    result = await db.execute(
        text(f"""
        SELECT
            p.id, p.title, p.year, p.citations, p.fwci, p.doi, p.open_access,
            p.type, p.subfield, p.topic, NULL::text AS abstract
        FROM papers p
        {join_clause}
        WHERE p.year IS NOT NULL
          {year_clause}
          {topic_clause}
          AND NOT EXISTS (
              SELECT 1
              FROM paper_quality_flags pqf
              WHERE pqf.paper_id = p.id
                AND pqf.severity = 'exclude'
          )
        ORDER BY {order_clause}
        LIMIT :limit
        """),
        params,
    )
    rows = result.fetchall()
    annotations = await _paper_annotations(db, [r.id for r in rows])
    papers = []
    for row in rows:
        item = _paper_item(row, annotations)
        item["abstract"] = None
        item["affiliations"] = []
        item["quality_flags"] = []
        item["authors"] = item["authors"][:3]
        papers.append(item)

    return {
        "topic": resolved_topic or None,
        "query": topic_value or None,
        "matched_axes": matched_axes,
        "match_kind": match_kind,
        "sort": sort,
        "limit": limit,
        "papers": papers,
        **QUALITY_PROVENANCE,
    }


@router.get("/timeline")
async def get_topic_timeline(
    topic: str = Query(..., min_length=1),
    axis: str | None = Query(None, pattern=AXIS_PATTERN),
    per_year: int = Query(3, ge=1, le=10),
    min_fwci: float = Query(2.0, ge=0.0, description="FWCI floor; null FWCI rows are still kept"),
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Major papers per year for a topic.
    Ranking: top-N citations per year, filtered to fwci >= min_fwci (null fwci allowed).
    """
    canonical_topic, matched_axes = canonicalize_facet_query(topic)
    axes = _axis_filter(axis) if axis else (matched_axes or list(FACET_TYPES))
    params: dict[str, object] = {
        "topic": canonical_topic,
        "axes": axes,
        "per_year": per_year,
        "min_fwci": min_fwci,
    }

    year_clause = ""
    if year_from is not None:
        year_clause += " AND p.year >= :year_from"
        params["year_from"] = year_from
    if year_to is not None:
        year_clause += " AND p.year <= :year_to"
        params["year_to"] = year_to

    if axis == SPECIFIC_AXIS:
        specific_sql = f"""
        WITH search_query AS MATERIALIZED (
            SELECT websearch_to_tsquery('english', :query) AS tsq
        ),
        ranked AS (
            SELECT
                p.id, p.title, p.year, p.citations, p.fwci, p.doi, p.open_access, p.type,
                ROW_NUMBER() OVER (
                    PARTITION BY p.year
                    ORDER BY
                        ts_rank_cd({PAPER_SEARCH_VECTOR}, sq.tsq) DESC,
                        p.citations DESC NULLS LAST,
                        p.fwci DESC NULLS LAST,
                        p.id
                ) AS rn
            FROM papers p
            CROSS JOIN search_query sq
            WHERE {PAPER_SEARCH_VECTOR} @@ sq.tsq
              AND p.year IS NOT NULL
              AND (p.fwci IS NULL OR p.fwci >= :min_fwci)
              {year_clause}
              AND NOT EXISTS (
                  SELECT 1
                  FROM paper_quality_flags pqf
                  WHERE pqf.paper_id = p.id
                    AND pqf.severity = 'exclude'
              )
        )
        SELECT id, title, year, citations, fwci, doi, open_access, type
        FROM ranked
        WHERE rn <= :per_year
        ORDER BY year ASC, citations DESC NULLS LAST
        """
        result = await db.execute(
            text(specific_sql),
            {
                **params,
                "query": topic,
            },
        )
        return await _timeline_response(
            db,
            topic=topic,
            query=topic,
            matched_axes=[SPECIFIC_AXIS],
            per_year=per_year,
            min_fwci=min_fwci,
            papers=result.fetchall(),
        )

    resolved = await db.execute(
        text("""
        SELECT facet_type, facet_value
        FROM paper_facet_summary
        WHERE LOWER(facet_value) = LOWER(:facet_value)
          AND facet_type = ANY(:axes)
        ORDER BY paper_count DESC
        LIMIT 1
        """),
        {"facet_value": canonical_topic, "axes": axes},
    )
    resolved_row = resolved.first()
    if resolved_row:
        canonical_topic = resolved_row.facet_value
        if axis or not matched_axes:
            matched_axes = [resolved_row.facet_type]
            axes = matched_axes
            params["axes"] = axes
        params["topic"] = canonical_topic
    elif not matched_axes:
        result = await db.execute(
            text(f"""
            WITH search_query AS MATERIALIZED (
                SELECT websearch_to_tsquery('english', :query) AS tsq
            ),
            ranked AS (
                SELECT
                    p.id, p.title, p.year, p.citations, p.fwci, p.doi, p.open_access, p.type,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.year
                        ORDER BY
                            ts_rank_cd({PAPER_SEARCH_VECTOR}, sq.tsq) DESC,
                            p.citations DESC NULLS LAST,
                            p.fwci DESC NULLS LAST,
                            p.id
                    ) AS rn
                FROM papers p
                CROSS JOIN search_query sq
                WHERE {PAPER_SEARCH_VECTOR} @@ sq.tsq
                  AND p.year IS NOT NULL
                  AND (p.fwci IS NULL OR p.fwci >= :min_fwci)
                  {year_clause}
                  AND NOT EXISTS (
                      SELECT 1
                      FROM paper_quality_flags pqf
                      WHERE pqf.paper_id = p.id
                        AND pqf.severity = 'exclude'
                  )
            )
            SELECT id, title, year, citations, fwci, doi, open_access, type
            FROM ranked
            WHERE rn <= :per_year
            ORDER BY year ASC, citations DESC NULLS LAST
            """),
            {
                **params,
                "query": topic,
            },
        )
        return await _timeline_response(
            db,
            topic=topic,
            query=topic,
            matched_axes=[SPECIFIC_AXIS],
            per_year=per_year,
            min_fwci=min_fwci,
            papers=result.fetchall(),
        )

    sql = f"""
    WITH matched_papers AS MATERIALIZED (
        SELECT DISTINCT paper_id
        FROM paper_facets
        WHERE facet_value = :topic
          AND facet_type = ANY(:axes)
    ),
    ranked AS (
        SELECT
            p.id, p.title, p.year, p.citations, p.fwci, p.doi, p.open_access, p.type,
            ROW_NUMBER() OVER (
                PARTITION BY p.year
                ORDER BY p.citations DESC NULLS LAST, p.fwci DESC NULLS LAST, p.id
            ) AS rn
        FROM matched_papers mp
        JOIN papers p ON p.id = mp.paper_id
        WHERE p.year IS NOT NULL
          AND (p.fwci IS NULL OR p.fwci >= :min_fwci)
          {year_clause}
          AND NOT EXISTS (
              SELECT 1
              FROM paper_quality_flags pqf
              WHERE pqf.paper_id = p.id
                AND pqf.severity = 'exclude'
          )
    )
    SELECT id, title, year, citations, fwci, doi, open_access, type
    FROM ranked
    WHERE rn <= :per_year
    ORDER BY year ASC, citations DESC NULLS LAST
    """

    result = await db.execute(text(sql), params)
    return await _timeline_response(
        db,
        topic=canonical_topic,
        query=topic,
        matched_axes=matched_axes,
        per_year=per_year,
        min_fwci=min_fwci,
        papers=result.fetchall(),
    )


@router.get("/{paper_id}")
async def get_paper_detail(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return a single paper with authors, facets, quality flags, and affiliations."""
    result = await db.execute(
        text("""
        SELECT
            id, title, doi, year, citations, fwci, subfield, topic, abstract,
            open_access, type
        FROM papers
        WHERE id = :paper_id
        """),
        {"paper_id": paper_id},
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")

    annotations = await _paper_annotations(db, [paper_id])
    return {
        **_paper_item(row, annotations),
        **QUALITY_PROVENANCE,
    }


@router.get("/{paper_id}/references")
async def get_paper_references(
    paper_id: str,
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return OpenAlex referenced works, prioritizing references that exist in the local DB."""
    source_exists = await db.execute(text("SELECT 1 FROM papers WHERE id = :paper_id"), {"paper_id": paper_id})
    if not source_exists.first():
        raise HTTPException(status_code=404, detail="Paper not found")

    rows = (
        await db.execute(
            text("""
            SELECT
                pre.target_openalex_id,
                pre.target_paper_id,
                p.id,
                p.title,
                p.year,
                p.citations,
                p.fwci,
                p.doi,
                p.open_access,
                p.type,
                p.subfield,
                p.topic,
                NULL::text AS abstract
            FROM paper_reference_edges pre
            JOIN papers source_p ON source_p.id = pre.source_paper_id
            LEFT JOIN papers p ON p.id = pre.target_paper_id
            WHERE pre.source_paper_id = :paper_id
              AND pre.source = 'openalex'
              AND (
                  p.id IS NULL
                  OR p.year IS NULL
                  OR source_p.year IS NULL
                  OR p.year <= source_p.year
              )
            ORDER BY
                CASE WHEN pre.target_paper_id IS NULL THEN 1 ELSE 0 END,
                CASE WHEN lower(COALESCE(p.type, '')) IN ('article', 'proceedings-article') THEN 0 ELSE 1 END,
                p.citations DESC NULLS LAST,
                p.year DESC NULLS LAST,
                pre.target_openalex_id
            LIMIT :limit
            """),
            {"paper_id": paper_id, "limit": limit},
        )
    ).fetchall()

    internal_rows = [row for row in rows if row.id]
    annotations = await _paper_annotations(db, [row.id for row in internal_rows])
    references = []
    for row in rows:
        if row.id:
            item = _paper_item(row, annotations)
            item["abstract"] = None
            item["authors"] = item["authors"][:3]
            item["target_openalex_id"] = row.target_openalex_id
            item["internal"] = True
            references.append(item)
        else:
            references.append({
                "id": None,
                "target_openalex_id": row.target_openalex_id,
                "openalex_url": _openalex_work_url(row.target_openalex_id),
                "internal": False,
            })

    summary = (
        await db.execute(
            text("""
            SELECT
                COUNT(*)::bigint AS total_references,
                COUNT(*) FILTER (WHERE target_paper_id IS NOT NULL)::bigint AS internal_references
            FROM paper_reference_edges
            WHERE source_paper_id = :paper_id
              AND source = 'openalex'
            """),
            {"paper_id": paper_id},
        )
    ).one()

    return {
        "paper_id": paper_id,
        "total_references": int(summary.total_references or 0),
        "internal_references": int(summary.internal_references or 0),
        "external_references": int((summary.total_references or 0) - (summary.internal_references or 0)),
        "references": references,
        **QUALITY_PROVENANCE,
    }


@router.get("/{paper_id}/citation-graph")
async def get_paper_citation_graph(
    paper_id: str,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Return a lightweight one-hop local reference graph for a paper."""
    detail = await db.execute(
        text("""
        SELECT id, title, year, citations, fwci, doi, open_access, type, subfield, topic, NULL::text AS abstract
        FROM papers
        WHERE id = :paper_id
        """),
        {"paper_id": paper_id},
    )
    seed = detail.first()
    if not seed:
        raise HTTPException(status_code=404, detail="Paper not found")

    ref_rows = (
        await db.execute(
            text("""
            SELECT
                p.id,
                p.title,
                p.year,
                p.citations,
                p.fwci,
                p.doi,
                p.open_access,
                p.type,
                p.subfield,
                p.topic,
                NULL::text AS abstract
            FROM paper_reference_edges pre
            JOIN papers source_p ON source_p.id = pre.source_paper_id
            JOIN papers p ON p.id = pre.target_paper_id
            WHERE pre.source_paper_id = :paper_id
              AND pre.source = 'openalex'
              AND (
                  p.year IS NULL
                  OR source_p.year IS NULL
                  OR p.year <= source_p.year
              )
            ORDER BY p.citations DESC NULLS LAST, p.year DESC NULLS LAST, p.id
            LIMIT :limit
            """),
            {"paper_id": paper_id, "limit": limit},
        )
    ).fetchall()

    nodes = [
        {
            "id": seed.id,
            "title": seed.title,
            "year": seed.year,
            "citations": int(seed.citations or 0),
            "role": "seed",
        }
    ]
    nodes.extend(
        {
            "id": row.id,
            "title": row.title,
            "year": row.year,
            "citations": int(row.citations or 0),
            "role": "reference",
        }
        for row in ref_rows
    )
    edges = [
        {
            "source": paper_id,
            "target": row.id,
            "type": "references",
        }
        for row in ref_rows
    ]
    return {
        "paper_id": paper_id,
        "nodes": nodes,
        "edges": edges,
        **QUALITY_PROVENANCE,
    }
