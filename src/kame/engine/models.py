"""Modelos de datos puros del juego (no dependen de Discord ni de la base de datos)."""
from __future__ import annotations

from dataclasses import dataclass, field

# Identificadores de los cinco atributos. Se usan también como columnas en la BD.
ATTRIBUTES: tuple[str, ...] = ("fuerza", "inteligencia", "vitalidad", "destreza", "suerte")


@dataclass(frozen=True)
class BasicAttack:
    """Ataque básico de una clase: tipo de daño y multiplicadores."""

    damage_type: str  # "physical" o "magic"
    power_multiplier: float
    crit_multiplier: float


@dataclass(frozen=True)
class ClassDef:
    """Definición de una clase jugable (viene de content/classes.toml)."""

    id: str
    name: str
    description: str
    base_attributes: dict[str, int]
    primary: tuple[str, ...]
    basic_attack: BasicAttack


@dataclass(frozen=True)
class Character:
    """Un personaje tal y como está guardado."""

    id: int
    player_id: int
    name: str
    class_id: str
    level: int
    xp: int
    gold: int
    unspent_points: int
    attributes: dict[str, int] = field(default_factory=dict)
    skill_1: str | None = None
    skill_2: str | None = None
    ultimate_mode: str = "always"
