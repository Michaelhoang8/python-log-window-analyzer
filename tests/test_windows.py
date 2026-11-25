import contextlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import unittest

from log_windows import Windows, main, parse_event, percentile


def event(second, latency=10, service="api", level="info"):
    return parse_event({"timestamp": f"2026-01-01T00:{second // 60:02}:{second % 60:02}Z", "service": service, "level": level, "latencyMs": latency})


class WindowTests(unittest.TestCase):
    def test_left_boundary_is_open_and_ties_are_retained(self):
        window = Windows(10)
        window.add(event(0, 100))
        window.add(event(1, 20))
        self.assertEqual(window.add(event(10, 30))["count"], 2)
        self.assertEqual(window.add(event(10, 40))["count"], 3)

    def test_services_do_not_mix_and_idle_services_expire(self):
        window = Windows(10)
        window.add(event(0, service="other", level="error"))
        row = window.add(event(10, service="api"))
        self.assertEqual((row["errors"], row["count"]), (0, 1))
        self.assertNotIn("other", window.services)

    def test_nearest_rank_and_error_denominator(self):
        window = Windows()
        for i in range(1, 21):
            row = window.add(event(i, i, level="error" if i == 20 else "warning"))
        self.assertEqual((row["p50LatencyMs"], row["p95LatencyMs"]), (10, 19))
        self.assertEqual(row["errorRate"], 0.05)
        self.assertEqual(row["meanLatencyMs"], 10.5)

    def test_rejects_out_of_order_globally(self):
        window = Windows()
        window.add(event(2, service="a"))
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            window.add(event(1, service="b"))

    def test_memory_guard_is_explicit(self):
        window = Windows(1, 1)
        window.add(event(0))
        with self.assertRaisesRegex(ValueError, "max-events"):
            window.add(event(0))
        self.assertEqual(window.add(event(1))["count"], 1)

    def test_rejects_missing_timezone_and_bad_measurements(self):
        base = {"timestamp": "2026-01-01T00:00:00Z", "service": "api", "level": "info", "latencyMs": 0}
        for field, value in [("timestamp", "2026-01-01T00:00:00"), ("timestamp", "bad"), ("service", ""), ("latencyMs", True), ("latencyMs", float("nan")), ("latencyMs", -1)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                parse_event(base | {field: value})

    def test_timezone_offsets_normalize(self):
        base = {"service": "api", "level": "info", "latencyMs": 0}
        a = parse_event(base | {"timestamp": "2026-01-01T01:00:00+01:00"})
        b = parse_event(base | {"timestamp": "2026-01-01T00:00:00Z"})
        self.assertEqual(a, b)

    def test_invalid_cli_line_does_not_hide_ordering_failure(self):
        raw = '\n'.join([json.dumps({"timestamp": "2026-01-01T00:00:02Z", "service": "api", "level": "info", "latencyMs": 10}), 'invalid', json.dumps({"timestamp": "2026-01-01T00:00:01Z", "service": "api", "level": "info", "latencyMs": 10})])
        result = subprocess.run([sys.executable, "log_windows.py", "-", "--skip-invalid"], input=raw, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("line 3", result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_empty_input_and_exact_fixture(self):
        result = subprocess.run([sys.executable, "log_windows.py", "fixtures/events.jsonl", "--window-seconds", "10"], text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, Path("fixtures/expected.jsonl").read_text())
        result = subprocess.run([sys.executable, "log_windows.py", "-"], input="", text=True, capture_output=True)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_configuration_and_percentile_bounds(self):
        for width in [0, -1, float("inf")]:
            with self.assertRaises(ValueError): Windows(width)
        with self.assertRaises(ValueError): percentile([], 0.5)


if __name__ == "__main__": unittest.main()
