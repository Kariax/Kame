from pathlib import Path

import pytest

from kame.content import ContentError, load_content
from kame.engine.models import ATTRIBUTES

ROOT_CONTENT = Path(__file__).resolve().parents[1] / "content"


def test_real_content_loads(content):
    assert set(content.classes) == {"guerrero", "mago", "picaro"}
    assert content.config.progression.max_level == 50


def test_classes_have_all_attributes_and_valid_primaries(content):
    for c in content.classes.values():
        assert set(c.base_attributes) == set(ATTRIBUTES)
        assert all(p in ATTRIBUTES for p in c.primary)


def test_classes_start_with_similar_total_attribute_points(content):
    totals = {sum(c.base_attributes.values()) for c in content.classes.values()}
    assert max(totals) - min(totals) <= 1


def _write(tmp_path, config=None, classes=None):
    for f in ROOT_CONTENT.glob("*.toml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    if config is not None:
        (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    if classes is not None:
        (tmp_path / "classes.toml").write_text(classes, encoding="utf-8")
    return tmp_path


def test_minimal_valid_content_loads(tmp_path):
    assert "guerrero" in load_content(_write(tmp_path)).classes  # copia del contenido real


def test_missing_attribute_is_rejected(tmp_path):
    bad = '[x]\nname="X"\ndescription="d"\n[x.attributes]\nfuerza = 1\n'
    with pytest.raises(ContentError):
        load_content(_write(tmp_path, classes=bad))


def test_unknown_attribute_is_rejected(tmp_path):
    bad = (
        '[x]\nname="X"\ndescription="d"\n[x.attributes]\nfuerza=1\ninteligencia=1\n'
        "vitalidad=1\ndestreza=1\nsuerte=1\nmagia=3\n"
    )
    with pytest.raises(ContentError):
        load_content(_write(tmp_path, classes=bad))


def test_negative_value_is_rejected(tmp_path):
    bad = (
        '[x]\nname="X"\ndescription="d"\n[x.attributes]\nfuerza=-1\ninteligencia=1\n'
        "vitalidad=1\ndestreza=1\nsuerte=1\n"
    )
    with pytest.raises(ContentError):
        load_content(_write(tmp_path, classes=bad))


def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_broken_toml_gives_clear_error(tmp_path):
    with pytest.raises(ContentError):
        load_content(_write(tmp_path, config="[game\nmax_level ="))


def test_real_content_cross_references(content):
    for enemy in content.enemies.values():
        for drop in enemy.drops:
            assert drop.material_id in content.materials
    for exp in content.expeditions.values():
        assert exp.min_level <= exp.recommended_level
        for enemy_id, weight in exp.enemy_pool:
            assert enemy_id in content.enemies and weight >= 1


def test_every_class_has_a_basic_attack(content):
    for c in content.classes.values():
        assert c.basic_attack.damage_type in ("physical", "magic")


def _copy_content(tmp_path):
    for f in ROOT_CONTENT.glob("*.toml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")


def test_unknown_enemy_in_expedition_is_rejected(tmp_path):
    _copy_content(tmp_path)
    path = tmp_path / "expeditions.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("cripta_ligero", "no_existe", 1), encoding="utf-8")
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_unknown_material_in_drops_is_rejected(tmp_path):
    _copy_content(tmp_path)
    path = tmp_path / "enemies.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("hueso_astillado", "polvo_raro", 1), encoding="utf-8")
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_invalid_damage_type_is_rejected(tmp_path):
    _copy_content(tmp_path)
    path = tmp_path / "enemies.toml"
    path.write_text(path.read_text(encoding="utf-8").replace('"physical"', '"fuego"', 1), encoding="utf-8")
    with pytest.raises(ContentError):
        load_content(tmp_path)


def _edit(tmp_path, name, old, new, count=1):
    _copy_content(tmp_path)
    path = tmp_path / name
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, count), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("skills.toml", 'class = "guerrero"', 'class = "paladin"'),                         # clase inexistente
        ("skills.toml", "guard = 0.5\nguard_turns = 2", "guard = 0.5"),                     # falta duración
        ("skills.toml", "guard = 0.5\nguard_turns = 2", "cooldown_extra = 1"),              # no hace nada
        ("skills.toml", "cooldown = 3\nunlock_level = 1\nmultiplier = 1.8", "cooldown = 0\nunlock_level = 1\nmultiplier = 1.8"),
        ("skills.toml", "ignore_armor = 0.4", "ignore_armor = 3"),
        ("items.toml", 'slot = "weapon"', 'slot = "cabeza"'),
        ("items.toml", 'rarity = "common"', 'rarity = "mitica"'),
        ("items.toml", "stats = { inteligencia = 1", "stats = { magia = 1"),
        ("items.toml", 'type = "crit_damage"', 'type = "explosion"'),
        ("items.toml", 'skill = "golpe_aplastante"', 'skill = "no_existe"'),
        ("config.toml", "stat_variance = 0.10", "stat_variance = 1.5"),
        ("config.toml", "[sell]", "[venta]"),
        ("expeditions.toml", "item_chance = 0.06", "item_chance = 7"),
    ],
)
def test_invalid_skills_items_and_loot_config_are_rejected(tmp_path, name, old, new):
    with pytest.raises(ContentError):
        load_content(_edit(tmp_path, name, old, new))


