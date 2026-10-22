"""Combate táctico por turnos para mazmorras cooperativas. Código puro: sin Discord ni BD.

Cómo funciona una ronda
-----------------------
1. Al empezar la ronda se anuncian (telegrafían) las intenciones de los enemigos.
2. Cada jugador elige UNA acción: atacar, habilidad 1/2, definitiva, defender o proteger a un aliado.
3. Se resuelven las acciones de los héroes (en orden) y después las de los enemigos.
4. Fin de ronda: venenos, cooldowns, estados. Si la sala se despeja, el grupo descansa y avanza.

Escalado (sin limitarse a multiplicar la vida)
----------------------------------------------
Los enemigos se generan a partir de las estadísticas del grupo, recortadas por un tope de
"rating" para que un jugador muy avanzado no trivialice el contenido:
- Vida del enemigo  = k * daño medio por ronda del héroe (medido; más jugadores => más enemigos)
- Daño del enemigo  = fracción * vida media del grupo  (el golpe es igual de peligroso a cualquier nivel)
- Armadura enemiga  = fracción * poder medio
- Nº de enemigos    = por héroe * nº de jugadores; el jefe golpea a más objetivos con más jugadores.
Así la duración en rondas y el peligro por jugador se mantienen con 2, 3, 4 o más participantes.
"""
from __future__ import annotations

import dataclasses
import math
import random
from dataclasses import dataclass, field

from kame.engine import combat as cb
from kame.engine.combat import Combatant
from kame.engine.effects import CombatModifiers
from kame.engine.skills import SkillDef

ACTION_KINDS = ("attack", "skill1", "skill2", "ultimate", "defend", "protect")
DEFEND_FACTOR = 0.5   # daño recibido al defender
PROTECT_FACTOR = 0.75  # daño que recibe quien protege a otro
HEAVY_MULT = 1.8       # golpe pesado de un enemigo fuerte
DEFICIT_EXPONENT = 0.6    # cuánto se endurece la mazmorra por cada % que falta de rating
STUN_IMMUNITY_ROUNDS = 3  # tras un aturdimiento, el enemigo fuerte es inmune durante este tiempo


# ---------------------------------------------------------------------------
# Definiciones (vienen de content/dungeons.toml y content/dungeon_enemies.toml)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DungeonEnemyDef:
    id: str
    name: str
    hp_k: float          # vida = hp_k * poder medio del grupo
    dmg_frac: float      # daño por golpe = dmg_frac * vida media del grupo
    armor_frac: float    # armadura = armor_frac * poder medio del grupo
    damage_type: str = "physical"
    elite: bool = False


@dataclass(frozen=True)
class BossMove:
    name: str
    kind: str            # attack | heavy | aoe | bone_shield
    power: float         # fracción de la vida media del grupo (en bone_shield: daño del estallido)
    every: int = 1       # se usa cada N rondas de la fase
    targets: str = "few"  # few (≈ 1/2 del grupo en ataques, ≈ 1/3 en golpes pesados) | half (1/2)
    shield_rounds: float = 0.0  # bone_shield: rondas de daño del grupo que absorbe


@dataclass(frozen=True)
class BossPhase:
    name: str
    intro: str
    until_hp: float      # la fase termina cuando la vida del jefe baja de esta fracción
    moves: tuple[BossMove, ...]


@dataclass(frozen=True)
class LootRoll:
    chance: float
    pool: str            # normal | elite (pesos de rareza)
    quality: float = 1.0


@dataclass(frozen=True)
class StageDef:
    kind: str            # fight | boss
    name: str
    intro: str
    xp: int
    gold: int
    enemies: tuple[tuple[str, float], ...] = ()   # (enemigo, cantidad por héroe)
    boss_enemy: str = ""
    boss_hp_rounds: float = 0.0
    phases: tuple[BossPhase, ...] = ()
    loot: tuple[LootRoll, ...] = ()
    shared_gold: int = 0
    shared_materials: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DungeonDef:
    id: str
    name: str
    description: str
    min_level: int
    recommended_level: int
    min_players: int
    max_players: int
    recruit_seconds: int
    turn_seconds: int
    hero_rating_cap: float
    stage_heal: float
    revive_hp: float
    auto_after_missed: int
    absent_after_missed: int
    max_rounds: int
    stages: tuple[StageDef, ...]
    hero_rating_floor: float = 0.0  # por debajo de este rating medio, los enemigos se endurecen


# ---------------------------------------------------------------------------
# Unidades y estado
# ---------------------------------------------------------------------------

