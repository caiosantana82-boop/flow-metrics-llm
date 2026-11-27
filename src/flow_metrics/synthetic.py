"""Synthetic Jira-like data generator.

Produces issues and a status changelog shaped like the Jira REST API v3
changelog, so the metrics engine can be exercised without any real data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Workflow with a flow category per status (see metrics.STATUS_CATEGORY).
WORKFLOW = ["To Do", "In Progress", "Code Review", "Waiting to Test", "Testing", "Done"]

# Mean days spent in each status (exponential), tuned so "Waiting to Test"
# becomes the bottleneck, which is a common real-world pattern.
MEAN_DAYS = {
    "To Do": 3.0,
    "In Progress": 2.5,
    "Code Review": 1.0,
    "Waiting to Test": 4.0,
    "Testing": 1.2,
}

ISSUE_TYPES = ["Story", "Bug", "Task"]


@dataclass
class Transition:
    issue_key: str
    from_status: str | None
    to_status: str
    at: datetime


@dataclass
class Issue:
    key: str
    issue_type: str
    created: datetime
    transitions: list[Transition] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.transitions[-1].to_status if self.transitions else "To Do"


def generate(n_issues: int = 120, start: datetime | None = None, seed: int = 42) -> list[Issue]:
    """Generate `n_issues` synthetic issues with a full changelog."""
    rng = random.Random(seed)
    start = start or datetime(2026, 1, 5, 9, 0)
    issues: list[Issue] = []

    for i in range(n_issues):
        key = f"DEMO-{i + 1:04d}"
        created = start + timedelta(days=rng.uniform(0, 90))
        issue = Issue(key=key, issue_type=rng.choice(ISSUE_TYPES), created=created)
        issue.transitions.append(Transition(key, None, "To Do", created))

        t = created
        # ~15% of issues are still open somewhere in the workflow.
        stop_at = len(WORKFLOW) if rng.random() > 0.15 else rng.randint(1, len(WORKFLOW) - 1)
        prev = "To Do"
        for status in WORKFLOW[1:stop_at]:
            t += timedelta(days=rng.expovariate(1 / MEAN_DAYS[prev]))
            # ~8% rework: bounce from Testing back to In Progress once.
            if status == "Done" and rng.random() < 0.08:
                issue.transitions.append(Transition(key, prev, "In Progress", t))
                t += timedelta(days=rng.expovariate(1 / MEAN_DAYS["In Progress"]))
                issue.transitions.append(Transition(key, "In Progress", "Testing", t))
                t += timedelta(days=rng.expovariate(1 / MEAN_DAYS["Testing"]))
                prev = "Testing"
            issue.transitions.append(Transition(key, prev, status, t))
            prev = status
        issues.append(issue)

    return issues
