"""Plain-text suite report: a profile per strategy (well / poorly lists) and a strategy x case matrix."""

from collections.abc import Mapping, Sequence

from quantgen.cases.case import Case
from quantgen.scoring.metrics import TIER_WEIGHTS, CaseStats, overall
from quantgen.scoring.verdicts import STRONG, WEAK, Verdict

RATING_MARK = {"strong": "S", "neutral": "N", "weak": "W"}
CELL_WIDTH = 14


def _weights_note() -> str:
    return " / ".join(f"{tier} {weight:.0%}" for tier, weight in TIER_WEIGHTS.items())


def _verdict_lines(cases: Mapping[str, Case], verdicts: Sequence[Verdict], rating: str) -> list[str]:
    chosen = [v for v in verdicts if v.rating == rating]
    if not chosen:
        return ["  (none)"]
    width = max(len(v.case_id) for v in chosen)
    return [f"  {v.case_id:<{width}}  [{cases[v.case_id].tier}] {v.reason}" for v in chosen]


def profile(name: str, cases: Mapping[str, Case], stats: Sequence[CaseStats], verdicts: Sequence[Verdict]) -> str:
    summary = overall(stats)
    traded = max((s.products_traded for s in stats), default=0)
    lines = [
        f"== {name} ==",
        f"Weighted score: {summary.weighted_pnl:+,.0f}  ({_weights_note()})",
        f"Worst case: {summary.worst_case} ({summary.worst_case_pnl:+,.0f})   Products traded: {traded}",
        "Performs well in:",
        *_verdict_lines(cases, verdicts, STRONG),
        "Performs poorly in:",
        *_verdict_lines(cases, verdicts, WEAK),
    ]
    return "\n".join(lines)


def matrix(
    cases: Sequence[Case], stats: Mapping[str, Sequence[CaseStats]], verdicts: Mapping[str, Sequence[Verdict]]
) -> str:
    names = list(stats)
    case_width = max(len("case"), *(len(case.id) for case in cases))
    header = f"{'case':<{case_width}}  {'tier':<9}" + "".join(
        f"{name[: CELL_WIDTH - 1]:>{CELL_WIDTH}}" for name in names
    )
    lines = [header, "-" * len(header)]
    for index, case in enumerate(cases):
        cells = []
        for name in names:
            mark = RATING_MARK[verdicts[name][index].rating] if name in verdicts else " "
            cells.append(f"{stats[name][index].mean_pnl:>{CELL_WIDTH - 2},.0f} {mark}")
        lines.append(f"{case.id:<{case_width}}  {case.tier:<9}" + "".join(cells))
    return "\n".join(lines)


def suite_report(
    title: str,
    cases: Sequence[Case],
    stats: Mapping[str, Sequence[CaseStats]],
    verdicts: Mapping[str, Sequence[Verdict]],
    indicative: bool,
) -> str:
    by_id = {case.id: case for case in cases}
    parts = [title]
    if indicative:
        parts.append("Verdicts are indicative: one seed per case cannot show whether a result is consistent.")
    parts += [profile(name, by_id, stats[name], verdicts[name]) for name in verdicts]
    parts.append("Mean PnL per case (S = strong, N = neutral, W = weak):\n" + matrix(cases, stats, verdicts))
    return "\n\n".join(parts)
