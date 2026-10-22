-- Migración 004: compañía (almacén compartido y mejoras) y mazmorras cooperativas.

-- Datos sueltos del sistema (p. ej. último latido del bot, para prorrogar plazos tras una caída).
CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Una única compañía por servidor (grupo privado). Todos los personajes son miembros.
CREATE TABLE company (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    name  TEXT NOT NULL
);
INSERT INTO company (id, name) VALUES (1, 'Compañía de Aventureros');

-- Almacén compartido: nunca puede quedar en negativo.
CREATE TABLE company_storage (
    resource_id  TEXT    PRIMARY KEY,                    -- 'gold' o id de material
    amount       INTEGER NOT NULL CHECK (amount >= 0)
);

-- Registro de TODOS los movimientos del almacén (quién, qué, cuánto y por qué).
CREATE TABLE company_ledger (
    id            INTEGER PRIMARY KEY,
    character_id  INTEGER REFERENCES characters(id),     -- NULL = recompensa de mazmorra
    resource_id   TEXT    NOT NULL,
    delta         INTEGER NOT NULL CHECK (delta <> 0),
    reason        TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE company_upgrades (
    upgrade_id  TEXT    PRIMARY KEY,
    level       INTEGER NOT NULL CHECK (level >= 1)
);

-- Partidas de mazmorra.
CREATE TABLE dungeon_runs (
    id                   INTEGER PRIMARY KEY,
    dungeon_id           TEXT    NOT NULL,
    leader_character_id  INTEGER NOT NULL REFERENCES characters(id),
    state                TEXT    NOT NULL CHECK (state IN ('recruiting', 'active', 'finished', 'cancelled')),
    channel_id           INTEGER,
    seed                 INTEGER NOT NULL,
    round                INTEGER NOT NULL DEFAULT 0,
    round_deadline       INTEGER,                              -- segundos desde 1970 (UTC)
    recruit_deadline     INTEGER NOT NULL,
    battle               TEXT,                                 -- estado del combate (JSON)
    cleared              TEXT    NOT NULL DEFAULT '[]',        -- salas superadas (JSON)
    outcome              TEXT,                                 -- win / loss / abandoned
    rewards_resolved     INTEGER NOT NULL DEFAULT 0 CHECK (rewards_resolved IN (0, 1)),
    result               TEXT,                                 -- resumen de recompensas (JSON)
    created_at           INTEGER NOT NULL,
    started_at           INTEGER,
    finished_at          INTEGER
);

CREATE TABLE dungeon_participants (
    run_id           INTEGER NOT NULL REFERENCES dungeon_runs(id),
    character_id     INTEGER NOT NULL REFERENCES characters(id),
    state            TEXT    NOT NULL CHECK (state IN ('active', 'absent', 'left')),
    mode             TEXT    NOT NULL DEFAULT 'manual' CHECK (mode IN ('manual', 'auto')),
    missed_turns     INTEGER NOT NULL DEFAULT 0,               -- rondas seguidas sin actuar
    manual_rounds    INTEGER NOT NULL DEFAULT 0,
    eligible_rounds  INTEGER NOT NULL DEFAULT 0,
    open             INTEGER NOT NULL DEFAULT 1 CHECK (open IN (0, 1)),
    joined_at        INTEGER NOT NULL,
    PRIMARY KEY (run_id, character_id)
);

-- Un personaje solo puede estar en UNA partida abierta a la vez.
CREATE UNIQUE INDEX idx_one_open_run_per_character
    ON dungeon_participants(character_id) WHERE open = 1;

-- Acción elegida por cada jugador en cada ronda (una sola por ronda: no se procesa dos veces).
CREATE TABLE dungeon_actions (
    run_id        INTEGER NOT NULL REFERENCES dungeon_runs(id),
    round         INTEGER NOT NULL,
    character_id  INTEGER NOT NULL REFERENCES characters(id),
    kind          TEXT    NOT NULL,
    target        INTEGER,
    created_at    INTEGER NOT NULL,
    PRIMARY KEY (run_id, round, character_id)
);
