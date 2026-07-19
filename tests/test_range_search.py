from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

import flight_tracker.range_search as range_search
from flight_tracker.models import FlightQuote
from flight_tracker.sources.eztravel import flight_options_from_cards, selected_outbounds


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


class MissingReturnTimeSource(FakeSource):
    def search(self, config: dict, route: dict) -> list[FlightQuote]:
        quote = super().search(config, route)[0]
        return [
            FlightQuote(
                **{
                    **quote.normalized(),
                    "return_time": "",
                    "fetched_at": "",
                }
            )
        ]


class PartialResultSource(FakeSource):
    def search(self, config: dict, route: dict) -> list[FlightQuote]:
        departure_date = config["trip"]["departure_date"]
        return_date = config["trip"]["return_date"]
        if departure_date == "2027-01-30":
            return []
        price = 22000 if return_date == "2027-02-04" else 21000
        return [
            FlightQuote(
                source=self.name,
                route_id=route["id"],
                route_name=route["name"],
                origin=config["trip"]["origin"],
                destination=route["destination"],
                airline="星宇航空",
                price=price,
                departure_date=departure_date,
                return_date=return_date,
                outbound_time="10:10",
                return_time="13:15",
                booking_url=self.build_url(config, route),
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
            self.assertEqual(
                [(item["departure_date"], item["return_date"], item["price"]) for item in summary.departure_best_quotes],
                [
                    ("2027-01-30", "2027-02-05", 18000),
                    ("2027-01-31", "2027-02-05", 17000),
                ],
            )

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

    def test_missing_return_time_becomes_parse_error(self) -> None:
        config = base_config()
        config["range_search"]["departure_end_date"] = "2027-01-30"
        config["range_search"]["return_start_date"] = "2027-02-05"
        with tempfile.TemporaryDirectory() as temp_dir:
            original_dir = range_search.RANGE_QUERY_DIR
            range_search.RANGE_QUERY_DIR = Path(temp_dir)
            try:
                summary = range_search.run_range_search(config, ROUTE, {"fake": MissingReturnTimeSource}, query_id="20260717_110202")
            finally:
                range_search.RANGE_QUERY_DIR = original_dir

            self.assertIsNone(summary.best_quote)
            with Path(summary.detail_path).open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["status"], range_search.PARSE_ERROR)
            self.assertEqual(rows[0]["error_message"], "return_time cannot be empty.")
            self.assertEqual(
                summary.departure_best_quotes,
                [{"departure_date": "2027-01-30", "success": False, "error": "該日期未取得有效報價"}],
            )

    def test_run_range_search_keeps_failed_departure_and_other_successes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_dir = range_search.RANGE_QUERY_DIR
            range_search.RANGE_QUERY_DIR = Path(temp_dir)
            try:
                summary = range_search.run_range_search(base_config(), ROUTE, {"fake": PartialResultSource}, query_id="20260717_110203")
            finally:
                range_search.RANGE_QUERY_DIR = original_dir

            self.assertEqual(
                summary.departure_best_quotes,
                [
                    {"departure_date": "2027-01-30", "success": False, "error": "該日期未取得有效報價"},
                    {
                        "departure_date": "2027-01-31",
                        "return_date": "2027-02-05",
                        "airline": "星宇航空",
                        "departure_time": "10:10",
                        "return_time": "13:15",
                        "price": 21000,
                        "source": "fake",
                        "success": True,
                    },
                ],
            )

    def test_old_config_defaults_to_disabled(self) -> None:
        self.assertFalse(range_search.is_enabled({"trip": {}}))

    def test_range_query_selects_only_overall_lowest_outbound(self) -> None:
        options = [
            {"airline": "國泰", "price": 20000, "time": "12:50"},
            {"airline": "星宇", "price": 18000, "time": "10:10"},
            {"airline": "華航", "price": 19000, "time": "12:35"},
        ]
        config = {"range_search": {"_range_query": True, "max_outbounds_total": 1}}
        self.assertEqual(selected_outbounds(config, options), [options[1]])

    def test_fixed_query_still_selects_candidates_by_airline(self) -> None:
        options = [
            {"airline": "國泰", "price": 20000, "time": "12:50"},
            {"airline": "星宇", "price": 18000, "time": "10:10"},
            {"airline": "華航", "price": 19000, "time": "12:35"},
        ]
        selected = selected_outbounds({}, options)
        self.assertEqual({item["airline"] for item in selected}, {"國泰", "星宇", "華航"})

    def test_eztravel_card_parser_does_not_match_tigerair_as_china_airlines(self) -> None:
        cards = [
            {
                "text": "台灣虎航\n14:35\nHND T3\n18:05\nTPE T1\nTWD 19,426\n選擇",
                "choice_index": 0,
            }
        ]
        self.assertEqual(flight_options_from_cards(cards, ["華航"]), [])

    def test_eztravel_card_parser_skips_mixed_airline_container(self) -> None:
        cards = [
            {
                "text": "中華航空\n12:35\n已選去程\n台灣虎航\n14:35\nTWD 19,426\n選擇",
                "choice_index": 0,
            }
        ]
        self.assertEqual(flight_options_from_cards(cards, ["華航"]), [])


if __name__ == "__main__":
    unittest.main()
