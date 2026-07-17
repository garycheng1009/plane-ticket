from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from flight_tracker.models import FlightQuote


class FlightSource(ABC):
    name: str

    @abstractmethod
    def search(self, config: dict[str, Any], route: dict[str, Any]) -> list[FlightQuote]:
        raise NotImplementedError
