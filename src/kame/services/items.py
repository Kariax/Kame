"""Servicio de objetos: inventario, equipo y venta.

Garantías:
- Un objeto solo se puede usar por su propietario (se comprueba siempre `owner_character_id`).
- Equipar, desequipar y vender son transacciones; la BD impide equipar un objeto dos veces
  (UNIQUE) y borrar uno equipado (ON DELETE RESTRICT).
- Cada instancia tiene un UUID propio y estadísticas definitivas guardadas.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from kame.content import Content
from kame.db.database import transaction
from kame.engine.build import EquippedItem, PlayerBuild
from kame.engine.items import RARITIES, SLOTS, ItemDrop, ItemTemplate, sell_value
from kame.engine.models import Character
from kame.engine.skills import resolve_loadout
from kame.services.characters import _log, get_character
from kame.services.errors import (
    InvalidSlot,
    ItemAlreadyEquipped,
    ItemEquippedCannotSell,
    ItemLevelTooLow,
    ItemNotFound,
    NothingEquipped,
)


@dataclass(frozen=True)
class ItemInstance:
    id: str
    template: ItemTemplate
    stats: dict[str, float]
    equipped_slot: str | None = None

    @property
    def equipped(self) -> bool:
        return self.equipped_slot is not None


@dataclass(frozen=True)
class AddedItems:
    kept: tuple[ItemInstance, ...]
    overflow: tuple[ItemInstance, ...]  # vendidos automáticamente por inventario lleno
    overflow_gold: int


def _instance(content: Content, row: sqlite3.Row, slot: str | None) -> ItemInstance | None:
    template = content.item_templates.get(row["template_id"])
    if template is None:  # plantilla retirada del contenido
        return None
    return ItemInstance(row["id"], template, json.loads(row["stats"]), slot)


def _rarity_key(item: ItemInstance):
    return (-RARITIES.index(item.template.rarity), item.template.name, item.id)


def list_inventory(
    conn: sqlite3.Connection, content: Content, discord_id: int, slot: str | None = None
) -> list[ItemInstance]:
    if slot is not None and slot not in SLOTS:
        raise InvalidSlot()
    character = get_character(conn, discord_id)
    rows = conn.execute(
        "SELECT i.*, e.slot AS equipped_slot FROM item_instances i"
        " LEFT JOIN equipment e ON e.item_id = i.id WHERE i.owner_character_id = ?",
        (character.id,),
    ).fetchall()
    items = [_instance(content, r, r["equipped_slot"]) for r in rows]
    items = [i for i in items if i is not None and (slot is None or i.template.slot == slot)]
    return sorted(items, key=_rarity_key)


def get_equipment(
    conn: sqlite3.Connection, content: Content, discord_id: int
) -> dict[str, ItemInstance]:
    return {i.equipped_slot: i for i in list_inventory(conn, content, discord_id) if i.equipped}


def _owned_item(
    conn: sqlite3.Connection, content: Content, character: Character, item_id: str
) -> ItemInstance:
    row = conn.execute(
        "SELECT i.*, e.slot AS equipped_slot FROM item_instances i"
        " LEFT JOIN equipment e ON e.item_id = i.id"
        " WHERE i.id = ? AND i.owner_character_id = ?",
        (str(item_id), character.id),
    ).fetchone()
    item = _instance(content, row, row["equipped_slot"]) if row else None
    if item is None:
        raise ItemNotFound()
    return item


def equip_item(
    conn: sqlite3.Connection, content: Content, discord_id: int, item_id: str
) -> tuple[ItemInstance, ItemInstance | None]:
    """Equipa un objeto. Devuelve (objeto equipado, objeto que había en esa ranura)."""
    with transaction(conn):
        character = get_character(conn, discord_id)
        item = _owned_item(conn, content, character, item_id)
        if item.equipped:
            raise ItemAlreadyEquipped()
        if character.level < item.template.min_level:
            raise ItemLevelTooLow(item.template.name, item.template.min_level)
        slot = item.template.slot
        old_row = conn.execute(
            "SELECT item_id FROM equipment WHERE character_id = ? AND slot = ?",
            (character.id, slot),
        ).fetchone()
        replaced = _owned_item(conn, content, character, old_row["item_id"]) if old_row else None
        conn.execute("DELETE FROM equipment WHERE character_id = ? AND slot = ?", (character.id, slot))
        conn.execute(
            "INSERT INTO equipment (character_id, slot, item_id) VALUES (?, ?, ?)",
            (character.id, slot, item.id),
        )
        _log(conn, character.id, "item_equipped", {"item": item.id, "template": item.template.id})
    return ItemInstance(item.id, item.template, item.stats, slot), replaced


def unequip_slot(
    conn: sqlite3.Connection, content: Content, discord_id: int, slot: str
) -> ItemInstance:
    if slot not in SLOTS:
        raise InvalidSlot()
    with transaction(conn):
        character = get_character(conn, discord_id)
        row = conn.execute(
            "SELECT item_id FROM equipment WHERE character_id = ? AND slot = ?", (character.id, slot)
        ).fetchone()
        if row is None:
            raise NothingEquipped()
        item = _owned_item(conn, content, character, row["item_id"])
        conn.execute("DELETE FROM equipment WHERE character_id = ? AND slot = ?", (character.id, slot))
        _log(conn, character.id, "item_unequipped", {"item": item.id, "template": item.template.id})
    return ItemInstance(item.id, item.template, item.stats, None)


def sell_item(
    conn: sqlite3.Connection, content: Content, discord_id: int, item_id: str
) -> tuple[ItemInstance, int]:
    """Vende un objeto no equipado. Devuelve (objeto, oro obtenido)."""
    with transaction(conn):
        character = get_character(conn, discord_id)
        item = _owned_item(conn, content, character, item_id)
        if item.equipped:
            raise ItemEquippedCannotSell()
        gold = sell_value(item.template, content.config.items)
        deleted = conn.execute(
            "DELETE FROM item_instances WHERE id = ? AND owner_character_id = ?",
            (item.id, character.id),
        )
        if deleted.rowcount != 1:
            raise ItemNotFound()
        conn.execute("UPDATE characters SET gold = gold + ? WHERE id = ?", (gold, character.id))
        _log(conn, character.id, "item_sold",
             {"item": item.id, "template": item.template.id, "gold": gold})
    return item, gold


def inventory_cap(conn: sqlite3.Connection, content: Content, character_id: int) -> int:
    """Huecos de inventario del personaje: los base más los de las ampliaciones de mochila."""
    row = conn.execute(
        "SELECT bag_upgrades FROM character_shop WHERE character_id = ?", (character_id,)
    ).fetchone()
    upgrades = row["bag_upgrades"] if row else 0
    return content.config.items.inventory_cap + upgrades * content.shop.bag_slots


def plan_new_items(
    conn: sqlite3.Connection, content: Content, character_id: int, drops: tuple[ItemDrop, ...]
) -> AddedItems:
    """Decide qué objetos caben en el inventario; el resto se venden solos. NO escribe en la BD."""
    cap = inventory_cap(conn, content, character_id)
    count = conn.execute(
        "SELECT COUNT(*) FROM item_instances WHERE owner_character_id = ?", (character_id,)
    ).fetchone()[0]
    free = max(0, cap - count)
    kept, overflow, gold = [], [], 0
    for index, drop in enumerate(drops):
        template = content.item_templates[drop.template_id]
        instance = ItemInstance(str(uuid.uuid4()), template, dict(drop.stats))
        if index < free:
            kept.append(instance)
        else:
            overflow.append(instance)
            gold += sell_value(template, content.config.items)
    return AddedItems(tuple(kept), tuple(overflow), gold)


def insert_items_tx(
    conn: sqlite3.Connection, character_id: int, items: tuple[ItemInstance, ...], source: str
) -> None:
    """Guarda las instancias. DEBE llamarse dentro de `transaction()`."""
    for item in items:
        conn.execute(
            "INSERT INTO item_instances (id, template_id, owner_character_id, stats, source)"
            " VALUES (?, ?, ?, ?, ?)",
            (item.id, item.template.id, character_id, json.dumps(item.stats), source),
        )


def current_build(
    conn: sqlite3.Connection, content: Content, character: Character
) -> PlayerBuild:
    """El personaje tal y como combatiría ahora: equipo y habilidades incluidos."""
    equipped = [
        EquippedItem(i.template, i.stats)
        for i in get_equipment(conn, content, _discord_id(conn, character)).values()
    ]
    skills, ultimate = resolve_loadout(
        content.skills, character.class_id, character.level, (character.skill_1, character.skill_2)
    )
    return PlayerBuild(
        name=character.name,
        class_def=content.classes[character.class_id],
        level=character.level,
        attributes=dict(character.attributes),
        items=tuple(equipped),
        skills=skills,
        ultimate=ultimate,
        ultimate_mode=character.ultimate_mode,
    )


def _discord_id(conn: sqlite3.Connection, character: Character) -> int:
    return conn.execute(
        "SELECT discord_id FROM players WHERE id = ?", (character.player_id,)
    ).fetchone()[0]


def snapshot_from_build(build: PlayerBuild) -> dict:
    return {
        "class_id": build.class_def.id,
        "level": build.level,
        "attributes": build.attributes,
        "items": [{"template": i.template.id, "stats": i.stats} for i in build.items],
        "skills": [s.id for s in build.skills],
        "ultimate_mode": build.ultimate_mode,
    }


def build_from_snapshot(content: Content, name: str, snap: dict) -> PlayerBuild:
    """Reconstruye el combatiente de una expedición (admite snapshots antiguos sin equipo)."""
    items = tuple(
        EquippedItem(content.item_templates[e["template"]], e["stats"])
        for e in snap.get("items", [])
        if e["template"] in content.item_templates
    )
    skills, ultimate = resolve_loadout(
        content.skills, snap["class_id"], snap["level"], snap.get("skills") or ()
    )
    return PlayerBuild(
        name=name,
        class_def=content.classes[snap["class_id"]],
        level=snap["level"],
        attributes=snap["attributes"],
        items=items,
        skills=skills,
        ultimate=ultimate,
        ultimate_mode=snap.get("ultimate_mode", "always"),
    )
