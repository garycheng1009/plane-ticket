from __future__ import annotations

import unittest

from tracker import has_fatal_error


class TrackerExitTests(unittest.TestCase):
    def test_no_quote_does_not_fail_workflow(self) -> None:
        self.assertFalse(has_fatal_error([{"status": "no_quote"}]))

    def test_error_fails_workflow(self) -> None:
        self.assertTrue(has_fatal_error([{"status": "error"}]))
