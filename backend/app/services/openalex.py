"""
OpenAlex API 클라이언트.
polite pool 사용을 위해 mailto 파라미터를 자동으로 붙입니다.
"""
import random
import httpx
from app.core.config import settings

BASE_URL = "https://api.openalex.org"

# ── AI/CS 토픽 필터 ────────────────────────────────────────────────────────────
# T12072: Machine Learning, T11636: Deep Learning, T10875: NLP,
# T12271: Computer Vision, T13130: Reinforcement Learning,
# T10559: Graph Neural Networks, T12133: Generative Models,
# T10994: Robotics, T11408: Federated Learning, T12076: Data Science
# "Artificial Intelligence" subfield에 속하는 전체 77개 topic ID
# python3로 OpenAlex /topics API 전수 조회해서 추출한 값
AI_TOPIC_IDS = (
    "T12157|T13650|T10181|T14335|T10320|T13398|T13734|T10215|T10028|T13623"
    "|T10020|T10682|T10126|T10201|T13559|T10237|T10764|T10862|T11512|T11010"
    "|T11975|T11269|T10100|T11130|T10664|T10639|T11902|T10711|T10820|T11689"
    "|T13674|T10456|T12031|T11901|T13018|T11303|T10462|T12128|T11276|T10906"
    "|T11273|T11574|T12026|T14064|T11307|T12260|T10951|T13083|T12262|T11424"
    "|T13702|T12535|T11598|T12805|T14381|T10637|T11652|T12072|T11550|T12611"
    "|T13851|T13898|T14351|T12380|T11612|T12814|T13904|T12761|T13629|T12131"
    "|T13062|T12676|T13935|T14413|T14175|T13567|T13514"
)

# ── CS/AI 화이트리스트 ─────────────────────────────────────────────────────────
# primary_topic의 subfield가 이 목록에 있어야 수집
# EE·Statistics·Applied Math 제거 (너무 넓어서 비CS 연구자 대량 포함됨)
CS_AI_SUBFIELDS = {
    "Artificial Intelligence",
    "Computer Vision and Pattern Recognition",
    "Natural Language Processing",
    "Human-Computer Interaction",
    "Computational Theory and Mathematics",
    "Information Systems",
    "Software Engineering",
    "Computer Networks and Communications",
    "Hardware and Architecture",
    "Signal Processing",
    "Robotics",
    "General Computer Science",
}

# ── 표시 이름 정규화 (긴 subfield → 짧은 레이블) ─────────────────────────────
FIELD_LABEL_MAP: dict[str, str] = {
    "Artificial Intelligence":                  "AI",
    "Computer Vision and Pattern Recognition":  "Computer Vision",
    "Natural Language Processing":              "NLP",
    "Human-Computer Interaction":               "HCI",
    "Computational Theory and Mathematics":     "Theory & Math",
    "Information Systems":                      "Information Systems",
    "Software Engineering":                     "Software Engineering",
    "Computer Networks and Communications":     "Networks",
    "Hardware and Architecture":                "Hardware",
    "Signal Processing":                        "Signal Processing",
    "Robotics":                                 "Robotics",
    "General Computer Science":                 "Computer Science",
}

# ── 유명 AI 연구 기관 OpenAlex ID ─────────────────────────────────────────────
TOP_AI_INST_IDS: list[str] = [
    # 북미 대학
    "I63966007",   # MIT
    "I97018004",   # Stanford University
    "I47524757",   # Carnegie Mellon University
    "I95457486",   # UC Berkeley
    "I136199984",  # Harvard University
    "I185261750",  # Princeton University
    "I49861081",   # Columbia University
    "I86987016",   # New York University
    "I40347166",   # University of Michigan
    "I74973139",   # UIUC
    "I130769515",  # University of Washington
    "I27837315",   # University of Toronto
    "I118515056",  # Université de Montréal
    "I148818662",  # University of British Columbia
    # 유럽
    "I33213144",   # University of Oxford
    "I14377782",   # University of Cambridge
    "I203069964",  # ETH Zurich
    "I19820366",   # EPFL
    "I162148367",  # UCL
    "I45129253",   # Imperial College London
    "I4210158659", # INRIA
    # 아시아
    "I204338459",  # Tsinghua University
    "I11748596",   # Peking University
    "I26678566",   # National University of Singapore
    "I173261297",  # Seoul National University
    # 산업 연구소
    "I1291924",    # Google / Google Research
    "I1299303",    # Microsoft Research
    "I4210100761", # OpenAI
    "I1313034",    # Google DeepMind
    "I4210117493", # Meta AI / FAIR
    "I4210119019", # Apple
    "I4210136034", # Amazon AWS / Amazon Science
    "I205966183",  # IBM Research
]


