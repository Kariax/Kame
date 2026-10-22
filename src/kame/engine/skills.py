"""Habilidades de clase. Código puro."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDef:
    id: str
    name: str
    description: str
    class_id: str
    ultimate: bool
    cooldown: int
    unlock_level: int
    multiplier: float = 0.0        # 0 = no hace daño directo
    damage_type: str = "basic"     # basic = el del ataque básico de la clase / physical / magic
    ignore_armor: float = 0.0      # fracción de armadura/resistencia que ignora
    always_crit: bool = False
    heal_pct: float = 0.0          # cura a sí mismo (fracción de vida máxima)
    guard: float = 0.0             # reducción del daño recibido
    guard_turns: int = 0
    stun_turns: int = 0
    vulnerable: float = 0.0        # el objetivo recibe +X de daño
    vulnerable_turns: int = 0
    weaken: float = 0.0            # el objetivo hace -X de daño
    weaken_turns: int = 0
    poison_pct: float = 0.0        # veneno: X * poder por turno
    poison_turns: int = 0
    splash: float = 0.0            # en mazmorras: fracción del daño que reciben los demás enemigos


ULTIMATE_MODES = ("always", "elite", "low_hp", "never")
ULTIMATE_MODE_LABELS = {
    "always": "siempre que esté lista",
    "elite": "solo contra enemigos fuertes",
    "low_hp": "solo con vida baja (< 50 %)",
    "never": "nunca",
}
LOADOUT_SIZE = 2


def class_skills(skills: dict[str, SkillDef], class_id: str, ultimate: bool) -> list[SkillDef]:
    return [s for s in skills.values() if s.class_id == class_id and s.ultimate == ultimate]


def resolve_loadout(
    skills: dict[str, SkillDef],
    class_id: str,
    level: int,
    chosen: list[str | None] | tuple[str | None, ...],
) -> tuple[tuple[SkillDef, ...], SkillDef | None]:
    """Devuelve (habilidades equipadas, definitiva) usables a ese nivel.

    Ignora elecciones inválidas (de otra clase, bloqueadas, repetidas) y rellena los
    huecos con las primeras habilidades desbloqueadas de la clase.
    """
    unlocked = [s for s in class_skills(skills, class_id, False) if s.unlock_level <= level]
    picked: list[SkillDef] = []
    for skill_id in chosen:
        skill = skills.get(skill_id) if skill_id else None
        if skill and skill in unlocked and skill not in picked:
            picked.append(skill)
    for skill in unlocked:
        if len(picked) >= LOADOUT_SIZE:
            break
        if skill not in picked:
            picked.append(skill)
    ultimates = [s for s in class_skills(skills, class_id, True) if s.unlock_level <= level]
    return tuple(picked[:LOADOUT_SIZE]), (ultimates[0] if ultimates else None)
