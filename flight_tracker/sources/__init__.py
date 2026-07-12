from __future__ import annotations

from flight_tracker.sources.eztravel import EzTravelSource
from flight_tracker.sources.mock import MockSource
from flight_tracker.sources.skyscanner import SkyscannerSource


SOURCE_REGISTRY = {
    "eztravel": EzTravelSource,
    "skyscanner": SkyscannerSource,
    "mock": MockSource,
}
