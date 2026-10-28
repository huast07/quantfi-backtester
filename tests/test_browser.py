"""The JSON API the web app's Pyodide workers call. Its results must equal the CLI's for the same case and seed."""

import json

import pytest

from quantgen import browser
from quantgen.adapter.runner import MatchMode
from quantgen.adapter.strategy import Strategy
from quantgen.cases.case import load_catalog
from quantgen.scoring.reference import REFERENCE_NAME, reference_strategy
from quantgen.scoring.run_suite import run_suite
from quantgen.scoring.suites import custom_suite
from quantgen.scoring.verdicts import all_verdicts
from quantgen.serde import to_dict

TAKES_AMETHYST = """
from datamodel import Order

class Trader:
    def run(self, state):
        depth = state.order_depths["AMETHYST"]
        position = state.position.get("AMETHYST", 0)
        print("position", position)
        if state.timestamp < 2_000 and position < 5 and depth.sell_orders:
            return {"AMETHYST": [Order("AMETHYST", min(depth.sell_orders), 1)]}, 0, ""
        return {}, 0, ""
"""
CASE_ID = "regular-day"
SEED = 1


def as_json(value):
    """What the web app receives: JSON object keys are strings, so seed-keyed maps compare after a round trip."""
    return json.loads(json.dumps(value))


def call(function, payload=None):
    return json.loads(function(json.dumps(payload)) if payload is not None else function())


@pytest.fixture(scope="module")
def ready(calibrated_params, tmp_path_factory):
    path = tmp_path_factory.mktemp("browser") / "params.json"
    path.write_text(json.dumps(to_dict(calibrated_params)))
    browser.init(str(path))
    return calibrated_params


@pytest.fixture(scope="module")
def runs(ready):
    payload = {"strategies": [{"name": "takes.py", "source": TAKES_AMETHYST}], "case_id": CASE_ID, "seed": SEED}
    return call(browser.run_case, {**payload, "match_mode": "all", "reference": True})


def test_catalog_lists_every_case_suite_and_tier_weight():
    catalog = call(browser.catalog)

    assert [case["id"] for case in catalog["cases"]] == [case.id for case in load_catalog()]
    assert {"id", "title", "tier", "family", "summary", "description", "references"} <= set(catalog["cases"][0])
    assert set(catalog["suites"]) == {"quick", "standard", "full"}
    assert catalog["suites"]["quick"]["indicative"] is True
    assert catalog["tier_weights"] == {"observed": 0.6, "plausible": 0.3, "stress": 0.1}
    assert catalog["reference"] == REFERENCE_NAME


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("def broken(:\n", "syntax error on line 1"),
        ("x = 1\n", "does not define a Trader class"),
        ("import no_such_module_here\n", "imports 'no_such_module_here'"),
    ],
)
def test_bad_strategies_are_reported_with_a_message_the_user_can_act_on(source, message):
    result = call(browser.check_strategy, {"name": "bad.py", "source": source})

    assert result["ok"] is False
    assert message in result["error"]


def test_a_valid_strategy_passes_the_check():
    assert call(browser.check_strategy, {"name": "takes.py", "source": TAKES_AMETHYST}) == {"ok": True, "error": None}


def test_reserved_and_duplicate_names_are_rejected(ready):
    strategy = {"name": REFERENCE_NAME, "source": TAKES_AMETHYST}

    with pytest.raises(ValueError, match="unique"):
        browser.run_case(json.dumps({"strategies": [strategy], "case_id": CASE_ID, "seed": SEED}))


def test_browser_runs_and_report_equal_the_cli_suite_for_the_same_case_and_seed(ready, runs):
    suite = custom_suite([CASE_ID], 1)
    strategies = [Strategy("takes.py", TAKES_AMETHYST), reference_strategy()]
    cli = run_suite(strategies, ready, suite.cases(load_catalog()), suite, MatchMode.ALL)
    cli_stats = {name: cli.stats(name) for name in cli.strategies}
    cli_verdicts = all_verdicts(cli_stats, ["takes.py"], REFERENCE_NAME)

    report = call(
        browser.report,
        {"suite": {"case_ids": [CASE_ID], "seeds": [SEED]}, "strategies": ["takes.py"], "runs": runs},
    )

    assert runs == as_json([to_dict(run) for run in cli.runs])
    assert report["stats"] == as_json({name: [to_dict(s) for s in stats] for name, stats in cli_stats.items()})
    assert report["verdicts"] == as_json({name: [to_dict(v) for v in v_] for name, v_ in cli_verdicts.items()})
    assert report["indicative"] is True
    assert "Performs well in:" in report["text"]


def test_drill_down_traces_agree_with_the_run_metrics(ready, runs):
    metrics = next(run for run in runs if run["strategy"] == "takes.py")
    payload = {"strategy": {"name": "takes.py", "source": TAKES_AMETHYST}, "case_id": CASE_ID, "seed": SEED}

    detail = call(browser.drill, payload)

    assert detail["total_pnl"][-1] == pytest.approx(metrics["total_pnl"])
    amethyst = next(trace for trace in detail["products"] if trace["product"] == "AMETHYST")
    assert amethyst["pnl"][-1] == pytest.approx(metrics["product_pnl"]["AMETHYST"])
    assert len(amethyst["mid"]) == len(detail["timestamps"]) == len(amethyst["position"])
    assert amethyst["position"][-1] == sum(fill["quantity"] for fill in amethyst["fills"])
    assert len(amethyst["fills"]) == metrics["own_trades"]
    assert detail["logs"][0]["text"].startswith("position")


def test_visualizer_log_is_prosperity3bt_output_format(ready):
    payload = {"strategy": {"name": "takes.py", "source": TAKES_AMETHYST}, "case_id": CASE_ID, "seed": SEED}

    log = browser.visualizer_log(json.dumps(payload))

    assert log.startswith("Sandbox logs:\n")
    assert "Activities log:" in log
    assert "Trade History:" in log


def test_case_download_is_competition_csv(ready):
    files = call(browser.case_csv, {"case_id": CASE_ID, "seed": SEED})

    assert files["prices"].startswith("day;timestamp;product;bid_price_1")
    assert files["trades"].startswith("timestamp;buyer;seller;symbol;currency;price;quantity")
    assert files["day"] == ready.day
