import dataclasses
import threading

import pytest

from kame.db.database import connect, transaction
from kame.engine.items import ItemDrop
from kame.engine.models import ATTRIBUTES
from kame.engine.shop import SECONDS_PER_DAY, daily_offers
from kame.engine.stats import derive_stats
from kame.services import characters, items, shop
from kame.services.errors import (
    BagMaxed,
    InventoryFull,
    ItemLevelTooLow,
    NoCharacter,
    NotEnoughGold,
    NothingToRespec,
    OfferAlreadyBought,
    OfferNotFound,
)

DAY = 20_000
NOW = DAY * SECONDS_PER_DAY + 3_600


def make(conn, content, discord_id=1, name="Aldric", class_id="guerrero", gold=0, level=1):
    c = characters.create_character(conn, content, discord_id, name, class_id)
    with transaction(conn):
        conn.execute("UPDATE characters SET gold = ?, level = ? WHERE id = ?", (gold, level, c.id))
    return characters.get_character(conn, discord_id)


def stock(content, day=DAY):
    return daily_offers(day, content.item_templates, content.shop)


def cheapest_usable(content, level=1):
    return next(o for o in stock(content)
                if content.item_templates[o.template_id].min_level <= level)


def gold_of(conn, did=1):
    return characters.get_character(conn, did).gold


def fill_inventory(conn, content, did, count):
    c = characters.get_character(conn, did)
    with transaction(conn):
        for _ in range(count):
            added = items.plan_new_items(conn, content, c.id, (ItemDrop("daga_mellada", {"destreza": 1}),))
            items.insert_items_tx(conn, c.id, added.kept or added.overflow, "test")


# ---------- ver ----------

def test_shop_view(conn, content):
    make(conn, content, gold=250)
    view = shop.get_shop(conn, content, 1, NOW)
    assert view.gold == 250 and view.day == DAY and view.refresh_at == (DAY + 1) * SECONDS_PER_DAY
    assert len(view.offers) == 6 * content.shop.offers_per_slot
    assert not any(o.bought for o in view.offers)
    assert view.bag_level == 0 and view.bag_cap == content.config.items.inventory_cap and view.bag_used == 0
    assert view.bag_next_price == content.shop.bag_prices[0]
    assert view.refundable == 0 and view.respec_is_free
    with pytest.raises(NoCharacter):
        shop.get_shop(conn, content, 9, NOW)


# ---------- comprar equipo ----------

def test_buying_charges_the_price_and_delivers_the_base_item(conn, content):
    make(conn, content, gold=1000)
    offer = cheapest_usable(content)
    item, price = shop.buy_offer(conn, content, 1, offer.key, NOW)
    template = content.item_templates[offer.template_id]
    assert price == offer.price and gold_of(conn) == 1000 - offer.price
    assert item.stats == dict(template.stats)                       # estadísticas base, sin variación
    inventory = items.list_inventory(conn, content, 1)
    assert [i.id for i in inventory] == [item.id] and inventory[0].template.id == template.id
    row = conn.execute("SELECT source FROM item_instances").fetchone()
    assert row["source"] == "shop"
    assert next(o for o in shop.get_shop(conn, content, 1, NOW).offers if o.offer.key == offer.key).bought


def test_each_offer_can_be_bought_once_a_day_and_again_tomorrow(conn, content):
    make(conn, content, gold=10_000, level=12)
    offer = stock(content)[0]
    shop.buy_offer(conn, content, 1, offer.key, NOW)
    before = gold_of(conn)
    with pytest.raises(OfferAlreadyBought):
        shop.buy_offer(conn, content, 1, offer.key, NOW + 60)
    assert gold_of(conn) == before and len(items.list_inventory(conn, content, 1)) == 1
    tomorrow = NOW + SECONDS_PER_DAY
    with pytest.raises(OfferNotFound):                # la oferta de ayer ya no existe
        shop.buy_offer(conn, content, 1, offer.key, tomorrow)
    new_offer = stock(content, DAY + 1)[0]
    shop.buy_offer(conn, content, 1, new_offer.key, tomorrow)
    assert len(items.list_inventory(conn, content, 1)) == 2


@pytest.mark.parametrize("key", ["", "abc", "1:2", "20000:weapon:99", "20000:weapon:-1", "20000:cola:0",
                                 "19999:weapon:0", "20001:weapon:0", "'; DROP TABLE shop_purchases;--"])
