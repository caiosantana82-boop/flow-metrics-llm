"""Deterministic flow metrics engine.

All metrics follow explicit, documented rules so results are reproducible
and auditable. Nothing here calls an LLM.

Rules
-----
- Lead time: first transition to any status (creation) -> first entry into DONE.
- Cycle time: first entry into an ACTIVE status -> first entry into DONE.
- Flow efficiency: sum(time in ACTIVE) / sum(time in ACTIVE + WAIT), computed
  as a ratio of sums across issues (not an average of per-issue percentages).
- Throughput: count of issues entering DONE per ISO week.
- Bottleneck: status (non-terminal, non-backlog) with the highest mean dwell time.
- Forecast: Monte Carlo sampling of historical weekly throughput.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .synthetic import Issue

QUEUE, ACTIVE, WAIT, DONE = "QUEUE", "ACTIVE", "WAIT", "DONE"

STATUS_CATEGORY = {
    "To Do": QUEUE,
    "In Progress": ACTIVE,
    "Code Review": WAIT,
    "Waiting to Test": WAIT,
    "Testing": ACTIVE,
    "Done": DONE,
}


def _days(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 86400


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (same method as numpy's default)."""
    if not values:
        return None
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def dwell_times(issue: Issue, now: datetime) -> list[tuple[str, float]]:
    """(status, days) for each stay; the open stay is measured until `now`."""
    out = []
    trs = issue.transitions
    for i, tr in enumerate(trs):
        end = trs[i + 1].at if i + 1 < len(trs) else now
        if STATUS_CATEGORY.get(tr.to_status) == DONE:
            continue
        out.append((tr.to_status, _days(tr.at, end)))
    return out


def _first_entry(issue: Issue, category: str) -> datetime | None:
    for tr in issue.transitions:
        if STATUS_CATEGORY.get(tr.to_status) == category:
            return tr.at
    return None


@dataclass
class FlowReport:
    n_issues: int
    n_done: int
    lead_time_p50: float | None
    lead_time_p85: float | None
    cycle_time_p50: float | None
    cycle_time_p85: float | None
    flow_efficiency: float | None
    throughput_per_week: dict[str, int]
    throughput_avg: float
    wip: int
    rework_rate: float
    bottleneck_status: str | None
    bottleneck_mean_days: float | None
    mean_dwell_by_status: dict[str, float]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def compute(issues: list[Issue], now: datetime) -> FlowReport:
    lead, cycle = [], []
    active_sum = wait_sum = 0.0
    dwell = defaultdict(list)
    weekly = defaultdict(int)
    rework = 0

    for iss in issues:
        done_at = _first_entry(iss, DONE)
        stays = dwell_times(iss, now)
        for status, d in stays:
            dwell[status].append(d)
        # Rework: any transition backwards from Testing to In Progress.
        if any(t.from_status == "Testing" and t.to_status == "In Progress" for t in iss.transitions):
            rework += 1
        if done_at is None:
            continue
        lead.append(_days(iss.transitions[0].at, done_at))
        started = _first_entry(iss, ACTIVE)
        if started:
            cycle.append(_days(started, done_at))
        for status, d in stays:
            cat = STATUS_CATEGORY.get(status)
            if cat == ACTIVE:
                active_sum += d
            elif cat == WAIT:
                wait_sum += d
        y, w, _ = done_at.isocalendar()
        weekly[f"{y}-W{w:02d}"] += 1

    mean_dwell = {s: sum(v) / len(v) for s, v in dwell.items()}
    candidates = {s: m for s, m in mean_dwell.items() if STATUS_CATEGORY.get(s) in (ACTIVE, WAIT)}
    bottleneck = max(candidates, key=candidates.get) if candidates else None
    weekly_sorted = dict(sorted(weekly.items()))
    wip = sum(1 for i in issues if STATUS_CATEGORY.get(i.status) in (ACTIVE, WAIT))

    return FlowReport(
        n_issues=len(issues),
        n_done=len(lead),
        lead_time_p50=percentile(lead, 50),
        lead_time_p85=percentile(lead, 85),
        cycle_time_p50=percentile(cycle, 50),
        cycle_time_p85=percentile(cycle, 85),
        flow_efficiency=(active_sum / (active_sum + wait_sum)) if (active_sum + wait_sum) else None,
        throughput_per_week=weekly_sorted,
        throughput_avg=(sum(weekly_sorted.values()) / len(weekly_sorted)) if weekly_sorted else 0.0,
        wip=wip,
        rework_rate=rework / len(issues) if issues else 0.0,
        bottleneck_status=bottleneck,
        bottleneck_mean_days=candidates.get(bottleneck) if bottleneck else None,
        mean_dwell_by_status=dict(sorted(mean_dwell.items(), key=lambda kv: -kv[1])),
    )


def monte_carlo_weeks(
    weekly_throughput: list[int], backlog: int, runs: int = 10_000, seed: int = 7
) -> dict[str, int]:
    """How many weeks to finish `backlog` items? Returns P50/P85/P95."""
    sample = [x for x in weekly_throughput if x >= 0]
    if backlog <= 0:
        return {"p50": 0, "p85": 0, "p95": 0}
    if not sample or max(sample) == 0:
        raise ValueError("historical throughput is empty or zero; cannot forecast")
    rng = random.Random(seed)
    results = []
    for _ in range(runs):
        done = weeks = 0
        while done < backlog:
            done += rng.choice(sample)
            weeks += 1
        results.append(weeks)
    return {f"p{p}": int(math.ceil(percentile(results, p))) for p in (50, 85, 95)}
