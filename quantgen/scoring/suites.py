"""Which cases and seeds a scoring run covers."""

from collections.abc import Sequence
from dataclasses import dataclass

from quantgen.cases.case import Case, find_cases


@dataclass(frozen=True)
class Suite:
    """`case_ids` None means every case in the catalog."""

    name: str
    case_ids: tuple[str, ...] | None
    seeds: tuple[int, ...]

    @property
    def indicative(self) -> bool:
        """One seed cannot show whether a result is consistent, so its verdicts are only indicative."""
        return len(self.seeds) < 2

    def cases(self, catalog: Sequence[Case]) -> list[Case]:
        return list(catalog) if self.case_ids is None else find_cases(catalog, self.case_ids)


QUICK_CASES = (
    "regular-day",
    "busy-day",
    "vol-clustering",
    "golden-continues",
    "vol-crush",
    "toxic-flow",
    "tellurium-storm",
    "black-swan-crash",
)

SUITES = {
    "quick": Suite("quick", QUICK_CASES, (1,)),
    "standard": Suite("standard", None, (1, 2)),
    "full": Suite("full", None, (1, 2, 3, 4, 5)),
}


def custom_suite(case_ids: Sequence[str] | None, seed_count: int) -> Suite:
    if seed_count < 1:
        raise ValueError("a suite needs at least one seed")
    return Suite("custom", None if case_ids is None else tuple(case_ids), tuple(range(1, seed_count + 1)))
