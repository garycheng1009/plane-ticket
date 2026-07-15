from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from flight_tracker.config import load_config
from flight_tracker.history import (
    append_daily_quote,
    append_query_csv,
    load_history,
    matching_history,
    previous_price,
    stats,
    tracking_key,
    update_daily_lowest_csv,
)
from flight_tracker.notify import build_message, send_line_message, should_alert
from flight_tracker.sources import SOURCE_REGISTRY


def enabled_routes(config: dict[str, Any], route_id: str | None = None) -> list[dict[str, Any]]:
    routes = [route for route in config.get("routes", []) if route.get("enabled", True)]
    if route_id:
        routes = [route for route in routes if route["id"] == route_id]
    return routes


def best_quote(config: dict[str, Any], route: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
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
        return None, errors, []
    return min(filtered, key=lambda item: int(item["price"])), errors, sorted(filtered, key=lambda item: int(item["price"]))


def run(config_path: str, dry_run: bool = False, route_id: str | None = None) -> list[dict[str, Any]]:
    config = load_config(config_path)
    results = []
    for route in enabled_routes(config, route_id):
        quote, errors, alternatives = best_quote(config, route)
        if not quote:
            results.append({"route": route["name"], "status": "no_quote", "errors": errors})
            continue

        before_history = load_history(route["id"])
        quote_key = tracking_key(quote)
        before_same_query = [item for item in before_history if item.get("tracking_key") == quote_key]
        before_today = next((item for item in before_same_query if item.get("date")), None)
        if before_same_query:
            before_today = before_same_query[-1]
        history = append_daily_quote(route["id"], quote)
        query_history = matching_history(history, quote)
        saved_quote = query_history[-1]
        append_query_csv(route, quote, saved_quote)
        update_daily_lowest_csv(route, saved_quote)
        is_new_daily_low = (
            not before_today
            or before_today.get("date") != saved_quote.get("date")
            or int(quote["price"]) < int(before_today.get("price", 0))
        )
        summary = stats(query_history)
        yesterday = previous_price(query_history)
        message = build_message(route, quote, query_history, summary, yesterday, alternatives)
        alert = is_new_daily_low and should_alert(config, route, int(saved_quote["price"]), yesterday)
        line_sent = False
        if not dry_run and config.get("line", {}).get("enabled"):
            send_line_message(message, config)
            line_sent = True
        results.append(
            {
                "route": route["name"],
                "status": "ok",
                "alert": alert,
                "line_sent": line_sent,
                "new_daily_low": is_new_daily_low,
                "quote": quote,
                "alternatives": alternatives,
                "daily_low": saved_quote,
                "summary": summary,
                "message": message,
                "errors": errors,
            }
        )
    return results


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--route", help="Only run one route id, for example tokyo or osaka.")
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.dry_run, args.route), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