async def fetch_ai_researchers(
    per_page: int = 200,
    cursor: str = "*",
) -> tuple[list[dict], str | None]:
    """
    AI 분야 연구자를 cursor 기반으로 가져옵니다.
    primary_topic이 Computer Science 필드인 연구자만 대상.
    Returns: (results, next_cursor)  — next_cursor가 None이면 마지막 페이지
    """
    params = {
        # AI 토픽 + 최소 인용수 50 (0인 연구자 대량 중복 방지, cursor 안정화)
        "filter": f"topics.id:{AI_TOPIC_IDS},cited_by_count:>50",
        "sort": "cited_by_count:desc",
        "per_page": per_page,
        "cursor": cursor,
        "mailto": settings.OPENALEX_EMAIL,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE_URL}/authors", params=params)
        r.raise_for_status()
        data = r.json()
        next_cursor = data.get("meta", {}).get("next_cursor")
        return data.get("results", []), next_cursor


async def fetch_researchers_by_institution(
    inst_id: str,
    per_page: int = 50,
) -> list[dict]:
    """특정 기관의 AI 연구자를 인용 수 기준으로 가져옵니다."""
    params = {
        "filter": f"last_known_institutions.id:{inst_id},topics.id:{AI_TOPIC_IDS}",
        "sort": "cited_by_count:desc",
        "per_page": per_page,
        "page": 1,
        "mailto": settings.OPENALEX_EMAIL,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE_URL}/authors", params=params)
        if r.status_code != 200:
            return []
        return r.json().get("results", [])


async def fetch_institution_coords(institution_ids: list[str]) -> dict[str, tuple[float, float]]:
    """
    기관 ID 목록을 배치로 조회해서 {institution_id: (lat, lng)} 딕셔너리를 반환합니다.
    """
    coords: dict[str, tuple[float, float]] = {}
    if not institution_ids:
        return coords

    unique_ids = list(set(institution_ids))
    batch_size = 50

    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(unique_ids), batch_size):
            batch = unique_ids[i : i + batch_size]
            short_ids = [bid.split("/")[-1] for bid in batch]
            filter_str = "|".join(short_ids)
            params = {
                "filter": f"openalex_id:{filter_str}",
                "per_page": batch_size,
                "select": "id,geo",
                "mailto": settings.OPENALEX_EMAIL,
            }
            r = await client.get(f"{BASE_URL}/institutions", params=params)
            if r.status_code != 200:
                continue
            for inst in r.json().get("results", []):
                inst_id = inst["id"].split("/")[-1]
                geo = inst.get("geo") or {}
                lat = geo.get("latitude")
                lng = geo.get("longitude")
                if lat is not None and lng is not None:
                    coords[inst_id] = (lat, lng)

    return coords


