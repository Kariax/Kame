import dataclasses
import json
import math
import threading

import pytest

from kame.db.database import connect, transaction
from kame.engine.dungeon import auto_action
from kame.services import characters, company, dungeons
from kame.services.characters import _log
from kame.services.errors import (
    AlreadyInDungeon,
    DungeonLevelTooLow,
    InvalidAction,
    NotEnoughPlayers,
    NotInDungeon,
    NotLeader,
    RunFull,
    RunNotActive,
    RunNotFound,
    UnknownDungeon,
)

D_ID = "cripta_del_rey_hueco"
T0 = 1_000_000
CLASSES = ["guerrero", "mago", "picaro"]


def name_of(did, prefix="Heroe"):
    """Los nombres solo admiten letras: el número se escribe con letras (1 -> b, 12 -> bc)."""
    return prefix + "".join(chr(97 + int(d)) for d in str(did))


# ---------- ayudas ----------

def tweak(content, hp=1.0, dmg=1.0, boss=1.0, max_rounds=None, **dungeon_changes):
    """Variante del contenido: dureza de enemigos, vida del jefe y datos de la mazmorra."""
    enemies = {k: dataclasses.replace(e, hp_k=e.hp_k * hp, dmg_frac=e.dmg_frac * dmg)
               for k, e in content.dungeon_enemies.items()}
    dungeon = content.dungeons[D_ID]
    stages = []
    for stage in dungeon.stages:
        if stage.kind == "boss":
            phases = tuple(dataclasses.replace(p, moves=tuple(dataclasses.replace(m, power=m.power * dmg)
                           for m in p.moves)) for p in stage.phases)
            stage = dataclasses.replace(stage, boss_hp_rounds=stage.boss_hp_rounds * boss, phases=phases)
        stages.append(stage)
    changes = dict(hero_rating_floor=0.0, stages=tuple(stages), **dungeon_changes)
    if max_rounds:
        changes["max_rounds"] = max_rounds
    return dataclasses.replace(content, dungeon_enemies=enemies,
                               dungeons={**content.dungeons, D_ID: dataclasses.replace(dungeon, **changes)})


def easy(content, **kw):
    return tweak(content, hp=0.15, dmg=0.4, boss=0.25, **kw)


def slow(content, **kw):  # los héroes casi no reciben daño: la partida dura varias rondas
    return tweak(content, hp=1.0, dmg=0.05, boss=0.8, **kw)


def party(conn, content, n, level=8, first_id=1):
    ids = []
    for i in range(n):
        did = first_id + i
        characters.create_character(conn, content, did, name_of(did), CLASSES[i % 3])
        cid = characters.get_character(conn, did).id
        with transaction(conn):
            conn.execute("UPDATE characters SET level = ?, fuerza = fuerza + 20, vitalidad = vitalidad + 20"
                         " WHERE id = ?", (level, cid))
        ids.append(did)
    return ids


def open_run(conn, content, n=3, now=T0, **kw):
    ids = party(conn, content, n, **kw)
    view = dungeons.create_run(conn, content, ids[0], D_ID, 555, now)
    for did in ids[1:]:
        dungeons.join_run(conn, content, did, view.id, now)
    return ids, view.id


def started(conn, content, n=3, now=T0):
    ids, run_id = open_run(conn, content, n, now)
    dungeons.start_run(conn, content, ids[0], now)
    return ids, run_id


def act(conn, content, did, now):
    """Acción automática de un jugador (la que elegiría el modo auto)."""
    view = dungeons.get_my_run(conn, content, did)
    st = view.battle
    hero = next(h for h in st.heroes if h.uid == f"c{characters.get_character(conn, did).id}")
    kind, target = auto_action(st, hero)
    return dungeons.submit_action(conn, content, did, kind, target, now)


