"""Combate con habilidades, estados y modificadores de objetos (sin aleatoriedad: variación 0)."""
import random

import pytest

from kame.engine import combat
from kame.engine.combat import Combatant, fight
from kame.engine.effects import CombatModifiers
from kame.engine.skills import SkillDef


@pytest.fixture(autouse=True)
def no_variance(monkeypatch):
    monkeypatch.setattr(combat, "DAMAGE_VARIANCE", 0.0)


def mk(**kw):
    base = dict(name="x", max_hp=10_000, power=10.0, damage_type="physical", defense=0.0, resistance=0.0)
    base.update(kw)
    return Combatant(**base)


def S(skill_id="s", **kw):
    base = dict(id=skill_id, name=skill_id, description="", class_id="guerrero", ultimate=False,
                cooldown=100, unlock_level=1)
    base.update(kw)
    return SkillDef(**base)


def run(player, enemy, rounds):
    return fight(player, enemy, random.Random(1), max_rounds=rounds)


FOE = dict(max_hp=1000, power=1.0)


def test_basic_attack_is_used_when_no_skills():
    assert run(mk(), mk(**FOE), 3).enemy_hp_left == 970


def test_cooldown_is_respected():
    player = mk(skills=(S(multiplier=3.0, cooldown=3),))
    # rondas 1..4: 30 + 10 + 10 + 30
    assert run(player, mk(**FOE), 4).enemy_hp_left == 920


def test_skill_haste_reduces_cooldown_but_never_below_one():
    player = mk(skills=(S(multiplier=3.0, cooldown=3),), modifiers=CombatModifiers(skill_haste=2))
    assert run(player, mk(**FOE), 4).enemy_hp_left == 1000 - 4 * 30
    player = mk(skills=(S(multiplier=3.0, cooldown=3),), modifiers=CombatModifiers(skill_haste=99))
    assert run(player, mk(**FOE), 4).enemy_hp_left == 1000 - 4 * 30


def test_skill_priority_follows_loadout_order():
    first, second = S("first", multiplier=2.0), S("second", multiplier=5.0)
    assert run(mk(skills=(first, second)), mk(**FOE), 1).enemy_hp_left == 980
    assert run(mk(skills=(second, first)), mk(**FOE), 1).enemy_hp_left == 950
    # al estar la primera en cooldown, se usa la segunda
    assert run(mk(skills=(first, second)), mk(**FOE), 2).enemy_hp_left == 1000 - 20 - 50


def test_stun_makes_enemy_skip_a_turn():
    stunner = S(multiplier=1.0, stun_turns=1)
    enemy = mk(max_hp=1000, power=50.0)
    assert run(mk(skills=(stunner,)), enemy, 1).player_hp_left == 10_000
    assert run(mk(), enemy, 1).player_hp_left == 10_000 - 50


def test_guard_reduces_damage_taken_for_its_duration():
    guard = S(guard=0.5, guard_turns=2)
    enemy = mk(max_hp=1000, power=20.0)
    assert run(mk(skills=(guard,)), enemy, 3).player_hp_left == 10_000 - (10 + 10 + 20)


def test_guard_is_not_reapplied_while_active():
    guard = S("guard", guard=0.5, guard_turns=3, cooldown=1)
    attack = S("attack", multiplier=2.0, cooldown=1)
    # con guardia activa, la habilidad de utilidad no se gasta: usa el ataque
    result = run(mk(skills=(guard, attack)), mk(max_hp=1000, power=20.0), 2)
    assert result.enemy_hp_left == 1000 - 20  # ronda 1: guardia; ronda 2: ataque (guardia sigue activa)


def test_vulnerable_increases_damage_for_its_duration():
    vuln = S(vulnerable=0.3, vulnerable_turns=2)
    assert run(mk(skills=(vuln,)), mk(**FOE), 4).enemy_hp_left == 1000 - (13 + 13 + 10)


def test_weaken_reduces_enemy_damage():
    weaken = S(weaken=0.5, weaken_turns=2)
    enemy = mk(max_hp=1000, power=20.0)
    assert run(mk(skills=(weaken,)), enemy, 3).player_hp_left == 10_000 - (10 + 10 + 20)


def test_poison_ticks_for_its_duration_and_ignores_armor():
    poison = S(poison_pct=0.5, poison_turns=3)
    armored = mk(max_hp=1000, power=1.0, defense=1000.0)
    # veneno: 5 por turno x 3; ataques básicos (muy mitigados, mínimo 1) en rondas 2-4
    result = run(mk(skills=(poison,)), armored, 4)
    assert result.enemy_hp_left == 1000 - 15 - 3


def test_heal_skill_is_only_used_when_hurt():
    heal = S(heal_pct=0.5)
    foe = mk(max_hp=1000, power=40.0)
    hurt = run(mk(max_hp=100, skills=(heal,)), foe, 2)
    plain = run(mk(max_hp=100), foe, 2)
    assert hurt.player_hp_left > plain.player_hp_left
    assert hurt.enemy_hp_left == 990  # la ronda 2 se gastó en curar
    # a vida completa nunca se usa
    assert run(mk(skills=(heal,)), mk(**FOE), 1).enemy_hp_left == 990


