from datetime import datetime, timedelta

import pytest

from flow_metrics import metrics, narrative, synthetic
from flow_metrics.synthetic import Issue, Transition

T0 = datetime(2026, 1, 5, 9, 0)


def make_issue(key, path):
    """path: list of (status, day_offset)."""
    iss = Issue(key=key, issue_type="Story", created=T0 + timedelta(days=path[0][1]))
    prev = None
    for status, d in path:
        iss.transitions.append(Transition(key, prev, status, T0 + timedelta(days=d)))
        prev = status
    return iss


def test_percentile_matches_linear_interpolation():
    assert metrics.percentile([1, 2, 3, 4], 50) == 2.5
    assert metrics.percentile([10], 85) == 10
    assert metrics.percentile([], 85) is None


def test_lead_cycle_and_flow_efficiency_on_known_case():
    # To Do 2d -> In Progress 3d -> Waiting to Test 5d -> Testing 2d -> Done
    iss = make_issue("A-1", [("To Do", 0), ("In Progress", 2), ("Waiting to Test", 5), ("Testing", 10), ("Done", 12)])
    rep = metrics.compute([iss], now=T0 + timedelta(days=20))
    assert rep.lead_time_p50 == pytest.approx(12)
    assert rep.cycle_time_p50 == pytest.approx(10)
    # active = 3 + 2 = 5, wait = 5  -> 50%
    assert rep.flow_efficiency == pytest.approx(0.5)
    assert rep.bottleneck_status == "Waiting to Test"
    assert rep.n_done == 1 and rep.wip == 0


def test_flow_efficiency_is_ratio_of_sums_not_mean_of_ratios():
    a = make_issue("A-1", [("To Do", 0), ("In Progress", 0), ("Done", 1)])  # 100% efficient, 1 day
    b = make_issue("A-2", [("To Do", 0), ("In Progress", 0), ("Waiting to Test", 1), ("Done", 10)])  # 1 active / 9 wait
    rep = metrics.compute([a, b], now=T0 + timedelta(days=30))
    # ratio of sums: (1+1) / (1+1+9) = 0.1818; mean of ratios would be 0.55
    assert rep.flow_efficiency == pytest.approx(2 / 11)


def test_open_items_count_as_wip_and_not_in_lead_time():
    open_item = make_issue("A-3", [("To Do", 0), ("In Progress", 1)])
    rep = metrics.compute([open_item], now=T0 + timedelta(days=5))
    assert rep.n_done == 0 and rep.wip == 1
    assert rep.lead_time_p85 is None


def test_monte_carlo_is_deterministic_and_ordered():
    f1 = metrics.monte_carlo_weeks([3, 5, 4, 6, 2], backlog=40, runs=2000)
    f2 = metrics.monte_carlo_weeks([3, 5, 4, 6, 2], backlog=40, runs=2000)
    assert f1 == f2
    assert f1["p50"] <= f1["p85"] <= f1["p95"]


def test_monte_carlo_rejects_zero_history():
    with pytest.raises(ValueError):
        metrics.monte_carlo_weeks([0, 0], backlog=5)


def test_synthetic_data_finds_waiting_to_test_bottleneck():
    issues = synthetic.generate(300, seed=1)
    rep = metrics.compute(issues, now=datetime(2026, 6, 1))
    assert rep.bottleneck_status == "Waiting to Test"


def test_template_narrative_passes_number_guardrail():
    issues = synthetic.generate(120)
    rep = metrics.compute(issues, now=datetime(2026, 4, 30, 18))
    fc = metrics.monte_carlo_weeks(list(rep.throughput_per_week.values()), 40)
    facts = narrative.fact_sheet(rep, fc, 40)
    text = narrative.template_narrative(facts)
    assert narrative.validate_narrative(text, facts) == []


def test_guardrail_catches_invented_numbers():
    facts = {"lead_time_p85_dias": 12.3}
    assert narrative.validate_narrative("P85 de 12.3 dias, mas cai para 47 dias", facts) == ["47"]
