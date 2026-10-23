import pytest

from kame.engine.combat import Combatant
from kame.engine.expeditions import (
    DropDef,
    EnemyDef,
    ExpeditionDef,
    ExpeditionRules,
    encounters_available,
    resolve_expedition,
    seconds_until_next_encounter,
    xp_factor,
)

RULES = ExpeditionRules(max_accumulation_hours=8, over_level_penalty=0.1, min_xp_factor=0.2, max_rounds=30)
EASY = EnemyDef("easy", "Fácil", hp=10, power=1, damage_type="physical", defense=0, resistance=0,
                xp=10, gold=10, drops=(DropDef("hueso", 1.0),))
DEADLY = EnemyDef("deadly", "Letal", hp=100_000, power=10_000, damage_type="physical",
                  defense=0, resistance=0, xp=500, gold=500)
HERO = Combatant("h", 500, 100, "physical", 10, 10)


def expedition(pool, eph=4.0, rec=1):
    return ExpeditionDef("e", "E", "d", "seguro", 1, rec, eph, tuple(pool))


def run(exp, enemies, n, seed=1, level=1, bonus=0.0):
    return resolve_expedition(expedition=exp, enemies=enemies, player=HERO, player_level=level,
                              loot_bonus=bonus, encounters=n, seed=seed, rules=RULES)


def test_encounters_follow_elapsed_time():
    exp = expedition([("easy", 1)])
    assert encounters_available(0, exp, RULES) == 0
    assert encounters_available(899, exp, RULES) == 0   # 4/h = uno cada 15 min
    assert encounters_available(900, exp, RULES) == 1
    assert encounters_available(3600, exp, RULES) == 4


def test_accumulation_is_capped_at_max_hours():
    exp = expedition([("easy", 1)])
    assert encounters_available(8 * 3600, exp, RULES) == 32
    assert encounters_available(100 * 3600, exp, RULES) == 32


def test_negative_elapsed_time_is_treated_as_zero():
    assert encounters_available(-500, expedition([("easy", 1)]), RULES) == 0


def test_seconds_until_next_encounter():
    exp = expedition([("easy", 1)])
    assert 0 < seconds_until_next_encounter(0, exp, RULES) <= 900
    assert seconds_until_next_encounter(8 * 3600, exp, RULES) is None


def test_xp_factor_penalizes_overleveled_characters():
    assert xp_factor(1, 1, RULES) == 1.0
    assert xp_factor(3, 5, RULES) == 1.0          # por debajo: sin penalización
    assert xp_factor(6, 5, RULES) == pytest.approx(0.9)
    assert xp_factor(100, 5, RULES) == RULES.min_xp_factor


def test_same_seed_gives_same_outcome():
    exp = expedition([("easy", 1)])
    assert run(exp, {"easy": EASY}, 20, seed=7) == run(exp, {"easy": EASY}, 20, seed=7)


def test_claiming_later_cannot_change_earlier_results():
    """Con la misma semilla, los primeros N encuentros salen igual reclames cuando reclames."""
    exp = expedition([("easy", 3), ("deadly", 1)])
    enemies = {"easy": EASY, "deadly": DEADLY}
    full = run(exp, enemies, 40, seed=11)
    for n in range(1, 41):
        partial = run(exp, enemies, n, seed=11)
        if n <= full.encounters:
            # un resultado parcial nunca supera al completo
            assert partial.victories <= full.victories
            # las derrotas parciales nunca superan a las del completo
            for enemy_id, count in partial.defeated_by.items():
                assert count <= full.defeated_by.get(enemy_id, 0)
        else:
            assert partial == full  # ya se alcanzó el tope: reclamar más tarde no cambia nada


def test_defeat_does_not_end_the_expedition_but_keeps_earned_rewards():
    """Cuando el personaje cae, el enemigo huye y la expedición continúa."""
    mixed = expedition([("easy", 1), ("deadly", 1)])
    outcome = run(mixed, {"easy": EASY, "deadly": DEADLY}, 32, seed=3)
    assert outcome.retreated
    assert outcome.encounters == 32
    assert outcome.victories + sum(outcome.defeated_by.values()) == outcome.encounters
    assert outcome.xp == 10 * outcome.victories
    assert outcome.defeated_by == {"deadly": 23}


def test_rewards_of_a_clean_run():
    outcome = run(expedition([("easy", 1)]), {"easy": EASY}, 10)
    assert (outcome.encounters, outcome.victories, outcome.retreated) == (10, 10, False)
    assert outcome.xp == 100
    assert 80 <= outcome.gold <= 120
    assert outcome.materials == {"hueso": 10}
    assert outcome.kills == {"easy": 10}


def test_overleveled_character_gets_less_xp_but_same_gold():
    exp = expedition([("easy", 1)], rec=1)
    normal = run(exp, {"easy": EASY}, 10, level=1)
    over = run(exp, {"easy": EASY}, 10, level=6)
    assert over.xp == int(round(100 * 0.5))
    assert abs(over.gold - normal.gold) <= 1


def test_loot_bonus_increases_gold_and_drops():
    chancy = EnemyDef("c", "C", 10, 1, "physical", 0, 0, 1, 10, (DropDef("hueso", 0.25),))
    exp = expedition([("c", 1)])
    no_bonus = run(exp, {"c": chancy}, 32, seed=2, bonus=0)
    bonus = run(exp, {"c": chancy}, 32, seed=2, bonus=100)
    assert bonus.gold > no_bonus.gold
    assert sum(bonus.materials.values()) >= sum(no_bonus.materials.values())


def test_zero_encounters_gives_empty_outcome():
    outcome = run(expedition([("easy", 1)]), {"easy": EASY}, 0)
    assert (outcome.encounters, outcome.xp, outcome.gold, outcome.retreated) == (0, 0, 0, False)
