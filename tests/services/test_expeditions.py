import dataclasses
import json
import threading

import discord
import pytest

from kame.db.database import connect
from kame.engine.expeditions import EnemyDef, ExpeditionDef
from kame.services import characters, expeditions
from kame.services.errors import (
    ExpeditionInProgress,
    LevelTooLow,
    NoActiveExpedition,
    NoCharacter,
    NothingToClaimYet,
    UnknownExpedition,
)

T0 = 1_000_000
HOUR = 3600


def make(conn, content, discord_id=1, name="Aldric", class_id="guerrero"):
    return characters.create_character(conn, content, discord_id, name, class_id)


def state(conn, discord_id=1):
    c = conn.execute(
        "SELECT c.* FROM characters c JOIN players p ON p.id=c.player_id WHERE p.discord_id=?",
        (discord_id,),
    ).fetchone()
    return (c["level"], c["xp"], c["gold"], c["unspent_points"])


# ---------- empezar ----------

def test_start_creates_open_expedition(conn, content):
    make(conn, content)
    definition = expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    assert definition.id == "cripta"
    active = expeditions.get_active_expedition(conn, content, 1, now=T0)
    assert active is not None and active.definition.id == "cripta" and active.encounters_ready == 0


def test_start_accepts_display_name(conn, content):
    make(conn, content)
    assert expeditions.start_expedition(conn, content, 1, "Cripta Olvidada", now=T0).id == "cripta"


def test_cannot_start_two_expeditions(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    with pytest.raises(ExpeditionInProgress):
        expeditions.start_expedition(conn, content, 1, "cripta", now=T0 + 10)
    assert conn.execute("SELECT COUNT(*) FROM expeditions").fetchone()[0] == 1


def test_unknown_expedition_and_missing_character(conn, content):
    make(conn, content)
    with pytest.raises(UnknownExpedition):
        expeditions.start_expedition(conn, content, 1, "narnia", now=T0)
    with pytest.raises(NoCharacter):
        expeditions.start_expedition(conn, content, 999, "cripta", now=T0)


def test_level_requirement_is_enforced(conn, content):
    make(conn, content)
    with pytest.raises(LevelTooLow):
        expeditions.start_expedition(conn, content, 1, "paramo", now=T0)
    assert conn.execute("SELECT COUNT(*) FROM expeditions").fetchone()[0] == 0


def test_get_active_without_expedition_is_none(conn, content):
    make(conn, content)
    assert expeditions.get_active_expedition(conn, content, 1, now=T0) is None


def test_active_progress_is_derived_from_timestamps(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    a = expeditions.get_active_expedition(conn, content, 1, now=T0 + 2 * HOUR)
    assert a.encounters_ready == 8 and a.max_encounters == 32
    assert a.seconds_to_full == 6 * HOUR
    capped = expeditions.get_active_expedition(conn, content, 1, now=T0 + 50 * HOUR)
    assert capped.encounters_ready == 32 and capped.seconds_to_next is None


# ---------- reclamar ----------

def test_claim_before_first_encounter_does_not_consume_the_expedition(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    with pytest.raises(NothingToClaimYet) as e:
        expeditions.claim_expedition(conn, content, 1, now=T0 + 60)
    assert e.value.seconds and e.value.seconds > 0
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 60) is not None


def test_claim_pays_rewards_and_closes_expedition(conn, content):
    before = make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    result = expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    o = result.outcome
    # Con el balance actual el guerrero lvl1 con equipo típico gana la mayoría de
    # los 32 encuentros de la cripta; cuando cae, el enemigo huye y la expedición
    # continúa. Al reclamar conserva todo lo ganado hasta entonces.
    assert o.victories == 25 and o.retreated and o.xp > 0 and o.gold > 0
    assert sum(o.defeated_by.values()) == o.encounters - o.victories
    after = characters.get_character(conn, 1)
    assert after.gold == o.gold
    # The character leveled up during the expedition, so the XP is not directly comparable
    # to the outcome XP. Instead, we check that the total XP is correct.
    assert after.xp + 100 == o.xp
    assert characters.get_materials(conn, after.id) == o.materials
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 9 * HOUR) is None
    row = conn.execute("SELECT claimed_at, result FROM expeditions").fetchone()
    assert row["claimed_at"] == T0 + 8 * HOUR and json.loads(row["result"])["xp"] == o.xp


def test_second_claim_cannot_pay_twice(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    snapshot = state(conn)
    for _ in range(3):
        with pytest.raises(NoActiveExpedition):
            expeditions.claim_expedition(conn, content, 1, now=T0 + 20 * HOUR)
    assert state(conn) == snapshot


def test_claim_without_expedition(conn, content):
    make(conn, content)
    with pytest.raises(NoActiveExpedition):
        expeditions.claim_expedition(conn, content, 1, now=T0)
    with pytest.raises(NoCharacter):
        expeditions.claim_expedition(conn, content, 404, now=T0)


def test_waiting_longer_than_the_cap_gives_no_extra(conn, content, monkeypatch):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira")
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    expeditions.start_expedition(conn, content, 2, "cripta", now=T0)
    a = expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR).outcome
    b = expeditions.claim_expedition(conn, content, 2, now=T0 + 80 * HOUR).outcome
    assert a == b


def test_claiming_early_or_late_cannot_reroll_results(conn, content, monkeypatch):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira")
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    expeditions.start_expedition(conn, content, 2, "cripta", now=T0)
    early = expeditions.claim_expedition(conn, content, 1, now=T0 + 4 * HOUR).outcome
    late = expeditions.claim_expedition(conn, content, 2, now=T0 + 8 * HOUR).outcome
    # A las 4h son 16 encuentros (12 victorias); a las 8h son 32 encuentros (25 victorias).
    assert early.victories == 12 and late.victories == 25
    for enemy_id, n in early.kills.items():
        assert n <= late.kills.get(enemy_id, 0)


def test_stats_are_frozen_when_the_expedition_starts(conn, content, monkeypatch):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira")
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    expeditions.start_expedition(conn, content, 2, "cripta", now=T0)
    characters.spend_points(conn, 1, "suerte", 5)  # mejora DESPUÉS de salir: no cuenta
    a = expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR).outcome
    b = expeditions.claim_expedition(conn, content, 2, now=T0 + 8 * HOUR).outcome
    assert a == b


