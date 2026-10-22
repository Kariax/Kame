import dataclasses
import json
import threading

import pytest

from kame.db.database import connect, transaction
from kame.engine.items import ItemDrop
from kame.services import characters, expeditions, items
from kame.services.errors import (
    InvalidSlot,
    ItemAlreadyEquipped,
    ItemEquippedCannotSell,
    ItemLevelTooLow,
    ItemNotFound,
    NothingEquipped,
    NoCharacter,
)

T0 = 1_000_000
HOUR = 3600


def make(conn, content, discord_id=1, name="Aldric", class_id="guerrero"):
    return characters.create_character(conn, content, discord_id, name, class_id)


def give(conn, content, discord_id, template_id, source="test"):
    """Añade un objeto al inventario con sus estadísticas base."""
    char = characters.get_character(conn, discord_id)
    t = content.item_templates[template_id]
    drop = ItemDrop(template_id, dict(t.stats))
    added = items.plan_new_items(conn, content, char.id, (drop,))
    with transaction(conn):
        items.insert_items_tx(conn, char.id, added.kept, source)
    return added.kept[0]


def level_up(conn, content, discord_id, level):
    char = characters.get_character(conn, discord_id)
    with transaction(conn):
        conn.execute("UPDATE characters SET level = ? WHERE id = ?", (level, char.id))


# ---------- inventario ----------

def test_inventory_lists_items_sorted_by_rarity(conn, content):
    make(conn, content)
    level_up(conn, content, 1, 20)
    give(conn, content, 1, "daga_mellada")
    give(conn, content, 1, "colmillo_del_verdugo")
    give(conn, content, 1, "estilete_envenenado")
    names = [i.template.id for i in items.list_inventory(conn, content, 1)]
    assert names == ["colmillo_del_verdugo", "estilete_envenenado", "daga_mellada"]


def test_inventory_filter_by_slot_and_invalid_slot(conn, content):
    make(conn, content)
    give(conn, content, 1, "daga_mellada")
    give(conn, content, 1, "yelmo_abollado")
    assert [i.template.slot for i in items.list_inventory(conn, content, 1, "helmet")] == ["helmet"]
    with pytest.raises(InvalidSlot):
        items.list_inventory(conn, content, 1, "cabeza")


def test_inventory_without_character(conn, content):
    with pytest.raises(NoCharacter):
        items.list_inventory(conn, content, 5)


def test_each_instance_has_a_unique_id(conn, content):
    make(conn, content)
    ids = {give(conn, content, 1, "daga_mellada").id for _ in range(10)}
    assert len(ids) == 10


# ---------- equipar ----------

def test_equip_and_replace(conn, content):
    make(conn, content)
    level_up(conn, content, 1, 5)
    a = give(conn, content, 1, "daga_mellada")
    b = give(conn, content, 1, "estilete_envenenado")
    equipped, replaced = items.equip_item(conn, content, 1, a.id)
    assert equipped.equipped_slot == "weapon" and replaced is None
    equipped, replaced = items.equip_item(conn, content, 1, b.id)
    assert replaced is not None and replaced.id == a.id
    eq = items.get_equipment(conn, content, 1)
    assert list(eq) == ["weapon"] and eq["weapon"].id == b.id
    inventory = {i.id: i for i in items.list_inventory(conn, content, 1)}
    assert inventory[a.id].equipped_slot is None and inventory[b.id].equipped_slot == "weapon"


def test_cannot_equip_twice(conn, content):
    make(conn, content)
    a = give(conn, content, 1, "daga_mellada")
    items.equip_item(conn, content, 1, a.id)
    with pytest.raises(ItemAlreadyEquipped):
        items.equip_item(conn, content, 1, a.id)


def test_level_requirement_for_equipping(conn, content):
    make(conn, content)
    rare = give(conn, content, 1, "espada_del_penitente")  # nivel 6
    with pytest.raises(ItemLevelTooLow):
        items.equip_item(conn, content, 1, rare.id)
    level_up(conn, content, 1, 6)
    items.equip_item(conn, content, 1, rare.id)


def test_items_go_to_the_slot_of_their_template(conn, content):
    make(conn, content)
    pieces = {"daga_mellada": "weapon", "yelmo_abollado": "helmet", "peto_remendado": "armor",
              "guanteletes_viejos": "gloves", "botas_gastadas": "boots", "amuleto_de_hueso": "amulet"}
    for template_id, slot in pieces.items():
        items.equip_item(conn, content, 1, give(conn, content, 1, template_id).id)
    assert set(items.get_equipment(conn, content, 1)) == set(pieces.values())


