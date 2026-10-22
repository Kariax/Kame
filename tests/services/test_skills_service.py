import pytest

from kame.services import characters, skills
from kame.services.errors import (
    DuplicateSkill,
    InvalidMode,
    InvalidSkill,
    NoCharacter,
    SkillLocked,
)
from kame.db.database import transaction


def make(conn, content, discord_id=1, name="Mira", class_id="mago"):
    return characters.create_character(conn, content, discord_id, name, class_id)


def set_level(conn, discord_id, level):
    cid = characters.get_character(conn, discord_id).id
    with transaction(conn):
        conn.execute("UPDATE characters SET level = ? WHERE id = ?", (level, cid))


def ids(view):
    return [s.id for s in view.equipped]


def test_default_loadout_has_two_unlocked_skills(conn, content):
    make(conn, content)
    view = skills.get_loadout(conn, content, 1)
    assert ids(view) == ["bola_de_sombra", "escarcha_cortante"]
    assert view.ultimate is None and view.ultimate_locked.id == "tormenta_del_abismo"
    assert view.ultimate_mode == "always"
    assert {s.id for s in view.locked} == {"maleficio", "fuego_maldito"}


def test_levels_unlock_skills_and_the_ultimate(conn, content):
    make(conn, content)
    set_level(conn, 1, 6)
    assert "maleficio" in {s.id for s in skills.get_loadout(conn, content, 1).available}
    set_level(conn, 1, 8)
    assert skills.get_loadout(conn, content, 1).ultimate.id == "tormenta_del_abismo"


def test_set_loadout_and_persistence(conn, content):
    make(conn, content)
    set_level(conn, 1, 6)
    view = skills.set_loadout(conn, content, 1, "maleficio", "bola_de_sombra", "elite")
    assert ids(view) == ["maleficio", "bola_de_sombra"] and view.ultimate_mode == "elite"
    assert ids(skills.get_loadout(conn, content, 1)) == ["maleficio", "bola_de_sombra"]


def test_change_a_single_slot_keeps_the_other(conn, content):
    make(conn, content)
    set_level(conn, 1, 6)
    view = skills.set_loadout(conn, content, 1, skill_2="Maleficio")  # por nombre
    assert ids(view) == ["bola_de_sombra", "maleficio"]
    view = skills.set_loadout(conn, content, 1, ultimate_mode="never")
    assert ids(view) == ["bola_de_sombra", "maleficio"] and view.ultimate_mode == "never"


def test_invalid_choices_are_rejected_without_changing_anything(conn, content):
    make(conn, content)
    before = skills.get_loadout(conn, content, 1)
    with pytest.raises(SkillLocked):
        skills.set_loadout(conn, content, 1, "maleficio")
    with pytest.raises(InvalidSkill):
        skills.set_loadout(conn, content, 1, "golpe_aplastante")      # de otra clase
    with pytest.raises(InvalidSkill):
        skills.set_loadout(conn, content, 1, "tormenta_del_abismo")   # las definitivas no se equipan
    with pytest.raises(InvalidSkill):
        skills.set_loadout(conn, content, 1, "no_existe")
    with pytest.raises(DuplicateSkill):
        skills.set_loadout(conn, content, 1, "bola_de_sombra", "bola_de_sombra")
    with pytest.raises(InvalidMode):
        skills.set_loadout(conn, content, 1, ultimate_mode="siempre_siempre")
    assert skills.get_loadout(conn, content, 1) == before


def test_duplicate_through_a_single_slot_is_rejected(conn, content):
    make(conn, content)
    with pytest.raises(DuplicateSkill):
        skills.set_loadout(conn, content, 1, skill_2="bola_de_sombra")  # ya está en el hueco 1


def test_loadouts_are_per_player(conn, content):
    make(conn, content, 1, "Mira")
    make(conn, content, 2, "Aldric", "guerrero")
    skills.set_loadout(conn, content, 1, ultimate_mode="never")
    assert skills.get_loadout(conn, content, 2).ultimate_mode == "always"
    assert ids(skills.get_loadout(conn, content, 2)) == ["golpe_aplastante", "bastion_de_hierro"]


def test_without_character(conn, content):
    with pytest.raises(NoCharacter):
        skills.get_loadout(conn, content, 99)
    with pytest.raises(NoCharacter):
        skills.set_loadout(conn, content, 99, ultimate_mode="never")


def test_invalid_stored_skill_falls_back_to_defaults(conn, content):
    make(conn, content)
    cid = characters.get_character(conn, 1).id
    conn.execute("UPDATE characters SET skill_1 = 'golpe_aplastante', skill_2 = 'inventada' WHERE id = ?", (cid,))
    assert ids(skills.get_loadout(conn, content, 1)) == ["bola_de_sombra", "escarcha_cortante"]