class Unit(cb._Side):
    """Un héroe o un enemigo en la mazmorra (reutiliza los estados del combate 1 vs 1)."""

    def __init__(self, uid: str, name: str, side: str, combatant: Combatant,
                 enemy_id: str | None = None, boss: bool = False):
        super().__init__(combatant)
        self.uid, self.name, self.side = uid, name, side
        self.enemy_id, self.boss = enemy_id, boss
        self.cooldowns = {s.id: 0 for s in combatant.skills}
        if combatant.ultimate:
            self.cooldowns[combatant.ultimate.id] = 0
        self.shield = 0
        self.stun_immunity = 0  # los enemigos fuertes y jefes no se pueden aturdir en cadena
        self.defending = False
        self.protecting: str | None = None
        self.gone = False  # ausente o abandonó

    @property
    def alive(self) -> bool:
        return self.hp > 0 and not self.gone


@dataclass
class DungeonState:
    seed: int
    scale: dict
    heroes: list[Unit]
    enemies: list[Unit] = field(default_factory=list)
    stage: int = 0
    phase: int = 0          # 0 = no es jefe; 1..3 = fase del jefe
    phase_round: int = 0
    round: int = 1
    intents: list[dict] = field(default_factory=list)
    shield_pending: bool = False
    log: list[str] = field(default_factory=list)


@dataclass
class RoundReport:
    events: list[str]
    outcome: str | None = None            # None | win | loss
    cleared_stages: list[int] = field(default_factory=list)


_STATUS_FIELDS = ("hp", "stun", "vuln_amt", "vuln_turns", "weaken_amt", "weaken_turns", "guard_amt",
                  "guard_turns", "poison_dmg", "poison_turns", "second_wind_used", "cooldowns",
                  "shield", "gone", "stun_immunity")


def _combatant_to_dict(c: Combatant) -> dict:
    return {
        "name": c.name, "max_hp": c.max_hp, "power": c.power, "damage_type": c.damage_type,
        "defense": c.defense, "resistance": c.resistance, "crit_chance": c.crit_chance,
        "crit_multiplier": c.crit_multiplier, "skills": [s.id for s in c.skills],
        "ultimate": c.ultimate.id if c.ultimate else None, "ultimate_mode": c.ultimate_mode,
        "modifiers": dataclasses.asdict(c.modifiers), "is_elite": c.is_elite,
    }


def _combatant_from_dict(d: dict, skills: dict[str, SkillDef]) -> Combatant:
    return Combatant(
        name=d["name"], max_hp=d["max_hp"], power=d["power"], damage_type=d["damage_type"],
        defense=d["defense"], resistance=d["resistance"], crit_chance=d["crit_chance"],
        crit_multiplier=d["crit_multiplier"],
        skills=tuple(skills[i] for i in d["skills"] if i in skills),
        ultimate=skills.get(d["ultimate"]) if d["ultimate"] else None,
        ultimate_mode=d["ultimate_mode"], modifiers=CombatModifiers(**d["modifiers"]),
        is_elite=d["is_elite"],
    )


def unit_to_dict(u: Unit) -> dict:
    data = {"uid": u.uid, "name": u.name, "side": u.side, "enemy_id": u.enemy_id, "boss": u.boss,
            "c": _combatant_to_dict(u.c)}
    for key in _STATUS_FIELDS:
        data[key] = getattr(u, key)
    return data


def unit_from_dict(d: dict, skills: dict[str, SkillDef]) -> Unit:
    unit = Unit(d["uid"], d["name"], d["side"], _combatant_from_dict(d["c"], skills),
                d["enemy_id"], d["boss"])
    for key in _STATUS_FIELDS:
        setattr(unit, key, d[key])
    return unit


def state_to_dict(st: DungeonState) -> dict:
    return {
        "seed": st.seed, "scale": st.scale, "stage": st.stage, "phase": st.phase,
        "phase_round": st.phase_round, "round": st.round, "intents": st.intents,
        "shield_pending": st.shield_pending, "log": st.log,
        "heroes": [unit_to_dict(u) for u in st.heroes],
        "enemies": [unit_to_dict(u) for u in st.enemies],
    }


def state_from_dict(d: dict, skills: dict[str, SkillDef]) -> DungeonState:
    return DungeonState(
        seed=d["seed"], scale=d["scale"], stage=d["stage"], phase=d["phase"],
        phase_round=d["phase_round"], round=d["round"], intents=d["intents"],
        shield_pending=d["shield_pending"], log=d["log"],
        heroes=[unit_from_dict(u, skills) for u in d["heroes"]],
        enemies=[unit_from_dict(u, skills) for u in d["enemies"]],
    )


