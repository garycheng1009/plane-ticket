from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from flight_tracker.models import FlightQuote
from flight_tracker.sources.browser_source import BrowserSource, query_url


AIRLINE_ALIASES = {
    "星宇": ["星宇", "星宇航空"],
    "長榮": ["長榮", "長榮航空"],
    "華航": ["華航", "中華航空"],
    "ANA": ["ANA", "全日空"],
    "JAL": ["JAL", "日本航空"],
    "United": ["United", "聯合航空"],
    "Peach": ["Peach", "樂桃航空"],
}


def eztravel_date(value: str) -> str:
    year, month, day = value.split("-")
    return f"{day}/{month}/{year}"


def price_from_lines(lines: list[str], start: int) -> int | None:
    window = "\n".join(lines[start : start + 8])
    match = re.search(r"TWD\s*([0-9,]+)", window)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


class EzTravelSource(BrowserSource):
    name = "eztravel"
    start_url = "https://flight.eztravel.com.tw"

    def build_url(self, config: dict[str, Any], route: dict[str, Any]) -> str:
        trip = config["trip"]
        direct = str(bool(trip.get("direct_only", True))).lower()
        path = f"{self.start_url}/tickets-roundtrip-{trip['origin']}-{route['destination']}/"
        return query_url(
            path,
            {
                "outbounddate": eztravel_date(trip["departure_date"]),
                "inbounddate": eztravel_date(trip["return_date"]),
                "dport": "",
                "aport": "",
                "adults": 1,
                "children": 0,
                "infants": 0,
                "direct": direct,
                "cabintype": "",
                "airline": "",
                "searchbox": "s",
            },
        )

    def search(self, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="zh-TW", timezone_id="Asia/Taipei", viewport={"width": 1280, "height": 720})
            try:
                page.goto(self.build_url(config, route), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(25000)
                text = page.locator("body").inner_text(timeout=10000)
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                requested = config.get("airlines", {}).get("include") or []
                excluded = set(config.get("airlines", {}).get("exclude") or [])
                quotes: list[FlightQuote] = []

                for airline in requested:
                    if airline in excluded:
                        continue
                    aliases = AIRLINE_ALIASES.get(airline, [airline])
                    prices = []
                    for index, line in enumerate(lines):
                        if line in aliases:
                            price = price_from_lines(lines, index)
                            if price:
                                prices.append(price)
                    if prices:
                        quotes.append(
                            FlightQuote(
                                source=self.name,
                                route_id=route["id"],
                                route_name=route["name"],
                                origin=config["trip"]["origin"],
                                destination=route["destination"],
                                airline=airline,
                                price=min(prices),
                                direct=bool(config["trip"].get("direct_only", True)),
                                fetched_at=datetime.now().isoformat(timespec="seconds"),
                                booking_url=page.url,
                            )
                        )

                if quotes:
                    return quotes
                return super().search(config, route)
            except PlaywrightTimeoutError:
                return []
            finally:
                browser.close()
