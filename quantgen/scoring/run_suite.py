"""Run strategies over a suite: every (case, seed) day is generated once and shared by all strategies.

Jobs run in worker processes when `workers` > 1. Parameters, cases and results cross the process boundary as plain
dicts (read-only mappings do not pickle) and are rebuilt with the strict serde loader.
"""

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

from quantgen.adapter.runner import MatchMode, run_day
from quantgen.adapter.strategy import Strategy, load_trader
from quantgen.cases.case import Case, case_day
from quantgen.generator.params import MarketParams
from quantgen.market_day import to_day_data
from quantgen.scoring.metrics import CaseStats, RunMetrics, case_stats, failed_run, run_metrics
from quantgen.scoring.suites import Suite
from quantgen.serde import from_dict, to_dict

Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class SuiteResult:
    suite: Suite
    cases: tuple[Case, ...]
    strategies: tuple[str, ...]
    runs: tuple[RunMetrics, ...]

    def stats(self, strategy: str) -> list[CaseStats]:
        """Per-case stats for one strategy, in suite case order."""
        return [
            case_stats([run for run in self.runs if run.strategy == strategy and run.case_id == case.id], case.tier)
            for case in self.cases
        ]


def run_job(
    params: MarketParams, case: Case, seed: int, strategies: Sequence[Strategy], match_mode: Any
) -> list[RunMetrics]:
    day = to_day_data(case_day(params, case, seed))
    results = []
    for strategy in strategies:
        try:
            result = run_day(strategy, day, match_mode, with_log=False)
        except Exception as error:  # a strategy bug must not abort the other runs; it is reported as a crash
            results.append(failed_run(strategy.name, case.id, seed, f"{type(error).__name__}: {error}"))
            continue
        results.append(run_metrics(strategy.name, case.id, seed, result))
    return results


def _worker_job(job: tuple[dict, dict, int, Sequence[Strategy], Any]) -> list[dict]:
    params_data, case_data, seed, strategies, match_mode = job
    runs = run_job(from_dict(MarketParams, params_data), from_dict(Case, case_data), seed, strategies, match_mode)
    return [to_dict(run) for run in runs]


def run_suite(
    strategies: Sequence[Strategy],
    params: MarketParams,
    cases: Sequence[Case],
    suite: Suite,
    match_mode: Any = MatchMode.ALL,
    workers: int = 1,
    progress: Progress | None = None,
) -> SuiteResult:
    """`cases` must already be the suite's cases. Strategies are loaded once up front, so a file that cannot load
    fails fast with a StrategyError before any day is generated."""
    for strategy in strategies:
        load_trader(strategy)
    jobs = [(case, seed) for case in cases for seed in suite.seeds]
    runs: list[RunMetrics] = []

    def collect(done: int, batch: list[RunMetrics]) -> None:
        runs.extend(batch)
        if progress:
            progress(done, len(jobs))

    if workers <= 1:
        for done, (case, seed) in enumerate(jobs, start=1):
            collect(done, run_job(params, case, seed, strategies, match_mode))
    else:
        params_data = to_dict(params)
        payload = [(params_data, to_dict(case), seed, tuple(strategies), match_mode) for case, seed in jobs]
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            for done, batch in enumerate(pool.map(_worker_job, payload), start=1):
                collect(done, [from_dict(RunMetrics, run) for run in batch])
    return SuiteResult(suite, tuple(cases), tuple(s.name for s in strategies), tuple(runs))


def default_workers() -> int:
    return max((os.cpu_count() or 2) - 1, 1)