# ---------------------------------------------------------------------------
# Creación del combate
# ---------------------------------------------------------------------------

def make_hero(uid: str, name: str, combatant: Combatant, rating_cap: float) -> Unit:
    """Convierte a un personaje en héroe, recortando a quien supere el tope de rating."""
    rating = math.sqrt(max(1.0, combatant.power) * max(1, combatant.max_hp))
    factor = min(1.0, rating_cap / rating) if rating_cap > 0 else 1.0
    scaled = dataclasses.replace(
        combatant, name=name, power=combatant.power * factor,
        max_hp=max(1, round(combatant.max_hp * factor)),
        defense=combatant.defense * factor, resistance=combatant.resistance * factor,
    )
    return Unit(uid, name, "hero", scaled)


BENCH_ROUNDS = 10
BENCH_ARMOR_FRAC = 0.35


def estimate_dps(combatant: Combatant) -> float:
    """Daño medio por ronda de un héroe (habilidades, críticos y objetos incluidos).

    Se mide con un combate de prueba contra un muñeco, con semilla fija (resultado estable).
    Así el escalado respeta el rendimiento real de cada build y no solo su "poder" nominal.
    """
    dummy_hp = 10**7
    armor = BENCH_ARMOR_FRAC * combatant.power
    dummy = Combatant("muñeco", dummy_hp, 1.0, "physical", armor, armor)
    total = 0
    for seed in range(4):
        result = cb.fight(combatant, dummy, random.Random(seed), max_rounds=BENCH_ROUNDS)
        total += dummy_hp - result.enemy_hp_left
    return max(1.0, total / (4 * BENCH_ROUNDS))


def _party_scale(dungeon: DungeonDef, heroes: list[Unit]) -> dict:
    """Medidas del grupo con las que se generan los enemigos.

    Si el rating medio del grupo está por debajo del mínimo de la mazmorra (`hero_rating_floor`),
    los enemigos se endurecen en esa proporción: un grupo flojo no encuentra una mazmorra más fácil.
    """
    n = len(heroes)
    dps = [estimate_dps(h.c) for h in heroes]
    avg_rating = sum(math.sqrt(max(1.0, h.c.power) * max(1, h.c.max_hp)) for h in heroes) / n
    deficit = (max(1.0, dungeon.hero_rating_floor / avg_rating) ** DEFICIT_EXPONENT
               if dungeon.hero_rating_floor > 0 else 1.0)
    return {
        "P": sum(h.c.power for h in heroes) / n,              # armadura enemiga
        "H": sum(h.c.max_hp for h in heroes) / n * deficit,   # daño enemigo
        "D": sum(dps) * deficit,                               # daño total por ronda (vida del jefe, coraza)
        "dps": sum(dps) / n * deficit,                         # daño medio por héroe (vida de los enemigos)
        "n": n,
        "deficit": deficit,
    }


def new_state(dungeon: DungeonDef, heroes: list[Unit],
              enemy_defs: dict[str, DungeonEnemyDef], seed: int) -> DungeonState:
    n = len(heroes)
    scale = _party_scale(dungeon, heroes)
    state = DungeonState(seed=seed, scale=scale, heroes=heroes)
    _spawn_stage(state, dungeon, enemy_defs, 0)
    roll_intents(state, dungeon)
    return state


def _spawn_stage(st: DungeonState, dungeon: DungeonDef,
                 enemy_defs: dict[str, DungeonEnemyDef], index: int) -> None:
    stage = dungeon.stages[index]
    P, H, D, n = st.scale["P"], st.scale["H"], st.scale["D"], st.scale["n"]
    st.stage, st.phase_round, st.shield_pending = index, 0, False
    st.enemies = []
    if stage.kind == "boss":
        d = enemy_defs[stage.boss_enemy]
        combatant = Combatant(
            name=d.name, max_hp=max(1, round(stage.boss_hp_rounds * D)), power=H,
            damage_type=d.damage_type, defense=d.armor_frac * P, resistance=d.armor_frac * P,
            is_elite=True,
        )
        st.enemies.append(Unit("e1", d.name, "enemy", combatant, d.id, boss=True))
        st.phase = 1
    else:
        st.phase = 0
        serial = 0
        for enemy_id, per_hero in stage.enemies:
            d = enemy_defs[enemy_id]
            count = max(1, round(per_hero * n))
            for i in range(count):
                serial += 1
                name = d.name if count == 1 else f"{d.name} {i + 1}"
                combatant = Combatant(
                    name=name, max_hp=max(1, round(d.hp_k * st.scale["dps"])), power=max(1.0, d.dmg_frac * H),
                    damage_type=d.damage_type, defense=d.armor_frac * P, resistance=d.armor_frac * P,
                    is_elite=d.elite,
                )
                st.enemies.append(Unit(f"e{serial}", name, "enemy", combatant, d.id))
    st.log = [f"— {stage.name} —", stage.intro] if stage.intro else [f"— {stage.name} —"]


