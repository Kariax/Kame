"""Herramientas para medir el equilibrio del juego (las usan scripts/simulate.py y las pruebas)."""
from __future__ import annotations

import random

from kame.engine.combat import fight, player_combatant
from kame.engine.expeditions import EnemyDef, ExpeditionDef, ExpeditionRules
from kame.engine.models import ClassDef


def standard_attributes(
    class_def: ClassDef, level: int, starting_points: int, points_per_level: int
) -> dict[str, int]:
    """Build 'típica' para medir el equilibrio: mitad de los puntos al atributo de daño
    principal de la clase (el primero de `primary`) y mitad a vitalidad."""
    attrs = dict(class_def.base_attributes)
    total = starting_points + points_per_level * (level - 1)
    damage_attr = class_def.primary[0] if class_def.primary else "fuerza"
    to_vit = total // 2
    attrs[damage_attr] += total - to_vit
    attrs["vitalidad"] += to_vit
    return attrs


def win_rate(
    class_def: ClassDef,
    level: int,
    attrs: dict[str, int],
    expedition: ExpeditionDef,
    enemies: dict[str, EnemyDef],
    rules: ExpeditionRules,
    fights: int = 400,
    seed: int = 1234,
) -> float:
    """Probabilidad de ganar un encuentro de esa expedición (media sobre su reparto de enemigos)."""
    rng = random.Random(seed)
    player = player_combatant("sim", level, attrs, class_def)
    ids = [e for e, _ in expedition.enemy_pool]
    weights = [w for _, w in expedition.enemy_pool]
    wins = 0
    for _ in range(fights):
        enemy = enemies[rng.choices(ids, weights)[0]]
        if fight(player, enemy.to_combatant(), rng, rules.max_rounds).player_won:
            wins += 1
    return wins / fights


# ---------------------------------------------------------------------------
# Builds completas (con equipo y habilidades) para medir el equilibrio
# ---------------------------------------------------------------------------
from kame.engine.build import EquippedItem, PlayerBuild, build_combatant  # noqa: E402
from kame.engine.combat import fight as _fight  # noqa: E402
from kame.engine.items import RARITIES, SLOTS, ItemTemplate  # noqa: E402
from kame.engine.skills import SkillDef, resolve_loadout  # noqa: E402

CLASS_FLAVOR = {"guerrero": "bruto", "mago": "arcano", "picaro": "sigilo"}


def typical_rarity_cap(level: int) -> str:
    """Rareza máxima del equipo 'típico' de un jugador medio a cada nivel."""
    if level < 3:
        return "common"
    if level < 8:
        return "uncommon"
    if level < 12:
        return "rare"
    return "epic"


def standard_gear(
    templates: dict[str, ItemTemplate],
    class_id: str,
    level: int,
    rarity_cap: str | None = None,
    mixed: bool = True,
) -> tuple[EquippedItem, ...]:
    """Una pieza por ranura: la mejor rareza permitida cuyo nivel requerido se cumple.

    Con `mixed=True` (equipo 'típico') las ranuras impares llevan una rareza menos que el tope.
    """
    cap = RARITIES.index(rarity_cap or typical_rarity_cap(level))
    flavor = CLASS_FLAVOR.get(class_id, "")
    gear = []
    for index, slot in enumerate(SLOTS):
        slot_cap = max(0, cap - 1) if (mixed and index % 2 == 1) else cap
        options = [
            t for t in templates.values()
            if t.slot == slot and t.min_level <= level and RARITIES.index(t.rarity) <= slot_cap
        ]
        if not options:
            continue
        best = max(RARITIES.index(t.rarity) for t in options)
        top = sorted((t for t in options if RARITIES.index(t.rarity) == best), key=lambda t: t.id)
        chosen = next((t for t in top if t.flavor == flavor), top[0])
        gear.append(EquippedItem(chosen, dict(chosen.stats)))
    return tuple(gear)


def standard_build(
    content, class_id: str, level: int, gear: bool | str = True, ultimate_mode: str = "always",
    mixed: bool = True, loadout: tuple[str, ...] = (),
) -> PlayerBuild:
    """Build típica: puntos repartidos (mitad daño, mitad vitalidad), habilidades por defecto y equipo."""
    cfg = content.config
    class_def = content.classes[class_id]
    attrs = standard_attributes(class_def, level, cfg.starting_points, cfg.progression.points_per_level)
    skills, ultimate = resolve_loadout(content.skills, class_id, level, loadout)
    items: tuple[EquippedItem, ...] = ()
    if gear:
        cap = gear if isinstance(gear, str) else None
        items = standard_gear(content.item_templates, class_id, level, cap, mixed)
    return PlayerBuild("sim", class_def, level, attrs, items, skills, ultimate, ultimate_mode)


def win_rate_build(
    build: PlayerBuild,
    expedition: ExpeditionDef,
    enemies: dict[str, EnemyDef],
    rules: ExpeditionRules,
    fights: int = 400,
    seed: int = 1234,
) -> float:
    rng = random.Random(seed)
    player = build_combatant(build)
    ids = [e for e, _ in expedition.enemy_pool]
    weights = [w for _, w in expedition.enemy_pool]
    wins = 0
    for _ in range(fights):
        enemy = enemies[rng.choices(ids, weights)[0]]
        if _fight(player, enemy.to_combatant(), rng, rules.max_rounds).player_won:
            wins += 1
    return wins / fights


# Habilidades que elegiría un jugador para trabajar en equipo (para simulaciones de mazmorra)
TEAM_LOADOUT = {
    "guerrero": ("golpe_aplastante", "quebrantar"),
    "mago": ("bola_de_sombra", "escarcha_cortante"),
    "picaro": ("punalada_trapera", "hendidura"),
}