def test_invalid_or_stale_offer_keys(conn, content, key):
    make(conn, content, gold=1000)
    with pytest.raises(OfferNotFound):
        shop.buy_offer(conn, content, 1, key, NOW)
    assert gold_of(conn) == 1000 and items.list_inventory(conn, content, 1) == []


def test_not_enough_gold(conn, content):
    make(conn, content, gold=10)
    offer = cheapest_usable(content)
    with pytest.raises(NotEnoughGold) as e:
        shop.buy_offer(conn, content, 1, offer.key, NOW)
    assert e.value.price == offer.price and e.value.have == 10 and str(offer.price - 10) in e.value.message
    assert gold_of(conn) == 10 and items.list_inventory(conn, content, 1) == []
    assert conn.execute("SELECT COUNT(*) FROM shop_purchases").fetchone()[0] == 0


def test_exact_gold_is_enough_and_leaves_zero(conn, content):
    offer = cheapest_usable(content)
    make(conn, content, gold=offer.price)
    shop.buy_offer(conn, content, 1, offer.key, NOW)
    assert gold_of(conn) == 0


def test_level_requirement_blocks_the_purchase_before_charging(conn, content):
    make(conn, content, gold=5_000, level=1)
    locked = next(o for o in stock(content) if content.item_templates[o.template_id].min_level > 1)
    with pytest.raises(ItemLevelTooLow):
        shop.buy_offer(conn, content, 1, locked.key, NOW)
    assert gold_of(conn) == 5_000
    view = shop.get_shop(conn, content, 1, NOW)
    assert not next(o for o in view.offers if o.offer.key == locked.key).level_ok


def test_a_full_inventory_rejects_the_purchase_and_never_sells_for_you(conn, content):
    make(conn, content, gold=1_000)
    fill_inventory(conn, content, 1, content.config.items.inventory_cap)
    offer = cheapest_usable(content)
    with pytest.raises(InventoryFull):
        shop.buy_offer(conn, content, 1, offer.key, NOW)
    assert gold_of(conn) == 1_000
    assert len(items.list_inventory(conn, content, 1)) == content.config.items.inventory_cap


def test_buying_and_selling_back_always_loses_gold(conn, content):
    make(conn, content, gold=20_000, level=12)
    for offer in stock(content):
        before = gold_of(conn)
        item, price = shop.buy_offer(conn, content, 1, offer.key, NOW)
        _, got = items.sell_item(conn, content, 1, item.id)
        assert gold_of(conn) < before and got < price


def test_players_are_independent_in_the_shop(conn, content):
    make(conn, content, 1, "Aldric", gold=500)
    make(conn, content, 2, "Brenna", "mago", gold=500)
    offer = cheapest_usable(content)
    shop.buy_offer(conn, content, 1, offer.key, NOW)
    shop.buy_offer(conn, content, 2, offer.key, NOW)       # la misma oferta, sin competir
    assert gold_of(conn, 1) == gold_of(conn, 2) == 500 - offer.price
    assert len(items.list_inventory(conn, content, 2)) == 1
    with pytest.raises(NoCharacter):
        shop.buy_offer(conn, content, 99, offer.key, NOW)


def test_purchases_are_logged(conn, content):
    c = make(conn, content, gold=500)
    shop.buy_offer(conn, content, 1, cheapest_usable(content).key, NOW)
    kinds = [r[0] for r in conn.execute("SELECT kind FROM activity_log WHERE character_id = ?", (c.id,))]
    assert "shop_purchase" in kinds


def test_double_click_on_the_same_offer_charges_once(db_path, content):
    setup = connect(db_path)
    make(setup, content, gold=1_000)
    offer = cheapest_usable(content)
    setup.close()
    results, barrier = [], threading.Barrier(4)

    def worker():
        c = connect(db_path)
        try:
            barrier.wait()
            shop.buy_offer(c, content, 1, offer.key, NOW)
            results.append("ok")
        except OfferAlreadyBought:
            results.append("repetida")
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("repetida") == 3
    check = connect(db_path)
    assert check.execute("SELECT gold FROM characters").fetchone()[0] == 1_000 - offer.price
    assert check.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0] == 1