def rescale_after_departure(st: DungeonState, dungeon: DungeonDef) -> None:
    """Un jugador se ha marchado (ausente o abandono): los enemigos actuales se ajustan al grupo restante.

    - El jefe pierde vida en proporción al daño que aporta el grupo que queda.
    - En salas con varios enemigos se retiran los más sanos hasta igualar la proporción de jugadores.
    - Las salas siguientes se generan ya para el grupo restante.
    Así una ausencia no condena al resto del grupo. (Las muertes en combate no reescalan nada.)
    """
    remaining = [h for h in st.heroes if not h.gone]
    old_n = st.scale["n"]
    if not remaining or len(remaining) >= old_n:
        return
    old_d = st.scale["D"]
    new_scale = _party_scale(dungeon, remaining)
    ratio = new_scale["D"] / old_d if old_d else 1.0
    stage = dungeon.stages[st.stage]
    if stage.kind == "boss":
        for boss in living(st.enemies):
            boss.c = dataclasses.replace(boss.c, max_hp=max(1, round(boss.c.max_hp * ratio)))
            boss.hp = max(1, min(boss.c.max_hp, round(boss.hp * ratio)))
    else:
        foes = living(st.enemies)
        keep = max(1, round(len(foes) * len(remaining) / old_n))
        for foe in sorted(foes, key=lambda e: (e.c.is_elite, -e.hp))[: max(0, len(foes) - keep)]:
            st.enemies.remove(foe)
    st.scale = new_scale
    roll_intents(st, dungeon)


def living(units: list[Unit]) -> list[Unit]:
    return [u for u in units if u.alive]


def _boss(st: DungeonState) -> Unit | None:
    return next((e for e in st.enemies if e.boss), None)


def roll_intents(st: DungeonState, dungeon: DungeonDef) -> None:
    """Decide (con una semilla por ronda) qué hará cada enemigo; se anuncia antes de actuar."""
    rng = random.Random(f"{st.seed}:{st.round}:intents")
    heroes = living(st.heroes)
    st.intents = []
    if not heroes:
        return
    for enemy in living(st.enemies):
        if enemy.boss:
            phase = dungeon.stages[st.stage].phases[st.phase - 1]
            shield_move = next((m for m in phase.moves if m.kind == "bone_shield"), None)
            if st.shield_pending and shield_move is not None:
                st.intents.append({"unit": enemy.uid, "kind": "burst", "mult": shield_move.power,
                                   "name": shield_move.name})
                continue
            if st.shield_pending:  # la fase cambió: la coraza desaparece sin estallar
                st.shield_pending = False
                enemy.shield = 0
            for move in phase.moves:
                if (st.phase_round + 1) % max(1, move.every) != 0:
                    continue
                if move.kind in ("attack", "heavy"):
                    count = _target_count(move, len(heroes))
                    targets = [h.uid for h in rng.sample(heroes, min(count, len(heroes)))]
                    st.intents.append({"unit": enemy.uid, "kind": move.kind, "mult": move.power,
                                       "targets": targets, "name": move.name})
                elif move.kind == "aoe":
                    st.intents.append({"unit": enemy.uid, "kind": "aoe", "mult": move.power,
                                       "name": move.name})
                elif move.kind == "bone_shield":
                    st.intents.append({"unit": enemy.uid, "kind": "shield", "mult": move.power,
                                       "shield_rounds": move.shield_rounds, "name": move.name})
        else:
            heavy = enemy.c.is_elite and st.round % 2 == 0
            st.intents.append({"unit": enemy.uid, "kind": "heavy" if heavy else "attack",
                               "mult": HEAVY_MULT if heavy else 1.0,
                               "targets": [rng.choice(heroes).uid],
                               "name": "golpe pesado" if heavy else "ataque"})


def _target_count(move: BossMove, heroes_alive: int) -> int:
    """Cuántos héroes recibe un movimiento: crece con el grupo para que el peligro por jugador no baje."""
    if move.targets == "half" or move.kind == "attack":
        return max(1, math.ceil(heroes_alive / 2))
    return max(1, math.ceil(heroes_alive / 3))  # golpe pesado


