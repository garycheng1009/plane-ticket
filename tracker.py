from __future__ import annotations

import argparse
import json
from typing import Any

from flight_tracker.config import load_config
from flight_tracker.history import append_daily_quote, previous_price, stats
from flight_tracker.notify import build_message, send_line_message, should_alert
from flight_tracker.sources import SOURCE_REGISTRY


def enabled_routes(config: dict[str, Any], route_id: str | None = None) -> list[dict[str, Any]]:
    routes = [route for route in config.get("routes", []) if route.get("enabled", True)]
    if route_id:
        routes = [route for route in routes if route["id"] == route_id]
    return routes


def best_quote(config: dict[str, Any], route: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    errors = []
    source_names = config.get("sources", {}).get("enabled", ["mock"])
    if config.get("sources", {}).get("fallback_to_mock") and "mock" not in source_names:
        source_names = [*source_names, "mock"]

    quotes = []
    for source_name in source_names:
        source_cls = SOURCE_REGISTRY.get(source_name)
        if not source_cls:
            errors.append(f"Unknown source: {source_name}")
            continue
        try:
            quotes.extend(source_cls().search(config, route))
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")

    include = set(config.get("airlines", {}).get("include") or [])
    exclude = set(config.get("airlines", {}).get("exclude") or [])
    filtered = []
    for quote in quotes:
        data = quote.normalized()
        airline = data.get("airline", "")
        if include and airline not in include and airline != "網站最低價":
            continue
        if airline in exclude:
            continue
        filtered.append(data)

    if not filtered:
        return None, errors
    return min(filtered, key=lambda item: int(item["price"])), errors


def run(config_path: str, dry_run: bool = False, route_id: str | None = None) -> list[dict[str, Any]]:
    config = load_config(config_path)
    results = []
    for route in enabled_routes(config, route_id):
        quote, errors = best_quote(config, route)
        if not quote:
            results.append({"route": route["name"], "status": "no_quote", "errors": errors})
            continue

        history = append_daily_quote(route["id"], quote)
        summary = stats(history)
        yesterday = previous_price(history)
        message = build_message(route, quote, history, summary, yesterday)
        alert = should_alert(config, route, int(quote["price"]), yesterday)
        if alert and not dry_run:
            send_line_message(message, config)
        results.append(
            {
                "route": route["name"],
                "status": "ok",
                "alert": alert,
                "quote": quote,
                "summary": summary,
                "message": message,
                "errors": errors,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--route", help="Only run one route id, for example tokyo or osaka.")
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.dry_run, args.route), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