def test_gold_never_goes_negative_with_simultaneous_purchases(db_path, content):
    setup = connect(db_path)
    make(setup, content, gold=0, level=12)
    wanted = [o for o in stock(content) if o.price == content.shop.prices["common"]][:3]
    cid = characters.get_character(setup, 1).id
    with transaction(setup):
        setup.execute("UPDATE characters SET gold = ? WHERE id = ?", (wanted[0].price + 5, cid))
    setup.close()
    results, barrier = [], threading.Barrier(len(wanted))

    def worker(offer):
        c = connect(db_path)
        try:
            barrier.wait()
            shop.buy_offer(c, content, 1, offer.key, NOW)
            results.append("ok")
        except NotEnoughGold:
            results.append("sin oro")
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(o,)) for o in wanted]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check = connect(db_path)
    gold = check.execute("SELECT gold FROM characters").fetchone()[0]
    assert results.count("ok") == 1 and gold == 5 and gold >= 0


# ---------- mochila ----------

def test_bag_upgrades_cost_more_each_time_and_add_slots(conn, content):
    rules = content.shop
    make(conn, content, gold=sum(rules.bag_prices))
    base = content.config.items.inventory_cap
    for level, price in enumerate(rules.bag_prices, start=1):
        got_level, cap, paid = shop.buy_bag_upgrade(conn, content, 1)
        assert (got_level, paid) == (level, price) and cap == base + level * rules.bag_slots
    assert gold_of(conn) == 0
    with pytest.raises(BagMaxed):
        shop.buy_bag_upgrade(conn, content, 1)
    assert shop.get_shop(conn, content, 1, NOW).bag_next_price is None


def test_bag_upgrade_needs_gold_and_changes_nothing_otherwise(conn, content):
    make(conn, content, gold=content.shop.bag_prices[0] - 1)
    with pytest.raises(NotEnoughGold):
        shop.buy_bag_upgrade(conn, content, 1)
    assert shop.get_shop(conn, content, 1, NOW).bag_level == 0
    assert gold_of(conn) == content.shop.bag_prices[0] - 1


def test_a_bigger_bag_really_changes_how_many_items_fit(conn, content):
    c = make(conn, content, gold=content.shop.bag_prices[0])
    base = content.config.items.inventory_cap
    fill_inventory(conn, content, 1, base)
    drop = (ItemDrop("daga_mellada", {"destreza": 1}),)
    assert len(items.plan_new_items(conn, content, c.id, drop).overflow) == 1       # no cabe: se vende solo
    shop.buy_bag_upgrade(conn, content, 1)
    assert len(items.plan_new_items(conn, content, c.id, drop).kept) == 1           # ahora sí
    assert items.inventory_cap(conn, content, c.id) == base + content.shop.bag_slots
    # y la bolsa de otro jugador no cambia
    other = make(conn, content, 2, "Brenna", "mago")
    assert items.inventory_cap(conn, content, other.id) == base


def test_with_a_bigger_bag_a_purchase_fits_where_it_did_not(conn, content):
    make(conn, content, gold=content.shop.bag_prices[0] + 500)
    fill_inventory(conn, content, 1, content.config.items.inventory_cap)
    offer = cheapest_usable(content)
    with pytest.raises(InventoryFull):
        shop.buy_offer(conn, content, 1, offer.key, NOW)
    shop.buy_bag_upgrade(conn, content, 1)
    shop.buy_offer(conn, content, 1, offer.key, NOW)


# ---------- reiniciar atributos ----------

def spend(conn, content, did, attribute, amount):
    return characters.spend_points(conn, did, attribute, amount)


def total_points(c):
    return sum(c.attributes.values()) + c.unspent_points


def test_nothing_to_respec_is_free_and_not_counted(conn, content):
    make(conn, content, gold=1_000)
    with pytest.raises(NothingToRespec):
        shop.respec_attributes(conn, content, 1)
    assert gold_of(conn) == 1_000
    assert conn.execute("SELECT COALESCE(SUM(respecs), 0) FROM character_shop").fetchone()[0] == 0


@pytest.mark.parametrize("class_id", ["guerrero", "mago", "picaro"])
def test_first_respec_is_free_and_restores_every_point(conn, content, class_id):
    c = make(conn, content, class_id=class_id, gold=0, level=6)
    spend(conn, content, 1, "suerte", 3)
    spend(conn, content, 1, "fuerza", 2)
    before = characters.get_character(conn, 1)
    result = shop.respec_attributes(conn, content, 1)
    after = result.character
    assert result.refunded == 5 and result.cost == 0 and gold_of(conn) == 0
    assert after.attributes == content.classes[class_id].base_attributes
    assert after.unspent_points == before.unspent_points + 5
    assert total_points(after) == total_points(before)                    # no se crean ni se pierden puntos


