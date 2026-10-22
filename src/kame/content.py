"""Carga y validación del contenido del juego (carpeta content/)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from kame.engine.company import GOLD, UpgradeDef, UpgradeLevel
from kame.engine.dungeon import (
    BossMove,
    BossPhase,
    DungeonDef,
    DungeonEnemyDef,
    LootRoll,
    StageDef,
)
from kame.engine.effects import EFFECT_TYPES, EffectDef
from kame.engine.expeditions import DropDef, EnemyDef, ExpeditionDef, ExpeditionRules
from kame.engine.items import RARITIES, SLOTS, STAT_KEYS, ItemRules, ItemTemplate
from kame.engine.models import ATTRIBUTES, BasicAttack, ClassDef
from kame.engine.progression import ProgressionRules
from kame.engine.shop import ShopRules
from kame.engine.skills import SkillDef

DAMAGE_TYPES = ("physical", "magic")


class ContentError(Exception):
    """El contenido del juego tiene un error (mensaje pensado para humanos)."""


@dataclass(frozen=True)
class GameConfig:
    progression: ProgressionRules
    expeditions: ExpeditionRules
    items: ItemRules
    starting_points: int
    name_min_length: int
    name_max_length: int


@dataclass(frozen=True)
class MaterialDef:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class Content:
    config: GameConfig
    classes: dict[str, ClassDef]
    materials: dict[str, MaterialDef]
    enemies: dict[str, EnemyDef]
    expeditions: dict[str, ExpeditionDef]
    skills: dict[str, SkillDef]
    item_templates: dict[str, ItemTemplate]
    company_upgrades: dict[str, UpgradeDef]
    dungeon_enemies: dict[str, DungeonEnemyDef]
    dungeons: dict[str, DungeonDef]
    shop: ShopRules


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ContentError(f"No encuentro el archivo {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ContentError(f"Error de formato en {path.name}: {e}") from None


def _section(data: dict, key: str, where: str) -> dict:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ContentError(f"{where}: falta la sección [{key}].")
    return value


def _int(section: dict, key: str, minimum: int, where: str) -> int:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContentError(f"{where}: '{key}' debe ser un número entero >= {minimum}.")
    return value


def _number(section: dict, key: str, minimum: float, where: str) -> float:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ContentError(f"{where}: '{key}' debe ser un número >= {minimum}.")
    return float(value)


def _prob(section: dict, key: str, where: str) -> float:
    value = _number(section, key, 0, where)
    if value > 1:
        raise ContentError(f"{where}: '{key}' debe estar entre 0 y 1.")
    return value


def _load_config(path: Path) -> GameConfig:
    where = path.name
    raw = _read_toml(path)
    game = _section(raw, "game", where)
    xp = _section(raw, "xp", where)
    names = _section(raw, "names", where)
    exp = _section(raw, "expeditions", where)
    penalty = _number(exp, "over_level_penalty", 0, where)
    min_factor = _number(exp, "min_xp_factor", 0, where)
    if penalty > 1 or min_factor > 1:
        raise ContentError(f"{where}: over_level_penalty y min_xp_factor deben estar entre 0 y 1.")
    items_cfg = _section(raw, "items", where)
    loot = _section(raw, "loot", where)
    sell = _section(raw, "sell", where)

    def weights(section: dict, label: str) -> dict[str, float]:
        return {r: _number(section, r, 0, f"{where} [{label}]") for r in RARITIES}

    variance = _number(items_cfg, "stat_variance", 0, where)
    if variance >= 1:
        raise ContentError(f"{where}: stat_variance debe ser menor que 1.")
    item_rules = ItemRules(
        stat_variance=variance,
        inventory_cap=_int(items_cfg, "inventory_cap", 1, where),
        drop_level_margin=_int(items_cfg, "drop_level_margin", 0, where),
        normal_weights=weights(_section(loot, "normal", f"{where} [loot]"), "loot.normal"),
        elite_weights=weights(_section(loot, "elite", f"{where} [loot]"), "loot.elite"),
        sell_values={r: _int(sell, r, 0, f"{where} [sell]") for r in RARITIES},
    )
    name_min = _int(names, "min_length", 1, where)
    name_max = _int(names, "max_length", name_min, where)
    return GameConfig(
        items=item_rules,
        expeditions=ExpeditionRules(
            max_accumulation_hours=_number(exp, "max_accumulation_hours", 0.1, where),
            over_level_penalty=penalty,
            min_xp_factor=min_factor,
            max_rounds=_int(exp, "max_rounds", 1, where),
        ),
        progression=ProgressionRules(
            max_level=_int(game, "max_level", 2, where),
            xp_base=_number(xp, "base", 1, where),
            xp_exponent=_number(xp, "exponent", 0.1, where),
            points_per_level=_int(game, "points_per_level", 0, where),
        ),
        starting_points=_int(game, "starting_points", 0, where),
        name_min_length=name_min,
        name_max_length=name_max,
    )


def _load_classes(path: Path) -> dict[str, ClassDef]:
    where = path.name
    raw = _read_toml(path)
    if not raw:
        raise ContentError(f"{where}: no hay ninguna clase definida.")
    classes: dict[str, ClassDef] = {}
    for class_id, data in raw.items():
        label = f"{where} [{class_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{label}: formato incorrecto.")
        name = data.get("name")
        description = data.get("description")
        if not isinstance(name, str) or not name.strip():
            raise ContentError(f"{label}: falta 'name'.")
        if not isinstance(description, str):
            raise ContentError(f"{label}: falta 'description'.")
        attrs = _section(data, "attributes", label)
        unknown = set(attrs) - set(ATTRIBUTES)
        if unknown:
            raise ContentError(f"{label}: atributos desconocidos: {', '.join(sorted(unknown))}.")
        base = {a: _int(attrs, a, 0, label) for a in ATTRIBUTES}
        primary = data.get("primary", [])
        if not isinstance(primary, list) or any(p not in ATTRIBUTES for p in primary):
            raise ContentError(f"{label}: 'primary' debe ser una lista de atributos válidos.")
        attack = _section(data, "basic_attack", label)
        damage_type = attack.get("damage_type")
        if damage_type not in DAMAGE_TYPES:
            raise ContentError(f"{label}: damage_type debe ser 'physical' o 'magic'.")
        classes[class_id] = ClassDef(
            id=class_id,
            name=name.strip(),
            description=description.strip(),
            base_attributes=base,
            primary=tuple(primary),
            basic_attack=BasicAttack(
                damage_type=damage_type,
                power_multiplier=_number(attack, "power_multiplier", 0.1, label),
                crit_multiplier=_number(attack, "crit_multiplier", 1.0, label),
            ),
        )
    return classes


def _text(data: dict, key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{where}: falta '{key}'.")
    return value.strip()


def _load_materials(path: Path) -> dict[str, MaterialDef]:
    raw = _read_toml(path)
    result = {}
    for material_id, data in raw.items():
        where = f"{path.name} [{material_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        result[material_id] = MaterialDef(
            material_id, _text(data, "name", where), str(data.get("description", "")).strip()
        )
    return result


def _load_enemies(path: Path, materials: dict[str, MaterialDef]) -> dict[str, EnemyDef]:
    raw = _read_toml(path)
    if not raw:
        raise ContentError(f"{path.name}: no hay ningún enemigo definido.")
    result = {}
    for enemy_id, data in raw.items():
        where = f"{path.name} [{enemy_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        damage_type = data.get("damage_type")
        if damage_type not in DAMAGE_TYPES:
            raise ContentError(f"{where}: damage_type debe ser 'physical' o 'magic'.")
        drops = []
        for drop in data.get("drops", []):
            material = drop.get("material") if isinstance(drop, dict) else None
            if material not in materials:
                raise ContentError(f"{where}: material desconocido en drops: {material!r}.")
            chance = _number(drop, "chance", 0, where)
            if chance > 1:
                raise ContentError(f"{where}: 'chance' debe estar entre 0 y 1.")
            drops.append(DropDef(material, chance))
        result[enemy_id] = EnemyDef(
            id=enemy_id,
            name=_text(data, "name", where),
            hp=_int(data, "hp", 1, where),
            power=_number(data, "power", 0.1, where),
            damage_type=damage_type,
            defense=_number(data, "defense", 0, where),
            resistance=_number(data, "resistance", 0, where),
            xp=_int(data, "xp", 0, where),
            gold=_int(data, "gold", 0, where),
            drops=tuple(drops),
            elite=bool(data.get("elite", False)),
        )
    return result


def _load_expeditions(path: Path, enemies: dict[str, EnemyDef]) -> dict[str, ExpeditionDef]:
    raw = _read_toml(path)
    if not raw:
        raise ContentError(f"{path.name}: no hay ninguna expedición definida.")
    result = {}
    for exp_id, data in raw.items():
        where = f"{path.name} [{exp_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        pool = []
        for entry in data.get("enemies", []):
            enemy = entry.get("enemy") if isinstance(entry, dict) else None
            if enemy not in enemies:
                raise ContentError(f"{where}: enemigo desconocido: {enemy!r}.")
            pool.append((enemy, _int(entry, "weight", 1, where)))
        if not pool:
            raise ContentError(f"{where}: necesita al menos un enemigo.")
        result[exp_id] = ExpeditionDef(
            id=exp_id,
            name=_text(data, "name", where),
            description=_text(data, "description", where),
            risk=_text(data, "risk", where),
            min_level=_int(data, "min_level", 1, where),
            recommended_level=_int(data, "recommended_level", 1, where),
            encounters_per_hour=_number(data, "encounters_per_hour", 0.1, where),
            enemy_pool=tuple(pool),
            item_chance=_prob(data, "item_chance", where),
            elite_item_chance=_prob(data, "elite_item_chance", where),
            loot_quality=_number(data, "loot_quality", 0.1, where),
        )
    return result


def _load_skills(path: Path, classes: dict[str, ClassDef]) -> dict[str, SkillDef]:
    raw = _read_toml(path)
    result: dict[str, SkillDef] = {}
    for skill_id, data in raw.items():
        where = f"{path.name} [{skill_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        class_id = data.get("class")
        if class_id not in classes:
            raise ContentError(f"{where}: clase desconocida: {class_id!r}.")
        damage_type = data.get("damage_type", "basic")
        if damage_type not in ("basic", *DAMAGE_TYPES):
            raise ContentError(f"{where}: damage_type inválido.")

        def num(key: str, minimum: float = 0, maximum: float | None = None) -> float:
            if key not in data:
                return 0.0
            value = _number(data, key, minimum, where)
            if maximum is not None and value > maximum:
                raise ContentError(f"{where}: '{key}' no puede superar {maximum}.")
            return value

        def turns(key: str) -> int:
            return _int(data, key, 0, where) if key in data else 0

        skill = SkillDef(
            id=skill_id, name=_text(data, "name", where), description=str(data.get("description", "")),
            class_id=class_id, ultimate=bool(data.get("ultimate", False)),
            cooldown=_int(data, "cooldown", 1, where), unlock_level=_int(data, "unlock_level", 1, where),
            multiplier=num("multiplier"), damage_type=damage_type, ignore_armor=num("ignore_armor", 0, 1),
            always_crit=bool(data.get("always_crit", False)), heal_pct=num("heal_pct", 0, 1),
            guard=num("guard", 0, 0.95), guard_turns=turns("guard_turns"), stun_turns=turns("stun_turns"),
            vulnerable=num("vulnerable"), vulnerable_turns=turns("vulnerable_turns"),
            weaken=num("weaken", 0, 0.95), weaken_turns=turns("weaken_turns"),
            poison_pct=num("poison_pct"), poison_turns=turns("poison_turns"),
            splash=num("splash", 0, 1),
        )
        if skill.guard and not skill.guard_turns or skill.weaken and not skill.weaken_turns \
                or skill.vulnerable and not skill.vulnerable_turns \
                or skill.poison_pct and not skill.poison_turns:
            raise ContentError(f"{where}: falta la duración (…_turns) de un efecto.")
        if not (skill.multiplier or skill.heal_pct or skill.guard or skill.stun_turns
                or skill.vulnerable or skill.weaken or skill.poison_pct):
            raise ContentError(f"{where}: la habilidad no hace nada.")
        result[skill_id] = skill
    for class_id in classes:
        mine = [s for s in result.values() if s.class_id == class_id]
        if sum(1 for s in mine if not s.ultimate) < 2 or sum(1 for s in mine if s.ultimate) < 1:
            raise ContentError(f"{path.name}: la clase {class_id} necesita 2+ habilidades y 1 definitiva.")
        if not any(not s.ultimate and s.unlock_level == 1 for s in mine):
            raise ContentError(f"{path.name}: la clase {class_id} necesita habilidades desde el nivel 1.")
    return result


def _load_items(path: Path, skills: dict[str, SkillDef]) -> dict[str, ItemTemplate]:
    raw = _read_toml(path)
    if not raw:
        raise ContentError(f"{path.name}: no hay ningún objeto definido.")
    result: dict[str, ItemTemplate] = {}
    for item_id, data in raw.items():
        where = f"{path.name} [{item_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        slot, rarity = data.get("slot"), data.get("rarity")
        if slot not in SLOTS:
            raise ContentError(f"{where}: slot inválido: {slot!r}.")
        if rarity not in RARITIES:
            raise ContentError(f"{where}: rareza inválida: {rarity!r}.")
        stats_raw = data.get("stats")
        if not isinstance(stats_raw, dict) or not stats_raw:
            raise ContentError(f"{where}: faltan las estadísticas (stats).")
        stats = {}
        for key, value in stats_raw.items():
            if key not in STAT_KEYS:
                raise ContentError(f"{where}: estadística desconocida: {key}.")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ContentError(f"{where}: '{key}' debe ser un número positivo.")
            stats[key] = value
        effects = []
        for effect in data.get("effects", []):
            etype = effect.get("type") if isinstance(effect, dict) else None
            if etype not in EFFECT_TYPES:
                raise ContentError(f"{where}: efecto desconocido: {etype!r}.")
            value = _number(effect, "value", 0.0001, where)
            skill = effect.get("skill")
            if etype == "empower" and skill not in skills:
                raise ContentError(f"{where}: empower necesita una habilidad existente (skill).")
            effects.append(EffectDef(etype, value, skill if etype == "empower" else None))
        result[item_id] = ItemTemplate(
            id=item_id, name=_text(data, "name", where), description=str(data.get("description", "")),
            slot=slot, rarity=rarity, min_level=_int(data, "min_level", 1, where),
            stats=stats, effects=tuple(effects), flavor=str(data.get("flavor", "")),
        )
    return result


def _load_company(path: Path, materials: dict[str, MaterialDef]) -> dict[str, UpgradeDef]:
    raw = _read_toml(path)
    result = {}
    for upgrade_id, data in raw.items():
        where = f"{path.name} [{upgrade_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        levels = []
        for entry in data.get("levels", []):
            cost = entry.get("cost") if isinstance(entry, dict) else None
            if not isinstance(cost, dict) or not cost:
                raise ContentError(f"{where}: cada nivel necesita un coste (cost).")
            for resource, amount in cost.items():
                if resource != GOLD and resource not in materials:
                    raise ContentError(f"{where}: recurso desconocido en el coste: {resource}.")
                if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
                    raise ContentError(f"{where}: cantidad inválida para {resource}.")
            levels.append(UpgradeLevel(
                xp_bonus=_number(entry, "xp_bonus", 0, where),
                gold_bonus=_number(entry, "gold_bonus", 0, where),
                cost=dict(cost),
            ))
        if not levels:
            raise ContentError(f"{where}: necesita al menos un nivel.")
        result[upgrade_id] = UpgradeDef(
            upgrade_id, _text(data, "name", where), str(data.get("description", "")), tuple(levels)
        )
    return result


def _load_dungeon_enemies(path: Path) -> dict[str, DungeonEnemyDef]:
    raw = _read_toml(path)
    result = {}
    for enemy_id, data in raw.items():
        where = f"{path.name} [{enemy_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        damage_type = data.get("damage_type", "physical")
        if damage_type not in DAMAGE_TYPES:
            raise ContentError(f"{where}: damage_type inválido.")
        result[enemy_id] = DungeonEnemyDef(
            id=enemy_id, name=_text(data, "name", where),
            hp_k=_number(data, "hp_k", 0.1, where), dmg_frac=_number(data, "dmg_frac", 0.01, where),
            armor_frac=_number(data, "armor_frac", 0, where), damage_type=damage_type,
            elite=bool(data.get("elite", False)),
        )
    return result


BOSS_MOVE_KINDS = ("attack", "heavy", "aoe", "bone_shield")


def _load_stage(data: dict, where: str, enemies: dict, materials: dict) -> StageDef:
    kind = data.get("kind")
    if kind not in ("fight", "boss"):
        raise ContentError(f"{where}: kind debe ser 'fight' o 'boss'.")
    loot = []
    for entry in data.get("loot", []):
        pool = entry.get("pool")
        if pool not in ("normal", "elite"):
            raise ContentError(f"{where}: pool de botín debe ser 'normal' o 'elite'.")
        loot.append(LootRoll(_prob(entry, "chance", where), pool, _number(entry, "quality", 0.1, where)))
    shared = data.get("shared", {})
    shared_materials = dict(shared.get("materials", {}))
    for material, amount in shared_materials.items():
        if material not in materials or not isinstance(amount, int) or amount < 1:
            raise ContentError(f"{where}: material compartido inválido: {material}.")
    common = dict(
        kind=kind, name=_text(data, "name", where), intro=str(data.get("intro", "")),
        xp=_int(data, "xp", 0, where), gold=_int(data, "gold", 0, where), loot=tuple(loot),
        shared_gold=int(shared.get("gold", 0)), shared_materials=shared_materials,
    )
    if kind == "fight":
        pool = []
        for entry in data.get("enemies", []):
            if entry.get("enemy") not in enemies:
                raise ContentError(f"{where}: enemigo de mazmorra desconocido: {entry.get('enemy')!r}.")
            pool.append((entry["enemy"], _number(entry, "per_hero", 0.05, where)))
        if not pool:
            raise ContentError(f"{where}: una sala de combate necesita enemigos.")
        return StageDef(enemies=tuple(pool), **common)
    boss = data.get("boss")
    if not isinstance(boss, dict) or boss.get("enemy") not in enemies:
        raise ContentError(f"{where}: el jefe necesita un 'enemy' existente.")
    phases = []
    for index, phase in enumerate(boss.get("phases", []), start=1):
        label = f"{where} fase {index}"
        moves = []
        for move in phase.get("moves", []):
            if move.get("kind") not in BOSS_MOVE_KINDS:
                raise ContentError(f"{label}: tipo de movimiento inválido: {move.get('kind')!r}.")
            targets = move.get("targets", "few")
            if targets not in ("few", "half"):
                raise ContentError(f"{label}: targets debe ser 'few' o 'half'.")
            moves.append(BossMove(
                name=_text(move, "name", label), kind=move["kind"],
                power=_number(move, "power", 0.01, label), every=_int(move, "every", 1, label) if "every" in move else 1,
                targets=targets,
                shield_rounds=_number(move, "shield_rounds", 0, label) if "shield_rounds" in move else 0.0,
            ))
        if not moves:
            raise ContentError(f"{label}: la fase necesita movimientos.")
        phases.append(BossPhase(_text(phase, "name", label), str(phase.get("intro", "")),
                                _number(phase, "until_hp", 0, label), tuple(moves)))
    if not phases or phases[-1].until_hp != 0:
        raise ContentError(f"{where}: el jefe necesita fases y la última debe terminar en until_hp = 0.")
    if any(a.until_hp <= b.until_hp for a, b in zip(phases, phases[1:])):
        raise ContentError(f"{where}: until_hp debe ir decreciendo entre fases.")
    for phase in phases:
        if any(m.kind == "bone_shield" for m in phase.moves) and not any(
            m.kind == "bone_shield" and m.shield_rounds > 0 for m in phase.moves
        ):
            raise ContentError(f"{where}: bone_shield necesita shield_rounds > 0.")
    return StageDef(boss_enemy=boss["enemy"], boss_hp_rounds=_number(boss, "hp_rounds", 0.5, where),
                    phases=tuple(phases), **common)


def _load_dungeons(path: Path, enemies: dict, materials: dict) -> dict[str, DungeonDef]:
    raw = _read_toml(path)
    result = {}
    for dungeon_id, data in raw.items():
        where = f"{path.name} [{dungeon_id}]"
        if not isinstance(data, dict):
            raise ContentError(f"{where}: formato incorrecto.")
        stages = tuple(
            _load_stage(stage, f"{where} sala {i}", enemies, materials)
            for i, stage in enumerate(data.get("stages", []), start=1)
        )
        if not stages or stages[-1].kind != "boss" or any(s.kind == "boss" for s in stages[:-1]):
            raise ContentError(f"{where}: debe terminar en un único jefe.")
        min_players = _int(data, "min_players", 1, where)
        heal, revive = _prob(data, "stage_heal", where), _prob(data, "revive_hp", where)
        result[dungeon_id] = DungeonDef(
            id=dungeon_id, name=_text(data, "name", where), description=str(data.get("description", "")),
            min_level=_int(data, "min_level", 1, where),
            recommended_level=_int(data, "recommended_level", 1, where),
            min_players=min_players, max_players=_int(data, "max_players", min_players, where),
            recruit_seconds=int(_number(data, "recruit_hours", 0.01, where) * 3600),
            turn_seconds=int(_number(data, "turn_hours", 0.01, where) * 3600),
            hero_rating_cap=_number(data, "hero_rating_cap", 1, where),
            stage_heal=heal, revive_hp=revive,
            auto_after_missed=_int(data, "auto_after_missed", 1, where),
            absent_after_missed=_int(data, "absent_after_missed", 2, where),
            max_rounds=_int(data, "max_rounds", 5, where), stages=stages,
            hero_rating_floor=_number(data, "hero_rating_floor", 0, where) if "hero_rating_floor" in data else 0.0,
        )
        if result[dungeon_id].absent_after_missed <= result[dungeon_id].auto_after_missed:
            raise ContentError(f"{where}: absent_after_missed debe ser mayor que auto_after_missed.")
    return result


def _load_shop(path: Path, templates: dict[str, ItemTemplate], sell_values: dict[str, int]) -> ShopRules:
    raw = _read_toml(path)
    where = path.name
    stock = _section(raw, "stock", where)
    prices_raw = _section(raw, "prices", where)
    respec = _section(raw, "respec", where)
    bag = _section(raw, "bag", where)
    rarities = stock.get("rarities")
    if not isinstance(rarities, list) or not rarities or any(r not in RARITIES for r in rarities):
        raise ContentError(f"{where}: [stock] rarities debe ser una lista de rarezas válidas.")
    per_slot = _int(stock, "offers_per_slot", 1, where)
    prices = {}
    for rarity in rarities:
        prices[rarity] = _int(prices_raw, rarity, 1, where)
        if prices[rarity] <= sell_values[rarity]:
            raise ContentError(
                f"{where}: el precio de '{rarity}' ({prices[rarity]}) debe ser mayor que su precio de venta "
                f"({sell_values[rarity]}): si no, se ganaría oro comprando y vendiendo.")
    for slot in SLOTS:
        available = sum(1 for t in templates.values() if t.slot == slot and t.rarity in rarities)
        if available < per_slot:
            raise ContentError(f"{where}: no hay objetos suficientes de la ranura {slot} para {per_slot} ofertas.")
    bag_prices = bag.get("prices")
    if (not isinstance(bag_prices, list) or not bag_prices
            or any(isinstance(p, bool) or not isinstance(p, int) or p < 1 for p in bag_prices)
            or bag_prices != sorted(bag_prices)):
        raise ContentError(f"{where}: [bag] prices debe ser una lista creciente de enteros positivos.")
    return ShopRules(
        rarities=tuple(rarities), offers_per_slot=per_slot, prices=prices,
        respec_free=_int(respec, "free", 0, where), respec_base=_int(respec, "base_cost", 0, where),
        respec_per_level=_int(respec, "cost_per_level", 0, where),
        bag_slots=_int(bag, "slots_per_upgrade", 1, where), bag_prices=tuple(bag_prices),
    )


# Cache con TTL de 300 segundos para load_content, claveada por directorio
import time

_cache: dict[str, tuple[Content, int]] = {}
_CACHE_TTL = 300


def _load_content_uncached(content_dir: Path) -> Content:
    content_dir = Path(content_dir)
    materials = _load_materials(content_dir / "materials.toml")
    enemies = _load_enemies(content_dir / "enemies.toml", materials)
    classes = _load_classes(content_dir / "classes.toml")
    skills = _load_skills(content_dir / "skills.toml", classes)
    dungeon_enemies = _load_dungeon_enemies(content_dir / "dungeon_enemies.toml")
    config = _load_config(content_dir / "config.toml")
    item_templates = _load_items(content_dir / "items.toml", skills)
    return Content(
        config=config,
        classes=classes,
        materials=materials,
        enemies=enemies,
        expeditions=_load_expeditions(content_dir / "expeditions.toml", enemies),
        skills=skills,
        item_templates=item_templates,
        company_upgrades=_load_company(content_dir / "company.toml", materials),
        dungeon_enemies=dungeon_enemies,
        dungeons=_load_dungeons(content_dir / "dungeons.toml", dungeon_enemies, materials),
        shop=_load_shop(content_dir / "shop.toml", item_templates, config.items.sell_values),
    )


def load_content(content_dir: Path, force_reload: bool = False) -> Content:
    """Carga el contenido del juego, cacheado con TTL de 300 segundos.

    `force_reload=True` ignora la caché y vuelve a leer los archivos (útil para tests).
    """
    key = str(Path(content_dir).resolve())
    now = int(time.time())
    if not force_reload:
        cached = _cache.get(key)
        if cached is not None and now - cached[1] < _CACHE_TTL:
            return cached[0]
    content = _load_content_uncached(content_dir)
    _cache[key] = (content, now)
    return content


def invalidate_content_cache(content_dir: Path | None = None) -> None:
    """Fuerza la recarga en la próxima llamada a load_content."""
    key = str(Path(content_dir).resolve()) if content_dir is not None else None
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)
