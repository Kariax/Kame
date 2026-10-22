import sqlite3
from pathlib import Path

import pytest

from kame.db.database import connect, migrate

ROOT = Path(__file__).resolve().parents[2]


def test_migrations_apply_on_empty_db(tmp_path):
    conn = connect(tmp_path / "a.db")
    assert migrate(conn, ROOT / "migrations") == [1, 2, 3, 4, 5, 6, 7]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"players", "characters", "activity_log", "schema_migrations", "expeditions",
            "character_materials", "item_instances", "equipment", "meta", "company", "company_storage",
            "company_ledger", "company_upgrades", "dungeon_runs", "dungeon_participants",
            "dungeon_actions", "character_shop", "shop_purchases", "ranking"} <= tables


def test_migrations_are_idempotent(tmp_path):
    conn = connect(tmp_path / "a.db")
    migrate(conn, ROOT / "migrations")
    assert migrate(conn, ROOT / "migrations") == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 7


def test_failed_migration_rolls_back_completely(tmp_path):
    mig = tmp_path / "migs"
    mig.mkdir()
    (mig / "001_ok.sql").write_text("CREATE TABLE a (id INTEGER);", encoding="utf-8")
    (mig / "002_rota.sql").write_text(
        "CREATE TABLE b (id INTEGER);\nTHIS IS NOT SQL;", encoding="utf-8"
    )
    conn = connect(tmp_path / "a.db")
    with pytest.raises(sqlite3.Error):
        migrate(conn, mig)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables          # la 001 sí se aplicó
    assert "b" not in tables      # la 002 se deshizo entera
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1]


def test_later_migration_is_applied_after_earlier(tmp_path):
    mig = tmp_path / "migs"
    mig.mkdir()
    (mig / "001_a.sql").write_text("CREATE TABLE a (id INTEGER);", encoding="utf-8")
    conn = connect(tmp_path / "a.db")
    migrate(conn, mig)
    (mig / "002_b.sql").write_text("CREATE TABLE b (id INTEGER);", encoding="utf-8")
    assert migrate(conn, mig) == [2]


def test_duplicate_versions_are_rejected(tmp_path):
    mig = tmp_path / "migs"
    mig.mkdir()
    (mig / "001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (mig / "001_b.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError):
        migrate(connect(tmp_path / "a.db"), mig)


def test_database_constraints(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO players (discord_id) VALUES (1)")
    conn.execute("INSERT INTO players (discord_id) VALUES (2)")

    def insert(player, name, gold=0):
        conn.execute(
            "INSERT INTO characters (player_id, name, class_id, gold, fuerza, inteligencia,"
            " vitalidad, destreza, suerte) VALUES (?, ?, 'mago', ?, 1, 1, 1, 1, 1)",
            (player, name, gold),
        )

    insert(1, "Aldric")
    with pytest.raises(sqlite3.IntegrityError):
        insert(1, "Otro")            # un personaje por jugador
    with pytest.raises(sqlite3.IntegrityError):
        insert(2, "ALDRIC")          # nombre repetido sin distinguir mayúsculas
    with pytest.raises(sqlite3.IntegrityError):
        insert(2, "Mira", gold=-5)   # oro negativo
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia,"
                     " vitalidad, destreza, suerte) VALUES (99, 'Fantasma', 'mago', 1,1,1,1,1)")


