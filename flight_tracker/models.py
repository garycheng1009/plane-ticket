from __future__ import annotations

from dataclasses import dataclass

from flight_tracker.timezone import now_taipei_iso


@dataclass(frozen=True)
class FlightQuote:
    source: str
    route_id: str
    route_name: str
    origin: str
    destination: str
    airline: str
    price: int
    currency: str = "TWD"
    direct: bool = True
    departure_date: str | None = None
    return_date: str | None = None
    outbound_time_range: str | None = None
    return_time_range: str | None = None
    passengers: str | None = None
    return_airline: str | None = None
    outbound_time: str | None = None
    return_time: str | None = None
    fetched_at: str = ""
    booking_url: str = ""

    def normalized(self) -> dict:
        data = self.__dict__.copy()
        if not data["fetched_at"]:
            data["fetched_at"] = now_taipei_iso()
        return data
