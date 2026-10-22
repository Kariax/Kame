"""Servicio de personajes: crea, consulta y mejora personajes de forma segura.

Cada función que escribe usa una transacción: o se guarda todo o no se guarda nada.
La identidad siempre es el `discord_id` de quien ejecuta el comando, así que un
jugador no puede tocar los datos de otro.
"""
from __future__ import annotations

import json
import re
import sqlite3

from kame.content import Content
from kame.db.database import transaction
from kame.engine.models import ATTRIBUTES, Character
from kame.engine.progression import ProgressionRules, XpResult, apply_xp
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

# Letras (con acentos), separadas por un espacio, apóstrofo o guion.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")


def validate_name(raw: str, min_len: int, max_len: int) -> str:
    name = " ".join((raw or "").split())  # quita espacios sobrantes
    if not (min_len <= len(name) <= max_len):
        raise InvalidName(f"El nombre debe tener entre {min_len} y {max_len} letras.")
    if not _NAME_RE.match(name):
        raise InvalidName("El nombre solo puede tener letras, espacios, guiones y apóstrofos.")
    return name


def _row_to_character(row: sqlite3.Row) -> Character:
    return Character(
        id=row["id"],
        player_id=row["player_id"],
        name=row["name"],
        class_id=row["class_id"],
        level=row["level"],
        xp=row["xp"],
        gold=row["gold"],
        unspent_points=row["unspent_points"],
        attributes={a: row[a] for a in ATTRIBUTES},
        skill_1=row["skill_1"],
        skill_2=row["skill_2"],
        ultimate_mode=row["ultimate_mode"],
    )


def _log(conn: sqlite3.Connection, character_id: int, kind: str, detail: dict) -> None:
    conn.execute(
        "INSERT INTO activity_log (character_id, kind, detail) VALUES (?, ?, ?)",
        (character_id, kind, json.dumps(detail, ensure_ascii=False)),
    )


def _find_class(content: Content, raw: str):
    key = (raw or "").strip().lower()
    if key in content.classes:
        return content.classes[key]
    for class_def in content.classes.values():
        if class_def.name.lower() == key:
            return class_def
    raise UnknownClass()


def get_character(conn: sqlite3.Connection, discord_id: int) -> Character:
    row = conn.execute(
        "SELECT c.* FROM characters c JOIN players p ON p.id = c.player_id"
        " WHERE p.discord_id = ?",
        (discord_id,),
    ).fetchone()
    if row is None:
        raise NoCharacter()
    return _row_to_character(row)


def get_materials(conn: sqlite3.Connection, character_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT material_id, amount FROM character_materials"
        " WHERE character_id = ? AND amount > 0 ORDER BY material_id",
        (character_id,),
    ).fetchall()
    return {r["material_id"]: r["amount"] for r in rows}


def create_character(
    conn: sqlite3.Connection, content: Content, discord_id: int, name: str, class_id: str
) -> Character:
    cfg = content.config
    name = validate_name(name, cfg.name_min_length, cfg.name_max_length)
    class_def = _find_class(content, class_id)
    try:
        with transaction(conn):
            row = conn.execute("SELECT id FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
            if row is None:
                player_id = conn.execute(
                    "INSERT INTO players (discord_id) VALUES (?)", (discord_id,)
                ).lastrowid
            else:
                player_id = row["id"]
            if conn.execute("SELECT 1 FROM characters WHERE player_id = ?", (player_id,)).fetchone():
                raise CharacterAlreadyExists()
            if conn.execute("SELECT 1 FROM characters WHERE name = ?", (name,)).fetchone():
                raise NameTaken()
            attrs = class_def.base_attributes
            character_id = conn.execute(
                "INSERT INTO characters (player_id, name, class_id, fuerza, inteligencia,"
                " vitalidad, destreza, suerte, unspent_points) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    player_id, name, class_def.id,
                    attrs["fuerza"], attrs["inteligencia"], attrs["vitalidad"],
                    attrs["destreza"], attrs["suerte"], cfg.starting_points,
                ),
            ).lastrowid
            _log(conn, character_id, "created", {"name": name, "class": class_def.id})
    except sqlite3.IntegrityError as e:
        # Red de seguridad: si dos peticiones chocan, la BD tiene la última palabra.
        if "characters.name" in str(e):
            raise NameTaken() from None
        raise CharacterAlreadyExists() from None
    return get_character(conn, discord_id)


def spend_points(
    conn: sqlite3.Connection, discord_id: int, attribute: str, amount: int
) -> Character:
    if attribute not in ATTRIBUTES:
        raise InvalidAttribute()
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
        raise InvalidAmount()
    with transaction(conn):
        character = get_character(conn, discord_id)
        if character.unspent_points < amount:
            raise NotEnoughPoints(character.unspent_points)
        # `attribute` está validado contra una lista fija, por eso es seguro usarlo aquí.
        cursor = conn.execute(
            f"UPDATE characters SET {attribute} = {attribute} + ?,"
            " unspent_points = unspent_points - ? WHERE id = ? AND unspent_points >= ?",
            (amount, amount, character.id, amount),
        )
        if cursor.rowcount != 1:
            raise NotEnoughPoints(character.unspent_points)
        _log(conn, character.id, "points_spent", {"attribute": attribute, "amount": amount})
    return get_character(conn, discord_id)


def grant_xp_tx(
    conn: sqlite3.Connection,
    rules: ProgressionRules,
    character_id: int,
    amount: int,
    source: str,
) -> XpResult:
    """Suma XP a un personaje. DEBE llamarse dentro de `transaction()`.

    Está separada de `grant_xp` para que en la Fase 2 una reclamación pueda dar
    XP, oro y objetos en una única transacción.
    """
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise InvalidAmount()
    row = conn.execute(
        "SELECT level, xp FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise NoCharacter()
    result = apply_xp(row["level"], row["xp"], amount, rules)
    conn.execute(
        "UPDATE characters SET level = ?, xp = ?, unspent_points = unspent_points + ? WHERE id = ?",
        (result.level, result.xp, result.points_gained, character_id),
    )
    _log(
        conn, character_id, "xp_gained",
        {"amount": amount, "source": source, "levels_gained": result.levels_gained},
    )
    return result


def grant_xp(
    conn: sqlite3.Connection, rules: ProgressionRules, character_id: int, amount: int, source: str
) -> XpResult:
    with transaction(conn):
        return grant_xp_tx(conn, rules, character_id, amount, source)
