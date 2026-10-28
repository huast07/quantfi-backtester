"""Serialise a prosperity3bt result in its own output-log format (readable by the Prosperity visualizer)."""

import hashlib

from prosperity3bt.models import BacktestResult

ACTIVITY_HEADER = (
    "day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
    "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss"
)


def format_log(result: BacktestResult) -> str:
    """Same layout as prosperity3bt.__main__.write_output, built in memory instead of written to disk."""
    return "".join(
        [
            "Sandbox logs:\n",
            "".join(map(str, result.sandbox_logs)),
            "\n\n\nActivities log:\n",
            ACTIVITY_HEADER + "\n",
            "\n".join(map(str, result.activity_logs)),
            "\n\n\n\n\nTrade History:\n[\n",
            ",\n".join(map(str, result.trades)),
            "]",
        ]
    )


def activity_digest(result: BacktestResult) -> str:
    """Fingerprint of the activity log, used to prove two runs are identical (CPython vs Pyodide, adapter vs CLI)."""
    return hashlib.sha256("\n".join(map(str, result.activity_logs)).encode()).hexdigest()