def describe_intents(st: DungeonState) -> list[str]:
    names = {u.uid: u.name for u in st.heroes + st.enemies}
    lines = []
    for it in st.intents:
        who = names.get(it["unit"], "?")
        kind = it["kind"]
        if kind in ("attack", "heavy"):
            targets = ", ".join(names.get(t, "?") for t in it["targets"])
            mark = "⚠️ " if kind == "heavy" else ""
            lines.append(f"{mark}**{who}** prepara «{it['name']}» contra {targets}")
        elif kind == "aoe":
            lines.append(f"⚠️ **{who}** prepara «{it['name']}» contra TODO el grupo")
        elif kind == "shield":
            lines.append(f"🛡️ **{who}** se envuelve en una coraza de huesos. Rómpela antes de que estalle")
        elif kind == "burst":
            lines.append(f"💥 La coraza de **{who}** estallará contra todos si no la rompéis esta ronda")
    return lines


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def validate_action(st: DungeonState, hero: Unit, kind: str, target: int | None) -> str | None:
    """Devuelve un mensaje de error, o None si la acción es válida."""
    if kind not in ACTION_KINDS:
        return "Esa acción no existe."
    if not hero.alive:
        return "Tu personaje ha caído y no puede actuar."
    foes = living(st.enemies)
    if kind in ("attack", "skill1", "skill2", "ultimate"):
        if target is not None and not (1 <= target <= len(foes)):
            return f"Objetivo inválido: hay {len(foes)} enemigo(s) en pie."
    if kind in ("skill1", "skill2"):
        index = 0 if kind == "skill1" else 1
        if index >= len(hero.c.skills):
            return "No tienes equipada esa habilidad."
        skill = hero.c.skills[index]
        if hero.cooldowns.get(skill.id, 0) > 0:
            return f"**{skill.name}** estará lista en {hero.cooldowns[skill.id]} ronda(s)."
    if kind == "ultimate":
        if hero.c.ultimate is None:
            return "Aún no tienes definitiva."
        if hero.cooldowns.get(hero.c.ultimate.id, 0) > 0:
            return f"Tu definitiva estará lista en {hero.cooldowns[hero.c.ultimate.id]} ronda(s)."
    if kind == "protect":
        if target is None or not (1 <= target <= len(st.heroes)):
            return "Indica a qué aliado proteges (número de la lista de héroes)."
        ally = st.heroes[target - 1]
        if ally.uid == hero.uid:
            return "No puedes protegerte a ti mismo: usa Defender."
        if not ally.alive:
            return "Ese aliado ya ha caído."
    return None


def _expected_hit(st: DungeonState, intent: dict, hero: Unit) -> float:
    """Daño aproximado (sin azar) de un golpe anunciado sobre un héroe."""
    enemy = next((e for e in st.enemies if e.uid == intent["unit"]), None)
    if enemy is None:
        return 0.0
    power = enemy.c.power * intent["mult"]
    return power * enemy.c.power / (enemy.c.power + hero.c.defense)


def _heavy_threat(st: DungeonState, hero: Unit) -> float:
    """Fracción de la vida actual del héroe que le quitaría el golpe pesado anunciado (0 si no es objetivo)."""
    worst = 0.0
    for it in st.intents:
        if it["kind"] == "heavy" and hero.uid in it.get("targets", []):
            worst = max(worst, _expected_hit(st, it, hero) / max(1, hero.hp))
    return worst


def auto_action(st: DungeonState, hero: Unit) -> tuple[str, int | None]:
    """Acción automática (jugador en modo auto): como los combates de expedición, y además
    se cubre ante un golpe pesado peligroso y protege a un aliado en apuros si es el más robusto."""
    foes = living(st.enemies)
    if not foes or not hero.alive:
        return "defend", None
    if _heavy_threat(st, hero) >= 0.45:
        return "defend", None
    allies = [h for h in living(st.heroes) if h.uid != hero.uid]
    if allies and hero.hp >= 0.7 * hero.c.max_hp:
        sturdiest = all(hero.c.max_hp * (1 + hero.c.defense / 100) >= a.c.max_hp * (1 + a.c.defense / 100)
                        for a in allies)
        threatened = [h for h in allies if _heavy_threat(st, h) >= 0.45
                      and not any(o.protecting == h.uid for o in allies)]
        if sturdiest and threatened:
            weakest = max(threatened, key=lambda h: _heavy_threat(st, h))
            return "protect", st.heroes.index(weakest) + 1
    target = min(foes, key=lambda e: (e.hp, e.uid))
    index = foes.index(target) + 1
    skill = cb._choose_skill(hero, target, hero.cooldowns)
    if skill is None:
        return "attack", index
    if hero.c.ultimate is not None and skill.id == hero.c.ultimate.id:
        return "ultimate", index
    return ("skill1" if hero.c.skills[0].id == skill.id else "skill2"), index


