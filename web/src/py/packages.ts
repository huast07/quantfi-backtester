export const PYODIDE_VERSION = "314.0.7";
export const PYODIDE_INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

/** Pyodide-built packages quantgen and prosperity3bt import. The pure-Python rest is vendored by build_python.py. */
export const PYODIDE_PACKAGES = ["numpy", "pyyaml", "orjson", "ipython", "tqdm"];

/** Where build_python.py writes the wheels, params.json and manifest.json, relative to the site root. */
export const PY_BUNDLE_PATH = "py/";
