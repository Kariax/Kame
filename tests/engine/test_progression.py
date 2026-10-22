import pytest

from kame.engine.progression import ProgressionRules, apply_xp, xp_to_next_level

RULES = ProgressionRules(max_level=5, xp_base=100, xp_exponent=1.0, points_per_level=3)
# Con estas reglas: nivel 1->2 = 100 XP, 2->3 = 200, 3->4 = 300, 4->5 = 400


def test_xp_to_next_level():
    assert xp_to_next_level(1, RULES) == 100
    assert xp_to_next_level(3, RULES) == 300
    assert xp_to_next_level(5, RULES) == 0  # nivel máximo


def test_no_level_up_when_xp_is_not_enough():
    r = apply_xp(1, 0, 99, RULES)
    assert (r.level, r.xp, r.levels_gained, r.points_gained) == (1, 99, 0, 0)


def test_exact_level_up():
    r = apply_xp(1, 0, 100, RULES)
    assert (r.level, r.xp, r.levels_gained, r.points_gained) == (2, 0, 1, 3)


def test_leftover_xp_is_kept():
    r = apply_xp(1, 50, 80, RULES)  # 130 -> sube y sobran 30
    assert (r.level, r.xp) == (2, 30)


def test_multiple_levels_at_once():
    r = apply_xp(1, 0, 650, RULES)  # 100 + 200 + 300 = 600 -> nivel 4, sobran 50
    assert (r.level, r.xp, r.levels_gained, r.points_gained) == (4, 50, 3, 9)


def test_max_level_is_capped_and_xp_not_accumulated():
    r = apply_xp(4, 0, 10_000, RULES)
    assert (r.level, r.xp, r.levels_gained) == (5, 0, 1)
    r2 = apply_xp(5, 0, 500, RULES)
    assert (r2.level, r2.xp, r2.levels_gained, r2.points_gained) == (5, 0, 0, 0)


def test_zero_xp_changes_nothing():
    r = apply_xp(2, 10, 0, RULES)
    assert (r.level, r.xp, r.levels_gained) == (2, 10, 0)


@pytest.mark.parametrize("level,xp,amount", [(1, 0, -1), (0, 0, 5), (6, 0, 5), (1, -1, 5)])
def test_invalid_input_raises(level, xp, amount):
    with pytest.raises(ValueError):
        apply_xp(level, xp, amount, RULES)


def test_real_rules_are_monotonic(content):
    rules = content.config.progression
    needs = [xp_to_next_level(lv, rules) for lv in range(1, rules.max_level)]
    assert all(n > 0 for n in needs)
    assert needs == sorted(needs)
