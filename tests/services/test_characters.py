import threading

import pytest

from kame.db.database import connect, transaction
from kame.engine.models import ATTRIBUTES
from kame.services import characters
from kame.services.errors import (
    CharacterAlreadyExists,
    InvalidAmount,
    InvalidAttribute,
    InvalidName,
    NameTaken,
    NoCharacter,
    NotEnoughPoints,
    UnknownClass,
)


def make(conn, content, discord_id=1, name="Aldric", class_id="guerrero"):
    return characters.create_character(conn, content, discord_id, name, class_id)


# ---------- creación ----------

def test_create_character_uses_class_base_attributes(conn, content):
    c = make(conn, content, class_id="mago")
    assert c.class_id == "mago"
    assert c.level == 1 and c.xp == 0 and c.gold == 0
    assert c.attributes == content.classes["mago"].base_attributes
    assert c.unspent_points == content.config.starting_points


def test_class_can_be_given_by_display_name(conn, content):
    assert make(conn, content, class_id="Pícaro").class_id == "picaro"


def test_second_character_for_same_player_is_rejected(conn, content):
    make(conn, content)
    with pytest.raises(CharacterAlreadyExists):
        make(conn, content, name="Otro")
    assert conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 1


def test_duplicate_name_is_rejected_case_insensitive(conn, content):
    make(conn, content, 1, "Aldric")
    with pytest.raises(NameTaken):
        make(conn, content, 2, "aldric")


def test_failed_creation_leaves_no_orphan_player(conn, content):
    make(conn, content, 1, "Aldric")
    with pytest.raises(NameTaken):
        make(conn, content, 2, "Aldric")
    assert conn.execute("SELECT COUNT(*) FROM players WHERE discord_id = 2").fetchone()[0] == 0


@pytest.mark.parametrize(
    "name", ["", "  ", "ab", "x" * 21, "Al3ric", "Al_dric", "<b>Hola</b>", "Ald\nric;--", "123"]
)
def test_invalid_names_are_rejected(conn, content, name):
    with pytest.raises(InvalidName):
        make(conn, content, name=name)


@pytest.mark.parametrize("name", ["Mira", "Ñandú", "Jean-Luc", "O'Neil", "Sir Aldric", "Élodie"])
def test_valid_names_are_accepted(conn, content, name):
    assert make(conn, content, name=name).name == name


def test_extra_spaces_in_name_are_collapsed(conn, content):
    assert make(conn, content, name="  Sir    Aldric ").name == "Sir Aldric"


def test_unknown_class_is_rejected(conn, content):
    with pytest.raises(UnknownClass):
        make(conn, content, class_id="paladin")


def test_get_character_without_creating(conn):
    with pytest.raises(NoCharacter):
        characters.get_character(conn, 12345)


def test_creation_is_logged(conn, content):
    c = make(conn, content)
    kinds = [r[0] for r in conn.execute(
        "SELECT kind FROM activity_log WHERE character_id = ?", (c.id,))]
    assert kinds == ["created"]


def test_concurrent_creation_same_player_only_one_wins(db_path, content):
    results = []
    barrier = threading.Barrier(4)

    def worker(i):
        c = connect(db_path)
        try:
            barrier.wait()
            characters.create_character(c, content, 777, f"Heroe{'abcd'[i]}", "guerrero")
            results.append("ok")
        except CharacterAlreadyExists:
            results.append("duplicado")
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["duplicado"] * 3 + ["ok"]
    check = connect(db_path)
    assert check.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 1


# ---------- atributos ----------

def test_spend_points_moves_points_to_attribute(conn, content):
    c = make(conn, content)
    start = c.attributes["fuerza"]
    c2 = characters.spend_points(conn, 1, "fuerza", 2)
    assert c2.attributes["fuerza"] == start + 2
    assert c2.unspent_points == c.unspent_points - 2


def test_cannot_spend_more_points_than_available(conn, content):
    c = make(conn, content)
    with pytest.raises(NotEnoughPoints):
        characters.spend_points(conn, 1, "suerte", c.unspent_points + 1)
    assert characters.get_character(conn, 1) == c  # nada cambió


def test_can_spend_exactly_all_points_but_not_one_more(conn, content):
    c = make(conn, content)
    characters.spend_points(conn, 1, "suerte", c.unspent_points)
    with pytest.raises(NotEnoughPoints):
        characters.spend_points(conn, 1, "suerte", 1)


@pytest.mark.parametrize("amount", [0, -1, -100, 1.5, "3", None, True])
def test_invalid_amounts_are_rejected(conn, content, amount):
    make(conn, content)
    with pytest.raises(InvalidAmount):
        characters.spend_points(conn, 1, "fuerza", amount)


@pytest.mark.parametrize("attr", ["magia", "", "fuerza; DROP TABLE characters", "gold", "level"])
def test_invalid_attributes_are_rejected(conn, content, attr):
    make(conn, content)
    with pytest.raises(InvalidAttribute):
        characters.spend_points(conn, 1, attr, 1)
    assert conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 1


def test_spend_points_without_character(conn):
    with pytest.raises(NoCharacter):
        characters.spend_points(conn, 99, "fuerza", 1)


@pytest.mark.parametrize("attr", ATTRIBUTES)
def test_every_attribute_can_receive_points(conn, content, attr):
    make(conn, content)
    before = characters.get_character(conn, 1).attributes[attr]
    assert characters.spend_points(conn, 1, attr, 1).attributes[attr] == before + 1


def test_players_are_isolated(conn, content):
    make(conn, content, 1, "Aldric")
    b = make(conn, content, 2, "Mira", "mago")
    characters.spend_points(conn, 1, "fuerza", 3)
    assert characters.get_character(conn, 2) == b


# ---------- experiencia ----------

def test_grant_xp_levels_up_and_adds_points(conn, content):
    c = make(conn, content)
    rules = content.config.progression
    r = characters.grant_xp(conn, rules, c.id, 100, "test")
    after = characters.get_character(conn, 1)
    assert r.levels_gained >= 1
    assert after.level == 1 + r.levels_gained
    assert after.unspent_points == c.unspent_points + rules.points_per_level * r.levels_gained


def test_grant_xp_invalid_amount(conn, content):
    c = make(conn, content)
    with pytest.raises(InvalidAmount):
        characters.grant_xp(conn, content.config.progression, c.id, -5, "test")


def test_grant_xp_unknown_character(conn, content):
    with pytest.raises(NoCharacter):
        characters.grant_xp(conn, content.config.progression, 9999, 10, "test")


def test_rolled_back_transaction_does_not_keep_xp(conn, content):
    c = make(conn, content)
    rules = content.config.progression
    with pytest.raises(RuntimeError):
        with transaction(conn):
            characters.grant_xp_tx(conn, rules, c.id, 100_000, "test")
            raise RuntimeError("fallo a mitad de la operación")
    after = characters.get_character(conn, 1)
    assert (after.level, after.xp) == (1, 0)


def test_state_survives_reconnect(db_path, content):
    c1 = connect(db_path)
    make(c1, content)
    characters.spend_points(c1, 1, "fuerza", 2)
    expected = characters.get_character(c1, 1)
    c1.close()
    c2 = connect(db_path)
    assert characters.get_character(c2, 1) == expected
