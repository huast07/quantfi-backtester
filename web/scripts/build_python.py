"""Bundle what the Pyodide workers load into web/public/py: the quantgen wheel, the pure-Python wheels it needs that
Pyodide does not ship (prosperity3bt, jsonpickle), the calibrated parameters, and a manifest with content hashes so
browsers refetch a file only when it changed. Also writes the case catalog to web/src/generated, so pages that only
describe cases render without booting Python.

Run from web/ with `npm run build:py` (needs uv).
"""

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from quantgen import browser

WEB = Path(__file__).resolve().parent.parent
ROOT = WEB.parent
OUT = WEB / "public" / "py"
GENERATED = WEB / "src" / "generated"
PYODIDE_VERSION = "314.0.7"
# Pinned to uv.lock; installed without dependency resolution, so every runtime dependency must be listed here or
# loaded from Pyodide's own packages (see web/src/py/packages.ts).
VENDORED = ("prosperity3bt==0.12.0", "jsonpickle==4.1.4")
# prosperity3bt bundles ~33 MB of historic Prosperity days; quantgen stages its own days, so only the code ships.
SLIMMED = {"prosperity3bt": "prosperity3bt/resources/"}


def run(*args: str) -> None:
    subprocess.run(args, check=True, cwd=ROOT)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(path: Path) -> dict[str, str]:
    return {"file": path.name, "sha256": sha256(path)}


def slim(wheel: Path, drop_prefix: str) -> None:
    """Rewrite the wheel without data files under `drop_prefix`, keeping the package __init__ modules."""
    keep_all = wheel.with_suffix(".full")
    wheel.rename(keep_all)
    with zipfile.ZipFile(keep_all) as source, zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename.startswith(drop_prefix) and not info.filename.endswith(".py"):
                continue
            target.writestr(info, source.read(info))
    keep_all.unlink()


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    run("uv", "build", "--wheel", "--out-dir", str(OUT), "--quiet")
    run(
        "uvx",
        "--from",
        "pip",
        "pip",
        "download",
        "--quiet",
        "--no-deps",
        "--only-binary=:all:",
        "--dest",
        str(OUT),
        *VENDORED,
    )
    for package, prefix in SLIMMED.items():
        slim(next(OUT.glob(f"{package}-*.whl")), prefix)
    params = OUT / "params.json"
    shutil.copyfile(ROOT / "params" / "params.json", params)
    wheels = sorted(OUT.glob("*.whl"))
    if len(wheels) != 1 + len(VENDORED):
        print(f"error: expected {1 + len(VENDORED)} wheels, found {[w.name for w in wheels]}", file=sys.stderr)
        return 1
    manifest = {"pyodide": PYODIDE_VERSION, "wheels": [entry(w) for w in wheels], "params": entry(params)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    GENERATED.mkdir(exist_ok=True)
    (GENERATED / "catalog.json").write_text(browser.catalog())
    print(f"wrote {OUT.relative_to(ROOT)}: {', '.join(w.name for w in wheels)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
