"""Servicio de habilidades: consultar y configurar el loadout y el modo de la definitiva."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from kame.content import Content
from kame.db.database import transaction
from kame.engine.models import Character
from kame.engine.skills import (
    LOADOUT_SIZE,
    ULTIMATE_MODES,
    SkillDef,
    class_skills,
    resolve_loadout,
)
from kame.services.characters import _log, get_character
from kame.services.errors import DuplicateSkill, InvalidMode, InvalidSkill, SkillLocked


@dataclass(frozen=True)
class LoadoutView:
    character: Character
    equipped: tuple[SkillDef, ...]
    ultimate: SkillDef | None
    ultimate_mode: str
    available: tuple[SkillDef, ...]   # desbloqueadas
    locked: tuple[SkillDef, ...]      # aún bloqueadas
    ultimate_locked: SkillDef | None


def _view(content: Content, character: Character) -> LoadoutView:
    equipped, ultimate = resolve_loadout(
        content.skills, character.class_id, character.level, (character.skill_1, character.skill_2)
    )
    normal = class_skills(content.skills, character.class_id, False)
    ultimates = class_skills(content.skills, character.class_id, True)
    return LoadoutView(
        character=character,
        equipped=equipped,
        ultimate=ultimate,
        ultimate_mode=character.ultimate_mode,
        available=tuple(s for s in normal if s.unlock_level <= character.level),
        locked=tuple(s for s in normal if s.unlock_level > character.level),
        ultimate_locked=next((s for s in ultimates if s.unlock_level > character.level), None)
        if ultimate is None else None,
    )


def get_loadout(conn: sqlite3.Connection, content: Content, discord_id: int) -> LoadoutView:
    return _view(content, get_character(conn, discord_id))


def _find_skill(content: Content, character: Character, raw: str) -> SkillDef:
    key = (raw or "").strip().lower()
    skill = content.skills.get(key)
    if skill is None:
        skill = next((s for s in content.skills.values() if s.name.lower() == key), None)
    if skill is None or skill.class_id != character.class_id or skill.ultimate:
        raise InvalidSkill()
    if skill.unlock_level > character.level:
        raise SkillLocked(skill.name, skill.unlock_level)
    return skill


def set_loadout(
    conn: sqlite3.Connection,
    content: Content,
    discord_id: int,
    skill_1: str | None = None,
    skill_2: str | None = None,
    ultimate_mode: str | None = None,
) -> LoadoutView:
    if ultimate_mode is not None and ultimate_mode not in ULTIMATE_MODES:
        raise InvalidMode()
    with transaction(conn):
        character = get_character(conn, discord_id)
        current, _ = resolve_loadout(
            content.skills, character.class_id, character.level, (character.skill_1, character.skill_2)
        )
        slots = [s.id for s in current] + [None] * LOADOUT_SIZE
        if skill_1 is not None:
            slots[0] = _find_skill(content, character, skill_1).id
        if skill_2 is not None:
            slots[1] = _find_skill(content, character, skill_2).id
        if slots[0] is not None and slots[0] == slots[1]:
            raise DuplicateSkill()
        mode = ultimate_mode or character.ultimate_mode
        conn.execute(
            "UPDATE characters SET skill_1 = ?, skill_2 = ?, ultimate_mode = ? WHERE id = ?",
            (slots[0], slots[1], mode, character.id),
        )
        _log(conn, character.id, "loadout_changed",
             {"skills": slots[:LOADOUT_SIZE], "ultimate_mode": mode})
    return get_loadout(conn, content, discord_id)