def test_useless_status_skills_are_not_wasted_on_already_affected_enemies():
    stun = S("stun", stun_turns=3, cooldown=1)
    attack = S("attack", multiplier=2.0, cooldown=1)
    # el aturdimiento largo sigue activo: no se repite, se ataca
    result = run(mk(skills=(stun, attack)), mk(**FOE), 3)
    assert result.enemy_hp_left == 1000 - 20 - 20


@pytest.mark.parametrize(
    "mode,elite,expected",
    [("always", False, 900), ("elite", False, 990), ("elite", True, 900),
     ("never", False, 990), ("never", True, 990), ("low_hp", False, 990)],
)
def test_ultimate_modes(mode, elite, expected):
    ult = S("ult", ultimate=True, multiplier=10.0)
    player = mk(ultimate=ult, ultimate_mode=mode)
    assert run(player, mk(max_hp=1000, power=1.0, is_elite=elite), 1).enemy_hp_left == expected


def test_low_hp_ultimate_triggers_below_half_health():
    ult = S("ult", ultimate=True, multiplier=10.0)
    player = mk(max_hp=100, ultimate=ult, ultimate_mode="low_hp")
    result = run(player, mk(max_hp=1000, power=60.0), 2)
    assert result.enemy_hp_left == 1000 - 10 - 100


def test_ultimate_goes_before_skills():
    ult = S("ult", ultimate=True, multiplier=10.0)
    player = mk(skills=(S("s", multiplier=2.0),), ultimate=ult)
    assert run(player, mk(**FOE), 1).enemy_hp_left == 900


def test_always_crit_skill():
    player = mk(skills=(S(multiplier=1.0, always_crit=True),))
    assert run(player, mk(**FOE), 1).enemy_hp_left == 1000 - 15


def test_ignore_armor():
    armored = mk(max_hp=1000, power=1.0, defense=10.0)
    assert run(mk(), armored, 1).enemy_hp_left == 995
    assert run(mk(skills=(S(multiplier=1.0, ignore_armor=1.0),)), armored, 1).enemy_hp_left == 990


def test_magic_skill_uses_resistance_and_basic_type_follows_the_class():
    foe = mk(max_hp=1000, power=1.0, defense=0.0, resistance=10.0)
    mage = mk(damage_type="magic", skills=(S(multiplier=1.0),))
    warrior = mk(damage_type="physical", skills=(S(multiplier=1.0),))
    assert run(mage, foe, 1).enemy_hp_left == 995
    assert run(warrior, foe, 1).enemy_hp_left == 990


# ---------- modificadores de objetos ----------

def test_skill_power_only_boosts_skills():
    mods = CombatModifiers(skill_power=0.5)
    assert run(mk(skills=(S(multiplier=1.0),), modifiers=mods), mk(**FOE), 1).enemy_hp_left == 985
    assert run(mk(modifiers=mods), mk(**FOE), 1).enemy_hp_left == 990


def test_empower_boosts_only_that_skill():
    mods = CombatModifiers(empower={"target": 1.0})
    assert run(mk(skills=(S("target", multiplier=1.0),), modifiers=mods), mk(**FOE), 1).enemy_hp_left == 980
    assert run(mk(skills=(S("other", multiplier=1.0),), modifiers=mods), mk(**FOE), 1).enemy_hp_left == 990


def test_crit_damage_modifier():
    player = mk(crit_chance=100.0, crit_multiplier=1.5, modifiers=CombatModifiers(crit_damage=0.5))
    assert run(player, mk(**FOE), 1).enemy_hp_left == 1000 - 20


def test_armor_pen_modifier():
    armored = mk(max_hp=1000, power=1.0, defense=10.0)
    assert run(mk(modifiers=CombatModifiers(armor_pen=0.5)), armored, 1).enemy_hp_left == 1000 - 7


def test_elite_damage_only_against_elites():
    mods = CombatModifiers(elite_damage=0.5)
    assert run(mk(modifiers=mods), mk(max_hp=1000, power=1.0, is_elite=True), 1).enemy_hp_left == 985
    assert run(mk(modifiers=mods), mk(**FOE), 1).enemy_hp_left == 990


def test_lifesteal_heals_a_part_of_the_damage():
    foe = mk(max_hp=1000, power=40.0)
    with_steal = run(mk(max_hp=100, modifiers=CombatModifiers(lifesteal=0.5)), foe, 2)
    without = run(mk(max_hp=100), foe, 2)
    assert with_steal.player_hp_left == without.player_hp_left + 5


def test_thorns_damage_the_attacker():
    foe = mk(max_hp=1000, power=40.0)
    assert run(mk(modifiers=CombatModifiers(thorns=0.5)), foe, 1).enemy_hp_left == 1000 - 10 - 20


def test_second_wind_triggers_once():
    foe = mk(max_hp=10_000, power=75.0)
    saved = run(mk(max_hp=100, modifiers=CombatModifiers(second_wind=0.9)), foe, 10)
    unsaved = run(mk(max_hp=100), foe, 10)
    # sin segundo aliento cae en la ronda 2; con él, sobrevive una ronda más y solo una vez
    assert unsaved.rounds == 2 and saved.rounds == 3 and not saved.player_won


def test_combat_with_skills_is_deterministic(monkeypatch):
    monkeypatch.undo()  # con variación real
    player = mk(max_hp=300, power=25.0, crit_chance=30.0, skills=(S(multiplier=2.0, cooldown=3),))
    foe = mk(max_hp=400, power=20.0)
    assert fight(player, foe, random.Random(5)) == fight(player, foe, random.Random(5))