def test_next_respecs_cost_gold_that_scales_with_level(conn, content):
    rules = content.shop
    make(conn, content, gold=10_000, level=10)
    spend(conn, content, 1, "fuerza", 2)
    shop.respec_attributes(conn, content, 1)                               # gratis
    spend(conn, content, 1, "fuerza", 2)
    result = shop.respec_attributes(conn, content, 1)
    expected = rules.respec_base + rules.respec_per_level * 10
    assert result.cost == expected and gold_of(conn) == 10_000 - expected
    assert shop.get_shop(conn, content, 1, NOW).respec_cost == expected


def test_respec_without_gold_changes_nothing(conn, content):
    make(conn, content, gold=0, level=10)
    spend(conn, content, 1, "fuerza", 1)
    shop.respec_attributes(conn, content, 1)                               # gratis
    spend(conn, content, 1, "fuerza", 1)
    before = characters.get_character(conn, 1)
    with pytest.raises(NotEnoughGold):
        shop.respec_attributes(conn, content, 1)
    assert characters.get_character(conn, 1) == before


def test_respec_after_levelling_returns_all_points_and_stats_follow(conn, content):
    c = make(conn, content, class_id="mago", level=1)
    rules = content.config.progression
    characters.grant_xp(conn, rules, c.id, 5_000, "test")
    leveled = characters.get_character(conn, 1)
    for attribute in ("inteligencia", "vitalidad"):
        spend(conn, content, 1, attribute, leveled.unspent_points // 2)
    stats_before = derive_stats(leveled.level, characters.get_character(conn, 1).attributes)
    result = shop.respec_attributes(conn, content, 1)
    expected_unspent = content.config.starting_points + rules.points_per_level * (leveled.level - 1)
    assert result.character.attributes == content.classes["mago"].base_attributes
    assert result.character.unspent_points == expected_unspent       # todos los puntos ganados, ninguno perdido
    assert derive_stats(leveled.level, result.character.attributes).max_hp < stats_before.max_hp


def test_respec_only_touches_the_caller(conn, content):
    make(conn, content, 1, "Aldric", gold=1_000, level=5)
    make(conn, content, 2, "Brenna", "mago", gold=1_000, level=5)
    spend(conn, content, 1, "fuerza", 2)
    spend(conn, content, 2, "inteligencia", 2)
    other = characters.get_character(conn, 2)
    shop.respec_attributes(conn, content, 1)
    assert characters.get_character(conn, 2) == other


def test_respec_and_open_expeditions_are_independent(conn, content):
    from kame.services import expeditions

    make(conn, content, gold=500, level=3)
    spend(conn, content, 1, "fuerza", 3)
    expeditions.start_expedition(conn, content, 1, "cripta", now=0)
    shop.respec_attributes(conn, content, 1)          # la expedición ya salió con los atributos de antes
    result = expeditions.claim_expedition(conn, content, 1, now=8 * 3600)
    assert result.outcome.victories > 0


def test_simultaneous_respecs_refund_only_once(db_path, content):
    setup = connect(db_path)
    c = make(setup, content, gold=0, level=5)
    characters.spend_points(setup, 1, "fuerza", 3)
    total_before = total_points(characters.get_character(setup, 1))
    setup.close()
    results, barrier = [], threading.Barrier(3)

    def worker():
        conn = connect(db_path)
        try:
            barrier.wait()
            shop.respec_attributes(conn, content, 1)
            results.append("ok")
        except NothingToRespec:
            results.append("nada")
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("nada") == 2
    check = connect(db_path)
    assert total_points(characters.get_character(check, 1)) == total_before


def test_the_shop_cannot_create_gold(conn, content):
    make(conn, content, gold=2_000, level=12)
    total = gold_of(conn)
    spent = 0
    for offer in stock(content)[:5]:
        spent += shop.buy_offer(conn, content, 1, offer.key, NOW)[1]
    spent += shop.buy_bag_upgrade(conn, content, 1)[2]
    assert gold_of(conn) == total - spent and gold_of(conn) >= 0
