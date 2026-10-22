"""Servicio de clasificación: calcula y expone el ranking de personajes.

El ranking se basa en la puntuación efectiva del personaje (nivel + atributos +
estadísticas derivadas). La puntuación se guarda en la tabla `ranking` y se
actualiza tras eventos que cambian el poder (reclamar una expedición, etc.).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from kame.content import Content

# Pesos para la puntuación.
_LEVEL_WEIGHT = 100
_ATTRIBUTE_WEIGHT = 2


@dataclass(frozen=True)
class RankEntry:
    name: str
    class_name: str
    level: int
    score: int
    rank: int


def _compute_score(row: sqlite3.Row, content: Content) -> int:
    """Calcula la puntuación de un personaje a partir de su fila de la BD."""
    class_def = content.classes[row["class_id"]]
    attrs = {a: row[a] for a in ("fuerza", "inteligencia", "vitalidad", "destreza", "suerte")}
    attr_points = sum(attrs[a] for a in attrs) - sum(class_def.base_attributes[a] for a in attrs)
    base_score = _LEVEL_WEIGHT * row["level"] + _ATTRIBUTE_WEIGHT * max(0, attr_points)
    vit = attrs["vitalidad"]
    fue = attrs["fuerza"]
    inte = attrs["inteligencia"]
    des = attrs["destreza"]
    max_hp = 40 + 5 * row["level"] + 10 * vit
    power = max(2 * fue + des + row["level"], 2 * inte + row["level"])
    return base_score + power + max_hp // 10


def _upsert_score(conn: sqlite3.Connection, content: Content, character_id: int) -> None:
    """Calcula y guarda la puntuación de un personaje tras un evento."""
    row = conn.execute(
        "SELECT class_id, level, fuerza, inteligencia, vitalidad, destreza, suerte"
        " FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        return
    score = _compute_score(row, content)
    conn.execute(
        "INSERT INTO ranking (character_id, score) VALUES (?, ?)"
        " ON CONFLICT(character_id) DO UPDATE SET score = excluded.score,"
        " updated_at = datetime('now')",
        (character_id, score),
    )


def recompute_ranking(conn: sqlite3.Connection, content: Content) -> int:
    """Recalcula y guarda las puntuaciones de TODOS los personajes. Devuelve el número de filas."""
    rows = conn.execute(
        "SELECT id, class_id, level, fuerza, inteligencia, vitalidad, destreza, suerte"
        " FROM characters ORDER BY id"
    ).fetchall()
    count = 0
    for row in rows:
        score = _compute_score(row, content)
        conn.execute(
            "INSERT INTO ranking (character_id, score) VALUES (?, ?)"
            " ON CONFLICT(character_id) DO UPDATE SET score = excluded.score,"
            " updated_at = datetime('now')",
            (row["id"], score),
        )
        count += 1
    return count


def get_ranking(conn: sqlite3.Connection, content: Content, limit: int = 10) -> tuple[RankEntry, ...]:
    """Devuelve los `limit` primeros del ranking con su posición."""
    rows = conn.execute(
        "SELECT r.score, c.name, c.class_id, c.level"
        " FROM ranking r JOIN characters c ON c.id = r.character_id"
        " ORDER BY r.score DESC, c.name ASC LIMIT ?",
        (int(limit),),
    ).fetchall()
    entries = []
    for rank, row in enumerate(rows, start=1):
        class_def = content.classes.get(row["class_id"])
        entries.append(RankEntry(
            name=row["name"],
            class_name=class_def.name if class_def else row["class_id"],
            level=row["level"],
            score=row["score"],
            rank=rank,
        ))
    return tuple(entries)


__all__ = ["RankEntry", "get_ranking", "recompute_ranking", "update_character_score"]


def update_character_score(
    conn: sqlite3.Connection, content: Content, character_id: int
) -> None:
    """Actualiza la puntuación de un personaje tras un evento (p. ej. reclamar XP)."""
    _upsert_score(conn, content, character_id)
