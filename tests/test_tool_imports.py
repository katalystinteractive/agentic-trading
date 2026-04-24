"""Import smoke tests for tool modules that should be side-effect-safe."""

import importlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"

# Private helper modules are allowed to be imported by their callers but are not
# part of the public CLI/tool surface this smoke test guards.
EXCLUDED_MODULES = {
    "_log_ts",
}


def _tool_modules():
    modules = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        name = path.stem
        if name in EXCLUDED_MODULES:
            continue
        modules.append(name)
    return modules


@pytest.mark.parametrize("module_name", _tool_modules())
def test_tool_module_imports(module_name):
    importlib.import_module(module_name)
