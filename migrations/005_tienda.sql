-- Migración 005: tienda del mercader (compras del día, mochila ampliada y reinicios de atributos).

-- Estado de tienda por personaje.
CREATE TABLE character_shop (
    character_id  INTEGER PRIMARY KEY REFERENCES characters(id),
    bag_upgrades  INTEGER NOT NULL DEFAULT 0 CHECK (bag_upgrades >= 0),
    respecs       INTEGER NOT NULL DEFAULT 0 CHECK (respecs >= 0)
);

-- Compras de equipo. La clave primaria impide comprar dos veces la misma oferta del día.
CREATE TABLE shop_purchases (
    character_id  INTEGER NOT NULL REFERENCES characters(id),
    offer_key     TEXT    NOT NULL,                      -- "<día>:<ranura>:<n>"
    item_id       TEXT    NOT NULL,                      -- UUID de la instancia creada
    price         INTEGER NOT NULL CHECK (price >= 0),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (character_id, offer_key)
);
