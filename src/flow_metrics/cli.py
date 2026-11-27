"""Command line entry point.

    python -m flow_metrics.cli --issues 150 --backlog 40 --out report.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from . import metrics, narrative, synthetic


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flow metrics (deterministic) + LLM narrative")
    ap.add_argument("--issues", type=int, default=120, help="synthetic issues to generate")
    ap.add_argument("--backlog", type=int, default=40, help="backlog size for the forecast")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--now", default="2026-04-30T18:00", help="reference date (ISO)")
    ap.add_argument("--out", help="write the fact sheet + narrative as JSON")
    args = ap.parse_args(argv)

    now = datetime.fromisoformat(args.now)
    issues = synthetic.generate(args.issues, seed=args.seed)
    report = metrics.compute(issues, now)
    forecast = metrics.monte_carlo_weeks(list(report.throughput_per_week.values()), args.backlog)
    facts = narrative.fact_sheet(report, forecast, args.backlog)
    text = narrative.llm_narrative(facts)

    print(json.dumps(facts, ensure_ascii=False, indent=2))
    print()
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"facts": facts, "narrative": text}, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