def test_unequip(conn, content):
    make(conn, content)
    a = give(conn, content, 1, "daga_mellada")
    items.equip_item(conn, content, 1, a.id)
    back = items.unequip_slot(conn, content, 1, "weapon")
    assert back.id == a.id and not back.equipped
    assert items.get_equipment(conn, content, 1) == {}
    with pytest.raises(NothingEquipped):
        items.unequip_slot(conn, content, 1, "weapon")
    with pytest.raises(InvalidSlot):
        items.unequip_slot(conn, content, 1, "cola")


def test_equipment_changes_the_current_build(conn, content):
    c = make(conn, content)
    base = items.current_build(conn, content, c)
    level_up(conn, content, 1, 3)
    c = characters.get_character(conn, 1)
    items.equip_item(conn, content, 1, give(conn, content, 1, "hacha_del_osario").id)
    geared = items.current_build(conn, content, c)
    assert len(geared.items) == 1 and len(base.items) == 0


# ---------- vender ----------

def test_sell_gives_gold_and_removes_the_item(conn, content):
    make(conn, content)
    a = give(conn, content, 1, "daga_mellada")
    item, gold = items.sell_item(conn, content, 1, a.id)
    assert gold == content.config.items.sell_values["common"]
    assert characters.get_character(conn, 1).gold == gold
    assert items.list_inventory(conn, content, 1) == []
    with pytest.raises(ItemNotFound):
        items.sell_item(conn, content, 1, a.id)  # no se puede vender dos veces
    assert characters.get_character(conn, 1).gold == gold


def test_cannot_sell_equipped_items(conn, content):
    make(conn, content)
    a = give(conn, content, 1, "daga_mellada")
    items.equip_item(conn, content, 1, a.id)
    with pytest.raises(ItemEquippedCannotSell):
        items.sell_item(conn, content, 1, a.id)
    assert characters.get_character(conn, 1).gold == 0
    assert len(items.list_inventory(conn, content, 1)) == 1


def test_sell_price_depends_on_rarity(conn, content):
    make(conn, content)
    level_up(conn, content, 1, 12)
    _, common = items.sell_item(conn, content, 1, give(conn, content, 1, "daga_mellada").id)
    _, legendary = items.sell_item(conn, content, 1, give(conn, content, 1, "colmillo_del_verdugo").id)
    assert legendary > common


def test_players_cannot_touch_each_others_items(conn, content):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira", "mago")
    a = give(conn, content, 1, "daga_mellada")
    for action in (
        lambda: items.equip_item(conn, content, 2, a.id),
        lambda: items.sell_item(conn, content, 2, a.id),
    ):
        with pytest.raises(ItemNotFound):
            action()
    assert items.list_inventory(conn, content, 2) == []
    assert len(items.list_inventory(conn, content, 1)) == 1


@pytest.mark.parametrize("bad_id", ["", "no-existe", "1 OR 1=1", "'; DROP TABLE item_instances;--"])
def test_garbage_item_ids_are_rejected(conn, content, bad_id):
    make(conn, content)
    give(conn, content, 1, "daga_mellada")
    for action in (items.equip_item, items.sell_item):
        with pytest.raises(ItemNotFound):
            action(conn, content, 1, bad_id)
    assert len(items.list_inventory(conn, content, 1)) == 1


