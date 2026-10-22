"""Efectos especiales de los objetos y modificadores de combate. Código puro."""
from __future__ import annotations

from dataclasses import dataclass, field

EFFECT_TYPES = (
    "crit_damage",    # +X al multiplicador de crítico
    "skill_haste",    # -X turnos de reutilización a todas las habilidades (mínimo 1)
    "skill_power",    # +X de daño en habilidades (no en el ataque básico)
    "lifesteal",      # recupera X del daño causado como vida
    "thorns",         # devuelve X del daño recibido
    "elite_damage",   # +X de daño contra enemigos fuertes (élites)
    "armor_pen",      # ignora X de la armadura/resistencia del enemigo
    "second_wind",    # una vez por combate, al bajar del 30 % de vida, cura X de la vida máxima
    "empower",        # +X de daño en una habilidad concreta (campo `skill`)
    "item_find",      # +X de probabilidad de que los enemigos suelten objetos
)


@dataclass(frozen=True)
class EffectDef:
    type: str
    value: float
    skill: str | None = None  # solo para "empower"


@dataclass(frozen=True)
class CombatModifiers:
    crit_damage: float = 0.0
    skill_haste: int = 0
    skill_power: float = 0.0
    lifesteal: float = 0.0
    thorns: float = 0.0
    elite_damage: float = 0.0
    armor_pen: float = 0.0
    second_wind: float = 0.0
    item_find: float = 0.0
    empower: dict[str, float] = field(default_factory=dict)


# Límites para que acumular objetos no rompa el combate.
CAPS = {"armor_pen": 0.6, "lifesteal": 0.3, "thorns": 0.6, "second_wind": 0.6}


def aggregate_modifiers(effects: list[EffectDef]) -> CombatModifiers:
    totals: dict[str, float] = {}
    empower: dict[str, float] = {}
    for effect in effects:
        if effect.type == "empower":
            empower[effect.skill or ""] = empower.get(effect.skill or "", 0.0) + effect.value
        else:
            totals[effect.type] = totals.get(effect.type, 0.0) + effect.value
    for key, cap in CAPS.items():
        if key in totals:
            totals[key] = min(cap, totals[key])
    return CombatModifiers(
        crit_damage=totals.get("crit_damage", 0.0),
        skill_haste=int(totals.get("skill_haste", 0)),
        skill_power=totals.get("skill_power", 0.0),
        lifesteal=totals.get("lifesteal", 0.0),
        thorns=totals.get("thorns", 0.0),
        elite_damage=totals.get("elite_damage", 0.0),
        armor_pen=totals.get("armor_pen", 0.0),
        second_wind=totals.get("second_wind", 0.0),
        item_find=totals.get("item_find", 0.0),
        empower=empower,
    )


def describe_effect(effect: EffectDef, skill_names: dict[str, str] | None = None) -> str:
    v = effect.value
    t = effect.type
    if t == "crit_damage":
        return f"+{v:.0%} de daño crítico"
    if t == "skill_haste":
        return f"-{v:g} turno de reutilización en todas las habilidades"
    if t == "skill_power":
        return f"+{v:.0%} de daño en habilidades"
    if t == "lifesteal":
        return f"Roba {v:.0%} del daño causado como vida"
    if t == "thorns":
        return f"Devuelve {v:.0%} del daño recibido"
    if t == "elite_damage":
        return f"+{v:.0%} de daño contra enemigos fuertes"
    if t == "armor_pen":
        return f"Ignora {v:.0%} de la armadura enemiga"
    if t == "second_wind":
        return f"Una vez por combate, al bajar del 30 % de vida, cura {v:.0%}"
    if t == "empower":
        name = (skill_names or {}).get(effect.skill or "", effect.skill or "?")
        return f"+{v:.0%} de daño en {name}"
    if t == "item_find":
        return f"+{v:.0%} de probabilidad de objetos"
    return t