def play(conn, content, ids, now=T0, max_rounds=80, stop=None):
    """Juega rondas con todos los jugadores indicados hasta que acabe (o `stop(view)`)."""
    events = []
    run_id = dungeons.get_my_run(conn, content, ids[0]).id
    for _ in range(max_rounds):
        view = dungeons.build_view(conn, content, run_id)
        if view.state != "active" or (stop and stop(view)):
            break
        for did in ids:
            try:
                hero_alive = next(h for h in view.battle.heroes
                                  if h.uid == f"c{characters.get_character(conn, did).id}")
                if not hero_alive.alive or hero_alive.stun > 0 or hero_alive.gone:
                    continue
                events += act(conn, content, did, now)
            except NotInDungeon:
                continue
        now += 60
    return events, now


def finished_summary(events):
    return next((e.summary for e in events if e.kind == "finished"), None)


def char_state(conn, did):
    c = characters.get_character(conn, did)
    return c.level, c.xp, c.gold


# ---------- crear / unirse / empezar ----------

def test_create_run_checks(conn, content):
    characters.create_character(conn, content, 1, "Novato", "guerrero")
    with pytest.raises(DungeonLevelTooLow):
        dungeons.create_run(conn, content, 1, D_ID, None, T0)
    ids = party(conn, content, 1, first_id=2)
    with pytest.raises(UnknownDungeon):
        dungeons.create_run(conn, content, ids[0], "narnia", None, T0)
    view = dungeons.create_run(conn, content, ids[0], "Cripta del Rey Hueco", 99, T0)  # por nombre
    assert view.state == "recruiting" and view.leader_name == name_of(2) and view.channel_id == 99
    with pytest.raises(AlreadyInDungeon):
        dungeons.create_run(conn, content, ids[0], D_ID, None, T0)
    assert view.recruit_deadline == T0 + content.dungeons[D_ID].recruit_seconds


def test_join_rules(conn, content):
    small = tweak(content, max_players=2)
    ids = party(conn, small, 4)
    characters.create_character(conn, small, 9, "Novato", "mago")
    view = dungeons.create_run(conn, small, ids[0], D_ID, None, T0)
    with pytest.raises(DungeonLevelTooLow):
        dungeons.join_run(conn, small, 9, view.id, T0)
    with pytest.raises(RunNotFound):
        dungeons.join_run(conn, small, ids[1], 999, T0)
    joined = dungeons.join_run(conn, small, ids[1], None, T0)       # sin id: la única que reúne gente
    assert [p.name for p in joined.participants] == [name_of(1), name_of(2)]
    with pytest.raises(AlreadyInDungeon):
        dungeons.join_run(conn, small, ids[1], view.id, T0)
    with pytest.raises(RunFull):
        dungeons.join_run(conn, small, ids[2], view.id, T0)


def test_joining_without_id_is_ambiguous_with_two_open_runs(conn, content):
    ids = party(conn, content, 3)
    dungeons.create_run(conn, content, ids[0], D_ID, None, T0)
    dungeons.create_run(conn, content, ids[1], D_ID, None, T0)
    with pytest.raises(RunNotFound):
        dungeons.join_run(conn, content, ids[2], None, T0)
    assert len(dungeons.list_open_runs(conn, content)) == 2


def test_start_rules(conn, content):
    ids, run_id = open_run(conn, content, 1)
    with pytest.raises(NotEnoughPlayers):
        dungeons.start_run(conn, content, ids[0], T0)
    ids = ids + party(conn, content, 2, first_id=10)
    dungeons.join_run(conn, content, ids[1], run_id, T0)
    with pytest.raises(NotLeader):
        dungeons.start_run(conn, content, ids[1], T0)
    with pytest.raises(NotInDungeon):
        dungeons.start_run(conn, content, ids[2], T0)
    event = dungeons.start_run(conn, content, ids[0], T0)
    assert event.kind == "started" and event.view.state == "active" and event.view.battle.round == 1
    assert event.view.round_deadline == T0 + content.dungeons[D_ID].turn_seconds
    assert event.view.intent_lines  # el enemigo ya ha anunciado lo que hará
    with pytest.raises(RunNotActive):
        dungeons.start_run(conn, content, ids[0], T0)
    with pytest.raises(RunNotFound):
        dungeons.join_run(conn, content, ids[2], run_id, T0)  # una partida empezada ya no admite jugadores


