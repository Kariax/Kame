import threading

import pytest

from kame.db.database import connect, transaction
from kame.services import characters, company, expeditions
from kame.services.errors import (
    InvalidAmount,
    InvalidResource,
    NoCharacter,
    NotEnoughResource,
    StorageShort,
    UnknownUpgrade,
    UpgradeMaxLevel,
)

HOUR = 3600


def make(conn, content, discord_id=1, name="Aldric", class_id="guerrero"):
    return characters.create_character(conn, content, discord_id, name, class_id)


def give(conn, discord_id, gold=0, **materials):
    cid = characters.get_character(conn, discord_id).id
    with transaction(conn):
        conn.execute("UPDATE characters SET gold = gold + ? WHERE id = ?", (gold, cid))
        for material, amount in materials.items():
            conn.execute(
                "INSERT INTO character_materials VALUES (?, ?, ?) ON CONFLICT(character_id, material_id)"
                " DO UPDATE SET amount = amount + excluded.amount", (cid, material, amount))


def fund(conn, **resources):
    with transaction(conn):
        for resource, amount in resources.items():
            company.add_shared_tx(conn, resource, amount, "test")


def ledger_matches_storage(conn):
    totals = {r["resource_id"]: r["total"] for r in conn.execute(
        "SELECT resource_id, SUM(delta) AS total FROM company_ledger GROUP BY resource_id")}
    storage = {r["resource_id"]: r["amount"] for r in conn.execute("SELECT * FROM company_storage")}
    return all(storage.get(k, 0) == totals.get(k, 0) for k in set(totals) | set(storage))


def test_empty_company_view(conn, content):
    view = company.get_company(conn, content)
    assert view.name and view.storage == {} and view.upgrades == {} and (view.xp_bonus, view.gold_bonus) == (0, 0)


def test_donating_gold_and_materials(conn, content):
    make(conn, content)
    give(conn, 1, gold=100, hueso_astillado=5)
    assert company.contribute(conn, content, 1, "gold", 60) == 60
    assert company.contribute(conn, content, 1, "hueso_astillado", 5) == 5
    assert company.contribute(conn, content, 1, "gold", 40) == 100
    char = characters.get_character(conn, 1)
    assert char.gold == 0 and characters.get_materials(conn, char.id) == {}
    assert company.get_company(conn, content).storage == {"gold": 100, "hueso_astillado": 5}
    assert ledger_matches_storage(conn)


def test_cannot_donate_more_than_you_have_and_nothing_changes(conn, content):
    make(conn, content)
    give(conn, 1, gold=10, ectoplasma=2)
    with pytest.raises(NotEnoughResource) as e:
        company.contribute(conn, content, 1, "gold", 11)
    assert "10" in e.value.message
    with pytest.raises(NotEnoughResource):
        company.contribute(conn, content, 1, "ectoplasma", 3)
    with pytest.raises(NotEnoughResource):
        company.contribute(conn, content, 1, "ceniza_maldita", 1)  # no la tiene
    assert characters.get_character(conn, 1).gold == 10
    assert company.get_company(conn, content).storage == {} and ledger_matches_storage(conn)


@pytest.mark.parametrize("amount", [0, -5, 1.5, "10", None, True])
def test_invalid_amounts(conn, content, amount):
    make(conn, content)
    give(conn, 1, gold=100)
    with pytest.raises(InvalidAmount):
        company.contribute(conn, content, 1, "gold", amount)
    assert characters.get_character(conn, 1).gold == 100


@pytest.mark.parametrize("resource", ["", "diamantes", "GOLD", "gold; DROP TABLE company_storage"])
def test_invalid_resources(conn, content, resource):
    make(conn, content)
    with pytest.raises(InvalidResource):
        company.contribute(conn, content, 1, resource, 1)


def test_donation_without_character(conn, content):
    with pytest.raises(NoCharacter):
        company.contribute(conn, content, 7, "gold", 1)


def test_players_only_donate_their_own_resources(conn, content):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira", "mago")
    give(conn, 1, gold=100)
    with pytest.raises(NotEnoughResource):
        company.contribute(conn, content, 2, "gold", 50)
    assert characters.get_character(conn, 1).gold == 100


def test_buying_an_upgrade_spends_the_storage_and_logs_it(conn, content):
    make(conn, content)
    cost = content.company_upgrades["armeria"].levels[0].cost
    fund(conn, **{k: v + 5 for k, v in cost.items()})
    level, paid = company.buy_upgrade(conn, content, 1, "armeria")
    assert level == 1 and paid == cost
    view = company.get_company(conn, content)
    assert view.upgrades == {"armeria": 1}
    assert view.storage == {k: 5 for k in cost}
    assert (view.xp_bonus, view.gold_bonus) == (0.03, 0.03)
    spent = conn.execute("SELECT COUNT(*) FROM company_ledger WHERE reason = 'upgrade:armeria:1'").fetchone()[0]
    assert spent == len(cost) and ledger_matches_storage(conn)


