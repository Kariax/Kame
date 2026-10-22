"""Servicio de mazmorras cooperativas: reunir grupo, jugar rondas, ausencias y recompensas.

Reglas de ausencias (previsibles y fáciles de explicar)
-------------------------------------------------------
- Si todos los jugadores que deben actuar ya han elegido acción, la ronda se resuelve al instante.
- Si no, se resuelve al llegar el plazo de la ronda (por defecto 12 h): quien no actuó DEFIENDE.
- 2 rondas seguidas sin actuar => modo AUTOMÁTICO (el juego juega por ti con la lógica de las
  expediciones). Actuar de nuevo te devuelve al control manual.
- 4 rondas seguidas sin actuar => AUSENTE: sales de la partida y no cobras recompensas.
- Abandonar es inmediato y tampoco da recompensas. Si quedan menos jugadores del mínimo, la partida
  termina y quien siga en ella cobra las salas ya superadas. Si se va alguien y quedan suficientes, los
  enemigos se reajustan al grupo restante (una ausencia no condena al resto).
- Si la partida no reúne al mínimo de jugadores antes del plazo de reclutamiento, se cancela.
- Quien actuó en menos de la mitad de las rondas en las que podía actuar cobra la MITAD de las
  recompensas personales (así no se gana nada extra "aprovechando" una ausencia).
- Recompensas: XP/oro y botín personales por cada sala superada (cada jugador tira su botín por
  separado); los recursos de la compañía se reparten una sola vez por sala, no por jugador.
- Si el bot estuvo apagado, los plazos se prorrogan el tiempo que estuvo caído.

Todo se calcula con marcas de tiempo guardadas: no hace falta ningún temporizador en memoria.
"""
from __future__ import annotations

import json
import random
import secrets
import sqlite3
import time
from dataclasses import dataclass, field

from kame.content import Content
from kame.db.database import transaction
from kame.engine.build import build_combatant
from kame.engine.dungeon import (
    DungeonDef,
    DungeonState,
    RoundReport,
    auto_action,
    describe_intents,
    make_hero,
    new_state,
    rescale_after_departure,
    resolve_round,
    roll_intents,
    state_from_dict,
    state_to_dict,
    validate_action,
)
from kame.engine.items import index_templates, roll_item
from kame.engine.models import Character
from kame.services import company
from kame.services.characters import _log, _row_to_character, get_character, grant_xp_tx
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
from kame.services.items import ItemInstance, current_build, insert_items_tx, plan_new_items

HEARTBEAT_KEY = "heartbeat"
DOWNTIME_THRESHOLD = 120  # segundos de silencio a partir de los cuales se prorrogan plazos


# ---------------------------------------------------------------------------
# Vistas y eventos (lo que consume el bot)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParticipantView:
    character_id: int
    uid: str
    name: str
    class_id: str
    state: str
    mode: str
    missed_turns: int
    acted: bool


@dataclass(frozen=True)
class RunView:
    id: int
    dungeon: DungeonDef
    state: str
    leader_id: int
    leader_name: str
    participants: tuple[ParticipantView, ...]
    round: int
    round_deadline: int | None
    recruit_deadline: int
    battle: DungeonState | None
    outcome: str | None
    channel_id: int | None
    intent_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParticipantResult:
    name: str
    state: str
    xp: int
    gold: int
    factor: float
    levels_gained: int
    items: tuple[ItemInstance, ...]
    overflow_gold: int


@dataclass(frozen=True)
class FinishSummary:
    outcome: str
    cleared: tuple[str, ...]
    participants: tuple[ParticipantResult, ...]
    shared: dict[str, int]


@dataclass(frozen=True)
class RunEvent:
    kind: str  # started | round | finished | cancelled | left
    run_id: int
    channel_id: int | None
    lines: tuple[str, ...] = ()
    view: RunView | None = None
    summary: FinishSummary | None = None


@dataclass(frozen=True)
class OpenRun:
    id: int
    dungeon_name: str
    leader_name: str
    players: int
    max_players: int
    recruit_deadline: int


