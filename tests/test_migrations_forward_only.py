from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "alembic" / "versions"


def _load_migration_module(module_name: str) -> ModuleType:
    migration_path = MIGRATIONS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"migration_{module_name}", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load migration module: {migration_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "module_name",
    [
        "0001_initial",
        "0002_add_autopilot_jobs",
        "0003_add_webhook_deliveries",
        "0004_add_policy_revisions",
    ],
)
def test_migration_downgrade_is_forward_only(module_name: str) -> None:
    module = _load_migration_module(module_name)
    with pytest.raises(RuntimeError, match="Forward-only migration policy"):
        module.downgrade()
