"""quantgen command line: calibrate the generator, generate days, check fidelity, and run strategies."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from quantgen.adapter.dataset import stage_day
from quantgen.adapter.runner import DayResult, MatchMode, run_day
from quantgen.adapter.strategy import Strategy, StrategyError
from quantgen.calibration.calibrate import calibrate, load_real_market_days, real_expiries
from quantgen.calibration.fidelity import format_report, run_fidelity
from quantgen.cases.case import case_day, find_cases, load_catalog
from quantgen.generator.params import load_params, save_params
from quantgen.market_day import to_day_data
from quantgen.real_data import REAL_DAYS, load_real_day
from quantgen.scoring.reference import REFERENCE_NAME, reference_strategy
from quantgen.scoring.report import suite_report
from quantgen.scoring.run_suite import default_workers, run_suite
from quantgen.scoring.suites import SUITES, custom_suite
from quantgen.scoring.verdicts import all_verdicts
from quantgen.serde import SchemaError

MATCH_MODES = {"all": MatchMode.ALL, "worse": MatchMode.WORSE, "none": MatchMode.NONE}
DEFAULT_PARAMS = Path("params/params.json")
DEFAULT_FIDELITY_SEEDS = (1, 2, 3, 4, 5)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantgen")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Backtest one or more strategy files (each file is one strategy).")
    run.add_argument("strategies", nargs="+", type=Path, help="trader.py files to compare")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--real", action="store_true", help="Run on the real training days instead of cases")
    source.add_argument("--suite", choices=sorted(SUITES), help="Case suite to run (default: standard)")
    source.add_argument("--cases", nargs="+", metavar="CASE", help="Run these case ids (see `quantgen cases`)")
    run.add_argument("--seeds", type=int, default=2, help="Seeds per case with --cases (default: 2)")
    run.add_argument("--days", nargs="+", type=int, default=list(REAL_DAYS), help="Real days to run (default: all)")
    run.add_argument("--data-root", type=Path, default=Path.cwd(), help="Folder holding the QuantFi data folders")
    run.add_argument("--params", type=Path, default=DEFAULT_PARAMS, help=f"Parameter file (default: {DEFAULT_PARAMS})")
    run.add_argument("--match", choices=sorted(MATCH_MODES), default="all", help="Passive fill rule (wiki: all)")
    run.add_argument("--workers", type=int, default=default_workers(), help="Parallel worker processes")

    commands.add_parser("cases", help="List the market cases.")

    cal = commands.add_parser("calibrate", help="Fit the generator to the real days and write its parameters.")
    cal.add_argument("--data-root", type=Path, default=Path.cwd(), help="Folder holding the QuantFi data folders")
    cal.add_argument("--out", type=Path, default=DEFAULT_PARAMS, help=f"Parameter file (default: {DEFAULT_PARAMS})")

    gen = commands.add_parser("gen", help="Generate a synthetic day 1 in prosperity3bt's data layout.")
    gen.add_argument("--seed", type=int, required=True, help="Random seed; the same seed gives the same day")
    gen.add_argument("--case", default="regular-day", help="Case id (default: regular-day)")
    gen.add_argument("--params", type=Path, default=DEFAULT_PARAMS, help=f"Parameter file (default: {DEFAULT_PARAMS})")
    gen.add_argument("--out", type=Path, required=True, help="Folder to write round1/prices_*.csv and trades_*.csv")

    fid = commands.add_parser("fidelity", help="Check generated days against the real days' stylized facts.")
    fid.add_argument("--params", type=Path, default=DEFAULT_PARAMS, help=f"Parameter file (default: {DEFAULT_PARAMS})")
    fid.add_argument("--data-root", type=Path, default=Path.cwd(), help="Folder holding the QuantFi data folders")
    fid.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_FIDELITY_SEEDS), help="Seeds to average")
    fid.add_argument("--all", action="store_true", help="List every check, not only the failures")
    return parser


def _read_strategy(path: Path) -> Strategy:
    if not path.is_file():
        raise StrategyError(f"{path}: file not found")
    return Strategy(name=path.name, source=path.read_text(encoding="utf-8"))


def _format_table(days: Sequence[int], rows: Sequence[tuple[str, Sequence[DayResult]]]) -> str:
    name_width = max(len("strategy"), *(len(name) for name, _ in rows))
    header = f"{'strategy':<{name_width}}" + "".join(f"{f'day {d}':>14}" for d in days) + f"{'total':>14}"
    lines = [header, "-" * len(header)]
    for name, results in rows:
        cells = "".join(f"{r.total_pnl:>14,.0f}" for r in results)
        lines.append(f"{name:<{name_width}}{cells}{sum(r.total_pnl for r in results):>14,.0f}")
    return "\n".join(lines)


def _run_real(args: argparse.Namespace, strategies: Sequence[Strategy]) -> int:
    days = [load_real_day(args.data_root, day) for day in args.days]
    rows = [(s.name, [run_day(s, day, MATCH_MODES[args.match]) for day in days]) for s in strategies]
    print(_format_table(args.days, rows))
    return 0


def _progress(done: int, total: int) -> None:
    print(f"\r{done}/{total} days", end="\n" if done == total else "", file=sys.stderr, flush=True)


def _run_suite(args: argparse.Namespace, strategies: Sequence[Strategy]) -> int:
    names = [s.name for s in strategies]
    if len(set(names)) != len(names) or REFERENCE_NAME in names:
        raise StrategyError(f"strategy file names must be unique and not '{REFERENCE_NAME}'")
    suite = custom_suite(args.cases, args.seeds) if args.cases else SUITES[args.suite or "standard"]
    cases = suite.cases(load_catalog())
    reference = [reference_strategy()] if len(strategies) == 1 else []
    result = run_suite(
        [*strategies, *reference],
        load_params(args.params),
        cases,
        suite,
        MATCH_MODES[args.match],
        args.workers,
        _progress,
    )
    stats = {name: result.stats(name) for name in result.strategies}
    verdicts = all_verdicts(stats, names, REFERENCE_NAME if reference else None)
    title = f"Suite: {suite.name} ({len(cases)} cases x {len(suite.seeds)} seeds)"
    print(suite_report(title, cases, stats, verdicts, suite.indicative))
    return 0


def _run(args: argparse.Namespace) -> int:
    try:
        strategies = [_read_strategy(path) for path in args.strategies]
        return _run_real(args, strategies) if args.real else _run_suite(args, strategies)
    except (StrategyError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _cases(_: argparse.Namespace) -> int:
    catalog = load_catalog()
    width = max(len(case.id) for case in catalog)
    for case in catalog:
        print(f"{case.id:<{width}}  {case.tier:<9}  {case.summary}")
    return 0


def _calibrate(args: argparse.Namespace) -> int:
    params = calibrate(load_real_market_days(args.data_root))
    save_params(params, args.out)
    print(f"wrote {args.out} ({len(params.products)} products)")
    return 0


def _gen(args: argparse.Namespace) -> int:
    (case,) = find_cases(load_catalog(), [args.case])
    day = to_day_data(case_day(load_params(args.params), case, args.seed))
    stage_day(day, args.out)
    print(f"wrote {case.id} day {day.day} (seed {args.seed}) to {args.out}")
    return 0


def _fidelity(args: argparse.Namespace) -> int:
    checks = run_fidelity(load_params(args.params), load_real_market_days(args.data_root), real_expiries(), args.seeds)
    print(format_report(checks, failures_only=not args.all))
    return 0 if all(check.passed for check in checks) else 1


COMMANDS = {"run": _run, "cases": _cases, "calibrate": _calibrate, "gen": _gen, "fidelity": _fidelity}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (FileNotFoundError, SchemaError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
