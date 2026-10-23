"""Motor de combate automático 1 contra 1. Código puro: sin Discord ni base de datos.

Reglas (provisionales, se afinan con scripts/simulate.py):
- Cada ronda: turno del jugador y luego turno del enemigo. Si nadie cae en 30 rondas, derrota.
- Daño = poder * multiplicador * variación(±20 %) * mitigación;
  mitigación = poder / (poder + armadura): la armadura se mide contra el poder del atacante,
  así escala sola con el nivel y no crea contrarios imposibles.
  Los ataques físicos se mitigan con la defensa y los mágicos con la resistencia.
- El jugador elige acción por orden: definitiva (según su modo) -> habilidades equipadas en orden
  de prioridad -> ataque básico. Las de utilidad (cura, escudo, estado) solo se usan si sirven.
- Reutilización (cooldown) N: si se usa en el turno t, vuelve a estar disponible en el turno t+N.
- Estados: aturdimiento, vulnerabilidad (+daño recibido), debilidad (-daño causado),
  guardia (-daño recibido) y veneno (daño por turno que ignora armadura).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from kame.engine.effects import CombatModifiers
from kame.engine.models import ClassDef
from kame.engine.skills import SkillDef
from kame.engine.stats import derive_stats

DAMAGE_VARIANCE = 0.20
LOW_HP_ULTIMATE = 0.5
HEAL_SKILL_THRESHOLD = 0.7
SECOND_WIND_THRESHOLD = 0.3


@dataclass(frozen=True)
class Combatant:
    name: str
    max_hp: int
    power: float
    damage_type: str  # "physical" o "magic"
    defense: float
    resistance: float
    crit_chance: float = 0.0  # en porcentaje
    crit_multiplier: float = 1.5
    skills: tuple[SkillDef, ...] = ()
    ultimate: SkillDef | None = None
    ultimate_mode: str = "always"
    modifiers: CombatModifiers = field(default_factory=CombatModifiers)
    is_elite: bool = False


@dataclass(frozen=True)
class CombatLogEntry:
    """Un solo evento durante un combate, para mostrar al jugador."""
    round: int
    turn: str  # "player" o "enemy"
    action: str  # "basic_attack", nombre de skill, "ult", "defend", etc.
    damage: int = 0
    damage_type: str = "physical"
    is_crit: bool = False
    is_heal: bool = False
    heal_amount: int = 0
    effect: str | None = None  # aturdimiento, vulnerabilidad, etc.
    target: str = ""  # nombre del objetivo


@dataclass(frozen=True)
class FightResult:
    player_won: bool
    rounds: int
    player_hp_left: int
    enemy_hp_left: int
    combat_log: tuple[CombatLogEntry, ...] = ()
    log: tuple[CombatLogEntry, ...] = ()


def player_combatant(
    name: str, level: int, attributes: dict[str, int], class_def: ClassDef
) -> Combatant:
    """Combatiente básico (sin objetos ni habilidades): útil para pruebas y simulaciones simples."""
    stats = derive_stats(level, attributes)
    attack = class_def.basic_attack
    base_power = stats.physical_power if attack.damage_type == "physical" else stats.magic_power
    return Combatant(
        name=name,
        max_hp=stats.max_hp,
        power=base_power * attack.power_multiplier,
        damage_type=attack.damage_type,
        defense=stats.defense,
        resistance=stats.defense,
        crit_chance=stats.crit_chance,
        crit_multiplier=attack.crit_multiplier,
    )


class _Side:
    """Estado mutable de un bando durante un combate."""

    def __init__(self, combatant: Combatant):
        self.c = combatant
        self.hp = combatant.max_hp
        self.stun = 0
        self.vuln_amt = 0.0
        self.vuln_turns = 0
        self.weaken_amt = 0.0
        self.weaken_turns = 0
        self.guard_amt = 0.0
        self.guard_turns = 0
        self.poison_dmg = 0
        self.poison_turns = 0
        self.second_wind_used = False


def _damage(
    att: _Side,
    dfn: _Side,
    rng: random.Random,
    *,
    multiplier: float = 1.0,
    damage_type: str = "basic",
    ignore_armor: float = 0.0,
    force_crit: bool = False,
    skill_id: str | None = None,
) -> int:
    c, d = att.c, dfn.c
    dtype = c.damage_type if damage_type == "basic" else damage_type
    raw = c.power * multiplier * rng.uniform(1 - DAMAGE_VARIANCE, 1 + DAMAGE_VARIANCE)
    if skill_id is not None:
        raw *= 1 + c.modifiers.skill_power + c.modifiers.empower.get(skill_id, 0.0)
    if d.is_elite:
        raw *= 1 + c.modifiers.elite_damage
    armor = d.defense if dtype == "physical" else d.resistance
    armor *= max(0.0, 1 - ignore_armor - c.modifiers.armor_pen)
    reference = max(1.0, c.power)
    damage = raw * reference / (reference + max(0.0, armor))
    if force_crit or (c.crit_chance > 0 and rng.random() * 100 < c.crit_chance):
        damage *= c.crit_multiplier + c.modifiers.crit_damage
    if dfn.vuln_turns > 0:
        damage *= 1 + dfn.vuln_amt
    if att.weaken_turns > 0:
        damage *= 1 - att.weaken_amt
    if dfn.guard_turns > 0:
        damage *= 1 - dfn.guard_amt
    return max(1, round(damage))


def _skill_is_useful(skill: SkillDef, me: _Side, foe: _Side) -> bool:
    if skill.multiplier > 0:
        return True
    useful = False
    if skill.heal_pct:
        useful |= me.hp < HEAL_SKILL_THRESHOLD * me.c.max_hp
    if skill.guard:
        useful |= me.guard_turns == 0
    if skill.stun_turns:
        useful |= foe.stun == 0
    if skill.vulnerable:
        useful |= foe.vuln_turns == 0
    if skill.weaken:
        useful |= foe.weaken_turns == 0
    if skill.poison_pct:
        useful |= foe.poison_turns == 0
    return useful


def _ultimate_allowed(mode: str, me: _Side, foe: _Side) -> bool:
    if mode == "never":
        return False
    if mode == "elite":
        return foe.c.is_elite
    if mode == "low_hp":
        return me.hp < LOW_HP_ULTIMATE * me.c.max_hp
    return True


def _choose_skill(me: _Side, foe: _Side, cooldowns: dict[str, int]) -> SkillDef | None:
    ult = me.c.ultimate
    if ult and cooldowns[ult.id] <= 0 and _ultimate_allowed(me.c.ultimate_mode, me, foe):
        return ult
    for skill in me.c.skills:
        if cooldowns[skill.id] <= 0 and _skill_is_useful(skill, me, foe):
            return skill
    return None


def _use_skill(skill: SkillDef, me: _Side, foe: _Side, rng: random.Random) -> int:
    dealt = 0
    if skill.multiplier > 0:
        dealt = _damage(
            me, foe, rng, multiplier=skill.multiplier, damage_type=skill.damage_type,
            ignore_armor=skill.ignore_armor, force_crit=skill.always_crit, skill_id=skill.id,
        )
        foe.hp -= dealt
    if skill.heal_pct:
        me.hp = min(me.c.max_hp, me.hp + round(me.c.max_hp * skill.heal_pct))
    if skill.guard:
        me.guard_amt, me.guard_turns = skill.guard, skill.guard_turns
    if skill.stun_turns:
        foe.stun = max(foe.stun, skill.stun_turns)
    if skill.vulnerable:
        foe.vuln_amt, foe.vuln_turns = skill.vulnerable, skill.vulnerable_turns + 1
    if skill.weaken:
        foe.weaken_amt, foe.weaken_turns = skill.weaken, skill.weaken_turns
    if skill.poison_pct:
        foe.poison_dmg = max(1, round(me.c.power * skill.poison_pct))
        foe.poison_turns = skill.poison_turns
    return dealt


def fight(
    player: Combatant, enemy: Combatant, rng: random.Random, max_rounds: int = 30
) -> FightResult:
    log: list[CombatLogEntry] = []

    def _log_entry(**kwargs):
        log.append(CombatLogEntry(round=round_number, **kwargs))

    me, foe = _Side(player), _Side(enemy)
    skills = list(player.skills) + ([player.ultimate] if player.ultimate else [])
    cooldowns = {s.id: 0 for s in skills}
    mods = player.modifiers

    for round_number in range(1, max_rounds + 1):
        # ---------- turno del jugador ----------
        for skill_id in cooldowns:
            if cooldowns[skill_id] > 0:
                cooldowns[skill_id] -= 1
        if me.stun > 0:
            me.stun -= 1
            _log_entry(turn="player", action="stunned", target=player.name)
        else:
            skill = _choose_skill(me, foe, cooldowns)
            if skill is not None:
                dealt = _use_skill(skill, me, foe, rng)
                cooldowns[skill.id] = max(1, skill.cooldown - mods.skill_haste)
                action_name = "ultimate" if skill is player.ultimate else skill.name
                _log_entry(
                    turn="player",
                    action=action_name,
                    damage=dealt,
                    damage_type=skill.damage_type if skill.damage_type != "basic" else player.damage_type,
                    is_crit=skill.always_crit or (dealt > player.power * skill.multiplier * 1.2),
                    target=enemy.name,
                    effect=(
                        "🛡️ Guardia" if skill.guard else
                        "⚡ Aturdimiento" if skill.stun_turns else
                        "💧 Veneno" if skill.poison_pct else
                        "🔻 Vulnerable" if skill.vulnerable else
                        "🔻 Debilidad" if skill.weaken else
                        None
                    ),
                )
                if skill.heal_pct:
                    heal_amt = round(me.c.max_hp * skill.heal_pct)
                    _log_entry(
                        turn="player",
                        action="heal",
                        is_heal=True,
                        heal_amount=heal_amt,
                        target=player.name,
                    )
            else:
                dealt = _damage(me, foe, rng)
                _log_entry(
                    turn="player",
                    action="basic_attack",
                    damage=dealt,
                    damage_type=player.damage_type,
                    is_crit=dealt > player.power * 1.5,
                    target=enemy.name,
                )
                foe.hp -= dealt
            if mods.lifesteal and dealt:
                heal_amt = round(dealt * mods.lifesteal)
                me.hp = min(player.max_hp, me.hp + heal_amt)
                _log_entry(
                    turn="player",
                    action="lifesteal",
                    is_heal=True,
                    heal_amount=heal_amt,
                    target=player.name,
                )
            if foe.hp <= 0:
                return FightResult(True, round_number, me.hp, 0, combat_log=tuple(log))

        # ---------- turno del enemigo ----------
        if foe.poison_turns > 0:
            foe.hp -= foe.poison_dmg
            _log_entry(
                turn="enemy",
                action="poison_damage",
                damage=foe.poison_dmg,
                is_crit=False,
                target=enemy.name,
            )
            foe.poison_turns -= 1
            if foe.hp <= 0:
                return FightResult(True, round_number, me.hp, 0, combat_log=tuple(log))
        if foe.stun > 0:
            foe.stun -= 1
            _log_entry(turn="enemy", action="stunned", target=enemy.name)
        else:
            hit = _damage(foe, me, rng)
            _log_entry(
                turn="enemy",
                action="basic_attack",
                damage=hit,
                damage_type=enemy.damage_type,
                is_crit=False,
                target=player.name,
            )
            me.hp -= hit
            if mods.thorns:
                thorns_dmg = max(1, round(hit * mods.thorns))
                foe.hp -= thorns_dmg
                _log_entry(
                    turn="player",
                    action="thorns",
                    damage=thorns_dmg,
                    target=enemy.name,
                )
                if foe.hp <= 0 and me.hp > 0:
                    return FightResult(True, round_number, me.hp, 0, combat_log=tuple(log))
            if me.hp <= 0:
                return FightResult(False, round_number, 0, foe.hp, log=tuple(log))
            if (
                mods.second_wind
                and not me.second_wind_used
                and me.hp < SECOND_WIND_THRESHOLD * player.max_hp
            ):
                me.second_wind_used = True
                heal_amt = round(player.max_hp * mods.second_wind)
                me.hp = min(player.max_hp, me.hp + heal_amt)
                _log_entry(
                    turn="player",
                    action="second_wind",
                    is_heal=True,
                    heal_amount=heal_amt,
                    target=player.name,
                )
        # fin de ronda: caducan los estados con duración
        if foe.weaken_turns > 0:
            foe.weaken_turns -= 1
        if foe.vuln_turns > 0:
            foe.vuln_turns -= 1
        if me.guard_turns > 0:
            me.guard_turns -= 1

    return FightResult(False, max_rounds, me.hp, foe.hp, combat_log=tuple(log))