def test_recruitment_expires_and_frees_the_players(conn, content):
    ids, run_id = open_run(conn, content, 2)
    seconds = content.dungeons[D_ID].recruit_seconds
    assert dungeons.process_due(conn, content, T0 + seconds - 1) == []
    events = dungeons.process_due(conn, content, T0 + seconds)
    assert [e.kind for e in events] == ["cancelled"]
    assert dungeons.build_view(conn, content, run_id).state == "cancelled"
    with pytest.raises(NotInDungeon):
        dungeons.get_my_run(conn, content, ids[0])
    with pytest.raises(RunNotFound):
        dungeons.join_run(conn, content, ids[1], run_id, T0 + seconds + 5)
    dungeons.create_run(conn, content, ids[0], D_ID, None, T0 + seconds + 10)  # pueden empezar otra


def test_leaving_while_recruiting_hands_over_leadership_then_cancels(conn, content):
    ids, run_id = open_run(conn, content, 3)
    dungeons.leave_run(conn, content, ids[0], T0)
    view = dungeons.build_view(conn, content, run_id)
    assert view.leader_name == name_of(2) and view.state == "recruiting"
    dungeons.leave_run(conn, content, ids[1], T0)
    dungeons.leave_run(conn, content, ids[2], T0)
    assert dungeons.build_view(conn, content, run_id).state == "cancelled"
    with pytest.raises(NotInDungeon):
        dungeons.leave_run(conn, content, ids[2], T0)


# ---------- acciones y rondas ----------

def test_acted_round_updates(conn, content):
    cfg = easy(content)
    ids, run_id = started(conn, cfg, 2)
    # Submit an action for the first participant
    dungeons.submit_action(conn, cfg, ids[0], "attack", 1, T0 + 1)
    # Verify acted_round is set to the current round (1)
    cid = characters.get_character(conn, ids[0]).id
    row = conn.execute("SELECT acted_round FROM dungeon_participants WHERE character_id = ?", (cid,)).fetchone()
    assert row["acted_round"] == 1



def test_round_resolves_only_when_everyone_has_acted(conn, content):
    ids, run_id = started(conn, content, 3)
    first = dungeons.submit_action(conn, content, ids[0], "attack", 1, T0 + 1)
    assert [e.kind for e in first] == ["action"]
    view = dungeons.build_view(conn, content, run_id)
    assert [p.acted for p in view.participants] == [True, False, False] and view.battle.round == 1
    dungeons.submit_action(conn, content, ids[1], "attack", 1, T0 + 2)
    events = dungeons.submit_action(conn, content, ids[2], "defend", None, T0 + 3)
    assert "round" in [e.kind for e in events]
    view = dungeons.build_view(conn, content, run_id)
    assert view.battle.round == 2 and not any(p.acted for p in view.participants)
    assert view.round_deadline == T0 + 3 + content.dungeons[D_ID].turn_seconds
    assert dungeons.build_view(conn, content, run_id).battle.log


def test_a_player_can_change_their_mind_before_the_round_resolves(conn, content):
    ids, run_id = started(conn, content, 2)
    dungeons.submit_action(conn, content, ids[0], "attack", 1, T0)
    dungeons.submit_action(conn, content, ids[0], "defend", None, T0 + 1)
    rows = conn.execute("SELECT kind FROM dungeon_actions WHERE run_id = ?", (run_id,)).fetchall()
    assert [r["kind"] for r in rows] == ["defend"]


def test_no_action_runs_twice_for_the_same_round(conn, content):
    ids, run_id = started(conn, content, 2)
    for did in ids:
        dungeons.submit_action(conn, content, did, "defend", None, T0)
    assert dungeons.build_view(conn, content, run_id).battle.round == 2
    rounds = conn.execute("SELECT round, COUNT(*) AS n FROM dungeon_actions GROUP BY round").fetchall()
    assert [(r["round"], r["n"]) for r in rounds] == [(1, 2)]


