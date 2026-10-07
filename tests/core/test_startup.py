"""Deployment command contract: fail closed before serving an unmigrated schema."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def startup(tmp_path):
    log = tmp_path / "calls"
    migration = tmp_path / "alembic"
    migration.write_text(
        '#!/bin/sh\nprintf "migration %s\\n" "$*" >> "$START_TEST_LOG"\nexit "${START_TEST_FAIL:-0}"\n'
    )
    server = tmp_path / "uvicorn"
    server.write_text(
        '#!/bin/sh\n[ -z "${MIGRATION_DATABASE_URL+x}" ] || exit 77\nprintf "uvicorn %s\\n" "$*" >> "$START_TEST_LOG"\n'
    )
    migration.chmod(0o700)
    server.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + ":" + os.environ["PATH"],
        "START_TEST_LOG": str(log),
        "MIGRATION_DATABASE_URL": "synthetic-migration-value",
        "PORT": "12345",
    }
    return Path("scripts/start.sh").resolve(), env, log


@pytest.mark.parametrize(
    ("mode", "reload", "expected"),
    [("production", "true", False), ("development", "true", True), ("development", "false", False)],
)
def test_migration_precedes_server_and_owner_secret_is_removed(startup, mode, reload, expected):
    script, env, log = startup
    subprocess.run(
        ["sh", str(script)], env={**env, "ENVIRONMENT": mode, "RELOAD": reload}, check=True
    )
    lines = log.read_text().splitlines()
    assert lines[0] == "migration upgrade head"
    assert lines[1].startswith("uvicorn app.vendor_app:create_app --factory")
    assert "--port 12345" in lines[1]
    assert ("--reload" in lines[1]) == expected


def test_failed_migration_never_starts_web_process(startup):
    script, env, log = startup
    result = subprocess.run(["sh", str(script)], env={**env, "START_TEST_FAIL": "42"})
    assert result.returncode == 42
    assert log.read_text().splitlines() == ["migration upgrade head"]


def test_missing_migration_connection_fails_before_start(startup):
    script, env, log = startup
    env.pop("MIGRATION_DATABASE_URL")
    result = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "MIGRATION_DATABASE_URL" in result.stderr
    assert not log.exists()