# ---------------------------------------------------------------------------
# Resolución de una ronda
# ---------------------------------------------------------------------------

def _hurt(unit: Unit, damage: int) -> int:
    """Aplica daño; el escudo (coraza) absorbe primero. Devuelve lo absorbido."""
    absorbed = min(unit.shield, damage)
    unit.shield -= absorbed
    unit.hp -= damage - absorbed
    return absorbed


def _skill_on(skill: SkillDef, hero: Unit, foe: Unit, st: DungeonState, rng, ev: list[str]) -> int:
    before_hp, before_shield, before_stun = foe.hp, foe.shield, foe.stun
    dealt = cb._use_skill(skill, hero, foe, rng)
    if foe.c.is_elite and foe.stun > before_stun:
        if foe.stun_immunity > 0:
            foe.stun = before_stun  # inmune: no se aturde
            ev.append(f"🧱 **{foe.name}** resiste el aturdimiento.")
        else:
            foe.stun_immunity = foe.stun + STUN_IMMUNITY_ROUNDS
    # _use_skill resta la vida directamente: devolvemos lo que debió absorber la coraza
    if dealt and before_shield:
        absorbed = min(before_shield, before_hp - foe.hp)
        foe.hp += absorbed
        foe.shield = before_shield - absorbed
    if skill.splash > 0 and skill.multiplier > 0:
        for other in living(st.enemies):
            if other.uid == foe.uid:
                continue
            splash = cb._damage(hero, other, rng, multiplier=skill.multiplier * skill.splash,
                                damage_type=skill.damage_type, ignore_armor=skill.ignore_armor,
                                skill_id=skill.id)
            _hurt(other, splash)
    return dealt


def _check_deaths(units: list[Unit], ev: list[str], seen: set[str]) -> None:
    for u in units:
        if u.hp <= 0 and u.uid not in seen and not u.gone:
            seen.add(u.uid)
            ev.append(f"💀 **{u.name}** cae.")


def _hero_hit(enemy: Unit, hero: Unit, damage: int, rng, ev: list[str], label: str) -> None:
    """Un enemigo golpea a un héroe (con sus efectos de objetos)."""
    mods = hero.c.modifiers
    hero.hp -= damage
    ev.append(f"{label}: **{enemy.name}** golpea a **{hero.name}** (-{damage}).")
    if mods.thorns and hero.hp + damage > 0:
        _hurt(enemy, max(1, round(damage * mods.thorns)))
    if (hero.hp > 0 and mods.second_wind and not hero.second_wind_used
            and hero.hp < cb.SECOND_WIND_THRESHOLD * hero.c.max_hp):
        hero.second_wind_used = True
        hero.hp = min(hero.c.max_hp, hero.hp + round(hero.c.max_hp * mods.second_wind))
        ev.append(f"✨ **{hero.name}** recupera el aliento.")


def _check_phase(st: DungeonState, dungeon: DungeonDef, ev: list[str]) -> None:
    boss = _boss(st)
    if boss is None or not boss.alive:
        return
    phases = dungeon.stages[st.stage].phases
    while st.phase < len(phases) and boss.hp <= phases[st.phase - 1].until_hp * boss.c.max_hp:
        st.phase += 1
        st.phase_round = -1  # se suma 1 al acabar la ronda
        st.shield_pending = False
        boss.shield = 0
        ev.append(f"🔥 **Nueva fase: {phases[st.phase - 1].name}.** {phases[st.phase - 1].intro}")


def _advance_stage(st: DungeonState, dungeon: DungeonDef,
                   enemy_defs: dict[str, DungeonEnemyDef], ev: list[str]) -> None:
    for h in st.heroes:
        if h.gone:
            continue
        if h.hp <= 0:
            h.hp = max(1, round(h.c.max_hp * dungeon.revive_hp))
        else:
            h.hp = min(h.c.max_hp, h.hp + round(h.c.max_hp * dungeon.stage_heal))
        h.cooldowns = {k: 0 for k in h.cooldowns}
        h.stun = h.guard_turns = h.vuln_turns = h.weaken_turns = h.poison_turns = 0
        h.second_wind_used = False
    ev.append("🕯️ El grupo recupera el aliento antes de avanzar (los caídos se levantan, heridos).")
    _spawn_stage(st, dungeon, enemy_defs, st.stage + 1)
    ev.extend(st.log)


