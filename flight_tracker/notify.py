from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import requests

from flight_tracker.timezone import to_taipei


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


def display_time(value: str | None) -> str:
    if not value:
        return "未取得"
    parsed = to_taipei(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M")
    return value.replace("T", " ")[:16]


def display_airline(value: str | None) -> str:
    if not value:
        return "未取得"
    return AIRLINE_DISPLAY_NAMES.get(value, value)


def display_airline_short(value: str | None) -> str:
    if not value:
        return "未取得"
    for short_name, full_name in AIRLINE_DISPLAY_NAMES.items():
        if value == short_name or value == full_name:
            return short_name
    return value


def display_clock(value: str | None) -> str:
    if not value:
        return "??:??"
    if re.fullmatch(r"\d{2}:\d{2}", value):
        return value
    parsed = to_taipei(value)
    if parsed:
        return parsed.strftime("%H:%M")
    return value[11:16] if len(value) >= 16 else "??:??"


def display_history_date(value: str | None) -> str:
    if not value:
        return "??/??"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%m/%d")
    except ValueError:
        return value[5:].replace("-", "/")


def display_range_date(value: str | None) -> str:
    if not value:
        return "??/??"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%m/%d")
    except ValueError:
        return value[5:].replace("-", "/")


def format_price(value: int | str | None) -> str:
    if value in (None, ""):
        return "無資料"
    return f"{int(value):,}"


def history_line(item: dict[str, Any], lowest_price: int | None) -> str:
    price = int(item.get("price", 0))
    airline = display_airline_short(item.get("airline"))
    marker = "⭐" if lowest_price is not None and price == lowest_price else ""
    return f"{display_history_date(item.get('date'))}　{format_price(price)}　{marker}{airline}"


def lowest_text(record: dict[str, Any] | None, fallback: int | None) -> str:
    if not record:
        return format_price(fallback)
    airline = display_airline_short(record.get("airline"))
    return (
        f"{format_price(record['price'])}"
        f"（{display_history_date(record.get('date'))} {display_clock(record.get('fetched_at') or record.get('time'))}）"
        f"{airline}"
    )


def change_block(current: int, previous_day_lowest: int | None) -> str:
    if previous_day_lowest is None:
        return ""
    difference = current - previous_day_lowest
    percentage = abs(difference) / previous_day_lowest * 100 if previous_day_lowest else 0
    if difference < 0:
        return f"📉 較昨日最低\n↓{abs(difference)} 元（-{percentage:.1f}%）\n\n"
    if difference > 0:
        return f"📈 較昨日最低\n↑{difference} 元（+{percentage:.1f}%）\n\n"
    return "📉 較昨日最低\n持平\n\n"


def quote_sort_key(quote: dict[str, Any]) -> tuple[int, str]:
    return int(quote.get("price", 0)), display_airline_short(quote.get("airline"))


def best_by_airline(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for quote in quotes:
        airline = display_airline_short(quote.get("airline"))
        if airline not in best or int(quote["price"]) < int(best[airline]["price"]):
            best[airline] = quote
    return sorted(best.values(), key=quote_sort_key)


def flight_line(quote: dict[str, Any], lowest_price: int) -> str:
    diff = int(quote["price"]) - lowest_price
    return (
        f"{display_airline_short(quote.get('airline'))}　"
        f"{quote.get('outbound_time') or '未取得'} / {quote.get('return_time') or '未取得'}　"
        f"{format_price(quote['price'])} 元（+{format_price(diff)}）"
    )


def lowest_blocks(quotes: list[dict[str, Any]]) -> tuple[str, str]:
    airline_quotes = best_by_airline(quotes)
    if not airline_quotes:
        return "🏆 最低價格\n無資料", ""

    lowest_price = min(int(quote["price"]) for quote in airline_quotes)
    lowest_quotes = [quote for quote in airline_quotes if int(quote["price"]) == lowest_price]
    other_quotes = [quote for quote in airline_quotes if int(quote["price"]) > lowest_price]

    lowest_parts = ["最低價格:"]
    for quote in lowest_quotes:
        lowest_parts.append(
            f"{display_airline(quote.get('airline'))} "
            f"{quote.get('outbound_time') or '未取得'} / {quote.get('return_time') or '未取得'}　"
            f"{format_price(quote['price'])} 元"
        )

    other_block = ""
    if other_quotes:
        other_block = "其他航空:\n" + "\n".join(flight_line(quote, lowest_price) for quote in other_quotes)
    return "\n".join(lowest_parts), other_block


def range_search_block(range_summary: dict[str, Any] | None) -> str:
    if not range_summary:
        return ""

    best_quote = range_summary.get("best_quote")
    header = (
        "範圍時段:\n"
        f"去程:{range_summary.get('departure_start') or '未設定'} ~ {range_summary.get('departure_end') or '未設定'}\n"
        f"回程:{range_summary.get('return_start') or '未設定'} ~ {range_summary.get('return_end') or '未設定'}"
    )

    if not best_quote:
        return f"{header}\n\n查詢失敗，未取得有效價格。"

    return (
        f"{header}\n\n"
        f"{display_airline(best_quote.get('airline'))}　"
        f"{display_range_date(best_quote.get('departure_date'))} ~ {display_range_date(best_quote.get('return_date'))}　"
        f"{best_quote.get('departure_time') or '未取得'} / {best_quote.get('return_time') or '未取得'}　"
        f"{format_price(best_quote.get('price'))} 元"
    )


def build_message(
    route: dict[str, Any],
    quote: dict[str, Any],
    history: list[dict[str, Any]],
    summary: dict[str, Any],
    yesterday: int | None,
    alternatives: list[dict[str, Any]] | None = None,
    range_summary: dict[str, Any] | None = None,
) -> str:
    current = int(quote["price"])
    route_name = quote.get("route_name") or route.get("name") or "未設定"
    fetched_at = display_time(quote.get("fetched_at"))
    departure_date = quote.get("departure_date") or "未設定"
    return_date = quote.get("return_date") or "未設定"
    quote_options = alternatives or [quote]
    lowest_block, other_block = lowest_blocks(quote_options)
    other_section = f"\n\n{other_block}" if other_block else ""
    range_section = f"\n\n{range_search_block(range_summary)}" if range_summary else ""
    history_records = sorted(history, key=lambda item: item["date"])[-7:]
    lowest_price = summary.get("lowest")
    history_lines = "\n".join(history_line(item, lowest_price) for item in history_records)

    return (
        f"查詢時間 {fetched_at}\n\n"
        f"地點:{route_name}\n\n"
        f"往返日期\n"
        f"{departure_date} ~ {return_date}\n\n"
        f"{lowest_block}"
        f"{other_section}"
        f"{range_section}\n\n"
        f"────────────────\n\n"
        f"{change_block(current, yesterday)}"
        f"最近30天\n"
        f"平均　{format_price(summary['average']) if summary['average'] else '無資料'}\n"
        f"最低　{lowest_text(summary.get('lowest_record'), summary.get('lowest'))}\n"
        f"目前　{format_price(current)}\n\n"
        f"近7日每日最低\n"
        f"{history_lines}"
    )


def should_alert(config: dict[str, Any], route: dict[str, Any], current: int, yesterday: int | None) -> bool:
    alerts = config.get("alerts", {})
    max_price = route.get("max_price")
    if max_price and alerts.get("price_drop_enabled", True) and current <= int(max_price):
        return True
    if yesterday is not None and alerts.get("price_rise_enabled", True):
        threshold = int(alerts.get("rise_threshold", 500))
        return current - yesterday >= threshold
    if yesterday is not None and alerts.get("price_drop_enabled", True):
        return current < yesterday
    return False


def send_line_message(message: str, config: dict[str, Any]) -> None:
    line_config = config.get("line", {})
    if not line_config.get("enabled"):
        return

    channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    to = os.environ.get("LINE_TO") or line_config.get("to") or ""
    recipients = line_recipients(to)
    if channel_token and recipients:
        for recipient in recipients:
            response = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {channel_token}", "Content-Type": "application/json"},
                json={"to": recipient, "messages": [{"type": "text", "text": message}]},
                timeout=20,
            )
            response.raise_for_status()
        return

    legacy_token = os.environ.get("LINE_NOTIFY_TOKEN")
    if line_config.get("legacy_notify_enabled") and legacy_token:
        response = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {legacy_token}"},
            data={"message": message},
            timeout=20,
        )
        response.raise_for_status()
        return

    raise RuntimeError("LINE is enabled, but LINE_CHANNEL_ACCESS_TOKEN/LINE_TO is not configured.")


def line_recipients(raw_to: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\s,;]+", raw_to) if item.strip()]
