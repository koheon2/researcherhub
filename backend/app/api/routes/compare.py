"""VS Comparison endpoint — country / topic / institution / researcher battles."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import distinct, select, func, text
from app.db.database import get_db
from app.models.paper import Paper, PaperAuthorAffiliation, PaperFacet
from app.models.researcher import Researcher
from app.services.paper_facets import canonicalize_facet_query, get_facet_emoji

router = APIRouter(prefix="/compare", tags=["compare"])

COUNTRY_META: dict[str, tuple[str, str]] = {
    "KR": ("South Korea", "🇰🇷"), "US": ("United States", "🇺🇸"),
    "CN": ("China", "🇨🇳"),       "JP": ("Japan", "🇯🇵"),
    "DE": ("Germany", "🇩🇪"),     "GB": ("United Kingdom", "🇬🇧"),
    "FR": ("France", "🇫🇷"),      "CA": ("Canada", "🇨🇦"),
    "AU": ("Australia", "🇦🇺"),   "IN": ("India", "🇮🇳"),
    "SG": ("Singapore", "🇸🇬"),   "CH": ("Switzerland", "🇨🇭"),
    "NL": ("Netherlands", "🇳🇱"), "SE": ("Sweden", "🇸🇪"),
    "IL": ("Israel", "🇮🇱"),      "BR": ("Brazil", "🇧🇷"),
    "IT": ("Italy", "🇮🇹"),       "ES": ("Spain", "🇪🇸"),
    "TW": ("Taiwan", "🇹🇼"),      "RU": ("Russia", "🇷🇺"),
    "HK": ("Hong Kong", "🇭🇰"),   "NZ": ("New Zealand", "🇳🇿"),
    "FI": ("Finland", "🇫🇮"),     "NO": ("Norway", "🇳🇴"),
    "DK": ("Denmark", "🇩🇰"),     "BE": ("Belgium", "🇧🇪"),
    "AT": ("Austria", "🇦🇹"),     "PT": ("Portugal", "🇵🇹"),
    "PL": ("Poland", "🇵🇱"),      "CZ": ("Czech Republic", "🇨🇿"),
    "MX": ("Mexico", "🇲🇽"),      "AR": ("Argentina", "🇦🇷"),
    "ZA": ("South Africa", "🇿🇦"), "EG": ("Egypt", "🇪🇬"),
    "IR": ("Iran", "🇮🇷"),        "SA": ("Saudi Arabia", "🇸🇦"),
    "AE": ("UAE", "🇦🇪"),         "TR": ("Turkey", "🇹🇷"),
    "GR": ("Greece", "🇬🇷"),      "HU": ("Hungary", "🇭🇺"),
    "RO": ("Romania", "🇷🇴"),     "UA": ("Ukraine", "🇺🇦"),
    "MY": ("Malaysia", "🇲🇾"),    "TH": ("Thailand", "🇹🇭"),
    "PH": ("Philippines", "🇵🇭"), "VN": ("Vietnam", "🇻🇳"),
    "ID": ("Indonesia", "🇮🇩"),   "PK": ("Pakistan", "🇵🇰"),
    "BD": ("Bangladesh", "🇧🇩"),  "NG": ("Nigeria", "🇳🇬"),
    "ET": ("Ethiopia", "🇪🇹"),    "KE": ("Kenya", "🇰🇪"),
}

TOPIC_EMOJIS: dict[str, str] = {
    "transformer": "🤖", "diffusion": "🌊", "gan": "🎨", "bert": "📚",
    "llm": "💬", "vision": "👁️", "nlp": "🗣️", "reinforcement": "🎮",
    "graph": "🕸️", "quantum": "⚛️", "federated": "🔗", "protein": "🧬",
    "robot": "🦾", "speech": "🎙️", "video": "🎬", "medical": "🏥",
    "autonomous": "🚗", "climate": "🌍", "drug": "💊",
}

INST_EMOJIS: dict[str, str] = {
    "mit": "🏛️", "stanford": "🌲", "cmu": "🔴", "harvard": "🎓",
    "oxford": "📖", "cambridge": "🎭", "berkeley": "🐻", "toronto": "🍁",
    "tokyo": "🗼", "seoul": "🏙️", "kaist": "⚡", "postech": "🔷",
    "tsinghua": "🐉", "peking": "🔴", "ethz": "🇨🇭", "epfl": "⛰️",
    "yonsei": "🌀", "korea university": "🏫", "snu": "🎆",
    "michigan": "💛", "princeton": "🐯", "yale": "🔵",
    "columbia": "🗽", "caltech": "🔭", "ucl": "🇬🇧",
}

INSTITUTION_ALIASES: dict[str, str] = {
    "mit": "Massachusetts Institute of Technology",
    "massachusetts institute of technology": "Massachusetts Institute of Technology",
    "stanford": "Stanford University",
    "stanford university": "Stanford University",
    "cmu": "Carnegie Mellon University",
    "carnegie mellon": "Carnegie Mellon University",
    "kaist": "Korea Advanced Institute of Science and Technology",
    "snu": "Seoul National University",
}


@router.get("")
async def compare(
    type: str   = Query(..., description="country | topic | institution | researcher"),
    entities: str = Query(..., description="콤마 구분 비교 대상"),
    db: AsyncSession = Depends(get_db),
):
    entity_list = [e.strip() for e in entities.split(",") if e.strip()][:3]
    if type == "country":      return await _countries(entity_list, db)
    if type == "topic":        return await _topics(entity_list, db)
    if type == "institution":  return await _institutions(entity_list, db)
    if type == "researcher":   return await _researchers(entity_list, db)
    return {"error": "unknown type"}


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _base_stats(db: AsyncSession, where_clause):
    """Returns (researchers, total_citations, avg_citations, avg_h_index)."""
    row = await db.execute(
        select(
            func.count().label("researchers"),
            func.coalesce(func.sum(Researcher.citations), 0).label("total_citations"),
            func.coalesce(func.avg(Researcher.citations), 0).label("avg_citations"),
            func.coalesce(func.avg(Researcher.h_index), 0).label("avg_h_index"),
        ).where(where_clause)
    )
    return row.fetchone()


async def _top_field(db: AsyncSession, where_clause) -> str:
    row = await db.execute(
        select(Researcher.field, func.count().label("n"))
        .where(where_clause).where(Researcher.field.isnot(None))
        .group_by(Researcher.field).order_by(func.count().desc()).limit(1)
    )
    r = row.fetchone()
    return r.field if r else "—"


async def _top_researcher(db: AsyncSession, where_clause) -> dict | None:
    row = await db.execute(
        select(Researcher.name, Researcher.citations, Researcher.institution)
        .where(where_clause).order_by(Researcher.citations.desc()).limit(1)
    )
    r = row.fetchone()
    return {"name": r.name, "citations": r.citations, "institution": r.institution} if r else None


async def _affiliation_stats(db: AsyncSession, where_clause):
    """Returns contribution-weighted paper stats for publication-time affiliations."""
    row = await db.execute(
        select(
            func.count(PaperAuthorAffiliation.id).label("contributions"),
            func.count(distinct(PaperAuthorAffiliation.paper_id)).label("papers"),
            func.coalesce(func.sum(Paper.citations), 0).label("total_citations"),
            func.coalesce(func.avg(Paper.citations), 0).label("avg_paper_citations"),
        )
        .join(Paper, Paper.id == PaperAuthorAffiliation.paper_id)
        .where(where_clause)
    )
    return row.fetchone()


async def _top_affiliation_field(db: AsyncSession, where_clause) -> str:
    row = await db.execute(
        select(Paper.subfield, func.count(PaperAuthorAffiliation.id).label("n"))
        .join(Paper, Paper.id == PaperAuthorAffiliation.paper_id)
        .where(where_clause)
        .where(Paper.subfield.isnot(None))
        .group_by(Paper.subfield)
        .order_by(func.count(PaperAuthorAffiliation.id).desc())
        .limit(1)
    )
    r = row.fetchone()
    return r.subfield if r else "—"


async def _top_affiliation_researcher(db: AsyncSession, where_clause) -> dict | None:
    row = await db.execute(
        select(
            PaperAuthorAffiliation.author_name,
            func.coalesce(func.sum(Paper.citations), 0).label("citations"),
            func.max(PaperAuthorAffiliation.institution_name).label("institution"),
        )
        .join(Paper, Paper.id == PaperAuthorAffiliation.paper_id)
        .where(where_clause)
        .where(PaperAuthorAffiliation.author_name.isnot(None))
        .group_by(PaperAuthorAffiliation.author_id, PaperAuthorAffiliation.author_name)
        .order_by(func.sum(Paper.citations).desc())
        .limit(1)
    )
    r = row.fetchone()
    if not r:
        return None
    return {
        "name": r.author_name,
        "citations": int(r.citations or 0),
        "institution": r.institution,
    }


# ── Country ───────────────────────────────────────────────────────────────────

async def _countries(codes: list[str], db: AsyncSession) -> dict:
    results = []
    stats_rows = await db.execute(
        text("""
        SELECT *
        FROM publication_country_stats
        WHERE country_code = ANY(:codes)
        """),
        {"codes": [code.upper() for code in codes]},
    )
    stats_by_code = {row.country_code: row for row in stats_rows.fetchall()}
    for code in codes:
        code = code.upper()
        name, emoji = COUNTRY_META.get(code, (code, "🏳️"))
        s = stats_by_code.get(code)
        contributions = int(s.contributions or 0) if s else 0
        total_citations = int(s.total_citations or 0) if s else 0
        avg_paper_citations = round(float(s.avg_paper_citations or 0), 1) if s else 0
        results.append({
            "key": code, "name": name, "emoji": emoji,
            "metrics": {
                "researchers":           contributions,
                "contributions":         contributions,
                "papers":                int(s.papers or 0) if s else 0,
                "total_citations":       total_citations,
                "avg_citations":         avg_paper_citations,
                "avg_paper_citations":   avg_paper_citations,
                "avg_h_index":           0,
                "top_field":             s.top_field if s and s.top_field else "—",
            },
            "top_researcher": None,
        })
    return {"comparison_type": "country", "entities": results}


# ── Topic ─────────────────────────────────────────────────────────────────────

async def _topics(topics: list[str], db: AsyncSession) -> dict:
    results = []
    for topic in topics:
        canonical, matched_axes = canonicalize_facet_query(topic)
        axis_filter = matched_axes or ["aboutness", "method", "task", "application"]
        stats_row = await db.execute(
            text("""
            SELECT
                facet_type,
                paper_count,
                total_citations
            FROM paper_facet_summary
            WHERE lower(facet_value) = lower(:facet_value)
              AND facet_type = ANY(:axes)
            ORDER BY paper_count DESC, facet_type
            LIMIT 1
            """),
            {"facet_value": canonical, "axes": axis_filter},
        )
        stats = stats_row.fetchone()

        papers = int(stats.paper_count or 0) if stats else 0
        total_citations = int(stats.total_citations or 0) if stats else 0
        avg_paper_citations = round(total_citations / papers, 1) if papers else 0
        results.append({
            "key": topic, "name": canonical, "emoji": get_facet_emoji(canonical),
            "metrics": {
                "researchers":         papers,
                "contributions":       papers,
                "papers":              papers,
                "total_citations":     total_citations,
                "avg_citations":       avg_paper_citations,
                "avg_paper_citations": avg_paper_citations,
                "avg_h_index":         0,
            },
            "matched_axis": stats.facet_type if stats else (matched_axes[0] if matched_axes else "—"),
            "top_cluster": canonical,
            "top_researcher": None,
        })
    return {"comparison_type": "topic", "entities": results}


# ── Institution ───────────────────────────────────────────────────────────────

async def _institutions(names: list[str], db: AsyncSession) -> dict:
    results = []
    normalized_names = [
        INSTITUTION_ALIASES.get(name.lower(), name)
        for name in names
    ]
    stats_rows = await db.execute(
        text("""
        SELECT *
        FROM publication_institution_stats
        WHERE institution_name = ANY(:names)
        """),
        {"names": normalized_names},
    )
    stats_by_name = {row.institution_name: row for row in stats_rows.fetchall()}
    for name in names:
        kw = name.lower()
        canonical_name = INSTITUTION_ALIASES.get(kw)
        emoji = next((v for k, v in INST_EMOJIS.items() if k in kw), "🏫")
        if canonical_name:
            display_name = canonical_name
        else:
            display_name = name
        s = stats_by_name.get(display_name)
        contributions = int(s.contributions or 0) if s else 0
        total_citations = int(s.total_citations or 0) if s else 0
        avg_paper_citations = round(float(s.avg_paper_citations or 0), 1) if s else 0
        results.append({
            "key": name, "name": display_name, "emoji": emoji,
            "metrics": {
                "researchers":           contributions,
                "contributions":         contributions,
                "papers":                int(s.papers or 0) if s else 0,
                "total_citations":       total_citations,
                "avg_citations":         avg_paper_citations,
                "avg_paper_citations":   avg_paper_citations,
                "avg_h_index":           0,
                "top_field":             s.top_field if s and s.top_field else "—",
            },
            "top_researcher": None,
        })
    return {"comparison_type": "institution", "entities": results}


# ── Researcher ────────────────────────────────────────────────────────────────

async def _researchers(names: list[str], db: AsyncSession) -> dict:
    results = []
    for name in names:
        last = name.split()[-1].lower()
        row = await db.execute(
            select(Researcher)
            .where(func.lower(Researcher.name).contains(last))
            .order_by(Researcher.citations.desc()).limit(1)
        )
        r = row.scalar_one_or_none()
        results.append({
            "key": name,
            "name": r.name if r else name,
            "emoji": "👨‍🔬",
            "metrics": {
                "citations":   r.citations   or 0 if r else 0,
                "h_index":     r.h_index     or 0 if r else 0,
                "works_count": r.works_count or 0 if r else 0,
            },
            "field":       r.field       if r else None,
            "institution": r.institution if r else None,
            "id":          r.id          if r else None,
        })
    return {"comparison_type": "researcher", "entities": results}