def test_absence_flow_default_defend_then_auto_then_absent(conn, content):
    cfg = slow(content)
    ids, run_id = started(conn, cfg, 3)
    turn = cfg.dungeons[D_ID].turn_seconds
    clock = T0

    def participant(did):
        return next(p for p in dungeons.build_view(conn, cfg, run_id).participants
                    if p.character_id == characters.get_character(conn, did).id)

    # ronda 1 y 2: el tercero no actúa; se resuelve al vencer el plazo y defiende
    for expected_missed in (1, 2):
        dungeons.submit_action(conn, cfg, ids[0], "attack", 1, clock + 1)
        dungeons.submit_action(conn, cfg, ids[1], "attack", 1, clock + 2)
        assert dungeons.build_view(conn, cfg, run_id).battle.round == expected_missed
        clock += turn
        events = dungeons.process_due(conn, cfg, clock)
        assert any("Defiende" in l or "se cubre" in l for e in events for l in e.lines)
        p = participant(ids[2])
        assert p.missed_turns == expected_missed
        assert p.mode == ("auto" if expected_missed >= 2 else "manual")
    # en modo auto ya no hace falta esperarle: la ronda se resuelve en cuanto actúan los demás
    dungeons.submit_action(conn, cfg, ids[0], "attack", 1, clock + 1)
    events = dungeons.submit_action(conn, cfg, ids[1], "attack", 1, clock + 2)
    assert "round" in [e.kind for e in events]
    assert participant(ids[2]).missed_turns == 3 and participant(ids[2]).state == "active"
    dungeons.submit_action(conn, cfg, ids[0], "attack", 1, clock + 3)
    events = dungeons.submit_action(conn, cfg, ids[1], "attack", 1, clock + 4)
    p = participant(ids[2])
    assert p.state == "absent"
    assert any("ausente" in l for e in events for l in e.lines)
    with pytest.raises(NotInDungeon):
        dungeons.get_my_run(conn, cfg, ids[2])
    view = dungeons.build_view(conn, cfg, run_id)
    assert view.state == "active" and view.battle.heroes[2].gone  # el resto sigue jugando
    dungeons.create_run(conn, cfg, ids[2], D_ID, None, clock + 10)  # y el ausente queda libre


def test_acting_again_returns_an_auto_player_to_manual_control(conn, content):
    cfg = slow(content)
    ids, run_id = started(conn, cfg, 3)
    turn = cfg.dungeons[D_ID].turn_seconds
    clock = T0
    for _ in range(2):
        dungeons.submit_action(conn, cfg, ids[0], "attack", 1, clock + 1)
        dungeons.submit_action(conn, cfg, ids[1], "attack", 1, clock + 2)
        clock += turn
        dungeons.process_due(conn, cfg, clock)
    row = conn.execute("SELECT mode, missed_turns FROM dungeon_participants WHERE character_id = 3").fetchone()
    assert (row["mode"], row["missed_turns"]) == ("auto", 2)
    dungeons.submit_action(conn, cfg, ids[2], "attack", 1, clock + 1)
    row = conn.execute("SELECT mode, missed_turns FROM dungeon_participants WHERE character_id = 3").fetchone()
    assert (row["mode"], row["missed_turns"]) == ("manual", 0)


def test_overdue_rounds_are_caught_up_without_looping_forever(conn, content):
    cfg = slow(content)
    ids, run_id = started(conn, cfg, 3)
    events = dungeons.process_due(conn, cfg, T0 + 365 * 86400)  # un año de silencio
    view = dungeons.build_view(conn, cfg, run_id)
    assert view.state == "finished" and view.outcome == "abandoned" and finished_summary(events)
    assert all(p.state == "absent" for p in view.participants)


def test_when_everybody_vanishes_nobody_is_paid(conn, content):
    cfg = easy(content)
    ids, run_id = started(conn, cfg, 2)
    before = [char_state(conn, d) for d in ids]
    dungeons.process_due(conn, cfg, T0 + 365 * 86400)
    assert [char_state(conn, d) for d in ids] == before
    assert company.get_company(conn, cfg).storage == {}


