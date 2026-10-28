"""The JSON API the web app's Pyodide workers call: strings in, strings out, so nothing crosses the JS boundary but
text. Every function reuses the CLI's code path (suite runner, metrics, verdicts), so a result in the browser equals
the CLI's for the same strategy, case, seed and match mode.
"""

import json
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

from quantgen.adapter.detail import run_detail
from quantgen.adapter.result_log import format_log
from quantgen.adapter.runner import MatchMode, backtest
from quantgen.adapter.strategy import Strategy, StrategyError, load_trader
from quantgen.cases.case import Case, case_day, find_cases, load_catalog
from quantgen.generator.params import MarketParams, load_params
from quantgen.market_day import to_day_data
from quantgen.scoring.metrics import TIER_WEIGHTS, RunMetrics, case_stats, overall
from quantgen.scoring.reference import REFERENCE_NAME, reference_strategy
from quantgen.scoring.report import suite_report
from quantgen.scoring.run_suite import run_job
from quantgen.scoring.suites import SUITES, Suite
from quantgen.scoring.verdicts import all_verdicts
from quantgen.serde import from_dict, to_dict

MATCH_MODES = {"all": MatchMode.ALL, "worse": MatchMode.WORSE, "none": MatchMode.NONE}

_state: dict[str, MarketParams] = {}


def init(params_path: str) -> None:
    """Load the calibrated parameters once per worker."""
    _state["params"] = load_params(Path(params_path))


def _params() -> MarketParams:
    if "params" not in _state:
        raise RuntimeError("browser.init(params_path) must be called first")
    return _state["params"]


@cache
def _catalog() -> tuple[Case, ...]:
    return tuple(load_catalog())


def _case(case_id: str) -> Case:
    return find_cases(_catalog(), [case_id])[0]


def _strategy(data: dict[str, Any]) -> Strategy:
    return Strategy(name=str(data["name"]), source=str(data["source"]))


def _match_mode(name: str | None) -> Any:
    return MATCH_MODES[name or "all"]


def catalog() -> str:
    suites = {
        name: {"case_ids": suite.case_ids, "seeds": suite.seeds, "indicative": suite.indicative}
        for name, suite in SUITES.items()
    }
    return json.dumps(
        {
            "cases": [to_dict(case) for case in _catalog()],
            "suites": suites,
            "tier_weights": dict(TIER_WEIGHTS),
            "reference": REFERENCE_NAME,
            "match_modes": list(MATCH_MODES),
        }
    )


def check_strategy(payload: str) -> str:
    """Compile and instantiate the uploaded file the way a run would, without running it."""
    try:
        load_trader(_strategy(json.loads(payload)))
    except StrategyError as error:
        return json.dumps({"ok": False, "error": str(error)})
    return json.dumps({"ok": True, "error": None})


def _validate_names(strategies: Sequence[Strategy]) -> None:
    names = [s.name for s in strategies]
    if len(set(names)) != len(names) or REFERENCE_NAME in names:
        raise ValueError(f"strategy file names must be unique and not '{REFERENCE_NAME}'")


def run_case(payload: str) -> str:
    """Every uploaded strategy (and the reference when asked) on one case and seed: a list of RunMetrics."""
    data = json.loads(payload)
    strategies = [_strategy(s) for s in data["strategies"]]
    _validate_names(strategies)
    if data.get("reference"):
        strategies.append(reference_strategy())
    case, seed = _case(data["case_id"]), int(data["seed"])
    runs = run_job(_params(), case, seed, strategies, _match_mode(data.get("match_mode")))
    return json.dumps([to_dict(run) for run in runs])


def report(payload: str) -> str:
    """Per-case stats, verdicts and overall scores from the collected runs, plus the CLI's text report."""
    data = json.loads(payload)
    suite_data = data["suite"]
    seeds = tuple(int(seed) for seed in suite_data["seeds"])
    case_ids = suite_data.get("case_ids")
    cases = list(_catalog()) if case_ids is None else find_cases(_catalog(), case_ids)
    suite = Suite(suite_data.get("name", "custom"), None if case_ids is None else tuple(case_ids), seeds)
    runs = [from_dict(RunMetrics, run) for run in data["runs"]]
    judged = list(data["strategies"])
    names = judged + sorted({run.strategy for run in runs} - set(judged))
    stats = {
        name: [
            case_stats([run for run in runs if run.strategy == name and run.case_id == case.id], case.tier)
            for case in cases
        ]
        for name in names
    }
    reference = REFERENCE_NAME if REFERENCE_NAME in stats else None
    verdicts = all_verdicts(stats, judged, reference)
    title = f"Suite: {suite.name} ({len(cases)} cases x {len(seeds)} seeds)"
    return json.dumps(
        {
            "stats": {name: [to_dict(s) for s in values] for name, values in stats.items()},
            "verdicts": {name: [to_dict(v) for v in values] for name, values in verdicts.items()},
            "overall": {name: to_dict(overall(values)) for name, values in stats.items()},
            "indicative": suite.indicative,
            "text": suite_report(title, cases, stats, verdicts, suite.indicative),
        }
    )


def _backtest(data: dict[str, Any]) -> Any:
    day = to_day_data(case_day(_params(), _case(data["case_id"]), int(data["seed"])))
    return backtest(_strategy(data["strategy"]), day, _match_mode(data.get("match_mode")))


def drill(payload: str) -> str:
    """Per-tick traces of one strategy on one case and seed."""
    return json.dumps(to_dict(run_detail(_backtest(json.loads(payload)))))


def visualizer_log(payload: str) -> str:
    """The full prosperity3bt output log (about 19 MB), for the open-source Prosperity visualizer."""
    return format_log(_backtest(json.loads(payload)))


def case_csv(payload: str) -> str:
    data = json.loads(payload)
    day = to_day_data(case_day(_params(), _case(data["case_id"]), int(data["seed"])))
    return json.dumps({"day": day.day, "prices": day.prices_csv, "trades": day.trades_csv})
