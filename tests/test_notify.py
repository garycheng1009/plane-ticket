from __future__ import annotations

import unittest
import sys
import types

sys.modules.setdefault("requests", types.SimpleNamespace(post=None))
from flight_tracker.notify import build_message


ROUTE = {"id": "tokyo", "name": "東京"}
QUOTE = {
    "route_name": "東京",
    "departure_date": "2027-01-30",
    "return_date": "2027-02-05",
    "airline": "國泰航空",
    "outbound_time": "12:50",
    "return_time": "15:30",
    "price": 18682,
    "fetched_at": "2026-07-17T11:02:00+08:00",
}
HISTORY = [{**QUOTE, "date": "2026-07-17"}]
SUMMARY = {"average": 19000, "lowest": 18682, "lowest_record": HISTORY[0], "current": 18682}


class NotifyTests(unittest.TestCase):
    def test_message_without_range_keeps_range_block_absent(self) -> None:
        message = build_message(ROUTE, QUOTE, HISTORY, SUMMARY, None, [QUOTE])
        self.assertNotIn("範圍時段", message)
        self.assertIn("最低價格:", message)
        self.assertIn("────────────────", message)

    def test_range_block_is_after_other_airlines_before_separator(self) -> None:
        alternatives = [
            QUOTE,
            {**QUOTE, "airline": "星宇", "price": 20492, "outbound_time": "10:10", "return_time": "13:45"},
        ]
        range_summary = {
            "departure_start": "2027-01-30",
            "departure_end": "2027-01-31",
            "return_start": "2027-02-04",
            "return_end": "2027-02-09",
            "best_quote": {
                "airline": "國泰航空",
                "departure_date": "2027-01-31",
                "return_date": "2027-02-09",
                "departure_time": "12:50",
                "return_time": "15:30",
                "price": 17682,
                "source": "eztravel",
                "success": True,
            },
        }
        message = build_message(ROUTE, QUOTE, HISTORY, SUMMARY, None, alternatives, range_summary)

        self.assertLess(message.index("其他航空:"), message.index("範圍時段:"))
        self.assertLess(message.index("範圍時段:"), message.index("────────────────"))
        self.assertIn("國泰航空　01/31 ~ 02/09　12:50 / 15:30　17,682 元", message)

    def test_failed_range_block_keeps_fixed_message(self) -> None:
        range_summary = {
            "departure_start": "2027-01-30",
            "departure_end": "2027-01-31",
            "return_start": "2027-02-04",
            "return_end": "2027-02-09",
            "best_quote": None,
        }
        message = build_message(ROUTE, QUOTE, HISTORY, SUMMARY, None, [QUOTE], range_summary)
        self.assertIn("最低價格:", message)
        self.assertIn("查詢失敗，未取得有效價格。", message)

    def test_lowest_block_shows_return_time_when_present(self) -> None:
        message = build_message(ROUTE, QUOTE, HISTORY, SUMMARY, None, [QUOTE])
        self.assertIn("國泰航空 12:50 / 15:30　18,682 元", message)

    def test_lowest_block_does_not_borrow_missing_return_time(self) -> None:
        missing_return = {**QUOTE, "return_time": None}
        other_quote = {**QUOTE, "airline": "星宇", "price": 20492, "outbound_time": "10:10", "return_time": "13:45"}
        message = build_message(ROUTE, missing_return, HISTORY, SUMMARY, None, [missing_return, other_quote])
        self.assertIn("國泰航空 12:50 / 未取得　18,682 元", message)
        self.assertNotIn("國泰航空 12:50 / 13:45", message)

    def test_range_block_lists_best_quote_for_each_departure_date(self) -> None:
        range_summary = {
            "departure_start": "2027-01-30",
            "departure_end": "2027-01-31",
            "return_start": "2027-02-06",
            "return_end": "2027-02-09",
            "best_quote": {"price": 20830},
            "departure_best_quotes": [
                {
                    "airline": "國泰航空",
                    "departure_date": "2027-01-30",
                    "return_date": "2027-02-06",
                    "departure_time": "12:50",
                    "return_time": "15:30",
                    "price": 20830,
                    "success": True,
                },
                {
                    "airline": "星宇航空",
                    "departure_date": "2027-01-31",
                    "return_date": "2027-02-09",
                    "departure_time": "10:10",
                    "return_time": "13:15",
                    "price": 21831,
                    "success": True,
                },
            ],
        }
        message = build_message(ROUTE, QUOTE, HISTORY, SUMMARY, None, [QUOTE], range_summary)
        self.assertIn("國泰航空　01/30 ~ 02/06　12:50 / 15:30　20,830 元", message)
        self.assertIn("星宇航空　01/31 ~ 02/09　10:10 / 13:15　21,831 元", message)
        self.assertLess(message.index("01/30 ~ 02/06"), message.index("01/31 ~ 02/09"))

    def test_range_block_keeps_failed_departure_date(self) -> None:
        range_summary = {
            "departure_start": "2027-01-30",
            "departure_end": "2027-01-31",
            "return_start": "2027-02-06",
            "return_end": "2027-02-09",
            "best_quote": {"price": 21831},
            "departure_best_quotes": [
                {"departure_date": "2027-01-30", "success": False, "error": "該日期未取得有效報價"},
                {
                    "airline": "星宇航空",
                    "departure_date": "2027-01-31",
                    "return_date": "2027-02-09",
                    "departure_time": "10:10",
                    "return_time": "13:15",
                    "price": 21831,
                    "success": True,
                },
            ],
        }
        message = build_message(ROUTE, QUOTE, HISTORY, SUMMARY, None, [QUOTE], range_summary)
        self.assertIn("01/30　該日期未取得有效報價", message)
        self.assertIn("星宇航空　01/31 ~ 02/09　10:10 / 13:15　21,831 元", message)


if __name__ == "__main__":
    unittest.main()
