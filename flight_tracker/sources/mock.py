from __future__ import annotations

from datetime import datetime
from random import Random
from typing import Any

from flight_tracker.models import FlightQuote
from flight_tracker.sources.base import FlightSource


class MockSource(FlightSource):
    name = "mock"

    def search(self, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        seed = f"{route['id']}-{config['trip']['departure_date']}-{datetime.now().date()}"
        random = Random(seed)
        base = int(route.get("max_price") or 14000)
        airlines = config.get("airlines", {}).get("include") or ["星宇"]
        return [
            FlightQuote(
                source=self.name,
                route_id=route["id"],
                route_name=route["name"],
                origin=config["trip"]["origin"],
                destination=route["destination"],
                airline=random.choice(airlines),
                price=max(3000, base + random.randint(-1800, 1600)),
                direct=bool(config["trip"].get("direct_only", True)),
                outbound_time="08:30",
                return_time="17:20",
                fetched_at=datetime.now().isoformat(timespec="seconds"),
                booking_url="mock://flight-price",
            )
        ]