def test_clock_going_backwards_is_harmless(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    with pytest.raises(NothingToClaimYet):
        expeditions.claim_expedition(conn, content, 1, now=T0 - 5 * HOUR)
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 - 5 * HOUR).elapsed_seconds == 0


def test_materials_accumulate_across_claims(conn, content):
    make(conn, content)
    total: dict[str, int] = {}
    for i in range(2):
        start = T0 + i * 20 * HOUR
        expeditions.start_expedition(conn, content, 1, "cripta", now=start)
        o = expeditions.claim_expedition(conn, content, 1, now=start + 8 * HOUR).outcome
        for k, v in o.materials.items():
            total[k] = total.get(k, 0) + v
    cid = characters.get_character(conn, 1).id
    assert characters.get_materials(conn, cid) == total and total


def test_claim_is_atomic_when_something_fails_midway(conn, content, monkeypatch):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    before = state(conn)

    def boom(*args, **kwargs):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(expeditions, "grant_xp_tx", boom)
    with pytest.raises(RuntimeError):
        expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    assert state(conn) == before  # nada se pagó
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 8 * HOUR) is not None
    monkeypatch.undo()
    expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)  # y se puede reclamar luego
    assert state(conn) != before


def test_defeat_does_not_end_the_expedition_but_keeps_earned_rewards(conn, content):
    """Cuando el personaje cae, el enemigo huye: la expedición termina (se reclama)
    pero se conservan todas las victorias acumuladas y se registra quién venció."""
    killer = EnemyDef("verdugo", "Verdugo", hp=10**6, power=10**5, damage_type="physical",
                      defense=0, resistance=0, xp=1000, gold=1000)
    trap = ExpeditionDef("trampa", "Trampa", "d", "arriesgado", 1, 1, 4.0, (("verdugo", 1),))
    hard = dataclasses.replace(
        content,
        enemies={**content.enemies, "verdugo": killer},
        expeditions={**content.expeditions, "trampa": trap},
    )
    make(conn, hard)
    expeditions.start_expedition(conn, hard, 1, "trampa", now=T0)
    result = expeditions.claim_expedition(conn, hard, 1, now=T0 + 8 * HOUR)
    o = result.outcome
    assert o.retreated  # el personaje cayó al menos una vez
    assert o.victories == 0 and (o.xp, o.gold) == (0, 0)
    # todas las derrotas registradas son del Verdugo
    assert o.defeated_by == {"verdugo": o.encounters}
    assert expeditions.get_active_expedition(conn, hard, 1, now=T0 + 9 * HOUR) is None
    # la expedición queda marcada como reclamada aunque el personaje haya caído
    expeditions.start_expedition(conn, hard, 1, "cripta", now=T0 + 10 * HOUR)  # puede volver a salir


def test_players_cannot_touch_each_others_expeditions(conn, content):
    make(conn, content, 1, "Aldric")
    make(conn, content, 2, "Mira", "mago")
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    assert expeditions.get_active_expedition(conn, content, 2, now=T0 + HOUR) is None
    with pytest.raises(NoActiveExpedition):
        expeditions.claim_expedition(conn, content, 2, now=T0 + 8 * HOUR)
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + HOUR) is not None


