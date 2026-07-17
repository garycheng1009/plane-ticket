from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from flight_tracker.models import FlightQuote
from flight_tracker.range_search import save_debug_artifact, save_debug_manifest
from flight_tracker.sources.browser_source import BrowserSource, query_url
from flight_tracker.timezone import now_taipei_iso


AIRLINE_ALIASES = {
    "星宇": ["星宇", "星宇航空"],
    "長榮": ["長榮", "長榮航空"],
    "華航": ["華航", "中華航空"],
    "國泰": ["國泰", "國泰航空"],
    "ANA": ["ANA", "全日空"],
    "JAL": ["JAL", "日本航空"],
    "United": ["United", "聯合航空"],
    "Peach": ["Peach", "樂桃航空"],
}


ALL_AIRLINE_NAMES = {alias for aliases in AIRLINE_ALIASES.values() for alias in aliases}


def display_airline_name(airline: str) -> str:
    aliases = AIRLINE_ALIASES.get(airline, [airline])
    return aliases[-1]


def passenger_value(trip: dict[str, Any], key: str, default: int) -> int:
    passengers = trip.get("passengers") or {}
    return max(0, int(passengers.get(key, default)))


def passenger_key(trip: dict[str, Any]) -> str:
    return (
        f"A{max(1, passenger_value(trip, 'adults', 1))}"
        f"C{passenger_value(trip, 'children', 0)}"
        f"I{passenger_value(trip, 'infants', 0)}"
    )


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


def minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def in_time_range(value: str | None, time_range: dict[str, str] | None) -> bool:
    if not value or not time_range:
        return True
    start = time_range.get("from")
    end = time_range.get("to")
    if not start or not end:
        return True
    current = minutes(value)
    return minutes(start) <= current <= minutes(end)


def time_range_key(time_range: dict[str, str] | None) -> str:
    if not time_range:
        return ""
    return f"{time_range.get('from', '')}-{time_range.get('to', '')}"


def result_start(lines: list[str], marker: str) -> int:
    for index, line in enumerate(lines):
        if line.startswith(marker):
            return index
    return 0


def body_lines(page: Any) -> list[str]:
    return [line.strip() for line in page.locator("body").inner_text(timeout=10000).splitlines() if line.strip()]


def debug_artifact_base(config: dict[str, Any], route: dict[str, Any], stage: str) -> Path | None:
    debug_dir = (config.get("range_search") or {}).get("_debug_dir")
    if not debug_dir:
        return None
    trip = config["trip"]
    safe_stage = re.sub(r'[<>:"/\\|?*\s]+', "-", stage).strip("-")
    stem = f"{route['id']}_{trip['departure_date']}_{trip['return_date']}_{safe_stage}"
    return Path(debug_dir) / stem


def save_page_debug(page: Any, config: dict[str, Any], route: dict[str, Any], stage: str, payload: dict[str, Any]) -> dict[str, str]:
    base = debug_artifact_base(config, route, stage)
    if not base:
        return {"debug_screenshot": "", "debug_html": "", "debug_dom": ""}
    screenshot_path = save_debug_artifact(base.with_suffix(".png"), page.screenshot(full_page=True))
    html_path = save_debug_artifact(base.with_suffix(".html"), page.content())
    dom_path = save_debug_manifest(
        base.with_suffix(".json"),
        {
            "url": page.url,
            "departure_date": config["trip"].get("departure_date"),
            "return_date": config["trip"].get("return_date"),
            **payload,
        },
    )
    return {"debug_screenshot": screenshot_path, "debug_html": html_path, "debug_dom": dom_path}


def scrolled_body_lines(page: Any, steps: int = 8) -> list[str]:
    all_lines: list[str] = []
    seen_pages: set[str] = set()
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(800)
    for _ in range(steps):
        lines = body_lines(page)
        page_text = "\n".join(lines)
        if page_text not in seen_pages:
            seen_pages.add(page_text)
            all_lines.extend(lines)
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
        page.wait_for_timeout(900)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    return all_lines


