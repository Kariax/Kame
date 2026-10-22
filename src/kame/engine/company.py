"""Compañía de aventureros: recursos compartidos y mejoras de la sede. Código puro."""
from __future__ import annotations

from dataclasses import dataclass

GOLD = "gold"


@dataclass(frozen=True)
class UpgradeLevel:
    xp_bonus: float
    gold_bonus: float
    cost: dict[str, int]  # recurso -> cantidad ("gold" o id de material)


@dataclass(frozen=True)
class UpgradeDef:
    id: str
    name: str
    description: str
    levels: tuple[UpgradeLevel, ...]

    @property
    def max_level(self) -> int:
        return len(self.levels)


def bonuses_for(upgrades: dict[str, UpgradeDef], owned: dict[str, int]) -> tuple[float, float]:
    """(bonus de XP, bonus de oro) de las expediciones según los niveles comprados."""
    xp = gold = 0.0
    for upgrade_id, level in owned.items():
        upgrade = upgrades.get(upgrade_id)
        if upgrade is None or level <= 0:
            continue
        step = upgrade.levels[min(level, upgrade.max_level) - 1]
        xp += step.xp_bonus
        gold += step.gold_bonus
    return xp, gold


def missing_resources(cost: dict[str, int], storage: dict[str, int]) -> dict[str, int]:
    """Lo que falta en el almacén para pagar `cost` (vacío = alcanza)."""
    return {r: n - storage.get(r, 0) for r, n in cost.items() if storage.get(r, 0) < n}
