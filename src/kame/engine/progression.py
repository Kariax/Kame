"""Reglas de experiencia y subida de nivel. Código puro, fácil de probar."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressionRules:
    max_level: int
    xp_base: float
    xp_exponent: float
    points_per_level: int


@dataclass(frozen=True)
class XpResult:
    level: int
    xp: int
    levels_gained: int
    points_gained: int


def xp_to_next_level(level: int, rules: ProgressionRules) -> int:
    """XP necesaria para pasar de `level` a `level + 1` (0 si ya es el nivel máximo)."""
    if level < 1:
        raise ValueError("El nivel mínimo es 1.")
    if level >= rules.max_level:
        return 0
    return max(1, int(rules.xp_base * level**rules.xp_exponent))


def apply_xp(level: int, xp: int, amount: int, rules: ProgressionRules) -> XpResult:
    """Suma `amount` de XP y devuelve el nuevo nivel, la XP restante y los puntos ganados.

    - Puede subir varios niveles de golpe y la XP sobrante se conserva.
    - En el nivel máximo la XP se queda en 0 (no se acumula).
    """
    if amount < 0:
        raise ValueError("La experiencia a sumar no puede ser negativa.")
    if level < 1 or level > rules.max_level:
        raise ValueError("Nivel fuera de rango.")
    if xp < 0:
        raise ValueError("La experiencia actual no puede ser negativa.")

    if level >= rules.max_level:
        return XpResult(level=level, xp=0, levels_gained=0, points_gained=0)

    xp += amount
    gained = 0
    while level < rules.max_level and xp >= xp_to_next_level(level, rules):
        xp -= xp_to_next_level(level, rules)
        level += 1
        gained += 1
    if level >= rules.max_level:
        xp = 0
    return XpResult(
        level=level,
        xp=xp,
        levels_gained=gained,
        points_gained=gained * rules.points_per_level,
    )