def test_data_survives_reconnect(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO players (discord_id) VALUES (42)")
    conn.close()
    conn2 = connect(db_path)
    assert conn2.execute("SELECT discord_id FROM players").fetchone()[0] == 42


def test_expedition_constraints(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO players (discord_id) VALUES (1)")
    conn.execute(
        "INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia, vitalidad,"
        " destreza, suerte) VALUES (1, 'Aldric', 'mago', 1, 1, 1, 1, 1)"
    )

    def open_one():
        conn.execute(
            "INSERT INTO expeditions (character_id, expedition_id, started_at, seed, snapshot)"
            " VALUES (1, 'cripta', 100, 5, '{}')"
        )

    open_one()
    with pytest.raises(sqlite3.IntegrityError):
        open_one()  # una sola expedición abierta por personaje
    conn.execute("UPDATE expeditions SET claimed_at = 200, result = '{}'")
    open_one()  # una vez cerrada, se puede abrir otra
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE expeditions SET claimed_at = 300 WHERE claimed_at IS NULL")  # cerrar sin resultado
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO character_materials VALUES (1, 'hueso_astillado', -1)")


def test_equipment_constraints(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO players (discord_id) VALUES (1)")
    conn.execute(
        "INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia, vitalidad,"
        " destreza, suerte) VALUES (1, 'Aldric', 'mago', 1, 1, 1, 1, 1)"
    )
    for item_id in ("a", "b"):
        conn.execute(
            "INSERT INTO item_instances (id, template_id, owner_character_id, stats, source)"
            " VALUES (?, 'daga_mellada', 1, '{}', 'test')", (item_id,)
        )
    conn.execute("INSERT INTO equipment VALUES (1, 'weapon', 'a')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO equipment VALUES (1, 'weapon', 'b')")   # una pieza por ranura
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO equipment VALUES (1, 'helmet', 'a')")   # no equipado dos veces
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO equipment VALUES (1, 'cabeza', 'b')")   # ranura inválida
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM item_instances WHERE id = 'a'")         # no se borra lo equipado
    conn.execute("DELETE FROM item_instances WHERE id = 'b'")             # lo no equipado sí
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE characters SET ultimate_mode = 'xx'")


def test_old_characters_get_defaults_after_migration_003(tmp_path):
    mig = ROOT / "migrations"
    conn = connect(tmp_path / "old.db")
    conn.executescript("PRAGMA foreign_keys=ON;")
    only_first_two = tmp_path / "m"
    only_first_two.mkdir()
    for f in sorted(mig.glob("00[12]_*.sql")):
        (only_first_two / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    migrate(conn, only_first_two)
    conn.execute("INSERT INTO players (discord_id) VALUES (1)")
    conn.execute(
        "INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia, vitalidad,"
        " destreza, suerte) VALUES (1, 'Vieja', 'mago', 1, 1, 1, 1, 1)"
    )
    # After adding migration 007 for activity_log partitioning, expect up to version 7
    assert migrate(conn, mig) == [3, 4, 5, 6, 7]
    row = conn.execute("SELECT skill_1, skill_2, ultimate_mode FROM characters").fetchone()
    assert (row["skill_1"], row["skill_2"], row["ultimate_mode"]) == (None, None, "always")


def test_company_row_exists_and_storage_cannot_go_negative(db_path):
    conn = connect(db_path)
    assert conn.execute("SELECT name FROM company WHERE id = 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO company (id, name) VALUES (2, 'otra')")      # una sola compañía
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO company_storage VALUES ('gold', -1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO company_ledger (resource_id, delta, reason) VALUES ('gold', 0, 'x')")
    conn.execute("INSERT INTO company_storage VALUES ('gold', 5)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE company_storage SET amount = amount - 6 WHERE resource_id = 'gold'")


def test_dungeon_constraints(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO players (discord_id) VALUES (1)")
    conn.execute(
        "INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia, vitalidad,"
        " destreza, suerte) VALUES (1, 'Aldric', 'mago', 1, 1, 1, 1, 1)")
    for run_id in (1, 2):
        conn.execute(
            "INSERT INTO dungeon_runs (id, dungeon_id, leader_character_id, state, seed, recruit_deadline,"
            " created_at) VALUES (?, 'x', 1, 'recruiting', 1, 10, 1)", (run_id,))
    conn.execute("INSERT INTO dungeon_participants (run_id, character_id, state, joined_at) VALUES (1, 1, 'active', 1)")
    with pytest.raises(sqlite3.IntegrityError):  # una sola partida abierta por personaje
        conn.execute("INSERT INTO dungeon_participants (run_id, character_id, state, joined_at) VALUES (2, 1, 'active', 1)")
    conn.execute("UPDATE dungeon_participants SET open = 0")
    conn.execute("INSERT INTO dungeon_participants (run_id, character_id, state, joined_at) VALUES (2, 1, 'active', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE dungeon_runs SET state = 'rara' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE dungeon_participants SET mode = 'x' WHERE run_id = 2")
    conn.execute("INSERT INTO dungeon_actions VALUES (1, 1, 1, 'attack', NULL, 1)")
    with pytest.raises(sqlite3.IntegrityError):  # una acción por jugador y ronda
        conn.execute("INSERT INTO dungeon_actions VALUES (1, 1, 1, 'defend', NULL, 2)")


def test_shop_constraints(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO players (discord_id) VALUES (1)")
    conn.execute(
        "INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia, vitalidad,"
        " destreza, suerte) VALUES (1, 'Aldric', 'mago', 1, 1, 1, 1, 1)")
    conn.execute("INSERT INTO character_shop (character_id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO character_shop (character_id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE character_shop SET bag_upgrades = -1")
    conn.execute("INSERT INTO shop_purchases (character_id, offer_key, item_id, price) VALUES (1, '5:weapon:0', 'a', 40)")
    with pytest.raises(sqlite3.IntegrityError):  # misma oferta, mismo día: una sola compra
        conn.execute("INSERT INTO shop_purchases (character_id, offer_key, item_id, price) VALUES (1, '5:weapon:0', 'b', 40)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO shop_purchases (character_id, offer_key, item_id, price) VALUES (1, '5:helmet:0', 'c', -1)")
