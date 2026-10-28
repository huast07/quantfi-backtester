from types import MappingProxyType

import pytest

from quantgen.adapter.strategy import load_trader
from quantgen.cases.case import find_cases, load_catalog
from quantgen.products import POSITION_LIMITS
from quantgen.scoring.metrics import CaseStats, RunMetrics, case_stats, max_drawdown, overall, tier_weighted
from quantgen.scoring.reference import reference_strategy
from quantgen.scoring.report import suite_report
from quantgen.scoring.run_suite import run_suite
from quantgen.scoring.suites import QUICK_CASES, SUITES, custom_suite
from quantgen.scoring.verdicts import NEUTRAL, STRONG, WEAK, all_verdicts, verdict

IDLE = 'class Trader:\n    def run(self, state):\n        return {}, 0, ""\n'
CRASHES_LATER = """
class Trader:
    def run(self, state):
        if state.timestamp == 500:
            raise RuntimeError("boom")
        return {}, 0, ""
"""


def stats(strategy: str, case_id: str, pnl: dict[int, float], tier: str = "observed", **extra) -> CaseStats:
    values = list(pnl.values())
    return CaseStats(
        strategy=strategy,
        case_id=case_id,
        tier=tier,
        pnl_by_seed=MappingProxyType(pnl),
        mean_pnl=sum(values) / len(values),
        worst_pnl=min(values),
        product_mean_pnl=MappingProxyType(extra.get("products", {"AMETHYST": sum(values) / len(values)})),
        mean_drawdown=0.0,
        limit_breaches=extra.get("breaches", 0),
        errors=extra.get("errors", ()),
    )


def test_drawdown_is_the_largest_fall_from_a_running_peak():
    assert max_drawdown([0, 5, 2, 8, 1, 3]) == 7
    assert max_drawdown([]) == 0.0


def test_case_stats_average_seeds_and_products():
    runs = [
        RunMetrics("a", "c", 1, 10.0, MappingProxyType({"X": 10.0}), 1.0, 3, 0),
        RunMetrics("a", "c", 2, -4.0, MappingProxyType({"X": -2.0, "Y": -2.0}), 3.0, 2, 1),
    ]

    result = case_stats(runs, "stress")

    assert result.mean_pnl == 3.0 and result.worst_pnl == -4.0
    assert dict(result.product_mean_pnl) == {"X": 4.0, "Y": -1.0}
    assert result.mean_drawdown == 2.0 and result.limit_breaches == 1
    assert result.products_traded == 2


def test_tier_weights_split_within_tiers_and_renormalise_missing_tiers():
    observed = [stats("a", "o1", {1: 100.0}), stats("a", "o2", {1: 200.0})]
    stress = [stats("a", "s1", {1: -1000.0}, tier="stress")]

    assert tier_weighted(observed + stress) == pytest.approx((0.6 * 150 + 0.1 * -1000) / 0.7)
    assert tier_weighted(observed) == pytest.approx(150.0)
    assert overall(observed + stress).worst_case == "s1"


def test_losing_money_is_always_weak():
    case = stats("a", "c", {1: -5.0, 2: -1.0})

    assert verdict(case, [case], []).rating == WEAK


def test_strong_cases_are_where_the_edge_over_others_is_largest_not_everywhere():
    # a beats b in every case, but by far the most in "storm": only that case is strong on the relative side
    a = [stats("a", c, {1: 100.0, 2: 100.0}) for c in ("c1", "c2", "c3", "c4")] + [
        stats("a", "storm", {1: 100.0, 2: 100.0})
    ]
    b = [stats("b", c, {1: 90.0, 2: 90.0}) for c in ("c1", "c2", "c3", "c4")] + [
        stats("b", "storm", {1: -900.0, 2: -800.0})
    ]

    verdicts = all_verdicts({"a": a, "b": b}, ["a", "b"])

    assert [v.rating for v in verdicts["a"]] == [NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL, STRONG]
    assert "beats b on every seed" in verdicts["a"][0].reason
    assert "well above its usual" in verdicts["a"][4].reason
    assert verdicts["b"][4].rating == WEAK


def test_mixed_seed_results_against_a_peer_are_not_reported_as_beating_it():
    mine = [stats("a", "c1", {1: 10.0, 2: 12.0}), stats("a", "c2", {1: 11.0, 2: 11.0})]
    theirs = stats("b", "c1", {1: 15.0, 2: 6.0})

    result = verdict(mine[0], mine, [theirs])

    assert result.rating == NEUTRAL
    assert "beats" not in result.reason and "behind" not in result.reason


