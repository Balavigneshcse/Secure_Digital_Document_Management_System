"""Creates the least-privilege accounts the backend runs as, so the database admin credentials never reach it: a
PostgreSQL role that owns the app's tables but is not a superuser, and a MongoDB user with readWrite on one database.
Idempotent; hands over tables the admin account created earlier. Run by docker compose as `db-init`.

    python -m app.provision          # reads the SDMS_PROVISION_* environment variables below
"""
from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql
from pymongo import MongoClient


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"{name} is required")
    return value


def provision_postgres(admin_url: str, user: str, password: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        role = sql.Identifier(user)
        attrs = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(
            sql.Literal(password))
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
        conn.execute(sql.SQL("ALTER ROLE {} WITH " if exists else "CREATE ROLE {} WITH ").format(role) + attrs)

        db = sql.Identifier(conn.info.dbname)
        conn.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(db, role))
        conn.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(role))

        # Tables first: that also moves the sequences owned by their columns. Then any standalone sequence.
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tableowner <> %s",
                              (user,)).fetchall()
        for (t,) in tables:
            conn.execute(sql.SQL("ALTER TABLE public.{} OWNER TO {}").format(sql.Identifier(t), role))
        seqs = conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'S' AND n.nspname = 'public' AND pg_get_userbyid(c.relowner) <> %s", (user,)).fetchall()
        for (s,) in seqs:
            conn.execute(sql.SQL("ALTER SEQUENCE public.{} OWNER TO {}").format(sql.Identifier(s), role))
    print(f"postgres: role {user} ready (not a superuser); {len(tables)} table(s), {len(seqs)} sequence(s) handed over")


def provision_mongo(admin_url: str, db_name: str, user: str, password: str) -> None:
    client = MongoClient(admin_url, serverSelectionTimeoutMS=10_000)
    try:
        db = client[db_name]
        roles = [{"role": "readWrite", "db": db_name}]
        if db.command("usersInfo", user)["users"]:
            db.command("updateUser", user, pwd=password, roles=roles)
        else:
            db.command("createUser", user, pwd=password, roles=roles)
    finally:
        client.close()
    print(f"mongo: user {user} ready (readWrite on {db_name} only)")


def main() -> None:
    provision_postgres(_env("SDMS_PROVISION_PG_ADMIN_URL"), _env("SDMS_PROVISION_PG_APP_USER", "sdms_app"),
                       _env("SDMS_PROVISION_PG_APP_PASSWORD"))
    provision_mongo(_env("SDMS_PROVISION_MONGO_ADMIN_URL"), _env("SDMS_PROVISION_MONGO_DB", "sdms"),
                    _env("SDMS_PROVISION_MONGO_APP_USER", "sdms_app"), _env("SDMS_PROVISION_MONGO_APP_PASSWORD"))


if __name__ == "__main__":
    main()
