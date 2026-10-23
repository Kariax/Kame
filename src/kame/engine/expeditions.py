"""Reglas de expediciones automáticas. Código puro.

Una expedición acumula encuentros con el tiempo (hasta un máximo de horas). Al
reclamar, se simulan en orden usando una semilla guardada al empezar. Como los
combates se resuelven en secuencia con una única semilla, el resultado de los
primeros N encuentros es siempre el mismo: reclamar antes o después no permite
"repetir tirada".

Si el personaje es derrotado en un encuentro, el enemigo huye y la expedición
continúa: el siguiente encuentro se enfrenta con las heridas del anterior (el
personaje entra con la HP con la que terminó el combate). Al reclamar, además de
los enemigos derrotados, se muestra cuántas veces cada enemigo te ha vencido.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from kame.engine.combat import Combatant, CombatLogEntry, fight
from kame.engine.items import ItemDrop, ItemRules, ItemTemplate, index_templates, roll_item


@dataclass(frozen=True)
class DropDef:
    material_id: str
    chance: float  # 0..1


@dataclass(frozen=True)
class EnemyDef:
    id: str
    name: str
    hp: int
    power: float
    damage_type: str
    defense: float
    resistance: float
    xp: int
    gold: int
    drops: tuple[DropDef, ...] = ()
    elite: bool = False

    def to_combatant(self) -> Combatant:
        return Combatant(
            name=self.name,
            max_hp=self.hp,
            power=self.power,
            damage_type=self.damage_type,
            defense=self.defense,
            resistance=self.resistance,
            is_elite=self.elite,
        )


@dataclass(frozen=True)
class ExpeditionDef:
    id: str
    name: str
    description: str
    risk: str  # texto: seguro / equilibrado / arriesgado
    min_level: int
    recommended_level: int
    encounters_per_hour: float
    enemy_pool: tuple[tuple[str, int], ...]  # (id de enemigo, peso)
    item_chance: float = 0.0        # probabilidad de objeto por enemigo normal derrotado
    elite_item_chance: float = 0.0  # ... por élite derrotado
    loot_quality: float = 1.0       # >1 favorece rarezas altas


@dataclass(frozen=True)
class ExpeditionRules:
    max_accumulation_hours: float
    over_level_penalty: float  # reducción de XP por nivel por encima del recomendado
    min_xp_factor: float
    max_rounds: int


@dataclass(frozen=True)
class ExpeditionOutcome:
    encounters: int  # encuentros disputados
    victories: int
    retreated: bool
    xp: int
    gold: int
    materials: dict[str, int] = field(default_factory=dict)
    kills: dict[str, int] = field(default_factory=dict)
    defeated_by: dict[str, int] = field(default_factory=dict)
    items: tuple[ItemDrop, ...] = ()
    last_combat_log: tuple[CombatLogEntry, ...] = field(default=(), compare=False)
    last_enemy_id: str = ""
    last_enemy_name: str = ""
    last_enemy_hp: int = 0
    last_enemy_max_hp: int = 0
    last_player_hp: int = 0
    last_player_max_hp: int = 0
    last_player_won: bool = True


def encounters_available(
    elapsed_seconds: float, expedition: ExpeditionDef, rules: ExpeditionRules
) -> int:
    """Encuentros acumulados tras `elapsed_seconds` (con el límite de acumulación)."""
    capped = min(max(0.0, elapsed_seconds), rules.max_accumulation_hours * 3600)
    return int(capped / 3600 * expedition.encounters_per_hour)


def seconds_until_next_encounter(
    elapsed_seconds: float, expedition: ExpeditionDef, rules: ExpeditionRules
) -> int | None:
    """Segundos hasta el siguiente encuentro, o None si ya se alcanzó el límite."""
    if elapsed_seconds >= rules.max_accumulation_hours * 3600:
        return None
    done = encounters_available(elapsed_seconds, expedition, rules)
    next_at = (done + 1) * 3600 / expedition.encounters_per_hour
    return max(0, math.ceil(next_at - elapsed_seconds))


def xp_factor(level: int, recommended_level: int, rules: ExpeditionRules) -> float:
    """Reduce la XP cuando el personaje supera con holgura el nivel recomendado."""
    over = max(0, level - recommended_level)
    return max(rules.min_xp_factor, 1.0 - rules.over_level_penalty * over)


def resolve_expedition(
    *,
    expedition: ExpeditionDef,
    enemies: dict[str, EnemyDef],
    player: Combatant,
    player_level: int,
    loot_bonus: float,
    encounters: int,
    seed: int,
    rules: ExpeditionRules,
    templates: dict[str, ItemTemplate] | None = None,
    item_rules: ItemRules | None = None,
) -> ExpeditionOutcome:
    rng = random.Random(seed)
    ids = [enemy_id for enemy_id, _ in expedition.enemy_pool]
    weights = [weight for _, weight in expedition.enemy_pool]
    factor = xp_factor(player_level, expedition.recommended_level, rules)
    loot_mult = 1 + loot_bonus / 100

    xp_total = 0.0
    gold_total = 0.0
    victories = 0
    attempted = 0
    defeated = 0
    retreated = False
    materials: dict[str, int] = {}
    kills: dict[str, int] = {}
    defeated_by: dict[str, int] = {}
    items: list[ItemDrop] = []
    grouped = None
    if templates and item_rules:
        grouped = index_templates(
            templates, expedition.recommended_level + item_rules.drop_level_margin
        )
    item_find = 1 + player.modifiers.item_find

    last_combat_log: tuple[CombatLogEntry, ...] = ()
    last_enemy_id = ""
    last_enemy_name = ""
    last_enemy_hp = 0
    last_enemy_max_hp = 0
    last_player_hp = 0
    last_player_max_hp = 0
    last_player_won = True

    # El personaje entra cada encuentro con su HP máxima: cuando cae, el enemigo
    # huye y la expedición continúa con el siguiente enemigo (no carrying damage).
    for _ in range(encounters):
        enemy = enemies[rng.choices(ids, weights)[0]]
        attempted += 1
        enemy_combatant = enemy.to_combatant()
        result = fight(player, enemy_combatant, rng, rules.max_rounds)

        # Guardar info del último combate
        last_combat_log = result.log
        last_enemy_id = enemy.id
        last_enemy_name = enemy.name
        last_enemy_hp = result.enemy_hp_left
        last_enemy_max_hp = enemy.hp
        last_player_hp = result.player_hp_left
        last_player_max_hp = player.max_hp
        last_player_won = result.player_won

        if not result.player_won:
            # El enemigo huye; la expedición continúa. Solo se cuentan derrotas
            # cuando el personaje sobrevive al encuentro.
            defeated += 1
            defeated_by[enemy.id] = defeated_by.get(enemy.id, 0) + 1
            retreated = True
            continue
        victories += 1
        kills[enemy.id] = kills.get(enemy.id, 0) + 1
        xp_total += enemy.xp * factor
        gold_total += enemy.gold * rng.uniform(0.8, 1.2) * loot_mult
        for drop in enemy.drops:
            if rng.random() < min(1.0, drop.chance * loot_mult):
                materials[drop.material_id] = materials.get(drop.material_id, 0) + 1
        if grouped is not None:
            chance = expedition.elite_item_chance if enemy.elite else expedition.item_chance
            if rng.random() < min(1.0, chance * loot_mult * item_find):
                loot_weights = item_rules.elite_weights if enemy.elite else item_rules.normal_weights
                drop = roll_item(
                    rng, grouped, loot_weights, expedition.loot_quality, item_rules.stat_variance
                )
                if drop is not None:
                    items.append(drop)

    return ExpeditionOutcome(
        encounters=attempted,
        victories=victories,
        retreated=retreated,
        xp=int(round(xp_total)),
        gold=int(round(gold_total)),
        materials=materials,
        kills=kills,
        defeated_by=defeated_by,
        items=tuple(items),
        last_combat_log=last_combat_log,
        last_enemy_id=last_enemy_id,
        last_enemy_name=last_enemy_name,
        last_enemy_hp=last_enemy_hp,
        last_enemy_max_hp=last_enemy_max_hp,
        last_player_hp=last_player_hp,
        last_player_max_hp=last_player_max_hp,
        last_player_won=last_player_won,
    )
