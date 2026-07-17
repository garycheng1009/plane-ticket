from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

import flight_tracker.range_search as range_search
from flight_tracker.models import FlightQuote


ROUTE = {"id": "tokyo", "name": "東京", "destination": "TYO"}


def base_config() -> dict:
    return {
        "trip": {
            "origin": "TPE",
            "departure_date": "2027-01-30",
            "return_date": "2027-02-05",
            "direct_only": True,
            "outbound_time": {"from": "05:00", "to": "14:00"},
            "return_time": {"from": "12:00", "to": "22:00"},
            "passengers": {"adults": 1, "children": 0, "infants": 0},
        },
        "routes": [ROUTE],
        "airlines": {"include": ["國泰航空"], "exclude": []},
        "sources": {"enabled": ["fake"], "fallback_to_mock": False},
        "range_search": {
            "enabled": True,
            "departure_start_date": "2027-01-30",
            "departure_end_date": "2027-01-31",
            "return_start_date": "2027-02-04",
            "return_end_date": "2027-02-05",
            "debug": False,
            "success_warning_threshold": 0.5,
        },
    }


class FakeSource:
    name = "fake"

    def build_url(self, config: dict, route: dict) -> str:
        return f"https://example.test/{config['trip']['departure_date']}/{config['trip']['return_date']}"

    def search(self, config: dict, route: dict) -> list[FlightQuote]:
        departure_date = config["trip"]["departure_date"]
        return_date = config["trip"]["return_date"]
        if return_date == "2027-02-04":
            return []
        price = 18000
        if departure_date == "2027-01-31" and return_date == "2027-02-05":
            price = 17000
        return [
            FlightQuote(
                source=self.name,
                route_id=route["id"],
                route_name=route["name"],
                origin=config["trip"]["origin"],
                destination=route["destination"],
                airline="國泰航空",
                price=price,
                departure_date=departure_date,
                return_date=return_date,
                outbound_time="12:50",
                return_time="15:30",
                booking_url=self.build_url(config, route),
            )
        ]


class InvalidDateSource(FakeSource):
    def search(self, config: dict, route: dict) -> list[FlightQuote]:
        quote = super().search(config, route)[0]
        return [
            FlightQuote(
                **{
                    **quote.normalized(),
                    "departure_date": "2027-01-29",
                    "fetched_at": "",
                }
            )
        ]


class RangeSearchTests(unittest.TestCase):
    def test_generate_date_pairs_only_return_after_departure(self) -> None:
        pairs = range_search.generate_date_pairs(
            date(2027, 1, 30),
            date(2027, 1, 31),
            date(2027, 1, 31),
            date(2027, 2, 1),
        )
        self.assertEqual(
            pairs,
            [
                ("2027-01-30", "2027-01-31"),
                ("2027-01-30", "2027-02-01"),
                ("2027-01-31", "2027-02-01"),
            ],
        )

    def test_choose_best_uses_stable_tie_breaker(self) -> None:
        rows = [
            range_search.RangeQueryRow(
                query_id="q",
                route_id="tokyo",
                route_name="東京",
                departure_date="2027-01-31",
                return_date="2027-02-05",
                source="fake",
                airline="國泰航空",
                price=17000,
                status=range_search.SUCCESS,
            ),
            range_search.RangeQueryRow(
                query_id="q",
                route_id="tokyo",
                route_name="東京",
                departure_date="2027-01-30",
                return_date="2027-02-05",
                source="fake",
                airline="國泰航空",
                price=17000,
                status=range_search.SUCCESS,
            ),
        ]
        self.assertEqual(range_search.choose_best(rows).departure_date, "2027-01-30")

    def test_run_range_search_writes_detail_csv_and_best_quote(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_dir = range_search.RANGE_QUERY_DIR
            range_search.RANGE_QUERY_DIR = Path(temp_dir)
            try:
                summary = range_search.run_range_search(base_config(), ROUTE, {"fake": FakeSource}, query_id="20260717_110200")
            finally:
                range_search.RANGE_QUERY_DIR = original_dir

            self.assertEqual(summary.total_combinations, 4)
            self.assertEqual(summary.success_combinations, 2)
            self.assertEqual(summary.failed_combinations, 2)
            self.assertEqual(summary.best_quote["departure_date"], "2027-01-31")
            self.assertEqual(summary.best_quote["price"], 17000)

            with Path(summary.detail_path).open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertIn(range_search.NO_RESULT, {row["status"] for row in rows})
            self.assertEqual([row for row in rows if row["selected_lowest"] == "YES"][0]["price"], "17000")

    def test_invalid_quote_becomes_parse_error_not_zero_price(self) -> None:
        config = base_config()
        config["range_search"]["departure_end_date"] = "2027-01-30"
        config["range_search"]["return_start_date"] = "2027-02-05"
        with tempfile.TemporaryDirectory() as temp_dir:
            original_dir = range_search.RANGE_QUERY_DIR
            range_search.RANGE_QUERY_DIR = Path(temp_dir)
            try:
                summary = range_search.run_range_search(config, ROUTE, {"fake": InvalidDateSource}, query_id="20260717_110201")
            finally:
                range_search.RANGE_QUERY_DIR = original_dir

            self.assertIsNone(summary.best_quote)
            with Path(summary.detail_path).open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["status"], range_search.PARSE_ERROR)
            self.assertEqual(rows[0]["price"], "18000")

    def test_old_config_defaults_to_disabled(self) -> None:
        self.assertFalse(range_search.is_enabled({"trip": {}}))


if __name__ == "__main__":
    unittest.main()