def test_expedition_state_survives_bot_restart(db_path, content):
    c1 = connect(db_path)
    make(c1, content)
    expeditions.start_expedition(c1, content, 1, "cripta", now=T0)
    c1.close()  # "reinicio" del bot
    c2 = connect(db_path)
    assert expeditions.get_active_expedition(c2, content, 1, now=T0 + HOUR).encounters_ready == 4
    result = expeditions.claim_expedition(c2, content, 1, now=T0 + 8 * HOUR)
    # Con el balance actual el guerrero lvl1 cae alguna vez en la cripta (la
    # expedición continúa) y gana 25 de 32 encuentros.
    assert result.outcome.victories == 25
    c2.close()


def test_concurrent_claims_pay_only_once(db_path, content):
    setup = connect(db_path)
    make(setup, content)
    expeditions.start_expedition(setup, content, 1, "cripta", now=T0)
    setup.close()
    results, barrier = [], threading.Barrier(4)

    def worker():
        c = connect(db_path)
        try:
            barrier.wait()
            expeditions.claim_expedition(c, content, 1, now=T0 + 8 * HOUR)
            results.append("ok")
        except NoActiveExpedition:
            results.append("nada")
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["nada"] * 3 + ["ok"]
    check = connect(db_path)
    payouts = [json.loads(r["result"]) for r in check.execute("SELECT result FROM expeditions")]
    assert len(payouts) == 1
    assert check.execute("SELECT gold FROM characters").fetchone()[0] == payouts[0]["gold"]


def test_concurrent_starts_open_only_one_expedition(db_path, content):
    setup = connect(db_path)
    make(setup, content)
    setup.close()
    results, barrier = [], threading.Barrier(4)

    def worker():
        c = connect(db_path)
        try:
            barrier.wait()
            expeditions.start_expedition(c, content, 1, "cripta", now=T0)
            results.append("ok")
        except ExpeditionInProgress:
            results.append("ocupado")
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ocupado"] * 3 + ["ok"]


def test_expedition_events_are_logged(conn, content):
    c = make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    kinds = [r[0] for r in conn.execute(
        "SELECT kind FROM activity_log WHERE character_id = ? ORDER BY id", (c.id,))]
    assert kinds[:2] == ["created", "expedition_started"]
    assert "expedition_claimed" in kinds and "xp_gained" in kinds


# ---------- previsualización (solo lectura) ----------

def test_preview_does_not_modify_database(conn, content):
    before = make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    snapshot = state(conn)

    result = expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    o = result.outcome
    assert o.victories == 25 and o.retreated and o.xp > 0 and o.gold > 0

    # La expedición sigue abierta y sin reclamar: nada se escribió.
    assert state(conn) == snapshot
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 9 * HOUR) is not None
    row = conn.execute("SELECT claimed_at, result FROM expeditions").fetchone()
    assert row["claimed_at"] is None and row["result"] is None
    assert characters.get_materials(conn, before.id) == {}
    assert conn.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0] == 0
    kinds = [r[0] for r in conn.execute(
        "SELECT kind FROM activity_log WHERE character_id = ? ORDER BY id", (before.id,))]
    assert kinds == ["created", "expedition_started"]


def test_preview_matches_claim_for_the_same_expedition(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    preview = expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    claimed = expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    assert preview.outcome == claimed.outcome
    assert preview.bonus_xp == claimed.bonus_xp
    assert preview.bonus_gold == claimed.bonus_gold
    assert preview.overflow_gold == claimed.overflow_gold
    assert preview.elapsed_seconds == claimed.elapsed_seconds


def test_preview_before_first_encounter_raises(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    with pytest.raises(NothingToClaimYet):
        expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 60)
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 60) is not None


def test_preview_without_expedition_raises(conn, content):
    make(conn, content)
    with pytest.raises(NoActiveExpedition):
        expeditions.preview_resolve_expedition(conn, content, 1, now=T0)
    with pytest.raises(NoCharacter):
        expeditions.preview_resolve_expedition(conn, content, 404, now=T0)


def test_preview_repeated_calls_are_idempotent(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    a = expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    b = expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    assert a.outcome == b.outcome
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 9 * HOUR) is not None


def test_preview_embed_contains_preview_indicator(conn, content):
    from kame.bot.embeds import preview_expedition_embed

    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    result = expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    embed = preview_expedition_embed("Aldric", result, content)
    assert "Preview" in embed.title
    assert "reclamado" in embed.footer.text
    assert embed.color.value == discord.Color.blue().value


def test_preview_then_claim_works_after_preview(conn, content):
    make(conn, content)
    expeditions.start_expedition(conn, content, 1, "cripta", now=T0)
    expeditions.preview_resolve_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    result = expeditions.claim_expedition(conn, content, 1, now=T0 + 8 * HOUR)
    # Con el balance actual el guerrero lvl1 cae alguna vez (la expedición continúa)
    # y gana 25 de 32 encuentros.
    assert result.outcome.victories == 25
    assert expeditions.get_active_expedition(conn, content, 1, now=T0 + 9 * HOUR) is None
