"""Construcción de un personaje listo para combatir: clase + nivel + atributos + equipo + habilidades."""
from __future__ import annotations

from dataclasses import dataclass

from kame.engine.combat import Combatant
from kame.engine.effects import CombatModifiers, EffectDef, aggregate_modifiers
from kame.engine.items import FLAT_STATS, ItemTemplate
from kame.engine.models import ATTRIBUTES, ClassDef
from kame.engine.skills import SkillDef
from kame.engine.stats import DerivedStats, derive_stats


@dataclass(frozen=True)
class EquippedItem:
    template: ItemTemplate
    stats: dict[str, float]


@dataclass(frozen=True)
class PlayerBuild:
    name: str
    class_def: ClassDef
    level: int
    attributes: dict[str, int]  # atributos base (sin objetos)
    items: tuple[EquippedItem, ...] = ()
    skills: tuple[SkillDef, ...] = ()
    ultimate: SkillDef | None = None
    ultimate_mode: str = "always"


def effective_attributes(build: PlayerBuild) -> dict[str, int]:
    attrs = dict(build.attributes)
    for item in build.items:
        for key in ATTRIBUTES:
            attrs[key] += int(round(item.stats.get(key, 0)))
    return attrs


def flat_bonuses(build: PlayerBuild) -> dict[str, float]:
    flat = {key: 0.0 for key in FLAT_STATS}
    for item in build.items:
        for key in FLAT_STATS:
            flat[key] += item.stats.get(key, 0)
    return flat


def item_effects(build: PlayerBuild) -> list[EffectDef]:
    return [effect for item in build.items for effect in item.template.effects]


def build_modifiers(build: PlayerBuild) -> CombatModifiers:
    return aggregate_modifiers(item_effects(build))


def build_stats(build: PlayerBuild) -> DerivedStats:
    return derive_stats(build.level, effective_attributes(build), flat_bonuses(build))


def build_combatant(build: PlayerBuild) -> Combatant:
    stats = build_stats(build)
    attack = build.class_def.basic_attack
    base_power = stats.physical_power if attack.damage_type == "physical" else stats.magic_power
    return Combatant(
        name=build.name,
        max_hp=stats.max_hp,
        power=base_power * attack.power_multiplier,
        damage_type=attack.damage_type,
        defense=stats.defense,
        resistance=stats.defense,
        crit_chance=stats.crit_chance,
        crit_multiplier=attack.crit_multiplier,
        skills=build.skills,
        ultimate=build.ultimate,
        ultimate_mode=build.ultimate_mode,
        modifiers=build_modifiers(build),
    )