def _now() -> int:
    return int(time.time())


def _uid(character_id: int) -> str:
    return f"c{character_id}"


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _run_row(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM dungeon_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise RunNotFound()
    return row


def _participants(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT p.*, c.name AS name, c.class_id AS class_id FROM dungeon_participants p"
        " JOIN characters c ON c.id = p.character_id WHERE p.run_id = ?"
        " ORDER BY p.joined_at, p.character_id",
        (run_id,),
    ).fetchall()


def _open_participation(conn: sqlite3.Connection, character_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM dungeon_participants WHERE character_id = ? AND open = 1", (character_id,)
    ).fetchone()


def _character_by_id(conn: sqlite3.Connection, character_id: int) -> Character:
    return _row_to_character(conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone())


def _discord_id_of(conn: sqlite3.Connection, character_id: int) -> int:
    return conn.execute(
        "SELECT p.discord_id FROM players p JOIN characters c ON c.player_id = p.id WHERE c.id = ?",
        (character_id,),
    ).fetchone()[0]


def _load_state(content: Content, run: sqlite3.Row) -> DungeonState | None:
    return state_from_dict(json.loads(run["battle"]), content.skills) if run["battle"] else None


def build_view(conn: sqlite3.Connection, content: Content, run_id: int) -> RunView:
    run = _run_row(conn, run_id)
    state = _load_state(content, run)
    acted: set[int] = set()
    if state is not None and run["state"] == "active":
        acted = {r["character_id"] for r in conn.execute(
            "SELECT character_id FROM dungeon_actions WHERE run_id = ? AND round = ?",
            (run_id, state.round))}
    parts = _participants(conn, run_id)
    leader = next((p["name"] for p in parts if p["character_id"] == run["leader_character_id"]), "?")
    return RunView(
        id=run_id, dungeon=content.dungeons[run["dungeon_id"]], state=run["state"],
        leader_id=run["leader_character_id"], leader_name=leader,
        participants=tuple(
            ParticipantView(p["character_id"], _uid(p["character_id"]), p["name"], p["class_id"],
                            p["state"], p["mode"], p["missed_turns"], p["character_id"] in acted)
            for p in parts
        ),
        round=state.round if state else 0, round_deadline=run["round_deadline"],
        recruit_deadline=run["recruit_deadline"], battle=state, outcome=run["outcome"],
        channel_id=run["channel_id"],
        intent_lines=tuple(describe_intents(state)) if state and run["state"] == "active" else (),
    )


def list_open_runs(conn: sqlite3.Connection, content: Content) -> list[OpenRun]:
    rows = conn.execute("SELECT id FROM dungeon_runs WHERE state = 'recruiting' ORDER BY id").fetchall()
    result = []
    for row in rows:
        view = build_view(conn, content, row["id"])
        active = sum(1 for p in view.participants if p.state == "active")
        result.append(OpenRun(view.id, view.dungeon.name, view.leader_name, active,
                              view.dungeon.max_players, view.recruit_deadline))
    return result


def get_my_run(conn: sqlite3.Connection, content: Content, discord_id: int) -> RunView:
    character = get_character(conn, discord_id)
    part = _open_participation(conn, character.id)
    if part is None:
        raise NotInDungeon()
    return build_view(conn, content, part["run_id"])


# ---------------------------------------------------------------------------
# Crear, unirse, salir, empezar
# ---------------------------------------------------------------------------

def _dungeon(content: Content, raw: str) -> DungeonDef:
    key = (raw or "").strip().lower()
    if key in content.dungeons:
        return content.dungeons[key]
    found = next((d for d in content.dungeons.values() if d.name.lower() == key), None)
    if found is None:
        raise UnknownDungeon()
    return found


def create_run(conn: sqlite3.Connection, content: Content, discord_id: int, dungeon_id: str,
               channel_id: int | None = None, now: int | None = None) -> RunView:
    now = _now() if now is None else int(now)
    dungeon = _dungeon(content, dungeon_id)
    try:
        with transaction(conn):
            character = get_character(conn, discord_id)
            if character.level < dungeon.min_level:
                raise DungeonLevelTooLow(dungeon.name, dungeon.min_level)
            if _open_participation(conn, character.id):
                raise AlreadyInDungeon()
            run_id = conn.execute(
                "INSERT INTO dungeon_runs (dungeon_id, leader_character_id, state, channel_id, seed,"
                " recruit_deadline, created_at) VALUES (?, ?, 'recruiting', ?, ?, ?, ?)",
                (dungeon.id, character.id, channel_id, secrets.randbits(62),
                 now + dungeon.recruit_seconds, now),
            ).lastrowid
            conn.execute(
                "INSERT INTO dungeon_participants (run_id, character_id, state, joined_at)"
                " VALUES (?, ?, 'active', ?)", (run_id, character.id, now))
            _log(conn, character.id, "dungeon_created", {"run": run_id, "dungeon": dungeon.id})
    except sqlite3.IntegrityError:
        raise AlreadyInDungeon() from None
    return build_view(conn, content, run_id)


def join_run(conn: sqlite3.Connection, content: Content, discord_id: int, run_id: int | None = None,
             now: int | None = None) -> RunView:
    now = _now() if now is None else int(now)
    process_due(conn, content, now)
    try:
        with transaction(conn):
            character = get_character(conn, discord_id)
            if _open_participation(conn, character.id):
                raise AlreadyInDungeon()
            if run_id is None:
                rows = conn.execute("SELECT id FROM dungeon_runs WHERE state = 'recruiting'").fetchall()
                if len(rows) != 1:
                    raise RunNotFound()
                run_id = rows[0]["id"]
            run = conn.execute("SELECT * FROM dungeon_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None or run["state"] != "recruiting":
                raise RunNotFound()
            dungeon = content.dungeons[run["dungeon_id"]]
            if character.level < dungeon.min_level:
                raise DungeonLevelTooLow(dungeon.name, dungeon.min_level)
            count = sum(1 for p in _participants(conn, run_id) if p["state"] == "active")
            if count >= dungeon.max_players:
                raise RunFull()
            conn.execute(
                "INSERT INTO dungeon_participants (run_id, character_id, state, joined_at)"
                " VALUES (?, ?, 'active', ?)", (run_id, character.id, now))
            _log(conn, character.id, "dungeon_joined", {"run": run_id})
    except sqlite3.IntegrityError:
        raise AlreadyInDungeon() from None
    return build_view(conn, content, run_id)


def start_run(conn: sqlite3.Connection, content: Content, discord_id: int,
              now: int | None = None) -> RunEvent:
    now = _now() if now is None else int(now)
    process_due(conn, content, now)
    with transaction(conn):
        character = get_character(conn, discord_id)
        part = _open_participation(conn, character.id)
        if part is None:
            raise NotInDungeon()
        run = _run_row(conn, part["run_id"])
        if run["leader_character_id"] != character.id:
            raise NotLeader()
        if run["state"] != "recruiting":
            raise RunNotActive()
        dungeon = content.dungeons[run["dungeon_id"]]
        members = [p for p in _participants(conn, run["id"]) if p["state"] == "active"]
        if len(members) < dungeon.min_players:
            raise NotEnoughPlayers(dungeon.min_players)
        heroes = []
        for p in members:
            char = _character_by_id(conn, p["character_id"])
            build = current_build(conn, content, char)
            heroes.append(make_hero(_uid(char.id), char.name, build_combatant(build), dungeon.hero_rating_cap))
        state = new_state(dungeon, heroes, content.dungeon_enemies, run["seed"])
        conn.execute(
            "UPDATE dungeon_runs SET state = 'active', battle = ?, round = ?, round_deadline = ?,"
            " started_at = ? WHERE id = ?",
            (json.dumps(state_to_dict(state)), state.round, now + dungeon.turn_seconds, now, run["id"]),
        )
        for p in members:
            _log(conn, p["character_id"], "dungeon_started", {"run": run["id"]})
    view = build_view(conn, content, run["id"])
    return RunEvent("started", run["id"], run["channel_id"], tuple(state.log), view)


def leave_run(conn: sqlite3.Connection, content: Content, discord_id: int,
              now: int | None = None) -> list[RunEvent]:
    now = _now() if now is None else int(now)
    events = process_due(conn, content, now)
    with transaction(conn):
        character = get_character(conn, discord_id)
        part = _open_participation(conn, character.id)
        if part is None:
            raise NotInDungeon()
        run = _run_row(conn, part["run_id"])
        conn.execute(
            "UPDATE dungeon_participants SET state = 'left', open = 0 WHERE run_id = ? AND character_id = ?",
            (run["id"], character.id))
        remaining = [p for p in _participants(conn, run["id"]) if p["state"] == "active"]
        lines = [f"**{character.name}** abandona la partida."]
        if run["state"] == "recruiting":
            if not remaining:
                conn.execute("UPDATE dungeon_runs SET state = 'cancelled', outcome = 'abandoned',"
                             " finished_at = ? WHERE id = ?", (now, run["id"]))
                lines.append("La partida se cancela: no queda nadie.")
            elif run["leader_character_id"] == character.id:
                conn.execute("UPDATE dungeon_runs SET leader_character_id = ? WHERE id = ?",
                             (remaining[0]["character_id"], run["id"]))
                lines.append(f"**{remaining[0]['name']}** es ahora el líder.")
        elif run["state"] == "active":
            state = _load_state(content, run)
            hero = next(h for h in state.heroes if h.uid == _uid(character.id))
            hero.gone = True
            rescale_after_departure(state, content.dungeons[run["dungeon_id"]])
            conn.execute("UPDATE dungeon_runs SET battle = ? WHERE id = ?",
                         (json.dumps(state_to_dict(state)), run["id"]))
            if len(remaining) < content.dungeons[run["dungeon_id"]].min_players:
                lines.append("La partida no puede continuar: quedan menos jugadores del mínimo.")
                summary = _finish_tx(conn, content, run, state, "abandoned", now)
                events.append(RunEvent("finished", run["id"], run["channel_id"], tuple(lines),
                                       build_view(conn, content, run["id"]), summary))
                _log(conn, character.id, "dungeon_left", {"run": run["id"]})
                return events
        _log(conn, character.id, "dungeon_left", {"run": run["id"]})
    events.append(RunEvent("left", run["id"], run["channel_id"], tuple(lines),
                           build_view(conn, content, run["id"])))
    return events


# ---------------------------------------------------------------------------
# Acciones y rondas
# ---------------------------------------------------------------------------

def _required(parts: list[sqlite3.Row], state: DungeonState) -> list[sqlite3.Row]:
    """Participantes que deben elegir acción esta ronda (activos, en pie, sin aturdir, en modo manual).
    Usa la columna denormalizada `acted_round` para saber quién ya ha actuado en la ronda actual.
    """
    required = []
    for p in parts:
        if p["state"] != "active" or p["mode"] != "manual":
            continue
        # Si el participante ya tiene acted_round >= ronda actual, ya actuó.
        if p["acted_round"] >= state.round:
            continue
        hero = next((h for h in state.heroes if h.uid == _uid(p["character_id"])), None)
        if hero is not None and hero.alive and hero.stun == 0:
            required.append(p)
    return required


def submit_action(conn: sqlite3.Connection, content: Content, discord_id: int, kind: str,
                  target: int | None = None, now: int | None = None) -> list[RunEvent]:
    """Registra la acción del jugador. Si ya han actuado todos, resuelve la ronda."""
    now = _now() if now is None else int(now)
    events = process_due(conn, content, now)
    with transaction(conn):
        character = get_character(conn, discord_id)
        part = _open_participation(conn, character.id)
        if part is None:
            raise NotInDungeon()
        run = _run_row(conn, part["run_id"])
        if run["state"] != "active":
            raise RunNotActive()
        state = _load_state(content, run)
        hero = next(h for h in state.heroes if h.uid == _uid(character.id))
        error = validate_action(state, hero, kind, target)
        if error:
            raise InvalidAction(error)
        if hero.stun > 0:
            raise InvalidAction("Estás aturdido: perderás este turno hagas lo que hagas.")
        conn.execute(
            "INSERT INTO dungeon_actions (run_id, round, character_id, kind, target, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(run_id, round, character_id)"
            " DO UPDATE SET kind = excluded.kind, target = excluded.target",
            (run["id"], state.round, character.id, kind, target, now))
        # Log the action for activity tracking
        _log(conn, character.id, "dungeon_action", {"kind": kind, "target": target})
        conn.execute(
            "UPDATE dungeon_participants SET acted_round = ?"
            " WHERE run_id = ? AND character_id = ?",
            (state.round, run["id"], character.id))
        if part["mode"] == "auto":  # vuelve al control manual
            conn.execute("UPDATE dungeon_participants SET mode = 'manual', missed_turns = 0"
                         " WHERE run_id = ? AND character_id = ?", (run["id"], character.id))
        parts = _participants(conn, run["id"])
        pending = _required(parts, state)
        if not pending:
            events.extend(_resolve_tx(conn, content, _run_row(conn, run["id"]), now, due=False))
    if not any(e.view and e.run_id == run["id"] for e in events):
        events.append(RunEvent("action", run["id"], run["channel_id"], (), build_view(conn, content, run["id"])))
    return events


def _resolve_tx(conn: sqlite3.Connection, content: Content, run: sqlite3.Row, now: int,
                due: bool) -> list[RunEvent]:
    """Resuelve la ronda actual (dentro de una transacción) y gestiona ausencias y final."""
    dungeon = content.dungeons[run["dungeon_id"]]
    state = _load_state(content, run)
    parts = _participants(conn, run["id"])
    submitted = {r["character_id"]: (r["kind"], r["target"]) for r in conn.execute(
        "SELECT character_id, kind, target FROM dungeon_actions WHERE run_id = ? AND round = ?",
        (run["id"], state.round))}

    actions: dict[str, tuple[str, int | None]] = {}
    absent_now: list[int] = []
    for p in parts:
        if p["state"] != "active":
            continue
        uid = _uid(p["character_id"])
        hero = next((h for h in state.heroes if h.uid == uid), None)
        if hero is None or not hero.alive or hero.stun > 0:
            continue
        if p["character_id"] in submitted:
            actions[uid] = submitted[p["character_id"]]
            conn.execute(
                "UPDATE dungeon_participants SET eligible_rounds = eligible_rounds + 1,"
                " manual_rounds = manual_rounds + 1, missed_turns = 0, mode = 'manual'"
                " WHERE run_id = ? AND character_id = ?", (run["id"], p["character_id"]))
            continue
        actions[uid] = auto_action(state, hero) if p["mode"] == "auto" else ("defend", None)
        missed = p["missed_turns"] + 1
        mode = "auto" if missed >= dungeon.auto_after_missed else p["mode"]
        conn.execute(
            "UPDATE dungeon_participants SET eligible_rounds = eligible_rounds + 1,"
            " missed_turns = ?, mode = ? WHERE run_id = ? AND character_id = ?",
            (missed, mode, run["id"], p["character_id"]))
        if missed >= dungeon.absent_after_missed:
            absent_now.append(p["character_id"])

    report: RoundReport = resolve_round(state, dungeon, content.dungeon_enemies, actions)
    lines = list(report.events)

    for character_id in absent_now:
        hero = next(h for h in state.heroes if h.uid == _uid(character_id))
        hero.gone = True
        conn.execute("UPDATE dungeon_participants SET state = 'absent', open = 0"
                     " WHERE run_id = ? AND character_id = ?", (run["id"], character_id))
        name = next(p["name"] for p in parts if p["character_id"] == character_id)
        lines.append(f"🚪 **{name}** lleva demasiadas rondas ausente y abandona la partida.")
    if absent_now and not report.outcome:
        rescale_after_departure(state, dungeon)

    cleared = json.loads(run["cleared"]) + report.cleared_stages
    outcome = report.outcome
    still_in = [p for p in _participants(conn, run["id"]) if p["state"] == "active"]
    if outcome is None and len(still_in) < dungeon.min_players:
        outcome = "abandoned"  # no quedan jugadores suficientes para continuar
        lines.append("La partida no puede continuar: quedan menos jugadores del mínimo.")

    next_deadline = (run["round_deadline"] + dungeon.turn_seconds) if due and run["round_deadline"] else now + dungeon.turn_seconds
    conn.execute(
        "UPDATE dungeon_runs SET battle = ?, round = ?, round_deadline = ?, cleared = ? WHERE id = ?",
        (json.dumps(state_to_dict(state)), state.round, next_deadline, json.dumps(cleared), run["id"]))

    events = [RunEvent("round", run["id"], run["channel_id"], tuple(lines),
                       build_view(conn, content, run["id"]))]
    if outcome:
        fresh = _run_row(conn, run["id"])
        summary = _finish_tx(conn, content, fresh, state, outcome, now)
        events.append(RunEvent("finished", run["id"], run["channel_id"], (),
                               build_view(conn, content, run["id"]), summary))
    return events


def _finish_tx(conn: sqlite3.Connection, content: Content, run: sqlite3.Row, state: DungeonState,
               outcome: str, now: int) -> FinishSummary:
    """Cierra la partida y reparte recompensas UNA sola vez (guardia en la BD)."""
    dungeon = content.dungeons[run["dungeon_id"]]
    cleared = json.loads(run["cleared"])
    parts = _participants(conn, run["id"])
    members = [p for p in parts if p["state"] == "active"]
    cfg = content.config
    grouped = index_templates(content.item_templates,
                              dungeon.recommended_level + cfg.items.drop_level_margin)

    shared: dict[str, int] = {}
    if members:
        for index in cleared:
            stage = dungeon.stages[index]
            if stage.shared_gold:
                shared["gold"] = shared.get("gold", 0) + stage.shared_gold
            for material, amount in stage.shared_materials.items():
                shared[material] = shared.get(material, 0) + amount

    plans = []
    for p in members:
        eligible, manual = p["eligible_rounds"], p["manual_rounds"]
        factor = 1.0 if eligible == 0 or manual / eligible >= 0.5 else 0.5
        xp = int(round(sum(dungeon.stages[i].xp for i in cleared) * factor))
        gold = int(round(sum(dungeon.stages[i].gold for i in cleared) * factor))
        rng = random.Random(f"{run['seed']}:loot:{p['character_id']}")
        drops = []
        for index in cleared:
            for roll in dungeon.stages[index].loot:
                if rng.random() < roll.chance * factor:
                    weights = cfg.items.elite_weights if roll.pool == "elite" else cfg.items.normal_weights
                    drop = roll_item(rng, grouped, weights, roll.quality, cfg.items.stat_variance)
                    if drop is not None:
                        drops.append(drop)
        added = plan_new_items(conn, content, p["character_id"], tuple(drops))
        plans.append((p, factor, xp, gold, added))

    names = tuple(dungeon.stages[i].name for i in cleared)
    summary_payload = {
        "outcome": outcome, "cleared": list(names), "shared": shared,
        "participants": [
            {"character_id": p["character_id"], "name": p["name"], "xp": xp, "gold": gold + added.overflow_gold,
             "factor": factor, "items": [i.id for i in added.kept]}
            for p, factor, xp, gold, added in plans],
    }
    closed = conn.execute(
        "UPDATE dungeon_runs SET state = 'finished', outcome = ?, rewards_resolved = 1, result = ?,"
        " finished_at = ? WHERE id = ? AND rewards_resolved = 0 AND state = 'active'",
        (outcome, json.dumps(summary_payload), now, run["id"]))
    if closed.rowcount != 1:  # ya resuelta: no se paga nada
        raise RunNotActive()
    conn.execute("UPDATE dungeon_participants SET open = 0 WHERE run_id = ?", (run["id"],))

    for resource, amount in shared.items():
        company.add_shared_tx(conn, resource, amount, f"dungeon:{run['id']}")

    results = []
    for p, factor, xp, gold, added in plans:
        xp_result = grant_xp_tx(conn, cfg.progression, p["character_id"], xp, f"dungeon:{dungeon.id}")
        conn.execute("UPDATE characters SET gold = gold + ? WHERE id = ?",
                     (gold + added.overflow_gold, p["character_id"]))
        insert_items_tx(conn, p["character_id"], added.kept, f"dungeon:{dungeon.id}")
        _log(conn, p["character_id"], "dungeon_finished",
             {"run": run["id"], "outcome": outcome, "xp": xp, "gold": gold, "factor": factor})
        results.append(ParticipantResult(p["name"], "active", xp, gold, factor, xp_result.levels_gained,
                                         added.kept, added.overflow_gold))
    for p in parts:
        if p["state"] != "active":
            results.append(ParticipantResult(p["name"], p["state"], 0, 0, 0.0, 0, (), 0))
    return FinishSummary(outcome, names, tuple(results), shared)


# ---------------------------------------------------------------------------
# Plazos (se evalúan al consultar y desde la tarea periódica del bot)
# ---------------------------------------------------------------------------

def process_due(conn: sqlite3.Connection, content: Content, now: int | None = None) -> list[RunEvent]:
    """Cancela reclutamientos caducados y resuelve rondas cuyo plazo venció."""
    now = _now() if now is None else int(now)
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM dungeon_runs WHERE (state = 'recruiting' AND recruit_deadline <= ?)"
        " OR (state = 'active' AND round_deadline <= ?) ORDER BY id", (now, now))]
    events: list[RunEvent] = []
    for run_id in ids:
        for _ in range(500):  # tope de seguridad
            with transaction(conn):
                run = _run_row(conn, run_id)
                if run["state"] == "recruiting" and run["recruit_deadline"] <= now:
                    conn.execute("UPDATE dungeon_runs SET state = 'cancelled', outcome = 'abandoned',"
                                 " finished_at = ? WHERE id = ?", (now, run_id))
                    conn.execute("UPDATE dungeon_participants SET open = 0 WHERE run_id = ?", (run_id,))
                    events.append(RunEvent("cancelled", run_id, run["channel_id"],
                                           ("La partida se cancela: no se reunió el grupo a tiempo.",),
                                           build_view(conn, content, run_id)))
                    break
                if run["state"] == "active" and run["round_deadline"] is not None \
                        and run["round_deadline"] <= now:
                    events.extend(_resolve_tx(conn, content, run, now, due=True))
                    continue
                break
    return events


def touch_heartbeat(conn: sqlite3.Connection, now: int | None = None) -> None:
    now = _now() if now is None else int(now)
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (HEARTBEAT_KEY, str(now)))


def apply_downtime_grace(conn: sqlite3.Connection, now: int | None = None) -> int:
    """Si el bot estuvo apagado, prorroga los plazos de las partidas abiertas. Devuelve los segundos."""
    now = _now() if now is None else int(now)
    with transaction(conn):
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (HEARTBEAT_KEY,)).fetchone()
        extension = 0
        if row is not None:
            gap = now - int(row["value"])
            if gap > DOWNTIME_THRESHOLD:
                extension = gap
                conn.execute("UPDATE dungeon_runs SET round_deadline = round_deadline + ?"
                             " WHERE state = 'active'", (extension,))
                conn.execute("UPDATE dungeon_runs SET recruit_deadline = recruit_deadline + ?"
                             " WHERE state = 'recruiting'", (extension,))
        touch_heartbeat(conn, now)
    return extension
