"""
Smoke-test paper facet API responses.

Usage:
    cd backend
    .venv/bin/python -m scripts.smoke_paper_facet_api
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx


DEFAULT_BASE_URL = "http://localhost:8000/api"


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _get(client: httpx.Client, path: str, failures: list[str]) -> dict[str, Any] | list[Any] | None:
    try:
        response = client.get(path)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        failures.append(f"GET {path} failed: {exc}")
        return None
    try:
        data = response.json()
    except ValueError as exc:
        failures.append(f"GET {path} returned non-JSON response: {exc}")
        return None
    print(f"OK {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    failures: list[str] = []
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=20.0) as client:
        trending = _get(client, "/trending?limit=20", failures)
        if isinstance(trending, list) and trending:
            first = trending[0]
            for key in (
                "topic_id",
                "topic_name",
                "growth_pct",
                "paper_count",
                "contributions",
                "dominant_axis",
                "emoji",
                "quality_filtered",
                "quality_policy",
            ):
                _require(key in first, f"trending entry missing {key}", failures)

        method_trending = _get(client, "/trending?axis=method&limit=20", failures)
        if isinstance(method_trending, list) and method_trending:
            first = method_trending[0]
            _require(first.get("dominant_axis") == "method", "method trending dominant_axis mismatch", failures)

        compare = _get(client, "/compare?type=topic&entities=transformer,diffusion", failures)
        if isinstance(compare, dict):
            _require(compare.get("quality_filtered") is True, "topic compare is not quality-filtered", failures)
            _require(compare.get("quality_policy") == "conservative_v0", "topic compare quality policy mismatch", failures)
            entities = compare.get("entities", [])
            _require(isinstance(entities, list), "topic compare entities is not a list", failures)
            if isinstance(entities, list) and entities:
                metrics = entities[0].get("metrics", {})
                for key in (
                    "papers",
                    "contributions",
                    "avg_paper_citations",
                    "total_citations",
                    "avg_h_index",
                ):
                    _require(key in metrics, f"topic compare metrics missing {key}", failures)
                _require("matched_axis" in entities[0], "topic compare entity missing matched_axis", failures)

        progress = _get(client, "/progress?type=field&entity=transformer&years=10", failures)
        if isinstance(progress, dict):
            _require(progress.get("quality_filtered") is True, "field progress is not quality-filtered", failures)
            _require(progress.get("quality_policy") == "conservative_v0", "field progress quality policy mismatch", failures)
            current = progress.get("current", {})
            _require("contributions" in current, "field progress current missing contributions", failures)

        search = _get(client, "/search/universal?q=%EB%94%94%ED%93%A8%EC%A0%84%20%EC%97%B0%EA%B5%AC%EC%9E%90%20%EC%88%98", failures)
        if isinstance(search, dict):
            _require(search.get("intent") == "stats", "search universal did not return stats intent", failures)
            _require("answer" in search, "search universal stats missing answer", failures)

    if failures:
        print("\nPaper facet API smoke test failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nPaper facet API smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
