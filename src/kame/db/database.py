"""Conexión a SQLite, transacciones y migraciones."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(path: str | Path) -> sqlite3.Connection:
    """Abre la base de datos con los ajustes de seguridad del proyecto."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: nosotros controlamos las transacciones a mano.
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")  # espera hasta 5 s si la BD está ocupada
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transacción con bloqueo de escritura inmediato: todo se guarda o nada."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection, migrations_dir: str | Path) -> list[int]:
    """Aplica las migraciones pendientes (archivos NNN_nombre.sql). Devuelve las aplicadas."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    files: dict[int, Path] = {}
    for f in sorted(Path(migrations_dir).glob("*.sql")):
        try:
            version = int(f.stem.split("_")[0])
        except ValueError:
            raise ValueError(f"Nombre de migración inválido: {f.name} (debe empezar por un número)")
        if version in files:
            raise ValueError(f"Versión de migración duplicada: {version}")
        files[version] = f

    newly_applied: list[int] = []
    for version in sorted(files):
        if version in applied:
            continue
        sql = files[version].read_text(encoding="utf-8")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            f"INSERT INTO schema_migrations (version) VALUES ({int(version)});\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        newly_applied.append(version)
    return newly_applied
