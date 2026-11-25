"""Rolling event-time statistics. Python standard library only."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import sys
from typing import Iterable


@dataclass(frozen=True)
class Event:
    timestamp: datetime
    service: str
    level: str
    latency: float


def parse_event(value: object) -> Event:
    if not isinstance(value, dict):
        raise ValueError("record must be an object")
    timestamp = value.get("timestamp")
    if not isinstance(timestamp, str) or "T" not in timestamp:
        raise ValueError("timestamp must be a timezone-aware ISO date-time")
    try:
        date = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if date.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    service = value.get("service")
    if not isinstance(service, str) or not service.strip() or len(service) > 200:
        raise ValueError("service must contain 1-200 characters")
    if value.get("level") not in {"debug", "info", "warning", "error"}:
        raise ValueError("level must be debug, info, warning, or error")
    latency = value.get("latencyMs")
    if isinstance(latency, bool) or not isinstance(latency, (int, float)):
        raise ValueError("latencyMs must be a finite nonnegative number")
    try:
        latency = float(latency)
    except OverflowError as exc:
        raise ValueError("latencyMs exceeds the numeric range") from exc
    if not math.isfinite(latency) or latency < 0:
        raise ValueError("latencyMs must be a finite nonnegative number")
    return Event(date.astimezone(timezone.utc), service, value["level"], latency)


def percentile(sorted_values: list[float], probability: float) -> float:
    """Nearest rank: sorted_values[ceil(p*n)-1], for 0 < p <= 1."""
    if not sorted_values or not 0 < probability <= 1:
        raise ValueError("percentile requires values and 0 < probability <= 1")
    return sorted_values[math.ceil(probability * len(sorted_values)) - 1]


class Windows:
    def __init__(self, seconds: float = 60, max_events: int = 100_000):
        if not math.isfinite(seconds) or seconds <= 0 or seconds > 31_536_000:
            raise ValueError("window must be positive and at most 365 days")
        if max_events < 1:
            raise ValueError("max-events must be positive")
        self.width = timedelta(seconds=seconds)
        self.seconds = seconds
        self.max_events = max_events
        self.events: deque[Event] = deque()
        self.services: dict[str, deque[Event]] = {}
        self.last: datetime | None = None

    def add(self, event: Event) -> dict:
        if self.last is not None and event.timestamp < self.last:
            raise ValueError("timestamps must be globally nondecreasing")
        cutoff = event.timestamp - self.width
        while self.events and self.events[0].timestamp <= cutoff:
            expired = self.events.popleft()
            group = self.services[expired.service]
            group.popleft()
            if not group:
                del self.services[expired.service]
        if len(self.events) >= self.max_events:
            raise ValueError("active window exceeds max-events")
        self.last = event.timestamp
        self.events.append(event)
        group = self.services.setdefault(event.service, deque())
        group.append(event)
        latencies = sorted(item.latency for item in group)
        errors = sum(item.level == "error" for item in group)
        return {
            "timestamp": event.timestamp.isoformat().replace("+00:00", "Z"),
            "service": event.service,
            "windowSeconds": self.seconds,
            "count": len(group),
            "errors": errors,
            "errorRate": errors / len(group),
            # Scaling before summation avoids overflow for large finite values.
            "meanLatencyMs": math.fsum(x / len(group) for x in latencies),
            "p50LatencyMs": percentile(latencies, 0.5),
            "p95LatencyMs": percentile(latencies, 0.95),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="UTF-8 JSONL file, or - for standard input")
    parser.add_argument("--window-seconds", type=float, default=60)
    parser.add_argument("--max-events", type=int, default=100_000)
    parser.add_argument("--skip-invalid", action="store_true", help="skip malformed records; ordering errors remain fatal")
    args = parser.parse_args(argv)
    stream = None
    try:
        windows = Windows(args.window_seconds, args.max_events)
        stream = sys.stdin if args.input == "-" else open(args.input, encoding="utf-8-sig")
        for line_number, line in enumerate(stream, 1):
            try:
                event = parse_event(json.loads(line))
            except (ValueError, TypeError) as exc:
                print(f"line {line_number}: {exc}", file=sys.stderr)
                if args.skip_invalid:
                    continue
                return 2
            try:
                result = windows.add(event)
            except (ValueError, OverflowError) as exc:
                print(f"line {line_number}: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, allow_nan=False, sort_keys=True))
    except (OSError, UnicodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if stream is not None and stream is not sys.stdin:
            stream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
