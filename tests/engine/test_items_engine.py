import random
from collections import Counter

import pytest

from kame.engine.build import EquippedItem, PlayerBuild, build_stats, effective_attributes, build_modifiers
from kame.engine.effects import EffectDef, aggregate_modifiers, describe_effect
from kame.engine.items import (
    RARITIES,
    SLOTS,
    index_templates,
    roll_item,
    roll_stats,
    sell_value,
)
from kame.engine.models import ATTRIBUTES
from kame.engine.skills import resolve_loadout
from kame.engine.stats import derive_stats


def template(content, item_id="daga_mellada"):
    return content.item_templates[item_id]


def test_roll_stays_inside_variance_and_keeps_stat_keys(content):
    t = template(content, "hacha_del_osario")
    var = content.config.items.stat_variance
    for seed in range(50):
        rolled = roll_stats(t, random.Random(seed), var)
        assert set(rolled) == set(t.stats)
        for key, base in t.stats.items():
            assert base * (1 - var) - 1 <= rolled[key] <= base * (1 + var) + 1
            assert rolled[key] >= 1 if key not in ("crit_chance", "loot_bonus") else rolled[key] > 0


def test_roll_is_deterministic_and_varies_between_seeds(content):
    t = template(content, "coraza_del_guardian")
    assert roll_stats(t, random.Random(3), 0.1) == roll_stats(t, random.Random(3), 0.1)
    assert len({tuple(roll_stats(t, random.Random(s), 0.1).items()) for s in range(30)}) > 1


def test_attribute_rolls_are_integers(content):
    for t in content.item_templates.values():
        rolled = roll_stats(t, random.Random(1), 0.1)
        for key in (*ATTRIBUTES, "max_hp", "physical_power", "magic_power", "defense"):
            if key in rolled:
                assert isinstance(rolled[key], int)


def test_index_templates_respects_level_limit(content):
    grouped = index_templates(content.item_templates, 5)
    assert grouped["common"] and grouped["uncommon"]
    assert not grouped["rare"] and not grouped["epic"] and not grouped["legendary"]
    everything = index_templates(content.item_templates, 99)
    assert sum(len(v) for v in everything.values()) == len(content.item_templates)


def test_roll_item_falls_back_to_lower_rarity_when_none_is_available(content):
    grouped = index_templates(content.item_templates, 5)  # solo común y poco común
    weights = {"common": 0, "uncommon": 0, "rare": 0, "epic": 0, "legendary": 1}
    for seed in range(20):
        drop = roll_item(random.Random(seed), grouped, weights, 1.0, 0.1)
        assert drop is not None and content.item_templates[drop.template_id].rarity == "uncommon"


def test_roll_item_with_no_weights_or_no_templates_returns_none(content):
    grouped = index_templates(content.item_templates, 99)
    assert roll_item(random.Random(1), grouped, {r: 0 for r in RARITIES}, 1.0, 0.1) is None
    empty = {r: [] for r in RARITIES}
    assert roll_item(random.Random(1), empty, {"common": 1}, 1.0, 0.1) is None


def test_rarity_distribution_follows_weights_and_quality(content):
    grouped = index_templates(content.item_templates, 99)
    rng = random.Random(11)
    normal = Counter(
        content.item_templates[roll_item(rng, grouped, content.config.items.normal_weights, 1.0, 0.1).template_id].rarity
        for _ in range(6000)
    )
    assert normal["common"] > normal["uncommon"] > normal["rare"] > normal["epic"]
    assert normal["legendary"] == 0  # los enemigos normales no sueltan legendarios
    elite = Counter(
        content.item_templates[roll_item(rng, grouped, content.config.items.elite_weights, 1.0, 0.1).template_id].rarity
        for _ in range(6000)
    )
    assert elite["rare"] > normal["rare"] and elite["legendary"] > 0
    boosted = Counter(
        content.item_templates[roll_item(rng, grouped, content.config.items.normal_weights, 2.0, 0.1).template_id].rarity
        for _ in range(6000)
    )
    assert boosted["epic"] > normal["epic"]


def test_sell_values_increase_with_rarity(content):
    values = [content.config.items.sell_values[r] for r in RARITIES]
    assert values == sorted(values) and len(set(values)) == len(values)
    assert sell_value(template(content), content.config.items) == values[0]


# ---------- builds ----------

def make_build(content, class_id="guerrero", level=5, items=()):
    skills, ult = resolve_loadout(content.skills, class_id, level, ())
    cd = content.classes[class_id]
    return PlayerBuild("x", cd, level, dict(cd.base_attributes), tuple(items), skills, ult)


def test_equipment_adds_attributes_and_flat_stats(content):
    t = template(content, "hacha_del_osario")
    bare = make_build(content)
    geared = make_build(content, items=[EquippedItem(t, dict(t.stats))])
    assert build_stats(geared).physical_power > build_stats(bare).physical_power
    assert build_stats(geared).max_hp > build_stats(bare).max_hp
    assert effective_attributes(geared)["fuerza"] == bare.attributes["fuerza"] + t.stats.get("fuerza", 0)


