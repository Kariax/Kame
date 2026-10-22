-- Migración 001: jugadores, personajes y registro de actividad.
-- (La tabla schema_migrations la crea el propio sistema de migraciones.)

CREATE TABLE players (
    id          INTEGER PRIMARY KEY,
    discord_id  INTEGER NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE characters (
    id              INTEGER PRIMARY KEY,
    player_id       INTEGER NOT NULL UNIQUE REFERENCES players(id),
    name            TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    class_id        TEXT    NOT NULL,
    level           INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1),
    xp              INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
    gold            INTEGER NOT NULL DEFAULT 0 CHECK (gold >= 0),
    fuerza          INTEGER NOT NULL CHECK (fuerza >= 0),
    inteligencia    INTEGER NOT NULL CHECK (inteligencia >= 0),
    vitalidad       INTEGER NOT NULL CHECK (vitalidad >= 0),
    destreza        INTEGER NOT NULL CHECK (destreza >= 0),
    suerte          INTEGER NOT NULL CHECK (suerte >= 0),
    unspent_points  INTEGER NOT NULL DEFAULT 0 CHECK (unspent_points >= 0),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE activity_log (
    id            INTEGER PRIMARY KEY,
    character_id  INTEGER NOT NULL REFERENCES characters(id),
    kind          TEXT    NOT NULL,
    detail        TEXT    NOT NULL DEFAULT '{}',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_activity_log_character ON activity_log(character_id, id);