# ---------- recompensas ----------

@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_full_run_pays_every_participant_once_and_the_company_once(conn, content, n):
    cfg = easy(content)
    ids, run_id = started(conn, cfg, n)
    before = {d: char_state(conn, d) for d in ids}
    events, _ = play(conn, cfg, ids)
    summary = finished_summary(events)
    assert summary is not None and summary.outcome == "win" and len(summary.cleared) == 3
    stages = cfg.dungeons[D_ID].stages
    xp_total, gold_total = sum(s.xp for s in stages), sum(s.gold for s in stages)
    for did, result in zip(ids, summary.participants):
        level, xp, gold = char_state(conn, did)
        assert result.factor == 1.0 and result.xp == xp_total
        assert gold == before[did][2] + gold_total + result.overflow_gold
        assert (level, xp) != (before[did][0], before[did][1])
    storage = company.get_company(conn, cfg).storage
    assert storage["gold"] == sum(s.shared_gold for s in stages)          # una vez, no por jugador
    assert storage["sello_del_sepulcro"] == 3
    for did in ids:
        with pytest.raises(NotInDungeon):
            dungeons.get_my_run(conn, cfg, did)                            # quedan libres
    dungeons.create_run(conn, cfg, ids[0], D_ID, None, T0 + 10_000)


def test_rewards_cannot_be_paid_twice(conn, content):
    cfg = easy(content)
    ids, run_id = started(conn, cfg, 3)
    play(conn, cfg, ids)
    snapshot = ([char_state(conn, d) for d in ids], company.get_company(conn, cfg).storage)
    dungeons.process_due(conn, cfg, T0 + 10**7)
    for did in ids:
        with pytest.raises(NotInDungeon):
            dungeons.submit_action(conn, cfg, did, "attack", 1, T0 + 10**7)
    with transaction(conn):
        run = conn.execute("SELECT * FROM dungeon_runs WHERE id = ?", (run_id,)).fetchone()
        with pytest.raises(RunNotActive):
            dungeons._finish_tx(conn, cfg, run, dungeons._load_state(cfg, run), "win", T0)
    assert snapshot == ([char_state(conn, d) for d in ids], company.get_company(conn, cfg).storage)


def test_loot_is_rolled_per_player_and_goes_to_their_inventory(conn, content):
    from kame.services import items

    cfg = easy(content)
    ids, run_id = started(conn, cfg, 4)
    events, _ = play(conn, cfg, ids)
    summary = finished_summary(events)
    for did, result in zip(ids, summary.participants):
        stored = {i.id for i in items.list_inventory(conn, cfg, did)}
        assert {i.id for i in result.items} <= stored
    total = sum(len(r.items) for r in summary.participants)
    assert total == conn.execute("SELECT COUNT(*) FROM item_instances WHERE source = ?",
                                 (f"dungeon:{D_ID}",)).fetchone()[0] and total >= 1


def test_low_participation_halves_personal_rewards(conn, content):
    cfg = easy(content)
    ids, run_id = started(conn, cfg, 3)
    cid = characters.get_character(conn, ids[2]).id
    with transaction(conn):
        conn.execute("UPDATE dungeon_participants SET eligible_rounds = 10, manual_rounds = 1"
                     " WHERE character_id = ?", (cid,))
    events, _ = play(conn, cfg, ids)
    summary = finished_summary(events)
    full, half = summary.participants[0], summary.participants[2]
    assert full.factor == 1.0 and half.factor == 0.5
    assert half.xp == round(full.xp * 0.5) and half.gold == round(full.gold * 0.5)
    assert company.get_company(conn, cfg).storage["gold"] == sum(
        s.shared_gold for s in cfg.dungeons[D_ID].stages)  # lo compartido no se reduce


