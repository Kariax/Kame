-- Migración 008: campos para simulación visual de combate en expediciones

-- Añadimos columnas para guardar el log del último combate resuelto
ALTER TABLE expeditions ADD COLUMN last_combat_log TEXT;
ALTER TABLE expeditions ADD COLUMN last_enemy_id TEXT;
ALTER TABLE expeditions ADD COLUMN last_enemy_name TEXT;
ALTER TABLE expeditions ADD COLUMN last_enemy_hp INTEGER;
ALTER TABLE expeditions ADD COLUMN last_enemy_max_hp INTEGER;
ALTER TABLE expeditions ADD COLUMN last_player_hp INTEGER;
ALTER TABLE expeditions ADD COLUMN last_player_max_hp INTEGER;
ALTER TABLE expeditions ADD COLUMN last_player_won INTEGER; -- 0 o 1

-- Índice para consultar más rápido
CREATE INDEX idx_expeditions_last_combat ON expeditions(character_id) WHERE claimed_at IS NULL;