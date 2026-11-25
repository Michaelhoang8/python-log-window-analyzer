# Log Window Analyzer

A Python CLI that reads time-ordered JSONL logs and emits rolling error and latency statistics for the service in each accepted record. Useful for inspecting bounded log extracts without a database or metrics server.

```sh
python log_windows.py --help
python log_windows.py fixtures/events.jsonl --window-seconds 10
python -m unittest discover -s tests -v
```

Requires Python 3.11 or later; no dependencies. Use `-` as the input to read standard input. The included fixture is a small authored test example, not production telemetry.

Each record needs `timestamp` (timezone-aware ISO date-time), `service`, `level` (`debug`, `info`, `warning`, `error`) and a finite, nonnegative `latencyMs`. Additional fields are ignored. Times normalize to UTC. Records must be globally nondecreasing in event time; equal timestamps are allowed and processed in input order.

For timestamp `t`, the window is **(t - window, t]**: the left boundary is excluded. Counts include all levels, while the error numerator includes only `error`. Percentiles use the nearest-rank definition: sort the `n` values and select rank `ceil(p*n)`, starting at 1. They are exact within the retained window and are not interpolated. The final checkout fixture row contains 2 events, an error rate of 0.5, mean latency 60 ms and p95 90 ms.

`--skip-invalid` skips malformed records with line-numbered diagnostics. Ordering violations and memory-limit violations always fail. Exit codes: 0 for completed processing, 2 for an error. Output is incremental: an error can follow already-emitted rows. Blank lines are invalid records. There are no periodic rows for idle services and no final wall-clock flush.

The implementation retains only the active event-time window, with a default 100,000-event cap (`--max-events`). Exact per-record quantiles sort the selected service's retained values, taking O(k log k) time. This is intended for offline inspection, not a high-throughput monitoring backend. It does not reorder late events, deduplicate request IDs, estimate missing observations or classify SLO violations.
