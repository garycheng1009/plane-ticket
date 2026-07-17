from __future__ import annotations

from typing import Any

from flight_tracker.sources.browser_source import BrowserSource, query_url


class SkyscannerSource(BrowserSource):
    name = "skyscanner"
    start_url = "https://www.skyscanner.com.tw/flights/day-view"

    def build_url(self, config: dict[str, Any], route: dict[str, Any]) -> str:
        trip = config["trip"]
        return query_url(
            self.start_url,
            {
                "origin": trip["origin"],
                "destination": route["destination"],
                "outboundDate": trip["departure_date"],
                "inboundDate": trip["return_date"],
                "adultsv2": 1,
                "cabinclass": "economy",
                "preferDirects": str(bool(trip.get("direct_only", True))).lower(),
                "outboundaltsenabled": "false",
                "inboundaltsenabled": "false",
                "market": "TW",
                "locale": "zh-TW",
                "currency": "TWD",
                "sortby": "cheapest",
            },
        )
