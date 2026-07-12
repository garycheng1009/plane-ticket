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


ALL_AIRLINE_NAMES = {alias for aliases in AIRLINE_ALIASES.values() for alias in aliases}


def eztravel_date(value: str) -> str:
    year, month, day = value.split("-")
    return f"{day}/{month}/{year}"


def price_from_lines(lines: list[str], start: int) -> int | None:
    window = "\n".join(lines[start : start + 8])
    match = re.search(r"TWD\s*([0-9,]+)", window)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def first_time_from_lines(lines: list[str], start: int) -> str | None:
    for line in lines[start + 1 : start + 6]:
        if re.fullmatch(r"\d{2}:\d{2}", line):
            return line
    return None


def result_start(lines: list[str], marker: str) -> int:
    for index, line in enumerate(lines):
        if line.startswith(marker):
            return index
    return 0


def flight_card_options(lines: list[str], start: int, requested: list[str]) -> list[dict[str, Any]]:
    requested_aliases = {airline: AIRLINE_ALIASES.get(airline, [airline]) for airline in requested}
    options: list[dict[str, Any]] = []
    choice_index = 0
    for index in range(start, len(lines)):
        line = lines[index]
        if line not in ALL_AIRLINE_NAMES:
            continue
        price = price_from_lines(lines, index)
        flight_time = first_time_from_lines(lines, index)
        if not price or not flight_time:
            continue
        for airline, aliases in requested_aliases.items():
            if line in aliases:
                options.append(
                    {
                        "airline": airline,
                        "price": price,
                        "time": flight_time,
                        "choice_index": choice_index,
                    }
                )
                break
        choice_index += 1
    return options


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
                requested = [airline for airline in requested if airline not in excluded]
                outbound_options = flight_card_options(lines, result_start(lines, "去程:"), requested)
                if not outbound_options:
                    return super().search(config, route)

                best_outbound = min(outbound_options, key=lambda item: int(item["price"]))
                return_airline = best_outbound["airline"]
                return_time = None
                final_price = int(best_outbound["price"])

                try:
                    page.locator("text=選擇").nth(int(best_outbound["choice_index"])).click()
                    page.wait_for_timeout(25000)
                    return_lines = [
                        line.strip()
                        for line in page.locator("body").inner_text(timeout=10000).splitlines()
                        if line.strip()
                    ]
                    return_options = flight_card_options(
                        return_lines,
                        result_start(return_lines, "回程:"),
                        [best_outbound["airline"]],
                    )
                    if return_options:
                        best_return = min(return_options, key=lambda item: int(item["price"]))
                        return_airline = best_return["airline"]
                        return_time = best_return["time"]
                        final_price = int(best_return["price"])
                except Exception:
                    pass

                return [
                    FlightQuote(
                        source=self.name,
                        route_id=route["id"],
                        route_name=route["name"],
                        origin=config["trip"]["origin"],
                        destination=route["destination"],
                        airline=best_outbound["airline"],
                        price=final_price,
                        direct=bool(config["trip"].get("direct_only", True)),
                        departure_date=config["trip"]["departure_date"],
                        return_date=config["trip"]["return_date"],
                        return_airline=return_airline,
                        outbound_time=best_outbound["time"],
                        return_time=return_time,
                        fetched_at=datetime.now().isoformat(timespec="seconds"),
                        booking_url=page.url,
                    )
                ]
            except PlaywrightTimeoutError:
                return []
            finally:
                browser.close()