def test_class_without_enough_skills_is_rejected(tmp_path):
    _copy_content(tmp_path)
    path = tmp_path / "skills.toml"
    text = path.read_text(encoding="utf-8")
    cut = text.index("[tormenta_del_abismo]")
    end = text.index("# ---------------- PÍCARO")
    path.write_text(text[:cut] + text[end:], encoding="utf-8")  # el mago pierde su definitiva
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_elite_enemies_are_flagged(content):
    elites = [e for e in content.enemies.values() if e.elite]
    assert elites and all(e.id.endswith("_elite") for e in elites)
    assert all(not e.elite for e in content.enemies.values() if not e.id.endswith("_elite"))


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("dungeons.toml", 'enemy = "esqueleto_osario"', 'enemy = "no_existe"'),
        ("dungeons.toml", 'kind = "fight"', 'kind = "emboscada"'),
        ("dungeons.toml", "until_hp = 0.0", "until_hp = 0.1"),
        ("dungeons.toml", "until_hp = 0.33", "until_hp = 0.8"),
        ("dungeons.toml", "shield_rounds = 1.5", "shield_rounds = 0"),
        ("dungeons.toml", 'kind = "aoe"', 'kind = "meteoro"'),
        ("dungeons.toml", 'targets = "half"', 'targets = "todos"'),
        ("dungeons.toml", 'pool = "elite"', 'pool = "mitico"', ),
        ("dungeons.toml", "hueso_astillado = 6", "polvo_raro = 6"),
        ("dungeons.toml", "absent_after_missed = 4", "absent_after_missed = 2"),
        ("dungeons.toml", "stage_heal = 0.4", "stage_heal = 4"),
        ("dungeons.toml", "chance = 0.25", "chance = 5"),
        ("dungeon_enemies.toml", 'damage_type = "physical"', 'damage_type = "fuego"'),
        ("dungeon_enemies.toml", "hp_k = 1.65", "hp_k = 0"),
    ],
)
def test_invalid_dungeon_content_is_rejected(tmp_path, name, old, new):
    with pytest.raises(ContentError):
        load_content(_edit(tmp_path, name, old, new))


def test_a_dungeon_must_end_in_a_single_boss(tmp_path):
    _copy_content(tmp_path)
    path = tmp_path / "dungeons.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('kind = "boss"', 'kind = "fight"\nenemies = [ { enemy = "susurrante", per_hero = 1 } ]', 1),
                    encoding="utf-8")
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_real_dungeon_content_is_coherent(content):
    dungeon = content.dungeons["cripta_del_rey_hueco"]
    assert 2 <= dungeon.min_players <= dungeon.max_players and dungeon.min_level <= dungeon.recommended_level
    boss = dungeon.stages[-1]
    assert len(boss.phases) == 3 and [p.until_hp for p in boss.phases] == [0.66, 0.33, 0.0]
    assert dungeon.hero_rating_floor < dungeon.hero_rating_cap
    for stage in dungeon.stages:
        for material in stage.shared_materials:
            assert material in content.materials
    assert dungeon.turn_seconds == 12 * 3600 and dungeon.recruit_seconds == 24 * 3600


@pytest.mark.parametrize(
    "old,new",
    [
        ("common = 40", "common = 8"),                     # no mayor que el precio de venta
        ("uncommon = 130", "uncommon = 25"),
        ('rarities = ["common", "uncommon"]', 'rarities = ["common", "mitica"]'),
        ('rarities = ["common", "uncommon"]', "rarities = []"),
        ("offers_per_slot = 2", "offers_per_slot = 0"),
        ("offers_per_slot = 2", "offers_per_slot = 9"),      # no hay tantos objetos por ranura
        ("prices = [500, 1000, 2000, 4000]", "prices = [1000, 500]"),
        ("prices = [500, 1000, 2000, 4000]", "prices = []"),
        ("slots_per_upgrade = 10", "slots_per_upgrade = 0"),
        ("cost_per_level = 40", "cost_per_level = -1"),
        ("[bag]", "[mochila]"),
    ],
)
def test_invalid_shop_content_is_rejected(tmp_path, old, new):
    with pytest.raises(ContentError):
        load_content(_edit(tmp_path, "shop.toml", old, new))


def test_habilidades_detallar_embed(conn, content):
    """Testea que /habilidades detallar muestra la descripción detallada de una habilidad."""
    from kame.bot.embeds import skill_detail_embed
    from kame.services import skills

    make(conn, content)
    character = get_character(conn, content, 1)
    view = skills.get_loadout(conn, content, 1)

    # Probar habilidad disponible
    skill = view.available[0]
    embed = skill_detail_embed(skill, character, content)
    assert embed.title == f"🔍 Detalle de {skill.name}"
    assert embed.color.value == DARK_RED.value
    assert "Descripción" in [f.name for f in embed.fields]
    assert "Daño" in [f.name for f in embed.fields] or "Efectos" in [f.name for f in embed.fields]
    assert "Reutilización" in [f.name for f in embed.fields]


def test_habilidades_detallar_autocomplete(conn, content):
    """Testea que /habilidades detallar tiene autocomplete."""
    from kame.bot.cogs.habilidades import HabilidadesCog
    from kame.bot.app import KameBot

    bot = KameBot(None, content, conn)
    cog = HabilidadesCog(bot)

    # Mock interaction
    class MockInteraction:
        def __init__(self):
            self.user = type('obj', (object,), {'id': 1})
            self.response = type('obj', (object,), {'send_message': lambda *args, **kwargs: None})

    interaction = MockInteraction()

    # Mock cog._skill_autocomplete
    async def mock_autocomplete(current):
        return []

    cog._skill_autocomplete = mock_autocomplete

    # Probar autocomplete
    choices = cog.detallar_autocomplete(interaction, "golpe")
    assert len(choices) > 0
    assert all(c.value in content.skills for c in choices)
