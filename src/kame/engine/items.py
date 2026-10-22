"""Plantillas de objetos, generación de instancias y bonificaciones. Código puro.

Plantilla = definición (nombre, rareza, estadísticas base, efectos).
Instancia = objeto concreto de un jugador, con estadísticas ya tiradas (±variación).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from kame.engine.effects import EffectDef
from kame.engine.models import ATTRIBUTES

SLOTS = ("weapon", "helmet", "armor", "gloves", "boots", "amulet")
SLOT_LABELS = {
    "weapon": "Arma", "helmet": "Casco", "armor": "Armadura",
    "gloves": "Guantes", "boots": "Botas", "amulet": "Amuleto",
}
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
RARITY_LABELS = {
    "common": "Común", "uncommon": "Poco común", "rare": "Raro",
    "epic": "Épico", "legendary": "Legendario",
}
RARITY_ICONS = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟠"}

# Bonificaciones planas sobre estadísticas derivadas
FLAT_STATS = ("max_hp", "physical_power", "magic_power", "defense", "crit_chance", "loot_bonus")
STAT_KEYS = ATTRIBUTES + FLAT_STATS
STAT_LABELS = {
    "fuerza": "Fuerza", "inteligencia": "Inteligencia", "vitalidad": "Vitalidad",
    "destreza": "Destreza", "suerte": "Suerte",
    "max_hp": "Vida", "physical_power": "Poder físico", "magic_power": "Poder mágico",
    "defense": "Defensa", "crit_chance": "Crítico %", "loot_bonus": "Botín %",
}
_DECIMAL_STATS = ("crit_chance", "loot_bonus")


@dataclass(frozen=True)
class ItemTemplate:
    id: str
    name: str
    description: str
    slot: str
    rarity: str
    min_level: int
    stats: dict[str, float]
    effects: tuple[EffectDef, ...] = ()
    flavor: str = ""  # bruto / arcano / sigilo (orientativo)


@dataclass(frozen=True)
class ItemRules:
    stat_variance: float
    inventory_cap: int
    drop_level_margin: int
    normal_weights: dict[str, float]
    elite_weights: dict[str, float]
    sell_values: dict[str, int]


@dataclass(frozen=True)
class ItemDrop:
    template_id: str
    stats: dict[str, float] = field(default_factory=dict)


def roll_stats(template: ItemTemplate, rng: random.Random, variance: float) -> dict[str, float]:
    """Tira las estadísticas definitivas de una instancia (±variance sobre la base)."""
    rolled: dict[str, float] = {}
    for key, base in template.stats.items():
        value = base * rng.uniform(1 - variance, 1 + variance)
        if key in _DECIMAL_STATS:
            rolled[key] = round(value, 1)
        else:
            rolled[key] = max(1, int(round(value))) if base > 0 else int(round(value))
    return rolled


def sell_value(template: ItemTemplate, rules: ItemRules) -> int:
    return rules.sell_values[template.rarity]


def index_templates(
    templates: dict[str, ItemTemplate], max_level: int
) -> dict[str, list[ItemTemplate]]:
    """Agrupa por rareza las plantillas que pueden soltarse hasta `max_level` (orden estable)."""
    grouped: dict[str, list[ItemTemplate]] = {r: [] for r in RARITIES}
    for template in sorted(templates.values(), key=lambda t: t.id):
        if template.min_level <= max_level:
            grouped[template.rarity].append(template)
    return grouped


def roll_item(
    rng: random.Random,
    grouped: dict[str, list[ItemTemplate]],
    weights: dict[str, float],
    quality: float,
    variance: float,
) -> ItemDrop | None:
    """Elige rareza (con `quality` favoreciendo rarezas altas), plantilla y estadísticas.

    Si la rareza elegida no tiene plantillas disponibles, baja a la rareza inferior más cercana.
    """
    w = [max(0.0, weights.get(r, 0.0)) * (quality**i) for i, r in enumerate(RARITIES)]
    if sum(w) <= 0:
        return None
    index = RARITIES.index(rng.choices(RARITIES, w)[0])
    while index >= 0 and not grouped[RARITIES[index]]:
        index -= 1
    if index < 0:
        return None
    template = rng.choice(grouped[RARITIES[index]])
    return ItemDrop(template.id, roll_stats(template, rng, variance))
