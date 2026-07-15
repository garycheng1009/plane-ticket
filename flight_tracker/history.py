from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from flight_tracker.timezone import to_taipei


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
DATA_DIR = DATA_ROOT / "prices"
QUERY_CSV = DATA_ROOT / "flight_price_queries.csv"
DAILY_LOWEST_CSV = DATA_ROOT / "flight_daily_lowest.csv"

AIRLINE_DISPLAY_NAMES = {
    "星宇": "星宇航空",
    "長榮": "長榮航空",
    "華航": "中華航空",
    "國泰": "國泰航空",
    "ANA": "全日空",
    "JAL": "日本航空",
    "United": "聯合航空",
    "Peach": "樂桃航空",
}

QUERY_FIELDS = [
    "query_datetime",
    "route_id",
    "route_name",
    "search_start_date",
    "search_end_date",
    "outbound_airline",
    "outbound_time",
    "return_airline",
    "return_time",
    "current_price",
    "today_lowest_price",
    "tracking_key",
]

DAILY_LOWEST_FIELDS = [
    "date",
    "time",
    "route_id",
    "route_name",
    "search_start_date",
    "search_end_date",
    "outbound_airline",
    "outbound_time",
    "return_airline",
    "return_time",
    "lowest_price",
    "tracking_key",
]


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
        for key in [
            "origin",
            "destination",
            "departure_date",
            "return_date",
            "direct",
            "outbound_time_range",
            "return_time_range",
            "passengers",
        ]
    )


def matching_history(history: list[dict[str, Any]], quote: dict[str, Any]) -> list[dict[str, Any]]:
    key = tracking_key(quote)
    return [item for item in history if item.get("tracking_key") == key]


def quote_date(quote: dict[str, Any]) -> str:
    parsed = to_taipei(quote.get("fetched_at"))
    if parsed:
        return parsed.date().isoformat()
    return date.today().isoformat()


def append_daily_quote(route_id: str, quote: dict[str, Any], today: str | None = None) -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    day = today or quote_date(quote)
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


def stats(history: list[dict[str, Any]], days: int = 30) -> dict[str, Any]:
    records = sorted(history, key=lambda item: item["date"])
    recent = records[-days:]
    prices = [int(item["price"]) for item in recent if item.get("price")]
    if not prices:
        return {"average": None, "lowest": None, "lowest_record": None, "current": None}
    lowest_record = min(recent, key=lambda item: int(item["price"]))
    return {
        "average": round(mean(prices)),
        "lowest": int(lowest_record["price"]),
        "lowest_record": lowest_record,
        "current": int(recent[-1]["price"]),
    }


def previous_price(history: list[dict[str, Any]]) -> int | None:
    record = previous_record(history)
    if not record:
        return None
    return int(record["price"])


def previous_record(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    records = sorted(history, key=lambda item: item["date"])
    if len(records) < 2:
        return None
    return records[-2]


def display_airline(value: str | None) -> str:
    if not value:
        return "未取得"
    return AIRLINE_DISPLAY_NAMES.get(value, value)


def display_datetime(value: str | None) -> str:
    if not value:
        return ""
    parsed = to_taipei(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return value.replace("T", " ")


def display_clock(value: str | None) -> str:
    if not value:
        return ""
    parsed = to_taipei(value)
    if parsed:
        return parsed.strftime("%H:%M")
    normalized = value.replace("T", " ")
    return normalized[11:16] if len(normalized) >= 16 else normalized[:5]


def csv_row(route: dict[str, Any], quote: dict[str, Any], price_key: str) -> dict[str, Any]:
    return {
        "route_id": quote.get("route_id") or route.get("id", ""),
        "route_name": quote.get("route_name") or route.get("name", ""),
        "search_start_date": quote.get("departure_date", ""),
        "search_end_date": quote.get("return_date", ""),
        "outbound_airline": display_airline(quote.get("airline")),
        "outbound_time": quote.get("outbound_time", ""),
        "return_airline": display_airline(quote.get("return_airline") or quote.get("airline")),
        "return_time": quote.get("return_time", ""),
        price_key: int(quote.get("price", 0)),
        "tracking_key": quote.get("tracking_key") or tracking_key(quote),
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_query_csv(route: dict[str, Any], quote: dict[str, Any], today_lowest: dict[str, Any]) -> None:
    row = {
        "query_datetime": display_datetime(quote.get("fetched_at")),
        **csv_row(route, quote, "current_price"),
        "today_lowest_price": int(today_lowest.get("price", quote.get("price", 0))),
    }
    rows = read_csv(QUERY_CSV)
    rows.append(row)
    write_csv(QUERY_CSV, rows, QUERY_FIELDS)


def update_daily_lowest_csv(route: dict[str, Any], today_lowest: dict[str, Any]) -> None:
    row = {
        "date": today_lowest["date"],
        "time": display_clock(today_lowest.get("fetched_at")),
        **csv_row(route, today_lowest, "lowest_price"),
    }
    key = (row["date"], row["route_id"], row["tracking_key"])
    rows = [
        item
        for item in read_csv(DAILY_LOWEST_CSV)
        if (item.get("date"), item.get("route_id"), item.get("tracking_key")) != key
    ]
    rows.append(row)
    rows.sort(key=lambda item: (item["date"], item.get("route_id", ""), item.get("tracking_key", "")))
    write_csv(DAILY_LOWEST_CSV, rows, DAILY_LOWEST_FIELDS)
