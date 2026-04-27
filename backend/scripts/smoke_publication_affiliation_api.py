"""
Smoke-test publication-time affiliation API response shapes.

Usage:
    cd backend
    .venv/bin/python -m scripts.smoke_publication_affiliation_api
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


def _get(client: httpx.Client, path: str, failures: list[str]) -> dict[str, Any] | None:
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


def _check_compare(
    data: dict[str, Any] | None,
    expected_type: str,
    failures: list[str],
) -> None:
    if data is None:
        return

    _require(
        data.get("comparison_type") == expected_type,
        f"{expected_type} compare has wrong comparison_type",
        failures,
    )
    entities = data.get("entities")
    _require(
        isinstance(entities, list) and len(entities) > 0,
        f"{expected_type} compare has no entities",
        failures,
    )
    if not isinstance(entities, list):
        return

    required_metric_keys = {
        "researchers",
        "contributions",
        "papers",
        "avg_paper_citations",
        "avg_h_index",
    }
    for entity in entities:
        metrics = entity.get("metrics") if isinstance(entity, dict) else None
        _require(
            isinstance(metrics, dict),
            f"{expected_type} compare entity has no metrics",
            failures,
        )
        if not isinstance(metrics, dict):
            continue
        missing = required_metric_keys - metrics.keys()
        _require(
            not missing,
            f"{expected_type} compare entity {entity.get('key')} missing metrics: {sorted(missing)}",
            failures,
        )


def _check_progress(data: dict[str, Any] | None, failures: list[str]) -> None:
    if data is None:
        return

    _require(data.get("type") == "country", "country progress has wrong type", failures)
    _require(data.get("entity") == "KR", "country progress has wrong entity", failures)
    trend = data.get("trend")
    current = data.get("current")
    _require(isinstance(trend, list), "country progress trend is not a list", failures)
    _require(isinstance(current, dict), "country progress current is not an object", failures)

    if isinstance(current, dict):
        for key in ("researcher_count", "contributions", "avg_citations"):
            _require(key in current, f"country progress current missing {key}", failures)

    if isinstance(trend, list) and trend:
        for key in ("year", "researcher_count", "contributions", "avg_citations"):
            _require(key in trend[0], f"country progress trend row missing {key}", failures)


def _check_leaderboard(data: dict[str, Any] | None, failures: list[str]) -> None:
    if data is None:
        return

    _require(data.get("type") == "country", "country leaderboard has wrong type", failures)
    entries = data.get("entries")
    _require(isinstance(entries, list), "country leaderboard entries is not a list", failures)
    if not isinstance(entries, list) or not entries:
        return

    first = entries[0]
    for key in (
        "rank",
        "key",
        "name",
        "researcher_count",
        "contributions",
        "papers",
        "total_citations",
        "avg_h_index",
    ):
        _require(key in first, f"country leaderboard entry missing {key}", failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    failures: list[str] = []

    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        _check_compare(
            _get(client, "/compare?type=country&entities=US,KR", failures),
            "country",
            failures,
        )
        _check_compare(
            _get(client, "/compare?type=institution&entities=MIT,Stanford", failures),
            "institution",
            failures,
        )
        _check_progress(
            _get(client, "/progress?type=country&entity=KR&years=10", failures),
            failures,
        )
        _check_leaderboard(
            _get(client, "/leaderboard?type=country&limit=20", failures),
            failures,
        )

    if failures:
        print("\nAPI smoke test failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nAPI smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
