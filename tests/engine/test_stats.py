import pytest

from kame.engine.models import ATTRIBUTES
from kame.engine.stats import CRIT_CAP, derive_stats


def base():
    return {a: 5 for a in ATTRIBUTES}


@pytest.mark.parametrize("attr", ATTRIBUTES)
def test_every_attribute_changes_some_stat(attr):
    """Ningún atributo debe ser inútil."""
    boosted = base()
    boosted[attr] += 10
    assert derive_stats(1, boosted) != derive_stats(1, base())


def test_level_raises_stats():
    assert derive_stats(10, base()).max_hp > derive_stats(1, base()).max_hp


def test_crit_chance_is_capped():
    huge = {a: 10_000 for a in ATTRIBUTES}
    assert derive_stats(1, huge).crit_chance == CRIT_CAP


def test_class_specialties(content):
    def stats(class_id):
        c = content.classes[class_id]
        return derive_stats(1, c.base_attributes)

    assert stats("guerrero").max_hp > stats("mago").max_hp
    assert stats("mago").magic_power > stats("guerrero").magic_power
    assert stats("picaro").crit_chance > stats("guerrero").crit_chance
