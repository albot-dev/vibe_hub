from __future__ import annotations

import app.db as db_module
from app.config import Settings


def test_init_db_skips_create_all_in_production(monkeypatch) -> None:
    calls: list[bool] = []

    monkeypatch.setattr(db_module, "get_settings", lambda: Settings(app_env="production"))

    def fake_create_all(*args, **kwargs) -> None:
        calls.append(True)

    monkeypatch.setattr(db_module.Base.metadata, "create_all", fake_create_all)

    db_module.init_db()
    assert calls == []


def test_init_db_runs_create_all_outside_production(monkeypatch) -> None:
    calls: list[bool] = []

    monkeypatch.setattr(db_module, "get_settings", lambda: Settings(app_env="development"))

    def fake_create_all(*args, **kwargs) -> None:
        calls.append(True)

    monkeypatch.setattr(db_module.Base.metadata, "create_all", fake_create_all)

    db_module.init_db()
    assert calls == [True]
