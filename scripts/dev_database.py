"""Isolated local PostgreSQL; never modifies existing clusters/system services."""

import os
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state" / "test"
BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))
PORT = os.environ.get("CUSTODIAN_PG_PORT", "55439")


def main() -> None:
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    data, password_file, envfile = STATE / "postgres", STATE / "owner-password", ROOT / ".env.test"
    first = not data.exists()
    if first:
        if envfile.exists():
            raise SystemExit("Existing .env: refusing to replace configured credentials")
        password_file.write_text(secrets.token_urlsafe(32))
        password_file.chmod(0o600)
        subprocess.run(
            [
                str(BIN / "initdb"),
                "-D",
                str(data),
                "-U",
                "custodian_owner",
                "--pwfile",
                str(password_file),
                "--auth",
                "scram-sha-256",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    status = subprocess.run(
        [str(BIN / "pg_ctl"), "-D", str(data), "status"], stdout=subprocess.DEVNULL
    )
    if status.returncode:
        subprocess.run(
            [
                str(BIN / "pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(STATE / "postgres.log"),
                "-o",
                f"-p {PORT} -h 127.0.0.1 -k {STATE}",
                "start",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    if first:
        owner_password, app_password = password_file.read_text(), secrets.token_urlsafe(32)
        sql = f"CREATE ROLE custodian_app LOGIN PASSWORD '{app_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;\nCREATE DATABASE custodian_test;\n"
        subprocess.run(
            [
                shutil.which("psql") or "psql",
                "-h",
                "127.0.0.1",
                "-p",
                PORT,
                "-U",
                "custodian_owner",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            check=True,
            input=sql,
            text=True,
            env={**os.environ, "PGPASSWORD": owner_password},
            stdout=subprocess.DEVNULL,
        )
        base = f"@127.0.0.1:{PORT}/"
        envfile.write_text(
            "ENVIRONMENT=test\nCOOKIE_SECURE=false\nDATABASE_SSL=false\n"
            'ALLOWED_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]\n'
            f"DATABASE_URL=postgresql+asyncpg://custodian_app:{app_password}{base}custodian_test\n"
            f"MIGRATION_DATABASE_URL=postgresql+asyncpg://custodian_owner:{owner_password}{base}custodian_test\n"
        )
        envfile.chmod(0o600)
        subprocess.run(
            [
                shutil.which("psql") or "psql",
                "-h",
                "127.0.0.1",
                "-p",
                PORT,
                "-U",
                "custodian_owner",
                "-d",
                "custodian_test",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            check=True,
            input="CREATE SCHEMA custodian; REVOKE ALL ON SCHEMA custodian FROM PUBLIC; GRANT USAGE ON SCHEMA custodian TO custodian_app;",
            text=True,
            env={**os.environ, "PGPASSWORD": owner_password},
            stdout=subprocess.DEVNULL,
        )
    print("Isolated test PostgreSQL ready; credentials are in ignored .env.test.")


if __name__ == "__main__":
    main()
