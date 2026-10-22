import pytest

from kame.content import ContentError, load_content
from kame.engine.company import GOLD, UpgradeDef, UpgradeLevel, bonuses_for, missing_resources
from tests.test_content import ROOT_CONTENT, _edit


def upgrades():
    return {"a": UpgradeDef("a", "A", "", (
        UpgradeLevel(0.03, 0.02, {"gold": 10}), UpgradeLevel(0.06, 0.05, {"gold": 20})))}


def test_bonuses_use_the_level_bonus_not_a_sum():
    assert bonuses_for(upgrades(), {}) == (0.0, 0.0)
    assert bonuses_for(upgrades(), {"a": 1}) == pytest.approx((0.03, 0.02))
    assert bonuses_for(upgrades(), {"a": 2}) == pytest.approx((0.06, 0.05))
    assert bonuses_for(upgrades(), {"a": 9}) == pytest.approx((0.06, 0.05))   # nivel por encima: tope
    assert bonuses_for(upgrades(), {"desconocida": 3}) == (0.0, 0.0)


def test_missing_resources():
    assert missing_resources({"gold": 10, "x": 2}, {"gold": 10, "x": 5}) == {}
    assert missing_resources({"gold": 10, "x": 2}, {"gold": 4}) == {"gold": 6, "x": 2}


def test_real_company_content(content):
    armeria = content.company_upgrades["armeria"]
    assert armeria.max_level == 3
    levels = list(armeria.levels)
    assert [l.xp_bonus for l in levels] == sorted(l.xp_bonus for l in levels)
    for level in levels:
        for resource in level.cost:
            assert resource == GOLD or resource in content.materials
    # los niveles altos exigen un material que solo da la mazmorra (cooperación)
    assert "sello_del_sepulcro" in levels[1].cost and "sello_del_sepulcro" in levels[2].cost
    dropped = {m for e in content.enemies.values() for d in e.drops for m in [d.material_id]}
    assert "sello_del_sepulcro" not in dropped
    in_dungeon = {m for d in content.dungeons.values() for s in d.stages for m in s.shared_materials}
    assert "sello_del_sepulcro" in in_dungeon


@pytest.mark.parametrize(
    "old,new",
    [("hueso_astillado = 20", "polvo_raro = 20"), ("cost = { gold = 600", "cost = { gold = 0"),
     ("xp_bonus = 0.03", "xp_bonus = -1")],
)
def test_invalid_company_content_is_rejected(tmp_path, old, new):
    with pytest.raises(ContentError):
        load_content(_edit(tmp_path, "company.toml", old, new))
