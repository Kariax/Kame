"""Pruebas de equilibrio: si alguien cambia números del contenido y rompe el equilibrio entre
clases, entre perfiles de riesgo o el valor del equipo, estas pruebas lo avisan.

Usan builds 'típicas': puntos repartidos (mitad daño, mitad vitalidad), habilidades por defecto y
equipo de rareza media para el nivel."""
import random
from statistics import mean

import pytest

from kame.engine.build import build_combatant, build_stats
from kame.engine.expeditions import encounters_available, resolve_expedition
from kame.engine.simulation import standard_build, win_rate_build


def rate(content, exp_id, class_id, level, gear=True, fights=500):
    exp = content.expeditions[exp_id]
    build = standard_build(content, class_id, level, gear)
    return win_rate_build(build, exp, content.enemies, content.config.expeditions, fights=fights)


def mean_xp(content, exp_id, class_id, level, runs=100):
    cfg = content.config
    exp = content.expeditions[exp_id]
    build = standard_build(content, class_id, level, True)
    player = build_combatant(build)
    bonus = build_stats(build).loot_bonus
    full = encounters_available(cfg.expeditions.max_accumulation_hours * 3600, exp, cfg.expeditions)
    rng = random.Random(5)
    return mean(
        resolve_expedition(
            expedition=exp, enemies=content.enemies, player=player, player_level=level,
            loot_bonus=bonus, encounters=full, seed=rng.getrandbits(62), rules=cfg.expeditions,
            templates=content.item_templates, item_rules=cfg.items,
        ).xp
        for _ in range(runs)
    )


MINIMUMS = {"cripta": 0.99, "catacumbas": 0.95, "abismo": 0.90, "paramo": 0.95}


@pytest.mark.parametrize("exp_id", list(MINIMUMS))
def test_recommended_level_is_survivable_with_typical_gear(content, exp_id):
    level = content.expeditions[exp_id].recommended_level
    for class_id in content.classes:
        assert rate(content, exp_id, class_id, level) >= MINIMUMS[exp_id], (exp_id, class_id)


@pytest.mark.parametrize("exp_id", list(MINIMUMS))
def test_classes_are_close_to_each_other_at_recommended_level(content, exp_id):
    level = content.expeditions[exp_id].recommended_level
    rates = [rate(content, exp_id, c, level) for c in content.classes]
    assert max(rates) - min(rates) <= 0.10


def test_the_entry_expedition_is_safe_even_without_gear_or_spent_points(content):
    from kame.engine.build import PlayerBuild
    from kame.engine.skills import resolve_loadout

    exp = content.expeditions["cripta"]
    for class_id, class_def in content.classes.items():
        skills, ultimate = resolve_loadout(content.skills, class_id, 1, ())
        fresh = PlayerBuild("n", class_def, 1, dict(class_def.base_attributes), (), skills, ultimate)
        wr = win_rate_build(fresh, exp, content.enemies, content.config.expeditions, fights=600)
        assert wr >= 0.99, class_id


@pytest.mark.parametrize("exp_id", ["catacumbas", "abismo", "paramo"])
def test_gear_matters_at_recommended_level(content, exp_id):
    level = content.expeditions[exp_id].recommended_level
    # Probabilidad de completar las 32 batallas de una expedición sin retirarse
    naked = mean(rate(content, exp_id, c, level, gear=False) ** 32 for c in content.classes)
    geared = mean(rate(content, exp_id, c, level, gear=True) ** 32 for c in content.classes)
    assert geared > naked + 0.15


def test_better_rarity_gives_better_results(content):
    level = 10
    rates = {
        cap: mean(rate(content, "paramo", c, level, gear=cap) for c in content.classes)
        for cap in ("common", "uncommon", "rare")
    }
    assert rates["common"] < rates["uncommon"] <= rates["rare"] + 0.005


def test_risk_profiles_are_ordered_at_the_same_level(content):
    cripta = mean(rate(content, "cripta", c, 4) for c in content.classes)
    cata = mean(rate(content, "catacumbas", c, 4) for c in content.classes)
    abismo = mean(rate(content, "abismo", c, 4) for c in content.classes)
    assert cripta >= cata > abismo


def test_overleveled_characters_beat_every_expedition(content):
    for exp in content.expeditions.values():
        for class_id in content.classes:
            assert rate(content, exp.id, class_id, exp.recommended_level + 6) >= 0.97


def test_underleveled_characters_struggle(content):
    assert mean(rate(content, "abismo", c, 2) for c in content.classes) < 0.8
    assert mean(rate(content, "paramo", c, 6) for c in content.classes) < 0.8


def test_risky_pays_more_only_when_the_character_is_strong(content):
    classes = list(content.classes)
    at_rec = {e: mean(mean_xp(content, e, c, 4) for c in classes) for e in ("catacumbas", "abismo")}
    strong = {e: mean(mean_xp(content, e, c, 10) for c in classes) for e in ("catacumbas", "abismo")}
    assert at_rec["catacumbas"] > at_rec["abismo"]   # al nivel recomendado, lo seguro rinde más
    assert strong["abismo"] > strong["catacumbas"]    # con ventaja, lo arriesgado rinde más


def test_yield_is_similar_between_classes(content):
    yields = [mean_xp(content, "catacumbas", c, 4) for c in content.classes]
    assert max(yields) / min(yields) <= 1.5


def test_overleveling_a_safe_expedition_reduces_xp(content):
    low = mean_xp(content, "cripta", "guerrero", 1, runs=20)
    high = mean_xp(content, "cripta", "guerrero", 7, runs=20)
    assert high < low * 0.6


def test_every_expedition_has_content_for_progression(content):
    levels = sorted(e.recommended_level for e in content.expeditions.values())
    assert levels[0] == 1 and all(b - a <= 6 for a, b in zip(levels, levels[1:]))


def test_ultimate_mode_never_is_weaker_than_always(content):
    exp = content.expeditions["catacumbas"]
    cfg = content.config.expeditions
    for class_id in content.classes:
        always = win_rate_build(standard_build(content, class_id, 10, True, "always"), exp,
                                content.enemies, cfg, fights=400)
        never = win_rate_build(standard_build(content, class_id, 10, True, "never"), exp,
                               content.enemies, cfg, fights=400)
        assert always >= never