async def fetch_works_institution(
    client: "httpx.AsyncClient",
    author_id: str,
    n_works: int = 10,
) -> dict | None:
    """
    연구자 본인의 최근 논문 n편에서 직접 명시한 소속 기관 반환 (빈도 1위).
    공저자 기관이 섞이지 않도록 authorship.author.id 로 필터.
    반환: {"inst_id": str, "inst_name": str, "country": str} | None
    """
    import asyncio
    from collections import Counter

    params = {
        "filter":   f"author.id:{author_id}",
        "sort":     "publication_date:desc",
        "per_page": n_works,
        "select":   "authorships",
        "mailto":   settings.OPENALEX_EMAIL,
    }
    try:
        r = await client.get(f"{BASE_URL}/works", params=params, timeout=20)
        r.raise_for_status()
        works = r.json().get("results", [])
    except Exception:
        return None

    short_id = author_id.split("/")[-1]
    counter: Counter = Counter()
    meta: dict[str, dict] = {}

    for work in works:
        for auth in work.get("authorships", []):
            if (auth.get("author") or {}).get("id", "").split("/")[-1] != short_id:
                continue
            for inst in auth.get("institutions", []):
                iid = (inst.get("id") or "").split("/")[-1]
                if not iid:
                    continue
                counter[iid] += 1
                if iid not in meta:
                    meta[iid] = {
                        "inst_id":   iid,
                        "inst_name": inst.get("display_name", ""),
                        "country":   inst.get("country_code", ""),
                    }

    if not counter:
        return None
    best_id = counter.most_common(1)[0][0]
    return meta[best_id]


async def fetch_works_institutions_batch(
    author_ids: list[str],
    concurrency: int = 10,
) -> dict[str, dict | None]:
    """
    여러 연구자의 works 기반 소속을 병렬 조회.
    반환: {author_id: {"inst_id", "inst_name", "country"} | None}
    """
    import asyncio
    import httpx as _httpx

    semaphore = asyncio.Semaphore(concurrency)
    results: dict[str, dict | None] = {}

    async def _one(client, aid: str) -> None:
        async with semaphore:
            results[aid] = await fetch_works_institution(client, aid)

    async with _httpx.AsyncClient(timeout=25) as client:
        await asyncio.gather(*[_one(client, aid) for aid in author_ids])

    return results


def parse_author(
    raw: dict,
    inst_coords: dict[str, tuple[float, float]] | None = None,
) -> dict | None:
    """
    OpenAlex author 응답을 DB 모델 형식으로 변환합니다.
    CS/AI 분야가 아닌 연구자는 None을 반환합니다.
    """
    topics = raw.get("topics", [])

    # ── CS/AI 분야 판별: topics[0] (primary topic) 기준 ───────────────────
    # OpenAlex는 topics를 빈도/관련성 순으로 정렬 → topics[0]이 primary
    # primary_topic 별도 필드는 비어 있는 경우가 많아 topics[0] 사용
    primary = topics[0] if topics else {}
    primary_field = primary.get("field", {}).get("display_name", "")
    primary_sf = primary.get("subfield", {}).get("display_name", "")

    # primary topic이 Computer Science 필드이고, subfield가 화이트리스트에 있어야 수집
    if primary_field != "Computer Science" or primary_sf not in CS_AI_SUBFIELDS:
        return None

    field = FIELD_LABEL_MAP.get(primary_sf, primary_sf)

    # ── 기관 좌표 ─────────────────────────────────────────────────────────────
    inst = (raw.get("last_known_institutions") or [{}])[0]
    country = inst.get("country_code")
    inst_id = inst.get("id", "").split("/")[-1] if inst.get("id") else None

    base_coords: tuple[float, float] | None = None
    if inst_coords and inst_id and inst_id in inst_coords:
        base_coords = inst_coords[inst_id]

    if base_coords:
        rng = random.Random(hash(raw.get("id", "")) % 10000)
        lat = base_coords[0] + rng.uniform(-0.003, 0.003)
        lng = base_coords[1] + rng.uniform(-0.003, 0.003)
    else:
        lat = None
        lng = None

    return {
        "id": raw["id"].split("/")[-1],
        "name": raw.get("display_name", ""),
        "institution": inst.get("display_name"),
        "country": country,
        "lat": lat,
        "lng": lng,
        "citations": raw.get("cited_by_count", 0),
        "h_index": raw.get("summary_stats", {}).get("h_index", 0),
        "works_count": raw.get("works_count", 0),
        "recent_papers": raw.get("summary_stats", {}).get("2yr_works_count", 0),
        "field": field,
        "umap_x": None,
        "umap_y": None,
        "openalex_url": raw.get("id"),
    }