def test_a_defeat_pays_only_the_rooms_that_were_cleared(conn, content):
    cfg = tweak(content, hp=0.15, dmg=0.4, boss=1000.0, max_rounds=18)
    ids, run_id = started(conn, cfg, 3)
    events, _ = play(conn, cfg, ids)
    summary = finished_summary(events)
    stages = cfg.dungeons[D_ID].stages
    assert summary.outcome == "loss" and len(summary.cleared) == 2
    assert summary.participants[0].xp == stages[0].xp + stages[1].xp
    storage = company.get_company(conn, cfg).storage
    assert "sello_del_sepulcro" not in storage                 # el jefe no cayó
    assert storage["gold"] == stages[0].shared_gold + stages[1].shared_gold


def test_leaver_gets_nothing_and_the_rest_continue_with_a_smaller_fight(conn, content):
    cfg = slow(content)
    ids, run_id = started(conn, cfg, 3)
    count = len(dungeons.build_view(conn, cfg, run_id).battle.enemies)
    events = dungeons.leave_run(conn, cfg, ids[2], T0 + 5)
    assert events[-1].kind == "left"
    view = dungeons.build_view(conn, cfg, run_id)
    assert view.state == "active" and len(view.battle.enemies) < count
    with pytest.raises(NotInDungeon):
        dungeons.submit_action(conn, cfg, ids[2], "attack", 1, T0 + 6)
    events, _ = play(conn, cfg, ids[:2], now=T0 + 10)
    summary = finished_summary(events)
    assert summary is not None
    leaver = next(p for p in summary.participants if p.state == "left")
    assert (leaver.xp, leaver.gold) == (0, 0) and char_state(conn, ids[2])[1:] == (0, 0)


def test_run_ends_when_too_few_players_remain_and_pays_cleared_rooms(conn, content):
    cfg = slow(content)
    ids, run_id = started(conn, cfg, 2)
    play(conn, cfg, ids, stop=lambda v: v.battle.stage >= 1)
    assert json.loads(conn.execute("SELECT cleared FROM dungeon_runs").fetchone()[0]) == [0]
    events = dungeons.leave_run(conn, cfg, ids[1], T0 + 99)
    summary = finished_summary(events)
    assert summary.outcome == "abandoned" and summary.cleared == (cfg.dungeons[D_ID].stages[0].name,)
    stayer = next(p for p in summary.participants if p.state == "active")
    assert stayer.xp == cfg.dungeons[D_ID].stages[0].xp
    assert char_state(conn, ids[1])[1:] == (0, 0)


# ---------- aislamiento, reinicios, concurrencia ----------

def test_two_runs_are_independent(conn, content):
    cfg = easy(content)
    ids_a, run_a = started(conn, cfg, 2)
    ids_b, run_b = open_run(conn, cfg, 2, first_id=10)
    dungeons.start_run(conn, cfg, ids_b[0], T0)
    play(conn, cfg, ids_a)
    assert dungeons.build_view(conn, cfg, run_a).state == "finished"
    view_b = dungeons.build_view(conn, cfg, run_b)
    assert view_b.state == "active" and view_b.battle.round == 1
    assert char_state(conn, ids_b[0])[1:] == (0, 0)


def test_the_battle_survives_a_bot_restart(db_path, content):
    cfg = easy(content)
    c1 = connect(db_path)
    ids, run_id = started(c1, cfg, 3)
    act(c1, cfg, ids[0], T0 + 1)
    c1.close()  # "reinicio"
    c2 = connect(db_path)
    view = dungeons.build_view(c2, cfg, run_id)
    assert view.battle.round == 1 and [p.acted for p in view.participants] == [True, False, False]
    events, _ = play(c2, cfg, ids, now=T0 + 10)
    assert finished_summary(events).outcome == "win"
    c2.close()


def test_downtime_extends_the_deadlines_instead_of_punishing_players(conn, content):
    cfg = slow(content)
    ids, run_id = started(conn, cfg, 3)
    turn = cfg.dungeons[D_ID].turn_seconds
    dungeons.touch_heartbeat(conn, T0 + 60)
    down = turn + 5000  # el bot estuvo apagado más que un plazo entero
    assert dungeons.apply_downtime_grace(conn, T0 + 60 + down) == down
    view = dungeons.build_view(conn, cfg, run_id)
    assert view.round_deadline == T0 + turn + down
    assert dungeons.process_due(conn, cfg, T0 + 60 + down) == []   # nadie ha perdido su turno
    assert dungeons.apply_downtime_grace(conn, T0 + 60 + down + 30) == 0   # un parón corto no prorroga


