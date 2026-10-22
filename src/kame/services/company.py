"""Servicio de la compañía: almacén compartido y mejoras de la sede.

Reglas:
- Todos los personajes son miembros (grupo privado). Cualquiera puede DONAR oro o materiales.
- Nadie retira recursos: el almacén solo se gasta en mejoras de la sede (que benefician a todos).
- Cada movimiento queda en `company_ledger` y el almacén no puede quedar en negativo (CHECK en la BD).
- Donar y comprar son transacciones: se descuenta al jugador/almacén y se registra, o no pasa nada.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from kame.content import Content
from kame.db.database import transaction
from kame.engine.company import GOLD, bonuses_for, missing_resources
from kame.services.characters import _log, get_character
from kame.services.errors import (
    InvalidAmount,
    InvalidResource,
    NotEnoughResource,
    StorageShort,
    UnknownUpgrade,
    UpgradeMaxLevel,
)


@dataclass(frozen=True)
class CompanyView:
    name: str
    storage: dict[str, int]
    upgrades: dict[str, int]
    xp_bonus: float
    gold_bonus: float


@dataclass(frozen=True)
class LedgerEntry:
    character_name: str | None
    resource_id: str
    delta: int
    reason: str
    created_at: str


def _storage(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT resource_id, amount FROM company_storage WHERE amount > 0").fetchall()
    return {r["resource_id"]: r["amount"] for r in rows}


def _upgrades(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT upgrade_id, level FROM company_upgrades").fetchall()
    return {r["upgrade_id"]: r["level"] for r in rows}


def bonuses_tx(conn: sqlite3.Connection, content: Content) -> tuple[float, float]:
    """(bonus de XP, bonus de oro) actuales de la Armería y demás mejoras."""
    return bonuses_for(content.company_upgrades, _upgrades(conn))


def get_company(conn: sqlite3.Connection, content: Content) -> CompanyView:
    name = conn.execute("SELECT name FROM company WHERE id = 1").fetchone()["name"]
    upgrades = _upgrades(conn)
    xp, gold = bonuses_for(content.company_upgrades, upgrades)
    return CompanyView(name, _storage(conn), upgrades, xp, gold)


def add_shared_tx(
    conn: sqlite3.Connection, resource_id: str, amount: int, reason: str, character_id: int | None = None
) -> None:
    """Suma al almacén (recompensas de mazmorra, donaciones). DEBE llamarse dentro de `transaction()`."""
    if amount <= 0:
        return
    conn.execute(
        "INSERT INTO company_storage (resource_id, amount) VALUES (?, ?)"
        " ON CONFLICT(resource_id) DO UPDATE SET amount = amount + excluded.amount",
        (resource_id, amount),
    )
    conn.execute(
        "INSERT INTO company_ledger (character_id, resource_id, delta, reason) VALUES (?, ?, ?, ?)",
        (character_id, resource_id, amount, reason),
    )


def contribute(
    conn: sqlite3.Connection, content: Content, discord_id: int, resource_id: str, amount: int
) -> int:
    """Dona recursos del jugador al almacén. Devuelve la cantidad total de ese recurso en el almacén."""
    if resource_id != GOLD and resource_id not in content.materials:
        raise InvalidResource()
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
        raise InvalidAmount()
    with transaction(conn):
        character = get_character(conn, discord_id)
        if resource_id == GOLD:
            cursor = conn.execute(
                "UPDATE characters SET gold = gold - ? WHERE id = ? AND gold >= ?",
                (amount, character.id, amount),
            )
            available = character.gold
        else:
            cursor = conn.execute(
                "UPDATE character_materials SET amount = amount - ?"
                " WHERE character_id = ? AND material_id = ? AND amount >= ?",
                (amount, character.id, resource_id, amount),
            )
            row = conn.execute(
                "SELECT amount FROM character_materials WHERE character_id = ? AND material_id = ?",
                (character.id, resource_id),
            ).fetchone()
            available = row["amount"] if row else 0
        if cursor.rowcount != 1:
            raise NotEnoughResource(available)
        add_shared_tx(conn, resource_id, amount, "donation", character.id)
        _log(conn, character.id, "company_donation", {"resource": resource_id, "amount": amount})
        total = conn.execute(
            "SELECT amount FROM company_storage WHERE resource_id = ?", (resource_id,)
        ).fetchone()["amount"]
    return total


def buy_upgrade(
    conn: sqlite3.Connection, content: Content, discord_id: int, upgrade_id: str
) -> tuple[int, dict[str, int]]:
    """Compra el siguiente nivel de una mejora con recursos del almacén. Devuelve (nuevo nivel, coste)."""
    key = (upgrade_id or "").strip().lower()
    upgrade = content.company_upgrades.get(key)
    if upgrade is None:
        upgrade = next((u for u in content.company_upgrades.values() if u.name.lower() == key), None)
    if upgrade is None:
        raise UnknownUpgrade()
    with transaction(conn):
        character = get_character(conn, discord_id)
        level = _upgrades(conn).get(upgrade.id, 0)
        if level >= upgrade.max_level:
            raise UpgradeMaxLevel(upgrade.name)
        cost = upgrade.levels[level].cost
        missing = missing_resources(cost, _storage(conn))
        if missing:
            raise StorageShort(missing)
        for resource, amount in cost.items():
            paid = conn.execute(
                "UPDATE company_storage SET amount = amount - ? WHERE resource_id = ? AND amount >= ?",
                (amount, resource, amount),
            )
            if paid.rowcount != 1:  # no debería ocurrir (ya comprobado), pero la BD manda
                raise StorageShort({resource: amount})
            conn.execute(
                "INSERT INTO company_ledger (character_id, resource_id, delta, reason) VALUES (?, ?, ?, ?)",
                (character.id, resource, -amount, f"upgrade:{upgrade.id}:{level + 1}"),
            )
        conn.execute(
            "INSERT INTO company_upgrades (upgrade_id, level) VALUES (?, ?)"
            " ON CONFLICT(upgrade_id) DO UPDATE SET level = excluded.level",
            (upgrade.id, level + 1),
        )
        _log(conn, character.id, "company_upgrade", {"upgrade": upgrade.id, "level": level + 1})
    return level + 1, dict(cost)


def get_ledger(conn: sqlite3.Connection, limit: int = 8) -> list[LedgerEntry]:
    rows = conn.execute(
        "SELECT c.name AS name, l.resource_id, l.delta, l.reason, l.created_at"
        " FROM company_ledger l LEFT JOIN characters c ON c.id = l.character_id"
        " ORDER BY l.id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [LedgerEntry(r["name"], r["resource_id"], r["delta"], r["reason"], r["created_at"]) for r in rows]
