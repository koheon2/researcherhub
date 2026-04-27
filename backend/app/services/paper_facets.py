from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


FACET_TYPES = ("aboutness", "method", "task", "application")

EMOJI_KEYWORDS: dict[str, str] = {
    "transformer": "⚡",
    "diffusion": "🌊",
    "gan": "🎨",
    "language": "💬",
    "vision": "👁️",
    "graph": "🕸️",
    "robot": "🦾",
    "speech": "🎙️",
    "medical": "🏥",
    "drug": "💊",
    "recommendation": "🎯",
    "autonomous": "🚗",
    "code": "⌨️",
}


def normalize_facet_text(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\s\-]+", " ", value)
    value = re.sub(r"[\-_]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _display_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return value


@lru_cache(maxsize=1)
def load_facet_seed_config() -> dict[str, list[dict]]:
    path = Path(__file__).resolve().parent.parent.parent / "data" / "paper_facet_seeds.json"
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _facet_entries() -> dict[str, list[dict]]:
    config = load_facet_seed_config()
    out: dict[str, list[dict]] = {}
    for facet_type in FACET_TYPES:
        entries = []
        for raw in config.get(facet_type, []):
            aliases = raw.get("aliases", [])
            value = _display_text(raw["value"])
            entries.append(
                {
                    "value": value,
                    "value_norm": normalize_facet_text(value),
                    "aliases": aliases,
                    "alias_norms": [normalize_facet_text(alias) for alias in aliases],
                }
            )
        out[facet_type] = entries
    return out


@lru_cache(maxsize=1)
def _alias_maps() -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    for facet_type, entries in _facet_entries().items():
        facet_map: dict[str, str] = {}
        for entry in entries:
            facet_map[entry["value_norm"]] = entry["value"]
            for alias_norm in entry["alias_norms"]:
                facet_map[alias_norm] = entry["value"]
        maps[facet_type] = facet_map
    return maps


@lru_cache(maxsize=1)
def _compiled_alias_patterns() -> dict[str, re.Pattern[str] | None]:
    compiled: dict[str, re.Pattern[str] | None] = {}
    for facet_type, entries in _facet_entries().items():
        aliases: set[str] = set()
        for entry in entries:
            for alias in [entry["value"], *entry["aliases"]]:
                normalized = normalize_facet_text(alias)
                if not normalized:
                    continue
                aliases.add(normalized)
        if not aliases:
            compiled[facet_type] = None
            continue
        alternatives = [
            re.escape(alias).replace(r"\ ", r"\s+")
            for alias in sorted(aliases, key=len, reverse=True)
        ]
        compiled[facet_type] = re.compile(
            rf"(?<![a-z0-9])(?:{'|'.join(alternatives)})(?![a-z0-9])"
        )
    return compiled


def get_facet_emoji(value: str) -> str:
    normalized = normalize_facet_text(value)
    for keyword, emoji in EMOJI_KEYWORDS.items():
        if keyword in normalized:
            return emoji
    return "🔬"


def slugify_facet(value: str) -> str:
    normalized = normalize_facet_text(value)
    return normalized.replace(" ", "-")


def canonicalize_facet_query(query: str) -> tuple[str, list[str]]:
    normalized = normalize_facet_text(query)
    matched_axes: list[str] = []
    canonical = ""
    for facet_type, alias_map in _alias_maps().items():
        if normalized in alias_map:
            canonical = alias_map[normalized]
            matched_axes.append(facet_type)

    if canonical:
        return canonical, matched_axes

    for facet_type, entries in _facet_entries().items():
        for entry in entries:
            candidates = [entry["value_norm"], *entry["alias_norms"]]
            if any(candidate and candidate in normalized for candidate in candidates):
                if not canonical:
                    canonical = entry["value"]
                matched_axes.append(facet_type)
                break

    return (canonical or _display_text(query), matched_axes)


def canonicalize_source_value(raw_value: str, facet_type: str) -> str:
    normalized = normalize_facet_text(raw_value)
    alias_map = _alias_maps().get(facet_type, {})
    if normalized in alias_map:
        return alias_map[normalized]

    for entry in _facet_entries().get(facet_type, []):
        candidates = [entry["value_norm"], *entry["alias_norms"]]
        if any(candidate and candidate in normalized for candidate in candidates):
            return entry["value"]

    return _display_text(raw_value)


def extract_keyword_facets(text: str, facet_type: str) -> list[str]:
    normalized = normalize_facet_text(text)
    if not normalized:
        return []

    matches: list[str] = []
    seen: set[str] = set()
    alias_map = _alias_maps().get(facet_type, {})
    pattern = _compiled_alias_patterns().get(facet_type)
    if not pattern:
        return matches

    for match in pattern.finditer(normalized):
        value = alias_map.get(normalize_facet_text(match.group(0)))
        if not value or value in seen:
            continue
        seen.add(value)
        matches.append(value)
    return matches


def build_paper_facets(
    *,
    title: str | None,
    abstract: str | None,
    subfield: str | None,
    topic: str | None,
) -> dict[str, list[dict]]:
    combined_text = " ".join(part for part in [title or "", abstract or ""] if part).strip()
    facets: dict[str, list[dict]] = {facet_type: [] for facet_type in FACET_TYPES}
    seen: dict[str, set[str]] = {facet_type: set() for facet_type in FACET_TYPES}

    def add(
        facet_type: str,
        facet_value: str,
        source: str,
        confidence: float,
    ) -> None:
        if facet_value in seen[facet_type]:
            return
        seen[facet_type].add(facet_value)
        facets[facet_type].append(
            {
                "facet_value": facet_value,
                "source": source,
                "confidence": confidence,
                "rank": len(facets[facet_type]) + 1,
            }
        )

    if subfield and subfield.strip():
        add(
            "aboutness",
            canonicalize_source_value(subfield, "aboutness"),
            "paper_subfield",
            0.9,
        )
    if topic and topic.strip():
        add(
            "aboutness",
            canonicalize_source_value(topic, "aboutness"),
            "paper_topic",
            0.75,
        )

    for facet_type in ("method", "task", "application"):
        for facet_value in extract_keyword_facets(combined_text, facet_type):
            add(facet_type, facet_value, "keyword_match", 0.55)

    return facets
