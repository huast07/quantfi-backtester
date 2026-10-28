"""Fit every generator parameter from the real training days (no hand tuning) and assemble MarketParams.

The archetype of each product comes from the EDA reports; everything numeric comes from the CSVs.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import numpy as np

from quantgen.calibration.fit_book import fit_book
from quantgen.calibration.fit_flow import fit_chase_flow, fit_iv_rule_flow, fit_noise_flow, taker_orders
from quantgen.calibration.fit_processes import (
    IMPACT_KNOTS,
    change_sd,
    correlation,
    find_jumps,
    fit_constant,
    fit_jump_diffusion,
    fit_local_trend_process,
    fit_mean_reverting_process,
    fit_random_walk_process,
    fit_steps,
    quote_noise_sd,
)
from quantgen.calibration.fit_structure import book_noise_var, days_to_expiry, fit_basket, fit_plug, fit_vouchers
from quantgen.calibration.variogram import fit_random_walk
from quantgen.generator import processes as proc
from quantgen.generator.book import BookParams, build_book
from quantgen.generator.params import FORMAT_VERSION, Correlation, MarketParams, ProductParams
from quantgen.generator.takers import Flow, expect_chase, unexpected_volume
from quantgen.market_day import MarketDay, ProductDay, from_day_data
from quantgen.products import VOUCHER_STRIKES, voucher_symbol
from quantgen.real_data import REAL_DAYS, load_real_day

TARGET_DAY = 1
VOUCHER_UNDERLYING = "LYCHEE"
VOUCHER_EXPIRY_AT_FIRST_DAY = 8.0  # wiki: the vouchers have 8 days to expiry at the open of day -2
CHASE_BIN_TICKS = 20
CHASE_BINS = 20
SIMULATION_SEED = 7

CONSTANT = "AMETHYST"
STEPS = "GOLDEN_PEARLS"
MOMENTUM = "BLUE_PEARLS"
MEAN_REVERTING = "TOFFEE_CAKE"
JUMPS = "TELLURIUM"
BASKET = "FRUIT_BASKET"
PLUG = "PINK_PEARLS"
BASKET_LEGS = ("DRAGONFRUIT", "GRANADILLA", "MANGOSTEEN")
PLUG_MEMBERS = ("WHITE_PEARLS", "BLACK_PEARLS", "GOLDEN_PEARLS", "BLUE_PEARLS")
STEP_ABSORBERS = ("WHITE_PEARLS", "BLACK_PEARLS", "BLUE_PEARLS")
CORRELATED = (
    "WHITE_PEARLS",
    "BLACK_PEARLS",
    "BLUE_PEARLS",
    "JELLY",
    "PEANUT_BUTTER",
    "LYCHEE",
    "DRAGONFRUIT",
    "GRANADILLA",
    "MANGOSTEEN",
    "PAPER_LANTERNS",
    "TOFFEE_CAKE",
)

Simulator = Callable[[float, np.ndarray], np.ndarray]


def load_real_market_days(data_root: Path, days: Sequence[int] = REAL_DAYS) -> list[MarketDay]:
    return [from_day_data(load_real_day(data_root, day)) for day in days]


def real_expiries(days: Sequence[int] = REAL_DAYS) -> list[float]:
    """Voucher days to expiry at the open of each real day."""
    return [VOUCHER_EXPIRY_AT_FIRST_DAY - (day - REAL_DAYS[0]) for day in days]


class _Calibrator:
    def __init__(self, days: Sequence[MarketDay]) -> None:
        self.days = list(days)
        self.names = sorted(days[0].products)
        self.by_product: dict[str, list[ProductDay]] = {n: [d.products[n] for d in days] for n in self.names}
        self.mids = {name: [day.mid for day in self.by_product[name]] for name in self.names}
        self.ticks = days[0].ticks
        self.simulators: dict[str, Simulator] = {}

    def noise(
        self, name: str, book: BookParams, simulate: Simulator, mids: Sequence[np.ndarray] | None = None
    ) -> float:
        self.simulators[name] = simulate
        real = mids if mids is not None else self.mids[name]
        rng = np.random.default_rng(SIMULATION_SEED)
        paths = [simulate(float(mid[0]), rng.standard_normal(self.ticks)) for mid in real]
        return quote_noise_sd(real, paths, book)

    def simulated_mids(self, name: str, product: ProductParams) -> list[np.ndarray]:
        """Mids the generator would produce for this product alone (fitted process, quote noise and book)."""
        rng = np.random.default_rng(SIMULATION_SEED + 1)
        mids = []
        for mid in self.mids[name]:
            center = self.simulators[name](float(mid[0]), rng.standard_normal(self.ticks))
            center = center + product.quote_noise_sd * rng.standard_normal(self.ticks)
            book = build_book(center, product.book, rng)
            mids.append((book.bid_prices[:, 0] + book.ask_prices[:, 0]) / 2)
        return mids

    def product(self, name: str, process: proc.Process, book: BookParams, flow: Flow, noise: float) -> ProductParams:
        start = float(self.mids[name][-1][-1])
        return ProductParams(start=start, process=process, quote_noise_sd=noise, book=book, flow=flow)

    def diffusive(self, name: str) -> ProductParams:
        book = fit_book(self.by_product[name])
        mids = self.mids[name]
        process: proc.Process
        if name == MOMENTUM:
            process = fit_local_trend_process(mids)
            noise = self.noise(name, book, lambda s, z: proc.local_trend(process, s, z).path)
        elif name == MEAN_REVERTING:
            process = fit_mean_reverting_process(mids)
            noise = self.noise(name, book, lambda s, z: proc.mean_reverting(process, s, z).path)
        else:
            process = fit_random_walk_process(mids)
            noise = self.noise(name, book, lambda s, z: proc.random_walk(process, s, z).path)
        return self.product(name, process, book, fit_noise_flow(self.by_product[name]), noise)

    def flat(self, name: str, process: proc.Process) -> ProductParams:
        return self.product(name, process, fit_book(self.by_product[name]), fit_noise_flow(self.by_product[name]), 0.0)

    def tellurium(self) -> ProductParams:
        days, mids = self.by_product[JUMPS], self.mids[JUMPS]
        jumps = [find_jumps(mid) for mid in mids]
        chase = fit_chase_flow(days, [(j.ticks, j.signs) for j in jumps], CHASE_BIN_TICKS, CHASE_BINS)
        surprises = [
            unexpected_volume(taker_orders(day), expect_chase(chase, day.ticks, j.ticks, j.signs))
            for day, j in zip(days, jumps, strict=True)
        ]
        fit = fit_jump_diffusion(mids, surprises)
        process = fit.process
        flow = replace(chase, impact_knots=IMPACT_KNOTS, impact_per_lot=fit.impact_per_lot)
        masks = []
        for day, day_jumps in zip(self.by_product[JUMPS], jumps, strict=True):
            calm = np.ones(day.ticks, dtype=bool)
            for tick in day_jumps.ticks:
                calm[tick : tick + CHASE_BIN_TICKS * CHASE_BINS] = False
            masks.append(calm)
        book = fit_book(self.by_product[JUMPS], masks)
        diffusion = process.diffusion
        noise = self.noise(JUMPS, book, lambda s, z: proc.local_trend(diffusion, s, z).path, fit.calm_mids)
        return self.product(JUMPS, process, book, flow, noise)

    def basket(self) -> ProductParams:
        book = fit_book(self.by_product[BASKET])
        process = fit_basket(self.mids[BASKET], {leg: self.mids[leg] for leg in BASKET_LEGS})
        walk = proc.RandomWalk(sigma=fit_random_walk(self.mids[BASKET]).sigma)
        noise = self.noise(BASKET, book, lambda s, z: proc.random_walk(walk, s, z).path)
        return self.product(BASKET, process, book, fit_noise_flow(self.by_product[BASKET]), noise)

    def vouchers(self, spot: ProductParams) -> tuple[dict[str, ProductParams], proc.VoucherSurface]:
        symbols = {strike: voucher_symbol(strike) for strike in VOUCHER_STRIKES}
        books = {strike: fit_book(self.by_product[symbol]) for strike, symbol in symbols.items()}
        first_day = self.days[0].day
        days_left = [days_to_expiry(d.day, VOUCHER_EXPIRY_AT_FIRST_DAY, first_day, self.ticks) for d in self.days]
        fit = fit_vouchers(
            self.mids[VOUCHER_UNDERLYING],
            {strike: self.mids[symbol] for strike, symbol in symbols.items()},
            days_left,
            {strike: book.layers[0] for strike, book in books.items()},
            book_noise_var(spot.book.layers[0], spot.quote_noise_sd),
            VOUCHER_UNDERLYING,
            VOUCHER_EXPIRY_AT_FIRST_DAY - (TARGET_DAY - first_day),
        )
        products = {}
        for strike, symbol in symbols.items():
            flow = fit_iv_rule_flow(self.by_product[symbol], fit.residuals[strike], fit.sign_agreement[strike])
            products[symbol] = self.product(
                symbol, fit.strikes[strike], books[strike], flow, fit.quote_noise_sd[strike]
            )
        return products, fit.surface

    def correlation(self, products: Mapping[str, ProductParams]) -> Correlation:
        model_sd = {name: change_sd(self.simulated_mids(name, products[name])) for name in CORRELATED}
        matrix = correlation(self.mids, CORRELATED, model_sd)
        return Correlation(products=CORRELATED, matrix=tuple(tuple(float(v) for v in row) for row in matrix))


def calibrate(days: Sequence[MarketDay]) -> MarketParams:
    """`days` must be consecutive real days in order; day 1 starts where the last one closes."""
    cal = _Calibrator(days)
    vouchers = {voucher_symbol(k) for k in VOUCHER_STRIKES}
    special = {CONSTANT, STEPS, JUMPS, BASKET, PLUG} | vouchers
    products = {name: cal.diffusive(name) for name in cal.names if name not in special}
    products[CONSTANT] = cal.flat(CONSTANT, fit_constant(cal.mids[CONSTANT]))
    absorbers = {name: cal.mids[name] for name in STEP_ABSORBERS}
    products[STEPS] = cal.flat(STEPS, fit_steps(cal.mids[STEPS], absorbers))
    products[PLUG] = cal.flat(PLUG, fit_plug(cal.mids[PLUG], [cal.mids[m] for m in PLUG_MEMBERS], PLUG_MEMBERS))
    products[JUMPS] = cal.tellurium()
    products[BASKET] = cal.basket()
    voucher_products, surface = cal.vouchers(products[VOUCHER_UNDERLYING])
    products.update(voucher_products)
    return MarketParams(
        format_version=FORMAT_VERSION,
        day=TARGET_DAY,
        ticks=cal.ticks,
        products=MappingProxyType(dict(sorted(products.items()))),
        correlation=cal.correlation(products),
        voucher_surface=surface,
    )
