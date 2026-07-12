from __future__ import annotations

import os
import re
from typing import Any

import requests

from flight_tracker.advice import rating


def build_message(route: dict[str, Any], quote: dict[str, Any], history: list[dict[str, Any]], summary: dict[str, Any], yesterday: int | None) -> str:
    current = int(quote["price"])
    delta = None if yesterday is None else current - yesterday
    if delta is None:
        headline = f"{route['name']}目前 {current} 元"
    elif delta < 0:
        headline = f"{route['name']}便宜 {abs(delta)} 元"
    elif delta > 0:
        headline = f"{route['name']}貴 {delta} 元"
    else:
        headline = f"{route['name']}價格持平"

    stars, advice = rating(current, summary["average"], summary["lowest"], route.get("max_price"))
    yesterday_line = f"昨天 {yesterday}" if yesterday is not None else "昨天 無資料"
    fetched_at = quote.get("fetched_at") or "無資料"
    history_lines = "\n".join(f"{item['date'][5:].replace('-', '/')} {item['price']}" for item in history[-10:])

    return (
        f"{headline}\n\n"
        f"查詢時間 {fetched_at}\n\n"
        f"{quote.get('airline', '未知航空')}\n"
        f"{yesterday_line}\n"
        f"今天 {current}\n"
        f"──────────────\n\n"
        f"最近30天\n"
        f"平均 {summary['average'] or '無資料'}\n"
        f"最低 {summary['lowest'] or '無資料'}\n"
        f"目前 {summary['current'] or current}\n\n"
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
