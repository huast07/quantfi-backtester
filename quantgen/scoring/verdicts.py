"""Strong / Neutral / Weak per strategy and case, with a one-line reason.

A verdict combines two questions, so it works for one strategy or many:
1. Absolute: did the strategy make money here, and how does this case compare with its own average across cases?
2. Relative (only with several uploads): is its edge over the other uploads here unusually large or small compared
   with its edge across all cases? A strategy that beats another everywhere is not "strong" everywhere; its strong
   cases are the ones where it beats the other by the most. Whether it is ahead on every seed is reported as well.
The built-in reference strategy is a gate, not a score: a case cannot be Strong if the strategy trails the reference
on every seed. (Scoring against the reference would let the reference's own inventory luck decide verdicts.)
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from quantgen.scoring.metrics import CaseStats

STRONG, NEUTRAL, WEAK = "strong", "neutral", "weak"
FAR_FROM_AVERAGE = 1.0  # in standard deviations of the strategy's own case means


@dataclass(frozen=True)
class Verdict:
    strategy: str
    case_id: str
    rating: str
    reason: str


@dataclass(frozen=True)
class _Relative:
    score: int
    phrase: str


NO_EDGE = _Relative(0, "")


def _absolute(stats: CaseStats, own_cases: Sequence[CaseStats]) -> tuple[int, str]:
    means = np.array([s.mean_pnl for s in own_cases])
    average, spread = float(means.mean()), float(means.std())
    if stats.mean_pnl < 0:
        return -1, "loses money"
    if spread == 0:
        return 0, ""
    z = (stats.mean_pnl - average) / spread
    if z <= -FAR_FROM_AVERAGE:
        return -1, f"well below its average of {average:+,.0f}"
    if z >= FAR_FROM_AVERAGE:
        return 1, f"well above its average of {average:+,.0f}"
    return 0, ""


def _seed_consistency(stats: CaseStats, comparators: Sequence[CaseStats]) -> _Relative:
    """+1 if ahead of every comparator on every seed, -1 if behind every one on every seed, else 0."""
    if not comparators:
        return _Relative(0, "")
    seeds = sorted(stats.pnl_by_seed)
    beats, loses = [], []
    for other in comparators:
        diffs = np.array([stats.pnl_by_seed[seed] - other.pnl_by_seed[seed] for seed in seeds])
        if np.all(diffs > 0):
            beats.append(other.strategy)
        elif np.all(diffs < 0):
            loses.append(other.strategy)
    on_seeds = "on every seed" if len(seeds) > 1 else "on the one seed run"
    names = ", ".join(other.strategy for other in comparators)
    if len(beats) == len(comparators):
        return _Relative(1, f"beats {names} {on_seeds}")
    if len(loses) == len(comparators):
        return _Relative(-1, f"behind {names} {on_seeds}")
    return _Relative(0, "")


def edge_scores(own: Sequence[CaseStats], peers: Sequence[Sequence[CaseStats]]) -> list[_Relative]:
    """Per case: is the edge over the peers' mean well above (+1) or below (-1) this strategy's usual edge?"""
    if not peers:
        return [NO_EDGE for _ in own]
    edges = np.array([case.mean_pnl - np.mean([peer[i].mean_pnl for peer in peers]) for i, case in enumerate(own)])
    usual, spread = float(edges.mean()), float(edges.std())
    names = ", ".join(peer[0].strategy for peer in peers)
    out = []
    for edge in edges:
        z = 0.0 if spread == 0 else (edge - usual) / spread
        if z >= FAR_FROM_AVERAGE:
            out.append(_Relative(1, f"edge over {names} {edge:+,.0f}, well above its usual {usual:+,.0f}"))
        elif z <= -FAR_FROM_AVERAGE:
            out.append(_Relative(-1, f"edge over {names} {edge:+,.0f}, well below its usual {usual:+,.0f}"))
        else:
            out.append(NO_EDGE)
    return out


def _seed_spread(stats: CaseStats) -> str:
    """Flag cases where seeds disagree in sign, so a mean near zero is not read as a consistent result."""
    if stats.worst_pnl < 0 < max(stats.pnl_by_seed.values()):
        return f"seeds disagree ({stats.worst_pnl:+,.0f} to {max(stats.pnl_by_seed.values()):+,.0f})"
    return ""


def _driver(stats: CaseStats, rating: str) -> str:
    """The product that explains the verdict: the biggest loser for Weak, the biggest earner otherwise."""
    products = {name: pnl for name, pnl in stats.product_mean_pnl.items() if pnl != 0}
    if not products:
        return "no trades"
    name = min(products, key=products.get) if rating == WEAK else max(products, key=products.get)
    return f"of which {name} {products[name]:+,.0f}"


def verdict(
    stats: CaseStats,
    own_cases: Sequence[CaseStats],
    peers: Sequence[CaseStats] = (),
    baseline: CaseStats | None = None,
    edge: _Relative = NO_EDGE,
) -> Verdict:
    """`peers` are the other uploads on this case, `edge` this case's score from `edge_scores`, and `baseline` the
    reference strategy if it ran."""
    if stats.errors:
        return Verdict(stats.strategy, stats.case_id, WEAK, f"crashed ({stats.errors[0]})")
    absolute, absolute_phrase = _absolute(stats, own_cases)
    consistency = _seed_consistency(stats, peers)
    gate = _seed_consistency(stats, [baseline]) if baseline is not None else _Relative(0, "")
    total = absolute + edge.score
    if stats.mean_pnl < 0 or total <= -1:
        rating = WEAK
    elif total >= 1 and gate.score >= 0:
        rating = STRONG
    else:
        rating = NEUTRAL
    parts = [f"{stats.mean_pnl:+,.0f} mean", _driver(stats, rating)]
    phrases = (absolute_phrase, edge.phrase, consistency.phrase, gate.phrase, _seed_spread(stats))
    parts += [phrase for phrase in phrases if phrase]
    if stats.limit_breaches:
        parts.append(f"{stats.limit_breaches} limit breaches")
    return Verdict(stats.strategy, stats.case_id, rating, "; ".join(parts))


def all_verdicts(
    stats: Mapping[str, Sequence[CaseStats]], judged: Sequence[str], reference: str | None = None
) -> dict[str, list[Verdict]]:
    """Verdicts for each strategy in `judged`. `stats` maps every strategy that ran (including the reference) to
    its per-case stats in the same case order."""
    out = {}
    for name in judged:
        peers = [other for other in judged if other != name]
        edges = edge_scores(stats[name], [stats[peer] for peer in peers])
        verdicts = []
        for index, case in enumerate(stats[name]):
            baseline = stats[reference][index] if reference else None
            peer_cases = [stats[peer][index] for peer in peers]
            verdicts.append(verdict(case, stats[name], peer_cases, baseline, edges[index]))
        out[name] = verdicts
    return out
