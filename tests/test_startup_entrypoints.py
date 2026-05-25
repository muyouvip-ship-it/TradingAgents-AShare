from __future__ import annotations

import os
import subprocess
import sys
import types


def test_database_modules_import_without_database_url() -> None:
    env = os.environ.copy()
    env["TA_DISABLE_DOTENV"] = "1"
    env.pop("DATABASE_URL", None)
    env.pop("STRATEGY_DATABASE_URL", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import api.database, api.core.strategy_db, api.main; print('ok')",
        ],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_init_db_still_requires_database_url_without_env(monkeypatch) -> None:
    env = os.environ.copy()
    env["TA_DISABLE_DOTENV"] = "1"
    env.pop("DATABASE_URL", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from api.database import init_db\n"
                "try:\n"
                "    init_db()\n"
                "except RuntimeError as exc:\n"
                "    print(str(exc))\n"
                "else:\n"
                "    raise SystemExit('init_db should require DATABASE_URL')\n"
            ),
        ],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "DATABASE_URL is required" in result.stdout


def test_cli_defaults_to_api_runner(monkeypatch) -> None:
    called: list[str] = []
    fake_api_main = types.ModuleType("api.main")
    fake_api_main.run = lambda: called.append("api")

    monkeypatch.setitem(sys.modules, "api.main", fake_api_main)
    monkeypatch.setattr(sys, "argv", ["tradingagents"])

    from cli.main import app

    app()

    assert called == ["api"]