def test_equip_and_sell_race_never_leaves_an_inconsistent_state(db_path, content):
    for round_number in range(8):
        setup = connect(db_path)
        if round_number == 0:
            make(setup, content)
        item = give(setup, content, 1, "daga_mellada")
        setup.close()
        results, barrier = [], threading.Barrier(2)

        def worker(action):
            c = connect(db_path)
            try:
                barrier.wait()
                action(c, content, 1, item.id)
                results.append("ok")
            except (ItemNotFound, ItemEquippedCannotSell, ItemAlreadyEquipped):
                results.append("rechazado")
            finally:
                c.close()

        threads = [threading.Thread(target=worker, args=(items.equip_item,)),
                   threading.Thread(target=worker, args=(items.sell_item,))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        check = connect(db_path)
        exists = check.execute("SELECT COUNT(*) FROM item_instances WHERE id = ?", (item.id,)).fetchone()[0]
        equipped = check.execute("SELECT COUNT(*) FROM equipment WHERE item_id = ?", (item.id,)).fetchone()[0]
        assert not (equipped and not exists)          # nunca equipado y borrado a la vez
        assert results.count("ok") >= 1               # al menos una acción triunfa
        gold = check.execute("SELECT gold FROM characters").fetchone()[0]
        assert (gold > 0) == (not exists)             # hay oro si y solo si se vendió
        # limpiar para la siguiente ronda
        with transaction(check):
            check.execute("DELETE FROM equipment")
            check.execute("DELETE FROM item_instances")
            check.execute("UPDATE characters SET gold = 0")
        check.close()


# ---------- botín de expediciones ----------

def loot_content(content, chance=1.0, cap=50):
    expeditions_ = {
        k: dataclasses.replace(e, item_chance=chance, elite_item_chance=chance)
        for k, e in content.expeditions.items()
    }
    cfg = dataclasses.replace(
        content.config, items=dataclasses.replace(content.config.items, inventory_cap=cap)
    )
    return dataclasses.replace(content, expeditions=expeditions_, config=cfg)


def test_claim_adds_dropped_items_to_the_inventory(conn, content):
    rich = loot_content(content)
    make(conn, rich)
    expeditions.start_expedition(conn, rich, 1, "cripta", now=T0)
    result = expeditions.claim_expedition(conn, rich, 1, now=T0 + 8 * HOUR)
    assert len(result.items) == result.outcome.victories == 32
    stored = items.list_inventory(conn, rich, 1)
    assert {i.id for i in stored} == {i.id for i in result.items}
    rows = conn.execute("SELECT source, owner_character_id FROM item_instances").fetchall()
    assert {r["source"] for r in rows} == {"expedition:cripta"} and len(rows) == 32


def test_second_claim_cannot_duplicate_items(conn, content):
    rich = loot_content(content)
    make(conn, rich)
    expeditions.start_expedition(conn, rich, 1, "cripta", now=T0)
    expeditions.claim_expedition(conn, rich, 1, now=T0 + 8 * HOUR)
    count = conn.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0]
    with pytest.raises(Exception):
        expeditions.claim_expedition(conn, rich, 1, now=T0 + 9 * HOUR)
    assert conn.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0] == count


def test_full_inventory_sells_the_overflow_automatically(conn, content):
    tiny = loot_content(content, cap=5)
    make(conn, tiny)
    expeditions.start_expedition(conn, tiny, 1, "cripta", now=T0)
    result = expeditions.claim_expedition(conn, tiny, 1, now=T0 + 8 * HOUR)
    assert len(result.items) == 5 and len(result.overflow_items) == 27
    assert result.overflow_gold == sum(
        tiny.config.items.sell_values[i.template.rarity] for i in result.overflow_items
    )
    assert conn.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0] == 5
    assert characters.get_character(conn, 1).gold == result.outcome.gold + result.overflow_gold


def test_inventory_never_exceeds_the_cap(conn, content):
    tiny = loot_content(content, cap=5)
    make(conn, tiny)
    for i in range(3):
        expeditions.start_expedition(conn, tiny, 1, "cripta", now=T0 + i * 20 * HOUR)
        expeditions.claim_expedition(conn, tiny, 1, now=T0 + i * 20 * HOUR + 8 * HOUR)
    assert conn.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0] == 5


def test_drops_respect_the_expedition_level_margin(conn, content):
    rich = loot_content(content)
    make(conn, rich)
    expeditions.start_expedition(conn, rich, 1, "cripta", now=T0)
    result = expeditions.claim_expedition(conn, rich, 1, now=T0 + 8 * HOUR)
    limit = rich.expeditions["cripta"].recommended_level + rich.config.items.drop_level_margin
    assert all(i.template.min_level <= limit for i in result.items)


def test_snapshot_freezes_equipment_and_skills_at_departure(conn, content):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira")
    for did in (1, 2):
        items.equip_item(conn, content, did, give(conn, content, did, "daga_mellada").id)
    for did in (1, 2):
        expeditions.start_expedition(conn, content, did, "cripta", now=T0)
    snap = json.loads(conn.execute("SELECT snapshot FROM expeditions ORDER BY id").fetchone()[0])
    assert snap["items"][0]["template"] == "daga_mellada" and len(snap["skills"]) == 2
    items.unequip_slot(conn, content, 1, "weapon")  # cambiar el equipo después de salir no cuenta
    a = expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR).outcome
    b = expeditions.claim_expedition(conn, content, 2, now=T0 + 8 * HOUR).outcome
    assert a == b


def test_claim_still_works_with_snapshots_from_phase_2(conn, content):
    c = make(conn, content)
    old = {"class_id": c.class_id, "level": 1, "attributes": c.attributes}  # sin equipo ni habilidades
    conn.execute(
        "INSERT INTO expeditions (character_id, expedition_id, started_at, seed, snapshot)"
        " VALUES (?, 'cripta', ?, 1, ?)", (c.id, T0, json.dumps(old)))
    assert expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR).outcome.victories == 32


def test_items_with_removed_templates_are_skipped_not_fatal(conn, content):
    make(conn, content)
    give(conn, content, 1, "daga_mellada")
    conn.execute("UPDATE item_instances SET template_id = 'retirado'")
    assert items.list_inventory(conn, content, 1) == []
