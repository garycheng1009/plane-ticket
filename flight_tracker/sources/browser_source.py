from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from flight_tracker.models import FlightQuote
from flight_tracker.sources.base import FlightSource


PRICE_PATTERN = re.compile(r"(?:NT\$|TWD|\$)\s*([0-9,]{4,6})")


class BrowserSource(FlightSource):
    start_url: str

    def build_url(self, config: dict[str, Any], route: dict[str, Any]) -> str:
        return self.start_url

    def search(self, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="zh-TW", timezone_id="Asia/Taipei")
            try:
                page.goto(self.build_url(config, route), wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(8000)
                if "captcha" in page.url.lower():
                    raise RuntimeError(f"{self.name} blocked the request with captcha: {page.url}")
                text = page.locator("body").inner_text(timeout=10000)
                if "are you a person or a robot" in text.lower():
                    raise RuntimeError(f"{self.name} blocked the request with bot detection.")
                prices = [int(match.replace(",", "")) for match in PRICE_PATTERN.findall(text)]
                sensible = [price for price in prices if 2000 <= price <= 120000]
                if not sensible:
                    return []
                return [
                    FlightQuote(
                        source=self.name,
                        route_id=route["id"],
                        route_name=route["name"],
                        origin=config["trip"]["origin"],
                        destination=route["destination"],
                        airline="網站最低價",
                        price=min(sensible),
                        direct=bool(config["trip"].get("direct_only", True)),
                        fetched_at=datetime.now().isoformat(timespec="seconds"),
                        booking_url=page.url,
                    )
                ]
            except PlaywrightTimeoutError:
                return []
            finally:
                browser.close()


def query_url(base_url: str, params: dict[str, str | int | bool]) -> str:
    return f"{base_url}?{urlencode(params)}"
