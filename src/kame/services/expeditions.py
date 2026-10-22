"""Servicio de expediciones: empezar, consultar y reclamar de forma segura.

Garantías:
- Una sola expedición abierta por personaje (índice único parcial en la BD).
- Las recompensas dependen solo de marcas de tiempo y de la semilla guardadas: no hay
  temporizadores en memoria, así que reiniciar el bot no afecta a nada.
- Reclamar es una única transacción (XP, oro, materiales y cierre de la expedición). La
  expedición se cierra con `UPDATE ... WHERE claimed_at IS NULL`, de modo que una segunda
  reclamación (o dos a la vez) no puede cobrar dos veces.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass

from kame.content import Content
from kame.db.database import transaction
from kame.engine.build import build_combatant, build_stats
from kame.engine.combat import CombatLogEntry
from kame.engine.expeditions import (
    ExpeditionDef,
    ExpeditionOutcome,
    encounters_available,
    resolve_expedition,
    seconds_until_next_encounter,
)
from kame.engine.progression import XpResult, apply_xp
from kame.services import company
from kame.services.characters import _log, get_character, grant_xp_tx
from kame.services.items import (
    ItemInstance,
    build_from_snapshot,
    current_build,
    insert_items_tx,
    plan_new_items,
    snapshot_from_build,
)
from kame.services.ranking import update_character_score
from kame.services.errors import (
    ExpeditionInProgress,
    LevelTooLow,
    NoActiveExpedition,
    NothingToClaimYet,
    UnknownExpedition,
)


@dataclass(frozen=True)
class ActiveExpedition:
    id: int
    definition: ExpeditionDef
    started_at: int
    elapsed_seconds: int
    encounters_ready: int
    max_encounters: int
    seconds_to_next: int | None  # None = límite de acumulación alcanzado
    seconds_to_full: int
    # Datos del último combate resuelto (si hay alguno)
    last_combat_log: tuple[CombatLogEntry, ...] = ()
    last_enemy_id: str = ""
    last_enemy_name: str = ""
    last_enemy_hp: int = 0
    last_enemy_max_hp: int = 0
    last_player_hp: int = 0
    last_player_max_hp: int = 0
    last_player_won: bool = True


@dataclass(frozen=True)
class ClaimResult:
    definition: ExpeditionDef
    outcome: ExpeditionOutcome
    xp_result: XpResult
    elapsed_seconds: int
    items: tuple[ItemInstance, ...] = ()           # objetos que entraron al inventario
    overflow_items: tuple[ItemInstance, ...] = ()  # vendidos solos por inventario lleno
    overflow_gold: int = 0
    bonus_xp: int = 0     # extra por mejoras de la compañía (Armería)
    bonus_gold: int = 0


def _now() -> int:
    return int(time.time())


def _find_expedition(content: Content, raw: str) -> ExpeditionDef:
    key = (raw or "").strip().lower()
    if key in content.expeditions:
        return content.expeditions[key]
    for definition in content.expeditions.values():
        if definition.name.lower() == key:
            return definition
    raise UnknownExpedition()


def start_expedition(
    conn: sqlite3.Connection,
    content: Content,
    discord_id: int,
    expedition_id: str,
    now: int | None = None,
) -> ExpeditionDef:
    now = _now() if now is None else int(now)
    definition = _find_expedition(content, expedition_id)
    try:
        with transaction(conn):
            character = get_character(conn, discord_id)
            if character.level < definition.min_level:
                raise LevelTooLow(definition.name, definition.min_level)
            if conn.execute(
                "SELECT 1 FROM expeditions WHERE character_id = ? AND claimed_at IS NULL",
                (character.id,),
            ).fetchone():
                raise ExpeditionInProgress()
            snapshot = snapshot_from_build(current_build(conn, content, character))
            conn.execute(
                "INSERT INTO expeditions (character_id, expedition_id, started_at, seed, snapshot)"
                " VALUES (?, ?, ?, ?, ?)",
                (character.id, definition.id, now, secrets.randbits(62), json.dumps(snapshot)),
            )
            _log(conn, character.id, "expedition_started", {"expedition": definition.id})
    except sqlite3.IntegrityError:
        # Red de seguridad: el índice único impide dos expediciones abiertas.
        raise ExpeditionInProgress() from None
    return definition


def get_active_expedition(
    conn: sqlite3.Connection, content: Content, discord_id: int, now: int | None = None
) -> ActiveExpedition | None:
    now = _now() if now is None else int(now)
    character = get_character(conn, discord_id)
    row = conn.execute(
        "SELECT id, expedition_id, started_at, last_combat_log, last_enemy_id, last_enemy_name, "
        "last_enemy_hp, last_enemy_max_hp, last_player_hp, last_player_max_hp, last_player_won "
        "FROM expeditions WHERE character_id = ? AND claimed_at IS NULL",
        (character.id,),
    ).fetchone()
    if row is None:
        return None
    definition = content.expeditions[row["expedition_id"]]
    rules = content.config.expeditions
    elapsed = max(0, now - row["started_at"])
    cap_seconds = int(rules.max_accumulation_hours * 3600)

    # Cargar log del último combate si existe
    last_combat_log = ()
    if row["last_combat_log"]:
        import json
        log_data = json.loads(row["last_combat_log"])
        last_combat_log = tuple(CombatLogEntry(**entry) for entry in log_data)

    return ActiveExpedition(
        id=row["id"],
        definition=definition,
        started_at=row["started_at"],
        elapsed_seconds=elapsed,
        encounters_ready=encounters_available(elapsed, definition, rules),
        max_encounters=encounters_available(cap_seconds, definition, rules),
        seconds_to_next=seconds_until_next_encounter(elapsed, definition, rules),
        seconds_to_full=max(0, cap_seconds - elapsed),
        last_combat_log=last_combat_log,
        last_enemy_id=row["last_enemy_id"] or "",
        last_enemy_name=row["last_enemy_name"] or "",
        last_enemy_hp=row["last_enemy_hp"] or 0,
        last_enemy_max_hp=row["last_enemy_max_hp"] or 0,
        last_player_hp=row["last_player_hp"] or 0,
        last_player_max_hp=row["last_player_max_hp"] or 0,
        last_player_won=bool(row["last_player_won"]),
    )


def claim_expedition(
    conn: sqlite3.Connection, content: Content, discord_id: int, now: int | None = None
) -> ClaimResult:
    now = _now() if now is None else int(now)
    rules = content.config.expeditions
    with transaction(conn):
        character = get_character(conn, discord_id)
        row = conn.execute(
            "SELECT id, expedition_id, started_at, seed, snapshot FROM expeditions"
            " WHERE character_id = ? AND claimed_at IS NULL",
            (character.id,),
        ).fetchone()
        if row is None:
            raise NoActiveExpedition()

        definition = content.expeditions[row["expedition_id"]]
        elapsed = max(0, now - row["started_at"])
        encounters = encounters_available(elapsed, definition, rules)
        if encounters < 1:
            raise NothingToClaimYet(seconds_until_next_encounter(elapsed, definition, rules))

        snap = json.loads(row["snapshot"])
        build = build_from_snapshot(content, character.name, snap)
        outcome = resolve_expedition(
            expedition=definition,
            enemies=content.enemies,
            player=build_combatant(build),
            player_level=snap["level"],
            loot_bonus=build_stats(build).loot_bonus,
            encounters=encounters,
            seed=row["seed"],
            rules=rules,
            templates=content.item_templates,
            item_rules=content.config.items,
        )
        added = plan_new_items(conn, content, character.id, outcome.items)
        xp_pct, gold_pct = company.bonuses_tx(conn, content)
        bonus_xp = int(round(outcome.xp * xp_pct))
        bonus_gold = int(round(outcome.gold * gold_pct))
        total_xp = outcome.xp + bonus_xp
        total_gold = outcome.gold + bonus_gold + added.overflow_gold

        # Cierre atómico: si otra reclamación ya lo cerró, rowcount será 0 y no se paga nada.
        # Guardamos también el log del último combate
        log_data = [entry.__dict__ for entry in outcome.last_combat_log] if outcome.last_combat_log else []
        closed = conn.execute(
            "UPDATE expeditions SET claimed_at = ?, result = ?, "
            "last_combat_log = ?, last_enemy_id = ?, last_enemy_name = ?, "
            "last_enemy_hp = ?, last_enemy_max_hp = ?, "
            "last_player_hp = ?, last_player_max_hp = ?, last_player_won = ? "
            "WHERE id = ? AND claimed_at IS NULL",
            (now, json.dumps(_outcome_to_dict(outcome, added, bonus_xp, bonus_gold)),
             json.dumps(log_data), outcome.last_enemy_id, outcome.last_enemy_name,
             outcome.last_enemy_hp, outcome.last_enemy_max_hp,
             outcome.last_player_hp, outcome.last_player_max_hp,
             1 if outcome.last_player_won else 0, row["id"]),
        )
        if closed.rowcount != 1:
            raise NoActiveExpedition()

        xp_result = grant_xp_tx(
            conn, content.config.progression, character.id, total_xp, f"expedition:{definition.id}"
        )
        conn.execute(
            "UPDATE characters SET gold = gold + ? WHERE id = ?", (total_gold, character.id)
        )
        insert_items_tx(conn, character.id, added.kept, f"expedition:{definition.id}")
        for material_id, amount in outcome.materials.items():
            conn.execute(
                "INSERT INTO character_materials (character_id, material_id, amount)"
                " VALUES (?, ?, ?) ON CONFLICT(character_id, material_id)"
                " DO UPDATE SET amount = amount + excluded.amount",
                (character.id, material_id, amount),
            )
        update_character_score(conn, content, character.id)
        _log(
            conn,
            character.id,
            "expedition_claimed",
            {"expedition": definition.id, **_outcome_to_dict(outcome, added, bonus_xp, bonus_gold)},
        )
    return ClaimResult(
        definition, outcome, xp_result, elapsed, added.kept, added.overflow, added.overflow_gold,
        bonus_xp, bonus_gold,
    )


def preview_resolve_expedition(
    conn: sqlite3.Connection, content: Content, discord_id: int, now: int | None = None
) -> ClaimResult:
    """Simula el resultado de `/reclamar` sin escribir nada en la base de datos.

    Es completamente de solo lectura: no cierra la expedición, no concede XP/oro,
    no inserta objetos ni materiales y no registra nada en el activity_log.
    Devuelve un ClaimResult idéntico al que devolvería claim_expedition para la
    misma expedición en el mismo instante.
    """
    now = _now() if now is None else int(now)
    rules = content.config.expeditions
    character = get_character(conn, discord_id)
    row = conn.execute(
        "SELECT id, expedition_id, started_at, seed, snapshot FROM expeditions"
        " WHERE character_id = ? AND claimed_at IS NULL",
        (character.id,),
    ).fetchone()
    if row is None:
        raise NoActiveExpedition()

    definition = content.expeditions[row["expedition_id"]]
    elapsed = max(0, now - row["started_at"])
    encounters = encounters_available(elapsed, definition, rules)
    if encounters < 1:
        raise NothingToClaimYet(seconds_until_next_encounter(elapsed, definition, rules))

    snap = json.loads(row["snapshot"])
    build = build_from_snapshot(content, character.name, snap)
    outcome = resolve_expedition(
        expedition=definition,
        enemies=content.enemies,
        player=build_combatant(build),
        player_level=snap["level"],
        loot_bonus=build_stats(build).loot_bonus,
        encounters=encounters,
        seed=row["seed"],
        rules=rules,
        templates=content.item_templates,
        item_rules=content.config.items,
    )
    added = plan_new_items(conn, content, character.id, outcome.items)
    xp_pct, gold_pct = company.bonuses_tx(conn, content)
    bonus_xp = int(round(outcome.xp * xp_pct))
    bonus_gold = int(round(outcome.gold * gold_pct))
    total_xp = outcome.xp + bonus_xp
    total_gold = outcome.gold + bonus_gold + added.overflow_gold

    # Simulación de solo lectura de la subida de nivel (no escribe en la BD).
    # Se usa el xp actual del personaje (igual que grant_xp_tx) y no el de la snapshot.
    xp_result = apply_xp(character.level, character.xp, total_xp, content.config.progression)

    return ClaimResult(
        definition, outcome, xp_result, elapsed, added.kept, added.overflow, added.overflow_gold,
        bonus_xp, bonus_gold,
    )


def _outcome_to_dict(outcome: ExpeditionOutcome, added=None, bonus_xp: int = 0, bonus_gold: int = 0) -> dict:
    items = []
    if added is not None:
        items = [{"id": i.id, "template": i.template.id, "stats": i.stats, "kept": True}
                 for i in added.kept]
        items += [{"id": i.id, "template": i.template.id, "stats": i.stats, "kept": False}
                  for i in added.overflow]
    return {
        "encounters": outcome.encounters,
        "victories": outcome.victories,
        "retreated": outcome.retreated,
        "xp": outcome.xp,
        "gold": outcome.gold,
        "materials": outcome.materials,
        "kills": outcome.kills,
        "items": items,
        "overflow_gold": added.overflow_gold if added is not None else 0,
        "bonus_xp": bonus_xp,
        "bonus_gold": bonus_gold,
    }
