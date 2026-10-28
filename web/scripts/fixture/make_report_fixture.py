"""Writes web/src/test/fixtures/report.json: real quantgen.browser output for the web unit tests.

Run from web/ with `uv run --project .. python scripts/fixture/make_report_fixture.py`.
"""

import json
import re
from pathlib import Path

from quantgen import browser

HERE = Path(__file__).resolve().parent
WEB = HERE.parent.parent
ROOT = WEB.parent
CASE_IDS = ["regular-day", "busy-day", "golden-continues", "tellurium-storm", "black-swan-crash"]
SEEDS = [1, 2]


def main() -> None:
    parity = (WEB / "tests" / "parity" / "parity.test.ts").read_text()
    sources = dict(re.findall(r"const (\w+) = `(.*?)`;", parity, re.S))
    strategies = [
        {"name": "amethyst_mm.py", "source": (HERE / "amethyst_mm.py").read_text()},
        {"name": "fades.py", "source": sources["FADES_TELLURIUM"]},
    ]
    browser.init(str(ROOT / "params" / "params.json"))
    catalog = json.loads(browser.catalog())
    runs = []
    for case_id in CASE_IDS:
        for seed in SEEDS:
            request = {
                "strategies": strategies,
                "case_id": case_id,
                "seed": seed,
                "match_mode": "all",
                "reference": True,
            }
            runs += json.loads(browser.run_case(json.dumps(request)))
    suite = {"name": "custom", "case_ids": CASE_IDS, "seeds": SEEDS}
    names = [s["name"] for s in strategies]
    report = json.loads(browser.report(json.dumps({"suite": suite, "strategies": names, "runs": runs})))
    cases = [c for c in catalog["cases"] if c["id"] in CASE_IDS]
    out = {"suite": suite, "strategies": strategies, "runs": runs, "report": report, "cases": cases}
    (WEB / "src" / "test" / "fixtures" / "report.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