def test_upgrade_by_name_and_unknown_upgrade(conn, content):
    make(conn, content)
    fund(conn, **content.company_upgrades["armeria"].levels[0].cost)
    assert company.buy_upgrade(conn, content, 1, "Armería")[0] == 1
    with pytest.raises(UnknownUpgrade):
        company.buy_upgrade(conn, content, 1, "torre_de_marfil")


def test_not_enough_in_storage_reports_what_is_missing_and_changes_nothing(conn, content):
    make(conn, content)
    cost = content.company_upgrades["armeria"].levels[0].cost
    partial = {k: v for k, v in cost.items() if k != "ectoplasma"}
    fund(conn, **partial)
    with pytest.raises(StorageShort) as e:
        company.buy_upgrade(conn, content, 1, "armeria")
    assert e.value.missing == {"ectoplasma": cost["ectoplasma"]}
    assert company.get_company(conn, content).storage == partial
    assert company.get_company(conn, content).upgrades == {}


def test_upgrades_go_level_by_level_up_to_the_maximum(conn, content):
    make(conn, content)
    up = content.company_upgrades["armeria"]
    for level in up.levels:
        fund(conn, **level.cost)
    for expected in (1, 2, 3):
        assert company.buy_upgrade(conn, content, 1, "armeria")[0] == expected
    with pytest.raises(UpgradeMaxLevel):
        company.buy_upgrade(conn, content, 1, "armeria")
    assert company.get_company(conn, content).storage == {} and ledger_matches_storage(conn)
    assert company.get_company(conn, content).xp_bonus == pytest.approx(0.10)


def test_armeria_boosts_xp_and_gold_for_everyone_in_expeditions(conn, content):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira")
    expeditions.start_expedition(conn, content, 1, "cripta", now=0)
    expeditions.start_expedition(conn, content, 2, "cripta", now=0)
    plain = expeditions.claim_expedition(conn, content, 1, now=8 * HOUR)
    fund(conn, **content.company_upgrades["armeria"].levels[0].cost)
    company.buy_upgrade(conn, content, 1, "armeria")
    boosted = expeditions.claim_expedition(conn, content, 2, now=8 * HOUR)  # otro jugador: también se beneficia
    assert plain.bonus_xp == 0 and plain.bonus_gold == 0
    assert boosted.bonus_xp == round(boosted.outcome.xp * 0.03) and boosted.bonus_xp > 0
    assert boosted.bonus_gold == round(boosted.outcome.gold * 0.03)
    after = characters.get_character(conn, 2)
    assert after.gold == boosted.outcome.gold + boosted.bonus_gold + boosted.overflow_gold


def test_concurrent_donations_cannot_overspend(db_path, content):
    setup = connect(db_path)
    make(setup, content)
    give(setup, 1, gold=100)
    setup.close()
    results, barrier = [], threading.Barrier(4)

    def worker():
        c = connect(db_path)
        try:
            barrier.wait()
            company.contribute(c, content, 1, "gold", 60)
            results.append("ok")
        except NotEnoughResource:
            results.append("sin fondos")
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "sin fondos", "sin fondos", "sin fondos"]
    check = connect(db_path)
    assert check.execute("SELECT amount FROM company_storage WHERE resource_id = 'gold'").fetchone()[0] == 60
    assert check.execute("SELECT gold FROM characters").fetchone()[0] == 40


def test_concurrent_purchases_with_funds_for_one_only_buy_once(db_path, content):
    setup = connect(db_path)
    make(setup, content)
    make(setup, content, 2, "Mira", "mago")
    fund(setup, **content.company_upgrades["armeria"].levels[0].cost)
    setup.close()
    results, barrier = [], threading.Barrier(2)

    def worker(discord_id):
        c = connect(db_path)
        try:
            barrier.wait()
            company.buy_upgrade(c, content, discord_id, "armeria")
            results.append("ok")
        except StorageShort:
            results.append("sin fondos")
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "sin fondos"]
    check = connect(db_path)
    assert check.execute("SELECT level FROM company_upgrades").fetchone()[0] == 1
    assert ledger_matches_storage(check)


def test_ledger_lists_latest_movements_first(conn, content):
    make(conn, content)
    give(conn, 1, gold=30)
    company.contribute(conn, content, 1, "gold", 10)
    company.contribute(conn, content, 1, "gold", 20)
    entries = company.get_ledger(conn)
    assert [e.delta for e in entries[:2]] == [20, 10] and entries[0].character_name == "Aldric"
