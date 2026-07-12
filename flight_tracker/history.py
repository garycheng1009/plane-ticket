from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "prices"


def history_path(route_id: str) -> Path:
    return DATA_DIR / f"{route_id}.json"


def load_history(route_id: str) -> list[dict[str, Any]]:
    path = history_path(route_id)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def tracking_key(quote: dict[str, Any]) -> str:
    return "|".join(
        str(quote.get(key) or "")
        for key in ["origin", "destination", "departure_date", "return_date", "direct"]
    )


def matching_history(history: list[dict[str, Any]], quote: dict[str, Any]) -> list[dict[str, Any]]:
    key = tracking_key(quote)
    return [item for item in history if item.get("tracking_key") == key]


def append_daily_quote(route_id: str, quote: dict[str, Any], today: str | None = None) -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    day = today or date.today().isoformat()
    history = load_history(route_id)
    entry = {"date": day, **quote, "tracking_key": tracking_key(quote)}
    existing = next(
        (
            item
            for item in history
            if item.get("date") == day and item.get("tracking_key") == entry["tracking_key"]
        ),
        None,
    )
    if existing and int(existing.get("price", 0)) <= int(entry.get("price", 0)):
        entry = existing
    history = [
        item
        for item in history
        if not (item.get("date") == day and item.get("tracking_key") == entry["tracking_key"])
    ]
    history.append(entry)
    history.sort(key=lambda item: item["date"])
    with history_path(route_id).open("w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return history


def stats(history: list[dict[str, Any]], days: int = 30) -> dict[str, int | None]:
    recent = history[-days:]
    prices = [int(item["price"]) for item in recent if item.get("price")]
    if not prices:
        return {"average": None, "lowest": None, "current": None}
    return {
        "average": round(mean(prices)),
        "lowest": min(prices),
        "current": prices[-1],
    }


def previous_price(history: list[dict[str, Any]]) -> int | None:
    if len(history) < 2:
        return None
    return int(history[-2]["price"])