def flight_card_options(
    lines: list[str],
    start: int,
    requested: list[str],
    time_range: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    requested_aliases = {airline: AIRLINE_ALIASES.get(airline, [airline]) for airline in requested}
    options: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    choice_index = 0
    for index in range(start, len(lines)):
        line = lines[index]
        if line not in ALL_AIRLINE_NAMES:
            continue
        price = price_from_lines(lines, index)
        flight_time = first_time_from_lines(lines, index)
        if not price or not flight_time:
            continue
        if not in_time_range(flight_time, time_range):
            continue
        for airline, aliases in requested_aliases.items():
            if line in aliases:
                key = (airline, flight_time, price)
                if key in seen:
                    break
                seen.add(key)
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


def click_matching_choice(page: Any, option: dict[str, Any]) -> bool:
    airline = display_airline_name(str(option["airline"]))
    price = f"TWD{int(option['price']):,}"
    flight_time = str(option["time"])
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    for _ in range(10):
        clicked = bool(
            page.evaluate(
                """
                ({ airline, price, flightTime }) => {
                    const buttons = Array.from(document.querySelectorAll('button, a, div, span'))
                        .filter((el) => (el.textContent || '').trim() === '選擇');

                    for (const button of buttons) {
                        let node = button;
                        for (let depth = 0; node && depth < 10; depth += 1, node = node.parentElement) {
                            const text = node.innerText || node.textContent || '';
                            const selectCount = (text.match(/選擇/g) || []).length;
                            if (
                                text.length < 500
                                && selectCount <= 1
                                && text.includes(airline)
                                && text.includes(flightTime)
                                && text.replace(/\\s+/g, '').includes(price)
                            ) {
                                button.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
                """,
                {"airline": airline, "price": price, "flightTime": flight_time},
            )
        )
        if clicked:
            return True
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
        page.wait_for_timeout(700)
    return False


def candidate_outbounds(options: list[dict[str, Any]], max_per_airline: int = 2) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for option in sorted(options, key=lambda item: int(item["price"])):
        airline = str(option["airline"])
        if counts.get(airline, 0) >= max_per_airline:
            continue
        counts[airline] = counts.get(airline, 0) + 1
        selected.append(option)
    return selected


def best_quotes_by_airline(quotes: list[FlightQuote]) -> list[FlightQuote]:
    best: dict[str, FlightQuote] = {}
    for quote in quotes:
        if quote.airline not in best or quote.price < best[quote.airline].price:
            best[quote.airline] = quote
    return sorted(best.values(), key=lambda quote: quote.price)


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
                "adults": max(1, passenger_value(trip, "adults", 1)),
                "children": passenger_value(trip, "children", 0),
                "infants": passenger_value(trip, "infants", 0),
                "direct": direct,
                "cabintype": "",
                "airline": "",
                "searchbox": "s",
            },
        )

    def quote_for_outbound(
        self,
        browser: Any,
        config: dict[str, Any],
        route: dict[str, Any],
        outbound: dict[str, Any],
        url: str,
    ) -> FlightQuote | None:
        page = browser.new_page(locale="zh-TW", timezone_id="Asia/Taipei", viewport={"width": 1280, "height": 720})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(16000)
            clicked = click_matching_choice(page, outbound)
            if not clicked:
                page.locator("text=選擇").nth(int(outbound["choice_index"])).click()
            page.wait_for_timeout(14000)
            return_lines = scrolled_body_lines(page)
            return_options = flight_card_options(
                return_lines,
                result_start(return_lines, "回程:"),
                [str(outbound["airline"])],
                config["trip"].get("return_time"),
            )
            debug_paths = save_page_debug(
                page,
                config,
                route,
                f"return_{outbound['airline']}_{outbound['time']}",
                {
                    "requested_outbound": outbound,
                    "parsed_return_options": return_options,
                    "body_lines": return_lines,
                },
            )
            return_airline = outbound["airline"]
            return_time = None
            final_price = int(outbound["price"])
            if return_options:
                best_return = min(return_options, key=lambda item: int(item["price"]))
                return_airline = best_return["airline"]
                return_time = best_return["time"]
                final_price = min(final_price, int(best_return["price"]))

            return FlightQuote(
                source=self.name,
                route_id=route["id"],
                route_name=route["name"],
                origin=config["trip"]["origin"],
                destination=route["destination"],
                airline=outbound["airline"],
                price=final_price,
                direct=bool(config["trip"].get("direct_only", True)),
                departure_date=config["trip"]["departure_date"],
                return_date=config["trip"]["return_date"],
                outbound_time_range=time_range_key(config["trip"].get("outbound_time")),
                return_time_range=time_range_key(config["trip"].get("return_time")),
                passengers=passenger_key(config["trip"]),
                return_airline=return_airline,
                outbound_time=outbound["time"],
                return_time=return_time,
                fetched_at=now_taipei_iso(),
                booking_url=page.url,
                debug_screenshot=debug_paths["debug_screenshot"],
                debug_html=debug_paths["debug_html"],
                debug_dom=debug_paths["debug_dom"],
            )
        except Exception:
            return None
        finally:
            page.close()

    def search_with_browser(self, browser: Any, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        page = browser.new_page(locale="zh-TW", timezone_id="Asia/Taipei", viewport={"width": 1280, "height": 720})
        try:
            url = self.build_url(config, route)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(18000)
            lines = scrolled_body_lines(page)
            requested = config.get("airlines", {}).get("include") or []
            excluded = set(config.get("airlines", {}).get("exclude") or [])
            requested = [airline for airline in requested if airline not in excluded]
            outbound_options = flight_card_options(
                lines,
                result_start(lines, "去程:"),
                requested,
                config["trip"].get("outbound_time"),
            )
            save_page_debug(
                page,
                config,
                route,
                "outbound",
                {
                    "parsed_outbound_options": outbound_options,
                    "body_lines": lines,
                },
            )
            if not outbound_options:
                return []

            quotes = [
                quote
                for option in candidate_outbounds(outbound_options)
                if (quote := self.quote_for_outbound(browser, config, route, option, url)) is not None
            ]
            return best_quotes_by_airline(quotes)
        finally:
            page.close()

    def search_range_dates(
        self,
        config: dict[str, Any],
        route: dict[str, Any],
        date_pairs: list[tuple[str, str]],
    ) -> list[tuple[str, str, list[FlightQuote], Exception | None, str]]:
        results = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for departure_date, return_date in date_pairs:
                    started_at = now_taipei_iso()
                    query_config = deepcopy(config)
                    query_config["trip"]["departure_date"] = departure_date
                    query_config["trip"]["return_date"] = return_date
                    try:
                        quotes = self.search_with_browser(browser, query_config, route)
                        results.append((departure_date, return_date, quotes, None, started_at))
                    except Exception as exc:
                        results.append((departure_date, return_date, [], exc, started_at))
            finally:
                browser.close()
        return results

    def search(self, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                return self.search_with_browser(browser, config, route)
            except PlaywrightTimeoutError:
                return []
            finally:
                browser.close()
