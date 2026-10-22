"""Servicio de estadísticas: agrega totales de progreso del personaje.

Este módulo implementa la lógica para calcular los datos que se muestran en el nuevo comando
`/estadisticas`.  Se basa en las tablas existentes `expeditions`, `dungeon_runs`,
`dungeon_participants` y `activity_log`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Optional

import sqlite3

from kame.services.items import ItemInstance
from kame.content import Content

# Orden de rareza, de mayor a menor, usado para determinar el ítem más raro.
_RARITY_ORDER = {"legendary": 5, "epic": 4, "rare": 3, "uncommon": 2, "common": 1}


@dataclass(frozen=True)
class StatisticsView:
    expeditions_completed: int
    expeditions_won: int
    expeditions_lost: int
    total_encounters: int
    total_victories: int
    total_gold: int
    total_xp: int
    enemies_killed: Dict[str, int]
    rarest_item: Optional[ItemInstance]
    dungeons_completed: int


def _load_expedition_results(conn: sqlite3.Connection, character_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT result FROM expeditions WHERE character_id = ? AND claimed_at IS NOT NULL",
        (character_id,)
    ).fetchall()
    results = []
    for row in rows:
        try:
            results.append(json.loads(row["result"]))
        except Exception:
            # Si el JSON está corrupto simplemente lo ignoramos.
            continue
    return results


def _load_dungeon_participations(conn: sqlite3.Connection, character_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT dr.* FROM dungeon_runs dr"
        " JOIN dungeon_participants dp ON dp.run_id = dr.id"
        " WHERE dp.character_id = ? AND dr.outcome IS NOT NULL",
        (character_id,)
    ).fetchall()


def get_statistics(conn: sqlite3.Connection, content: Content, character_id: int) -> StatisticsView:
    """Calcula y devuelve un ``StatisticsView`` con los totales del personaje.

    - **Expediciones**: solo se consideran las reclamadas (``claimed_at`` no es ``NULL``).
    - **Mazmorras**: se cuentan las partidas finales en las que participó el personaje.
    - **Enemigos**: suma los ``kills`` de las expediciones.
    - **Objeto más raro**: el ``ItemInstance`` con mayor rareza según ``_RARITY_ORDER``.
    """
    # ---------- Expediciones ----------
    expedition_results = _load_expedition_results(conn, character_id)
    exped_completed = len(expedition_results)
    exped_won = sum(1 for r in expedition_results if r.get("victories") == r.get("encounters"))
    exped_lost = sum(1 for r in expedition_results if r.get("retreated"))
    total_encounters = sum(r.get("encounters", 0) for r in expedition_results)
    total_victories = sum(r.get("victories", 0) for r in expedition_results)
    total_gold = sum(r.get("gold", 0) for r in expedition_results)
    total_xp = sum(r.get("xp", 0) for r in expedition_results)

    # ---------- Enemigos derrotados ----------
    enemies: Dict[str, int] = {}
    for r in expedition_results:
        kills = r.get("kills", {}) or {}
        for enemy_id, count in kills.items():
            enemies[enemy_id] = enemies.get(enemy_id, 0) + int(count)

    # ---------- Ítem más raro ----------
    rows = conn.execute(
        "SELECT i.*, e.slot AS equipped_slot FROM item_instances i"
        " LEFT JOIN equipment e ON e.item_id = i.id"
        " WHERE i.owner_character_id = ?",
        (character_id,)
    ).fetchall()
    rarest: Optional[ItemInstance] = None
    max_rank = -1
    for r in rows:
        template = content.item_templates.get(r["template_id"])
        if not template:
            continue
        instance = ItemInstance(r["id"], template, json.loads(r["stats"]), r["equipped_slot"])
        rank = _RARITY_ORDER.get(template.rarity, 0)
        if rank > max_rank:
            max_rank = rank
            rarest = instance
    # ---------- Mazmorras completadas ----------
    dungeon_rows = _load_dungeon_participations(conn, character_id)
    dungeons_completed = len(dungeon_rows)

    return StatisticsView(
        expeditions_completed=exped_completed,
        expeditions_won=exped_won,
        expeditions_lost=exped_lost,
        total_encounters=total_encounters,
        total_victories=total_victories,
        total_gold=total_gold,
        total_xp=total_xp,
        enemies_killed=enemies,
        rarest_item=rarest,
        dungeons_completed=dungeons_completed,
    )

