-- Migración 009: registro de derrotas por enemigo en expediciones

-- Cuando un personaje es derrotado en un encuentro, el enemigo huye y la
-- expedición continúa. Esta columna guarda, por tipo de enemigo, cuántas
-- veces el personaje fue derrotado durante la última expedición reclamada.
ALTER TABLE expeditions ADD COLUMN defeated_by TEXT;