def resolve_round(
    st: DungeonState,
    dungeon: DungeonDef,
    enemy_defs: dict[str, DungeonEnemyDef],
    actions: dict[str, tuple[str, int | None]],
) -> RoundReport:
    """Resuelve una ronda con las acciones de los héroes. `actions`: uid -> (tipo, objetivo)."""
    rng = random.Random(f"{st.seed}:{st.round}:combat")
    ev: list[str] = [f"**Ronda {st.round}**"]
    report = RoundReport(ev)
    dead_seen = {u.uid for u in st.heroes + st.enemies if u.hp <= 0}

    for h in st.heroes:
        h.defending, h.protecting = False, None

    # ---------- héroes ----------
    for hero in st.heroes:
        if not hero.alive:
            continue
        for key in hero.cooldowns:
            if hero.cooldowns[key] > 0:
                hero.cooldowns[key] -= 1
        if hero.stun > 0:
            hero.stun -= 1
            ev.append(f"😵 **{hero.name}** está aturdido y pierde el turno.")
            continue
        kind, target = actions.get(hero.uid, ("defend", None))
        if validate_action(st, hero, kind, target) is not None:
            kind, target = "defend", None
        foes = living(st.enemies)
        if kind == "defend":
            hero.defending = True
            ev.append(f"🛡️ **{hero.name}** se cubre.")
            continue
        if kind == "protect":
            ally = st.heroes[target - 1]
            hero.protecting = ally.uid
            ev.append(f"🛡️ **{hero.name}** protege a **{ally.name}**.")
            continue
        if not foes:
            continue
        foe = foes[(target or 1) - 1]
        skill = None
        if kind == "skill1":
            skill = hero.c.skills[0]
        elif kind == "skill2":
            skill = hero.c.skills[1]
        elif kind == "ultimate":
            skill = hero.c.ultimate
        if skill is None:
            dealt = cb._damage(hero, foe, rng)
            absorbed = _hurt(foe, dealt)
            ev.append(f"⚔️ **{hero.name}** ataca a **{foe.name}** (-{dealt - absorbed})"
                      + (f", la coraza absorbe {absorbed}" if absorbed else "") + ".")
        else:
            before = foe.hp + foe.shield
            dealt = _skill_on(skill, hero, foe, st, rng, ev)
            hero.cooldowns[skill.id] = max(1, skill.cooldown - hero.c.modifiers.skill_haste)
            lost = max(0, before - (foe.hp + foe.shield))
            icon = "🌟" if skill.ultimate else "✨"
            ev.append(f"{icon} **{hero.name}** usa **{skill.name}** sobre **{foe.name}**"
                      + (f" (-{lost})" if lost else "") + ".")
        if hero.c.modifiers.lifesteal and dealt:
            hero.hp = min(hero.c.max_hp, hero.hp + round(dealt * hero.c.modifiers.lifesteal))
        _check_deaths(st.enemies, ev, dead_seen)

    boss = _boss(st)
    _check_phase(st, dungeon, ev)

    # ---------- enemigos ----------
    if living(st.enemies):
        _enemy_turn(st, enemy_defs, rng, ev)
        _check_deaths(st.heroes, ev, dead_seen)
        _check_deaths(st.enemies, ev, dead_seen)

    # ---------- fin de ronda ----------
    for enemy in living(st.enemies):
        if enemy.poison_turns > 0:
            enemy.hp -= enemy.poison_dmg
            enemy.poison_turns -= 1
            ev.append(f"☠️ **{enemy.name}** sufre el veneno (-{enemy.poison_dmg}).")
        if enemy.weaken_turns > 0:
            enemy.weaken_turns -= 1
        if enemy.vuln_turns > 0:
            enemy.vuln_turns -= 1
        if enemy.stun_immunity > 0:
            enemy.stun_immunity -= 1
    for h in st.heroes:
        if h.guard_turns > 0:
            h.guard_turns -= 1
    _check_deaths(st.enemies, ev, dead_seen)
    _check_phase(st, dungeon, ev)

    if not living(st.heroes):
        report.outcome = "loss"
        ev.append("☠️ El grupo ha caído.")
        st.log = ev
        return report

    if not living(st.enemies):
        report.cleared_stages.append(st.stage)
        ev.append(f"✅ **{dungeon.stages[st.stage].name}** superada.")
        if st.stage + 1 >= len(dungeon.stages):
            report.outcome = "win"
            st.log = ev
            return report
        _advance_stage(st, dungeon, enemy_defs, ev)

    st.round += 1
    st.phase_round += 1
    if st.round > dungeon.max_rounds:
        report.outcome = "loss"
        ev.append("⌛ El grupo se agota: la mazmorra se ha alargado demasiado.")
        st.log = ev
        return report
    roll_intents(st, dungeon)
    st.log = ev
    return report


