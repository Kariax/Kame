import pytest

from kame.engine.items import RARITIES, SLOTS
from kame.engine.shop import (
    SECONDS_PER_DAY,
    bag_upgrade_price,
    daily_offers,
    day_of,
    next_refresh,
    parse_offer_key,
    refundable_points,
    respec_cost,
)


def offers(content, day):
    return daily_offers(day, content.item_templates, content.shop)


def test_the_stock_is_deterministic_and_the_same_for_everyone(content):
    assert offers(content, 20_000) == offers(content, 20_000)


def test_stock_changes_from_day_to_day(content):
    days = [tuple(o.template_id for o in offers(content, d)) for d in range(20_000, 20_015)]
    assert len(set(days)) > 10


def test_shape_of_the_daily_stock(content):
    stock = offers(content, 20_000)
    per_slot = content.shop.offers_per_slot
    assert len(stock) == len(SLOTS) * per_slot
    assert len({o.key for o in stock}) == len(stock)
    for slot in SLOTS:
        in_slot = [o for o in stock if o.slot == slot]
        assert len(in_slot) == per_slot and len({o.template_id for o in in_slot}) == per_slot
    for o in stock:
        t = content.item_templates[o.template_id]
        assert t.slot == o.slot and t.rarity in content.shop.rarities
        assert o.price == content.shop.prices[t.rarity] and o.day == 20_000
        assert parse_offer_key(o.key) == (20_000, o.slot, int(o.key.split(":")[2]))


def test_only_basic_equipment_is_ever_sold_and_everything_basic_shows_up(content):
    seen = set()
    for day in range(20_000, 20_120):
        seen |= {o.template_id for o in offers(content, day)}
    rarities = {content.item_templates[t].rarity for t in seen}
    assert rarities == set(content.shop.rarities)
    for rarity in ("rare", "epic", "legendary"):
        assert rarity not in rarities
    basic = {t.id for t in content.item_templates.values() if t.rarity in content.shop.rarities}
    assert seen == basic  # con el tiempo se ve todo el catálogo básico (todas las builds encuentran su equipo)


def test_buying_is_never_cheaper_than_selling(content):
    for rarity in content.shop.rarities:
        assert content.shop.prices[rarity] > content.config.items.sell_values[rarity]


def test_prices_follow_rarity(content):
    prices = [content.shop.prices[r] for r in RARITIES if r in content.shop.prices]
    assert prices == sorted(prices) and len(set(prices)) == len(prices)


@pytest.mark.parametrize("key", ["", "abc", "1:2", "a:b:c", "20000:weapon", "20000:weapon:x", "-5:weapon:0",
                                 "20000:weapon:-1", "20000:weapon:0:extra", None, 42])
def test_garbage_offer_keys_do_not_parse(key):
    assert parse_offer_key(key) is None


def test_days_and_refresh():
    noon = 20_000 * SECONDS_PER_DAY + 43_200
    assert day_of(noon) == 20_000 and next_refresh(noon) == 20_001 * SECONDS_PER_DAY
    assert day_of(20_001 * SECONDS_PER_DAY) == 20_001 and day_of(20_001 * SECONDS_PER_DAY - 1) == 20_000


def test_respec_cost_first_ones_free_then_scales_with_level(content):
    rules = content.shop
    assert respec_cost(10, 0, rules) == 0
    cost = respec_cost(10, rules.respec_free, rules)
    assert cost == rules.respec_base + rules.respec_per_level * 10
    assert respec_cost(20, rules.respec_free, rules) > cost
    assert respec_cost(0, rules.respec_free, rules) == rules.respec_base + rules.respec_per_level


def test_refundable_points_ignore_anything_below_the_class_base():
    base = {"fuerza": 8, "inteligencia": 3, "vitalidad": 8, "destreza": 4, "suerte": 3}
    spent = {"fuerza": 12, "inteligencia": 3, "vitalidad": 10, "destreza": 4, "suerte": 3}
    assert refundable_points(spent, base) == 6
    assert refundable_points(base, base) == 0


def test_bag_prices_are_increasing_and_end(content):
    rules = content.shop
    prices = [bag_upgrade_price(i, rules) for i in range(len(rules.bag_prices))]
    assert prices == sorted(prices) and bag_upgrade_price(len(rules.bag_prices), rules) is None
