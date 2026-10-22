-- Migración 002: expediciones automáticas y materiales.

CREATE TABLE expeditions (
    id             INTEGER PRIMARY KEY,
    character_id   INTEGER NOT NULL REFERENCES characters(id),
    expedition_id  TEXT    NOT NULL,
    started_at     INTEGER NOT NULL,   -- segundos desde 1970 (UTC)
    seed           INTEGER NOT NULL,   -- semilla del azar, fijada al empezar
    snapshot       TEXT    NOT NULL,   -- clase, nivel y atributos al salir
    claimed_at     INTEGER,            -- NULL mientras siga abierta
    result         TEXT,               -- resultado congelado al reclamar
    CHECK ((claimed_at IS NULL) = (result IS NULL))
);

-- Solo puede haber UNA expedición abierta por personaje.
CREATE UNIQUE INDEX idx_one_open_expedition
    ON expeditions(character_id) WHERE claimed_at IS NULL;

CREATE INDEX idx_expeditions_character ON expeditions(character_id, id);

CREATE TABLE character_materials (
    character_id  INTEGER NOT NULL REFERENCES characters(id),
    material_id   TEXT    NOT NULL,
    amount        INTEGER NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (character_id, material_id)
);
