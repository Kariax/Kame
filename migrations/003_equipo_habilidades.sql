-- Migración 003: objetos, equipo y habilidades seleccionables.

-- Habilidades equipadas (NULL = usar las de por defecto) y modo de la definitiva.
ALTER TABLE characters ADD COLUMN skill_1 TEXT;
ALTER TABLE characters ADD COLUMN skill_2 TEXT;
ALTER TABLE characters ADD COLUMN ultimate_mode TEXT NOT NULL DEFAULT 'always'
    CHECK (ultimate_mode IN ('always', 'elite', 'low_hp', 'never'));

-- Instancias concretas de objetos (la plantilla vive en content/items.toml).
CREATE TABLE item_instances (
    id                  TEXT    PRIMARY KEY,                       -- UUID
    template_id         TEXT    NOT NULL,
    owner_character_id  INTEGER NOT NULL REFERENCES characters(id),
    stats               TEXT    NOT NULL,                          -- estadísticas definitivas (JSON)
    source              TEXT    NOT NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_item_instances_owner ON item_instances(owner_character_id);

-- Un objeto por ranura y personaje; un objeto no puede estar equipado dos veces.
-- ON DELETE RESTRICT: la base de datos impide borrar (vender) un objeto equipado.
CREATE TABLE equipment (
    character_id  INTEGER NOT NULL REFERENCES characters(id),
    slot          TEXT    NOT NULL CHECK (slot IN ('weapon','helmet','armor','gloves','boots','amulet')),
    item_id       TEXT    NOT NULL UNIQUE REFERENCES item_instances(id) ON DELETE RESTRICT,
    PRIMARY KEY (character_id, slot)
);
