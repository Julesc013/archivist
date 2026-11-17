#!/usr/bin/env python3
"""Portable checkout entry point; maps the unique package to physical source/."""

import importlib.util
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    raise SystemExit("Archivist requires Python 3.8 or newer.")

_package_root = Path(__file__).resolve().parent / "source"
_spec = importlib.util.spec_from_file_location(
    "archivist",
    _package_root / "__init__.py",
    submodule_search_locations=[str(_package_root)],
)
if _spec is None or _spec.loader is None:
    raise SystemExit("Cannot find the Archivist source directory.")
_package = importlib.util.module_from_spec(_spec)
sys.modules["archivist"] = _package
_spec.loader.exec_module(_package)

if __name__ == "__main__":
    from archivist.cli import main

    main()
