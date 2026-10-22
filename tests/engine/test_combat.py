import random

import pytest

from kame.engine.combat import Combatant, fight, player_combatant
from kame.engine.stats import derive_stats


def mk(name="x", hp=100, power=20.0, dtype="physical", defense=5.0, resistance=5.0, crit=0.0):
    return Combatant(name, hp, power, dtype, defense, resistance, crit_chance=crit)


def test_fight_is_deterministic_with_same_seed():
    a, b = mk("jugador", power=25), mk("enemigo", power=18)
    r1 = fight(a, b, random.Random(42))
    r2 = fight(a, b, random.Random(42))
    assert r1 == r2


def test_much_stronger_player_wins_and_much_weaker_loses():
    strong = mk(hp=500, power=200)
    weak = mk(hp=20, power=1)
    assert fight(strong, weak, random.Random(1)).player_won
    assert not fight(weak, strong, random.Random(1)).player_won


def test_defense_reduces_physical_damage_and_resistance_reduces_magic():
    rng_seed = 5
    tank = mk(hp=10_000, power=1, defense=100, resistance=0)
    physical = mk(power=50, dtype="physical")
    magical = mk(power=50, dtype="magic")
    r_phys = fight(physical, tank, random.Random(rng_seed), max_rounds=3)
    r_magic = fight(magical, tank, random.Random(rng_seed), max_rounds=3)
    assert r_phys.enemy_hp_left > r_magic.enemy_hp_left  # el físico se mitiga más


def test_minimum_damage_is_one_so_fights_always_progress():
    wall = mk(hp=5, power=1, defense=10_000, resistance=10_000)
    attacker = mk(hp=1000, power=1)
    result = fight(attacker, wall, random.Random(3), max_rounds=100)
    assert result.player_won  # 1 de daño por ronda acaba con 5 de vida


def test_stalemate_counts_as_defeat():
    tank = mk(hp=100_000, power=1, defense=0)
    result = fight(tank, tank, random.Random(1), max_rounds=5)
    assert result.player_won is False and result.rounds == 5


def test_crits_increase_average_damage():
    base = mk(hp=100_000, power=30, crit=0)
    crit = mk(hp=100_000, power=30, crit=100)
    dummy = mk(hp=100_000, power=0.1)
    no_crit = fight(base, dummy, random.Random(9), max_rounds=20).enemy_hp_left
    with_crit = fight(crit, dummy, random.Random(9), max_rounds=20).enemy_hp_left
    assert with_crit < no_crit


def test_player_combatant_uses_class_attack_type(content):
    attrs = content.classes["mago"].base_attributes
    mage = player_combatant("m", 1, attrs, content.classes["mago"])
    stats = derive_stats(1, attrs)
    assert mage.damage_type == "magic"
    assert mage.power == pytest.approx(stats.magic_power * content.classes["mago"].basic_attack.power_multiplier)
    warrior = player_combatant("g", 1, content.classes["guerrero"].base_attributes, content.classes["guerrero"])
    assert warrior.damage_type == "physical"
