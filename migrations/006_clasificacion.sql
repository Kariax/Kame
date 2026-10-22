-- Migración 006: tabla de clasificación de personajes.

-- Ranking de personajes basado en poder efectivo (nivel, atributos y equipo).
-- Se recalcula periódicamente (al reclamar XP de una expedición, por ejemplo).
CREATE TABLE ranking (
    character_id  INTEGER PRIMARY KEY REFERENCES characters(id),
    score         INTEGER NOT NULL,            -- puntuación de clasificación
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);