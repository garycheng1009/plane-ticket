from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import requests

from flight_tracker.advice import rating


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
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value.replace("T", " ")


def display_airline(value: str | None) -> str:
    if not value:
        return "未取得"
    return AIRLINE_DISPLAY_NAMES.get(value, value)


def display_clock(value: str | None) -> str:
    if not value:
        return "??:??"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value[11:16] if len(value) >= 16 else "??:??"


def history_line(item: dict[str, Any]) -> str:
    price = item.get("price", "無資料")
    clock = display_clock(item.get("fetched_at"))
    return f"{item['date'][5:].replace('-', '/')} {price} ({clock})"


def build_message(route: dict[str, Any], quote: dict[str, Any], history: list[dict[str, Any]], summary: dict[str, Any], yesterday: int | None) -> str:
    current = int(quote["price"])
    fetched_at = display_time(quote.get("fetched_at"))
    departure_date = quote.get("departure_date") or "未設定"
    return_date = quote.get("return_date") or "未設定"
    outbound_airline = display_airline(quote.get("airline"))
    outbound_time = quote.get("outbound_time") or "未取得"
    return_airline = display_airline(quote.get("return_airline") or quote.get("airline"))
    return_time = quote.get("return_time") or "未取得"
    stars, advice = rating(current, summary["average"], summary["lowest"], route.get("max_price"))
    history_lines = "\n".join(history_line(item) for item in history[-10:])
    current_daily_low = summary["current"] or current
    daily_low_line = f"\n\u4eca\u65e5\u6700\u4f4e {current_daily_low}" if current_daily_low != current else ""

    return (
        f"查詢時間 {fetched_at}\n\n"
        f"查詢時間範圍:\n"
        f"{departure_date} ~ {return_date}\n\n"
        f"去程 {outbound_airline} {outbound_time}\n"
        f"回程 {return_airline} {return_time}\n\n"
        f"金額:{current}\n"
        f"{daily_low_line}\n\n"
        f"----------------------------\n"
        f"最近30天\n"
        f"平均 {summary['average'] or '無資料'}\n"
        f"最低 {summary['lowest'] or '無資料'}\n"
        f"目前 {current}\n\n"
        f"{stars}\n"
        f"{advice}\n\n"
        f"歷史價格\n"
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
