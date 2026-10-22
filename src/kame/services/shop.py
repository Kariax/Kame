"""Servicio de la tienda del mercader: equipo del día, mochila y reinicio de atributos.

Garantías:
- Todo se paga con UPDATE ... WHERE gold >= precio (el oro nunca queda en negativo) dentro de una
  transacción: o se cobra y se entrega, o no pasa nada.
- Cada oferta del día solo se puede comprar una vez por jugador (clave primaria en la BD).
- Comprar equipo NUNCA vende cosas por ti: si el inventario está lleno, se rechaza la compra.
- El precio de compra es mayor que el de venta (validado al cargar el contenido): no hay oro gratis.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass

from kame.content import Content
from kame.db.database import transaction
from kame.engine.items import ItemTemplate
from kame.engine.models import ATTRIBUTES, Character
from kame.engine.shop import (
    Offer,
    bag_upgrade_price,
    daily_offers,
    day_of,
    next_refresh,
    parse_offer_key,
    refundable_points,
    respec_cost,
)
from kame.services.characters import _log, get_character
from kame.services.errors import (
    BagMaxed,
    InventoryFull,
    ItemLevelTooLow,
    NotEnoughGold,
    NothingToRespec,
    OfferAlreadyBought,
    OfferNotFound,
)
from kame.services.items import ItemInstance, inventory_cap


@dataclass(frozen=True)
class OfferView:
    offer: Offer
    template: ItemTemplate
    bought: bool
    level_ok: bool


@dataclass(frozen=True)
class ShopView:
    gold: int
    level: int
    day: int
    refresh_at: int
    offers: tuple[OfferView, ...]
    bag_level: int
    bag_cap: int
    bag_used: int
    bag_next_price: int | None
    bag_slots: int
    respec_cost: int
    respec_is_free: bool
    refundable: int


@dataclass(frozen=True)
class RespecResult:
    character: Character
    refunded: int
    cost: int


def _now() -> int:
    return int(time.time())


def _shop_state(conn: sqlite3.Connection, character_id: int) -> sqlite3.Row:
    conn.execute("INSERT OR IGNORE INTO character_shop (character_id) VALUES (?)", (character_id,))
    return conn.execute("SELECT * FROM character_shop WHERE character_id = ?", (character_id,)).fetchone()


def _pay(conn: sqlite3.Connection, character: Character, price: int) -> None:
    paid = conn.execute(
        "UPDATE characters SET gold = gold - ? WHERE id = ? AND gold >= ?", (price, character.id, price))
    if paid.rowcount != 1:
        have = conn.execute("SELECT gold FROM characters WHERE id = ?", (character.id,)).fetchone()["gold"]
        raise NotEnoughGold(price, have)


def get_shop(conn: sqlite3.Connection, content: Content, discord_id: int, now: int | None = None) -> ShopView:
    now = _now() if now is None else int(now)
    character = get_character(conn, discord_id)
    day = day_of(now)
    bought = {r["offer_key"] for r in conn.execute(
        "SELECT offer_key FROM shop_purchases WHERE character_id = ?", (character.id,))}
    offers = tuple(
        OfferView(o, content.item_templates[o.template_id], o.key in bought,
                  character.level >= content.item_templates[o.template_id].min_level)
        for o in daily_offers(day, content.item_templates, content.shop)
    )
    state = conn.execute("SELECT * FROM character_shop WHERE character_id = ?", (character.id,)).fetchone()
    bag_level = state["bag_upgrades"] if state else 0
    respecs = state["respecs"] if state else 0
    used = conn.execute("SELECT COUNT(*) FROM item_instances WHERE owner_character_id = ?",
                        (character.id,)).fetchone()[0]
    cost = respec_cost(character.level, respecs, content.shop)
    return ShopView(
        gold=character.gold, level=character.level, day=day, refresh_at=next_refresh(now), offers=offers,
        bag_level=bag_level, bag_cap=inventory_cap(conn, content, character.id), bag_used=used,
        bag_next_price=bag_upgrade_price(bag_level, content.shop), bag_slots=content.shop.bag_slots,
        respec_cost=cost, respec_is_free=cost == 0,
        refundable=refundable_points(character.attributes, content.classes[character.class_id].base_attributes),
    )


def buy_offer(conn: sqlite3.Connection, content: Content, discord_id: int, offer_key: str,
              now: int | None = None) -> tuple[ItemInstance, int]:
    """Compra una oferta del equipo del día. Devuelve (objeto, precio)."""
    now = _now() if now is None else int(now)
    parsed = parse_offer_key(offer_key)
    if parsed is None or parsed[0] != day_of(now):
        raise OfferNotFound()
    offer = next((o for o in daily_offers(parsed[0], content.item_templates, content.shop)
                  if o.key == str(offer_key)), None)
    if offer is None:
        raise OfferNotFound()
    template = content.item_templates[offer.template_id]
    try:
        with transaction(conn):
            character = get_character(conn, discord_id)
            if conn.execute("SELECT 1 FROM shop_purchases WHERE character_id = ? AND offer_key = ?",
                            (character.id, offer.key)).fetchone():
                raise OfferAlreadyBought()
            if character.level < template.min_level:
                raise ItemLevelTooLow(template.name, template.min_level)
            used = conn.execute("SELECT COUNT(*) FROM item_instances WHERE owner_character_id = ?",
                                (character.id,)).fetchone()[0]
            if used >= inventory_cap(conn, content, character.id):
                raise InventoryFull()
            _pay(conn, character, offer.price)
            item = ItemInstance(str(uuid.uuid4()), template, dict(template.stats))  # estadísticas base
            conn.execute(
                "INSERT INTO item_instances (id, template_id, owner_character_id, stats, source)"
                " VALUES (?, ?, ?, ?, 'shop')", (item.id, template.id, character.id, json.dumps(item.stats)))
            conn.execute("INSERT INTO shop_purchases (character_id, offer_key, item_id, price)"
                         " VALUES (?, ?, ?, ?)", (character.id, offer.key, item.id, offer.price))
            _log(conn, character.id, "shop_purchase", {"offer": offer.key, "template": template.id,
                                                       "price": offer.price})
    except sqlite3.IntegrityError:
        raise OfferAlreadyBought() from None
    return item, offer.price


def buy_bag_upgrade(conn: sqlite3.Connection, content: Content, discord_id: int) -> tuple[int, int, int]:
    """Compra la siguiente ampliación de mochila. Devuelve (nivel, huecos totales, precio)."""
    with transaction(conn):
        character = get_character(conn, discord_id)
        state = _shop_state(conn, character.id)
        price = bag_upgrade_price(state["bag_upgrades"], content.shop)
        if price is None:
            raise BagMaxed()
        _pay(conn, character, price)
        conn.execute("UPDATE character_shop SET bag_upgrades = bag_upgrades + 1 WHERE character_id = ?",
                     (character.id,))
        _log(conn, character.id, "shop_bag", {"level": state["bag_upgrades"] + 1, "price": price})
        cap = inventory_cap(conn, content, character.id)
    return state["bag_upgrades"] + 1, cap, price


def respec_attributes(conn: sqlite3.Connection, content: Content, discord_id: int) -> RespecResult:
    """Devuelve a los atributos de partida de la clase y recupera los puntos gastados."""
    with transaction(conn):
        character = get_character(conn, discord_id)
        base = content.classes[character.class_id].base_attributes
        refunded = refundable_points(character.attributes, base)
        if refunded <= 0:
            raise NothingToRespec()
        state = _shop_state(conn, character.id)
        cost = respec_cost(character.level, state["respecs"], content.shop)
        if cost:
            _pay(conn, character, cost)
        sets = ", ".join(f"{a} = ?" for a in ATTRIBUTES)  # nombres de columna fijos (constantes)
        conn.execute(
            f"UPDATE characters SET {sets}, unspent_points = unspent_points + ? WHERE id = ?",
            (*[base[a] for a in ATTRIBUTES], refunded, character.id))
        conn.execute("UPDATE character_shop SET respecs = respecs + 1 WHERE character_id = ?", (character.id,))
        _log(conn, character.id, "shop_respec", {"refunded": refunded, "cost": cost})
    return RespecResult(get_character(conn, discord_id), refunded, cost)