def _enemy_turn(st: DungeonState, enemy_defs, rng: random.Random, ev: list[str]) -> None:
    boss = _boss(st)
    for intent in st.intents:
        enemy = next((e for e in st.enemies if e.uid == intent["unit"]), None)
        if enemy is None or not enemy.alive:
            continue
        if enemy.stun > 0:
            enemy.stun -= 1
            ev.append(f"😵 **{enemy.name}** está aturdido y pierde el turno.")
            continue
        kind = intent["kind"]
        weak = (1 - enemy.weaken_amt) if enemy.weaken_turns > 0 else 1.0

        if kind in ("attack", "heavy"):
            for target_uid in intent["targets"]:
                hero = next((h for h in st.heroes if h.uid == target_uid), None)
                if hero is None or not hero.alive:
                    continue
                damage = cb._damage(enemy, hero, rng, multiplier=intent["mult"])
                victim = hero
                protector = next((h for h in living(st.heroes)
                                  if h.protecting == hero.uid and h.uid != hero.uid and h.stun == 0), None)
                if protector is not None:
                    victim = protector
                    damage = max(1, round(damage * PROTECT_FACTOR))
                if victim.defending:
                    damage = max(1, round(damage * DEFEND_FACTOR))
                label = "💥" if kind == "heavy" else "🗡️"
                if protector is not None:
                    ev.append(f"🛡️ **{protector.name}** se interpone por **{hero.name}**.")
                _hero_hit(enemy, victim, damage, rng, ev, label)
                if enemy.hp <= 0:
                    break
        elif kind in ("aoe", "burst"):
            if kind == "burst":
                if enemy.shield <= 0:
                    ev.append(f"💫 ¡La coraza de **{enemy.name}** se ha roto! Queda aturdido y pierde el turno.")
                    st.shield_pending = False
                    continue
                enemy.shield = 0
                st.shield_pending = False
                ev.append(f"💥 La coraza de **{enemy.name}** estalla.")
            for hero in living(st.heroes):
                damage = cb._damage(enemy, hero, rng, multiplier=intent["mult"])
                if hero.defending:
                    damage = max(1, round(damage * DEFEND_FACTOR))
                _hero_hit(enemy, hero, damage, rng, ev, "🌑")
        elif kind == "shield":
            enemy.shield = max(1, round(intent["shield_rounds"] * st.scale["D"]))
            st.shield_pending = True
            ev.append(f"🛡️ **{enemy.name}** se cubre con una coraza de huesos ({enemy.shield}).")


# ---------------------------------------------------------------------------
# Simulación automática (equilibrio y pruebas)
# ---------------------------------------------------------------------------

def simulate_auto(
    dungeon: DungeonDef,
    heroes: list[Unit],
    enemy_defs: dict[str, DungeonEnemyDef],
    seed: int,
    absent: set[str] | None = None,
) -> tuple[str, int, list[int]]:
    """Juega la mazmorra con todos los héroes en modo auto. Devuelve (resultado, rondas, salas superadas).

    `absent`: uids de héroes que nunca actúan: defienden y, tras `absent_after_missed` rondas, se
    marchan (con el mismo reescalado que en una partida real).
    """
    state = new_state(dungeon, heroes, enemy_defs, seed)
    cleared: list[int] = []
    missed: dict[str, int] = {}
    for _ in range(dungeon.max_rounds + 2):
        actions = {}
        left = []
        for h in state.heroes:
            if not h.alive:
                continue
            if absent and h.uid in absent:
                actions[h.uid] = ("defend", None)
                missed[h.uid] = missed.get(h.uid, 0) + 1
                if missed[h.uid] >= dungeon.absent_after_missed:
                    left.append(h)
            else:
                actions[h.uid] = auto_action(state, h)
        report = resolve_round(state, dungeon, enemy_defs, actions)
        cleared.extend(report.cleared_stages)
        if report.outcome:
            return report.outcome, state.round, cleared
        if left:
            for h in left:
                h.gone = True
            rescale_after_departure(state, dungeon)
            if not living(state.heroes):
                return "loss", state.round, cleared
    return "loss", state.round, cleared
