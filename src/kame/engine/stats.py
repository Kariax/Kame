"""Estadísticas derivadas a partir del nivel y los atributos.

Los coeficientes son PROVISIONALES: se ajustarán en la Fase 3 con el simulador
de equilibrio. Regla de diseño: ningún atributo debe ser inútil.

  fuerza       -> poder físico
  inteligencia -> poder mágico
  vitalidad    -> vida máxima y defensa
  destreza     -> poder físico (algo), probabilidad de crítico
  suerte       -> probabilidad de crítico (algo) y bonus de botín
"""
from __future__ import annotations

from dataclasses import dataclass

CRIT_BASE = 5.0
CRIT_CAP = 60.0


@dataclass(frozen=True)
class DerivedStats:
    max_hp: int
    physical_power: int
    magic_power: int
    defense: int
    crit_chance: float  # en porcentaje
    loot_bonus: float  # en porcentaje


def derive_stats(
    level: int, attributes: dict[str, int], flat: dict[str, float] | None = None
) -> DerivedStats:
    """Calcula las estadísticas derivadas. `flat` suma bonificaciones planas (objetos)."""
    flat = flat or {}
    fue = attributes["fuerza"]
    inte = attributes["inteligencia"]
    vit = attributes["vitalidad"]
    des = attributes["destreza"]
    sue = attributes["suerte"]
    crit = CRIT_BASE + 0.4 * des + 0.2 * sue + flat.get("crit_chance", 0.0)
    return DerivedStats(
        max_hp=40 + 5 * level + 10 * vit + int(round(flat.get("max_hp", 0))),
        physical_power=2 * fue + des + level + int(round(flat.get("physical_power", 0))),
        magic_power=2 * inte + level + int(round(flat.get("magic_power", 0))),
        defense=vit + level // 2 + int(round(flat.get("defense", 0))),
        crit_chance=round(min(CRIT_CAP, crit), 1),
        loot_bonus=round(0.5 * sue + flat.get("loot_bonus", 0.0), 1),
    )
