"""Register QuantiFi position limits with prosperity3bt for the duration of a run.

prosperity3bt 0.12.0 reads limits from the module-level dict ``prosperity3bt.data.LIMITS``, which only knows the
IMC Prosperity 3 products. There is no parameter for it, so the dict is extended inside a context manager and
restored on exit, leaving the library exactly as it was.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import prosperity3bt.data as p3data

from quantgen.products import POSITION_LIMITS


@contextmanager
def quantifi_limits() -> Iterator[None]:
    original = dict(p3data.LIMITS)
    p3data.LIMITS.update(POSITION_LIMITS)
    try:
        yield
    finally:
        p3data.LIMITS.clear()
        p3data.LIMITS.update(original)