def test_a_far_stronger_character_is_capped_inside_the_dungeon(conn, content):
    cfg = easy(content)
    ids, run_id = open_run(conn, cfg, 2)
    cid = characters.get_character(conn, ids[0]).id
    with transaction(conn):
        conn.execute("UPDATE characters SET level = 40, fuerza = 900, vitalidad = 900 WHERE id = ?", (cid,))
    dungeons.start_run(conn, cfg, ids[0], T0)
    hero = dungeons.build_view(conn, cfg, run_id).battle.heroes[0]
    cap = cfg.dungeons[D_ID].hero_rating_cap
    assert math.sqrt(hero.c.power * hero.c.max_hp) == pytest.approx(cap, rel=0.02)


def test_concurrent_final_actions_resolve_the_round_exactly_once(db_path, content):
    cfg = slow(content)
    setup = connect(db_path)
    ids, run_id = started(setup, cfg, 3)
    setup.close()
    barrier = threading.Barrier(3)
    kinds = []

    def worker(did):
        c = connect(db_path)
        try:
            barrier.wait()
            events = dungeons.submit_action(c, cfg, did, "attack", 1, T0 + 5)
            kinds.extend(e.kind for e in events)
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(d,)) for d in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert kinds.count("round") == 1
    check = connect(db_path)
    assert check.execute("SELECT round FROM dungeon_runs").fetchone()[0] == 2
    assert check.execute("SELECT COUNT(*) FROM dungeon_actions WHERE round = 1").fetchone()[0] == 3


def test_concurrent_starts_begin_the_run_once(db_path, content):
    setup = connect(db_path)
    ids, run_id = open_run(setup, content, 2)
    setup.close()
    results, barrier = [], threading.Barrier(3)

    def worker():
        c = connect(db_path)
        try:
            barrier.wait()
            dungeons.start_run(c, content, ids[0], T0)
            results.append("ok")
        except RunNotActive:
            results.append("ya empezada")
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "ya empezada", "ya empezada"]


def test_concurrent_joins_respect_the_capacity(db_path, content):
    small = tweak(content, max_players=3)
    setup = connect(db_path)
    ids = party(setup, small, 5)
    view = dungeons.create_run(setup, small, ids[0], D_ID, None, T0)
    setup.close()
    results, barrier = [], threading.Barrier(4)

    def worker(did):
        c = connect(db_path)
        try:
            barrier.wait()
            dungeons.join_run(c, small, did, view.id, T0)
            results.append("ok")
        except RunFull:
            results.append("llena")
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(d,)) for d in ids[1:]]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 2 and results.count("llena") == 2


def test_party_without_any_particular_class_can_finish(conn, content):
    cfg = easy(content)
    for did in (1, 2):
        characters.create_character(conn, cfg, did, name_of(did, "Mago"), "mago")
        cid = characters.get_character(conn, did).id
        with transaction(conn):
            conn.execute("UPDATE characters SET level = 8 WHERE id = ?", (cid,))
    view = dungeons.create_run(conn, cfg, 1, D_ID, None, T0)
    dungeons.join_run(conn, cfg, 2, view.id, T0)
    dungeons.start_run(conn, cfg, 1, T0)
    events, _ = play(conn, cfg, [1, 2])
    assert finished_summary(events).outcome in ("win", "loss")


def test_activity_log_records_dungeon_events(conn, content):
    cfg = easy(content)
    ids, run_id = started(conn, cfg, 2)
    play(conn, cfg, ids)
    cid = characters.get_character(conn, ids[0]).id
    kinds = [r[0] for r in conn.execute("SELECT kind FROM activity_log WHERE character_id = ?", (cid,))]
    assert {"dungeon_created", "dungeon_started", "dungeon_finished", "dungeon_action"} <= set(kinds)
