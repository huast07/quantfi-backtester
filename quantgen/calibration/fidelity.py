"""The fidelity gate: do generated regular days reproduce the real days' stylized facts?

Every statistic is computed on each real day, giving a real range. The generated value (mean over seeds) must land
inside that range, widened by the statistic's tolerance.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from quantgen.calibration.stats import MARKET_STATS, PRODUCT_STATS, Tolerance, batch_sd
from quantgen.generator.market import generate_day
from quantgen.generator.params import MarketParams
from quantgen.market_day import MarketDay

MARKET_SUBJECT = "market"


@dataclass(frozen=True)
class Check:
    subject: str
    stat: str
    real_low: float
    real_high: float
    generated: float
    margin: float

    @property
    def passed(self) -> bool:
        return self.real_low - self.margin <= self.generated <= self.real_high + self.margin


def _check(
    subject: str,
    stat: str,
    real: Sequence[float],
    generated: Sequence[float],
    tolerance: Tolerance,
    day_sd: float = 0.0,
) -> Check:
    low, high = float(min(real)), float(max(real))
    return Check(subject, stat, low, high, float(np.mean(generated)), tolerance.margin(real, generated, day_sd))


def fidelity_checks(
    real_days: Sequence[MarketDay],
    real_expiries: Sequence[float],
    generated_days: Sequence[MarketDay],
    generated_expiry: float,
) -> list[Check]:
    checks = []
    for name in sorted(real_days[0].products):
        for stat, (compute, tolerance) in PRODUCT_STATS.items():
            real_product = [day.products[name] for day in real_days]
            generated_product = [day.products[name] for day in generated_days]
            real = [compute(day) for day in real_product]
            generated = [compute(day) for day in generated_product]
            day_sd = batch_sd(compute, real_product + generated_product) if tolerance.sampling_z > 0 else 0.0
            checks.append(_check(name, stat, real, generated, tolerance, day_sd))
    for stat, (compute, tolerance) in MARKET_STATS.items():
        real = [compute(day, expiry) for day, expiry in zip(real_days, real_expiries, strict=True)]
        generated = [compute(day, generated_expiry) for day in generated_days]
        checks.append(_check(MARKET_SUBJECT, stat, real, generated, tolerance))
    return checks


def run_fidelity(
    params: MarketParams, real_days: Sequence[MarketDay], real_expiries: Sequence[float], seeds: Sequence[int]
) -> list[Check]:
    generated = [generate_day(params, seed) for seed in seeds]
    return fidelity_checks(real_days, real_expiries, generated, params.voucher_surface.days_to_expiry)


def format_report(checks: Sequence[Check], failures_only: bool = False) -> str:
    lines = [f"{'subject':<16}{'statistic':<32}{'real range':>24}{'generated':>14}  result"]
    for check in checks:
        if failures_only and check.passed:
            continue
        real = f"{check.real_low:.3f} .. {check.real_high:.3f}"
        verdict = "ok" if check.passed else f"FAIL (margin {check.margin:.3f})"
        lines.append(f"{check.subject:<16}{check.stat:<32}{real:>24}{check.generated:>14.3f}  {verdict}")
    failed = sum(not check.passed for check in checks)
    lines.append(f"{len(checks) - failed}/{len(checks)} checks passed")
    return "\n".join(lines)