def test_every_item_stat_changes_something(content):
    for key in ("max_hp", "physical_power", "magic_power", "defense", "crit_chance", "loot_bonus"):
        attrs = {a: 5 for a in ATTRIBUTES}
        assert derive_stats(1, attrs, {key: 10}) != derive_stats(1, attrs)


def test_item_effects_become_combat_modifiers(content):
    t = template(content, "colmillo_del_verdugo")
    mods = build_modifiers(make_build(content, level=12, items=[EquippedItem(t, dict(t.stats))]))
    assert mods.crit_damage == pytest.approx(0.35) and mods.lifesteal == pytest.approx(0.06)


def test_resolve_loadout_defaults_and_validation(content):
    s, u = resolve_loadout(content.skills, "mago", 1, ())
    assert [x.id for x in s] == ["bola_de_sombra", "escarcha_cortante"] and u is None
    s, u = resolve_loadout(content.skills, "mago", 8, ("maleficio", "bola_de_sombra"))
    assert [x.id for x in s] == ["maleficio", "bola_de_sombra"] and u.id == "tormenta_del_abismo"
    # elecciones inválidas: otra clase, bloqueada, repetida
    s, _ = resolve_loadout(content.skills, "mago", 1, ("golpe_aplastante", "fuego_maldito"))
    assert [x.id for x in s] == ["bola_de_sombra", "escarcha_cortante"]
    s, _ = resolve_loadout(content.skills, "mago", 8, ("bola_de_sombra", "bola_de_sombra"))
    assert len({x.id for x in s}) == 2


# ---------- efectos ----------

def test_aggregate_modifiers_sums_and_caps():
    mods = aggregate_modifiers([
        EffectDef("crit_damage", 0.2), EffectDef("crit_damage", 0.3),
        EffectDef("armor_pen", 0.5), EffectDef("armor_pen", 0.5),
        EffectDef("lifesteal", 0.9), EffectDef("skill_haste", 1),
        EffectDef("empower", 0.4, "a"), EffectDef("empower", 0.1, "a"), EffectDef("empower", 0.2, "b"),
    ])
    assert mods.crit_damage == pytest.approx(0.5)
    assert mods.armor_pen == 0.6 and mods.lifesteal == 0.3  # límites
    assert mods.skill_haste == 1
    assert mods.empower == {"a": pytest.approx(0.5), "b": 0.2}


def test_every_effect_type_has_a_description():
    from kame.engine.effects import EFFECT_TYPES

    for t in EFFECT_TYPES:
        text = describe_effect(EffectDef(t, 0.25 if t != "skill_haste" else 1, "x" if t == "empower" else None),
                               {"x": "Mi habilidad"})
        assert text and t not in text


# ---------- contenido real ----------

def test_item_catalog_is_complete_and_coherent(content):
    templates = list(content.item_templates.values())
    assert len(templates) < 100  # catálogo reducido a propósito
    for slot in SLOTS:
        in_slot = [t for t in templates if t.slot == slot]
        rarities = {t.rarity for t in in_slot}
        assert rarities == set(RARITIES), slot
        commons = [t for t in in_slot if t.rarity == "common"]
        assert {t.flavor for t in commons} == {"bruto", "arcano", "sigilo"}


def test_rare_or_better_items_have_effects_and_low_rarities_do_not(content):
    for t in content.item_templates.values():
        if RARITIES.index(t.rarity) >= RARITIES.index("rare"):
            assert t.effects, t.id
        else:
            assert not t.effects, t.id


def test_min_level_grows_with_rarity(content):
    by_rarity = {r: {t.min_level for t in content.item_templates.values() if t.rarity == r} for r in RARITIES}
    levels = [min(by_rarity[r]) for r in RARITIES]
    assert levels == sorted(levels) and all(len(v) == 1 for v in by_rarity.values())


def test_item_power_grows_with_rarity(content):
    conv = {"max_hp": 8, "physical_power": 1.6, "magic_power": 1.6, "defense": 0.9, "crit_chance": 0.8,
            "loot_bonus": 1.5}

    def budget(t):
        return sum(v / conv.get(k, 1) for k, v in t.stats.items())

    averages = [
        sum(budget(t) for t in content.item_templates.values() if t.rarity == r)
        / sum(1 for t in content.item_templates.values() if t.rarity == r)
        for r in RARITIES
    ]
    assert averages == sorted(averages) and len(set(round(a, 1) for a in averages)) == len(averages)


def test_empower_items_point_to_real_skills_of_a_class(content):
    for t in content.item_templates.values():
        for e in t.effects:
            if e.type == "empower":
                assert e.skill in content.skills and not content.skills[e.skill].ultimate


def test_every_class_has_a_full_kit(content):
    for class_id in content.classes:
        normal = [s for s in content.skills.values() if s.class_id == class_id and not s.ultimate]
        ults = [s for s in content.skills.values() if s.class_id == class_id and s.ultimate]
        assert len(normal) >= 3 and len(ults) == 1
        assert sum(1 for s in normal if s.unlock_level == 1) >= 2
