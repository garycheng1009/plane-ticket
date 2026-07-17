from __future__ import annotations

from random import Random
from typing import Any

from flight_tracker.models import FlightQuote
from flight_tracker.sources.base import FlightSource
from flight_tracker.timezone import now_taipei, now_taipei_iso


class MockSource(FlightSource):
    name = "mock"

    def search(self, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        seed = f"{route['id']}-{config['trip']['departure_date']}-{now_taipei().date()}"
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
                departure_date=config["trip"]["departure_date"],
                return_date=config["trip"]["return_date"],
                outbound_time_range=f"{config['trip']['outbound_time'].get('from', '')}-{config['trip']['outbound_time'].get('to', '')}",
                return_time_range=f"{config['trip']['return_time'].get('from', '')}-{config['trip']['return_time'].get('to', '')}",
                passengers=passenger_key(config["trip"]),
                return_airline=random.choice(airlines),
                outbound_time="08:30",
                return_time="17:20",
                fetched_at=now_taipei_iso(),
                booking_url="mock://flight-price",
            )
        ]


def passenger_key(trip: dict[str, Any]) -> str:
    passengers = trip.get("passengers") or {}
    return (
        f"A{max(1, int(passengers.get('adults', 1)))}"
        f"C{max(0, int(passengers.get('children', 0)))}"
        f"I{max(0, int(passengers.get('infants', 0)))}"
    )
