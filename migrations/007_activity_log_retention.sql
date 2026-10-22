-- Migración 007: índice de activity_log y columna acted_round en dungeon_participants

-- Índice para consultas por character_id y fecha
CREATE INDEX idx_activity_log_char_date ON activity_log (character_id, created_at);

-- Desnormalizar la última ronda actuada en dungeon_participants
ALTER TABLE dungeon_participants ADD COLUMN acted_round INTEGER NOT NULL DEFAULT 0;
