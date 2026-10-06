"""Add Custodian isolation using migration credentials; preserve all other schemas."""

import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def main() -> None:
    path = Path(".env")
    config = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    owner_url = config["MIGRATION_DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    u = urlsplit(owner_url)
    env = {
        **os.environ,
        "PGHOST": str(u.hostname),
        "PGPORT": str(u.port or 5432),
        "PGUSER": str(u.username),
        "PGPASSWORD": str(u.password),
        "PGDATABASE": u.path[1:],
        "PGSSLMODE": "require" if config.get("DATABASE_SSL", "true") == "true" else "disable",
        "PGCONNECT_TIMEOUT": "15",
    }

    def sql(query: str) -> str:
        result = subprocess.run(
            ["psql", "-X", "-tA", "-v", "ON_ERROR_STOP=1"],
            input=query,
            text=True,
            capture_output=True,
            env=env,
        )
        if result.returncode:
            raise RuntimeError(
                "Database provisioning failed; inspect database permissions (credentials suppressed)"
            )
        return result.stdout.strip()

    exists = sql("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='custodian');")
    role = sql("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='custodian_app');")
    if exists == "t" or role == "t":
        if urlsplit(config["DATABASE_URL"]).username == "custodian_app":
            print("Custodian schema/runtime role already configured; no changes.")
            return
        raise SystemExit(
            "Existing Custodian schema/role found; refusing to reuse or change its credentials automatically"
        )
    password = secrets.token_urlsafe(32)
    sql(f"""BEGIN;
CREATE ROLE custodian_app LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE SCHEMA custodian;
REVOKE ALL ON SCHEMA custodian FROM PUBLIC;
GRANT USAGE ON SCHEMA custodian TO custodian_app;
COMMIT;""")
    host = f"{u.hostname}:{u.port or 5432}"
    config["DATABASE_URL"] = urlunsplit(
        ("postgresql+asyncpg", f"custodian_app:{password}@{host}", u.path, "", "")
    )
    path.write_text("\n".join(f"{key}={value}" for key, value in config.items()) + "\n")
    path.chmod(0o600)
    print(
        "Created isolated Custodian schema and restricted runtime login. Existing schemas preserved."
    )


if __name__ == "__main__":
    main()
