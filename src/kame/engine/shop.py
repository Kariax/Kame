"""Reglas de la tienda del mercader. Código puro: sin Discord ni base de datos.

Equipo del día
--------------
La oferta se calcula con una semilla derivada del día (UTC) y de la ranura: es la misma para todos los
jugadores, se renueva sola a medianoche y no necesita ningún temporizador ni tabla de existencias.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from kame.engine.items import SLOTS, ItemTemplate

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class ShopRules:
    rarities: tuple[str, ...]          # rarezas que se venden
    offers_per_slot: int
    prices: dict[str, int]             # precio por rareza
    respec_free: int
    respec_base: int
    respec_per_level: int
    bag_slots: int                     # huecos que da cada ampliación
    bag_prices: tuple[int, ...]        # precio de cada ampliación sucesiva


@dataclass(frozen=True)
class Offer:
    key: str          # "<día>:<ranura>:<n>"
    day: int
    slot: str
    template_id: str
    price: int


def day_of(timestamp: int) -> int:
    return int(timestamp) // SECONDS_PER_DAY


def next_refresh(timestamp: int) -> int:
    """Instante (segundos desde 1970, UTC) en que se renueva la tienda."""
    return (day_of(timestamp) + 1) * SECONDS_PER_DAY


def daily_offers(day: int, templates: dict[str, ItemTemplate], rules: ShopRules) -> list[Offer]:
    """Ofertas de equipo de un día: `offers_per_slot` objetos distintos por ranura."""
    offers: list[Offer] = []
    for slot in SLOTS:
        pool = sorted(
            (t for t in templates.values() if t.slot == slot and t.rarity in rules.rarities),
            key=lambda t: t.id,
        )
        if not pool:
            continue
        rng = random.Random(f"shop:{day}:{slot}")
        chosen = rng.sample(pool, min(rules.offers_per_slot, len(pool)))
        chosen.sort(key=lambda t: (t.min_level, t.id))
        for index, template in enumerate(chosen):
            offers.append(Offer(f"{day}:{slot}:{index}", day, slot, template.id, rules.prices[template.rarity]))
    return offers


def parse_offer_key(key: str) -> tuple[int, str, int] | None:
    """Devuelve (día, ranura, nº) o None si la clave no tiene el formato esperado."""
    parts = str(key).split(":")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
        return None
    return int(parts[0]), parts[1], int(parts[2])


def respec_cost(level: int, respecs_done: int, rules: ShopRules) -> int:
    """Oro por reiniciar los atributos (los primeros reinicios son gratis)."""
    if respecs_done < rules.respec_free:
        return 0
    return rules.respec_base + rules.respec_per_level * max(1, level)


def refundable_points(attributes: dict[str, int], class_base: dict[str, int]) -> int:
    """Puntos que el jugador ha gastado por encima de los atributos de partida de su clase."""
    return sum(max(0, attributes[a] - class_base[a]) for a in class_base)


def bag_upgrade_price(bag_level: int, rules: ShopRules) -> int | None:
    """Precio de la siguiente ampliación de mochila, o None si ya está al máximo."""
    if bag_level >= len(rules.bag_prices):
        return None
    return rules.bag_prices[bag_level]
