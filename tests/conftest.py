from pathlib import Path

import pytest

from kame.content import load_content
from kame.db.database import connect, migrate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def content():
    return load_content(ROOT / "content")


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    conn = connect(path)
    migrate(conn, ROOT / "migrations")
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def fixed_expedition_seed(monkeypatch):
    """Semilla fija: las pruebas son reproducibles. (Con la semilla 1, todas las clases limpian la Cripta.)"""
    import secrets
    monkeypatch.setattr(secrets, "randbits", lambda _bits: 1)