def test_far_above_own_average_is_strong_unless_the_reference_is_ahead_on_every_seed():
    own = [stats("a", f"c{i}", {1: 100.0, 2: 100.0}) for i in range(4)] + [stats("a", "good", {1: 900.0, 2: 900.0})]
    behind = stats("reference", "good", {1: 1000.0, 2: 950.0})
    mixed = stats("reference", "good", {1: 1000.0, 2: 10.0})

    assert verdict(own[-1], own, []).rating == STRONG
    assert verdict(own[-1], own, [], baseline=mixed).rating == STRONG
    demoted = verdict(own[-1], own, [], baseline=behind)
    assert demoted.rating == NEUTRAL and "behind reference" in demoted.reason


def test_seeds_that_disagree_in_sign_are_flagged():
    case = stats("a", "c", {1: 900.0, 2: -100.0})

    assert "seeds disagree (-100 to +900)" in verdict(case, [case], []).reason


def test_far_below_own_average_is_weak_even_when_profitable():
    own = [stats("a", f"c{i}", {1: 1000.0}) for i in range(4)] + [stats("a", "bad", {1: 10.0})]

    result = verdict(own[-1], own, [])

    assert result.rating == WEAK
    assert "well below its average" in result.reason


def test_weak_reason_names_the_losing_product():
    case = stats("a", "c", {1: -500.0}, products={"TELLURIUM": -900.0, "AMETHYST": 400.0})

    assert "of which TELLURIUM -900" in verdict(case, [case], []).reason


def test_crashes_are_weak_and_reported():
    case = stats("a", "c", {1: 0.0}, errors=("seed 1: RuntimeError: boom",))

    result = verdict(case, [case], [])

    assert result.rating == WEAK and "boom" in result.reason


def test_a_single_strategy_is_judged_against_the_reference():
    table = {"a": [stats("a", "c", {1: 10.0, 2: 10.0})], "reference": [stats("reference", "c", {1: 0.0, 2: 1.0})]}

    verdicts = all_verdicts(table, ["a"], "reference")

    assert list(verdicts) == ["a"]
    assert verdicts["a"][0].rating == NEUTRAL
    assert "beats reference" in verdicts["a"][0].reason


def test_suites_cover_the_planned_runs():
    catalog = load_catalog()

    assert len(SUITES["quick"].cases(catalog)) == len(QUICK_CASES) == 8
    assert len(SUITES["standard"].cases(catalog)) * len(SUITES["standard"].seeds) == 2 * len(catalog)
    assert len(SUITES["full"].cases(catalog)) * len(SUITES["full"].seeds) == 5 * len(catalog)
    assert SUITES["quick"].indicative and not SUITES["standard"].indicative
    assert custom_suite(["regular-day"], 3).seeds == (1, 2, 3)
    with pytest.raises(ValueError):
        custom_suite(None, 0)


def test_reference_strategy_loads_and_knows_every_limit():
    trader = load_trader(reference_strategy())
    limits = trader.run.__globals__["LIMITS"]

    assert dict(limits) == {name: limit for name, limit in POSITION_LIMITS.items() if name in limits}
    assert all(name in limits for name in POSITION_LIMITS if not name.startswith(("VOUCHER", "LYCHEE_VOUCHERS")))


@pytest.mark.slow
@pytest.mark.parametrize("workers", [1, 2])
def test_run_suite_runs_every_strategy_on_every_case_and_seed(calibrated_params, workers):
    from quantgen.adapter.strategy import Strategy

    suite = custom_suite(["regular-day", "anchor-break"], 1)
    cases = find_cases(load_catalog(), ["regular-day", "anchor-break"])
    strategies = [reference_strategy(), Strategy("idle.py", IDLE), Strategy("crash.py", CRASHES_LATER)]

    result = run_suite(strategies, calibrated_params, cases, suite, workers=workers)

    assert len(result.runs) == 6
    assert all(s.mean_pnl == 0 for s in result.stats("idle.py"))
    assert all(s.errors and "boom" in s.errors[0] for s in result.stats("crash.py"))
    table = {name: result.stats(name) for name in result.strategies}
    report = suite_report("t", cases, table, all_verdicts(table, ["idle.py", "crash.py"]), True)
    assert "crashed" in report and "indicative" in report
