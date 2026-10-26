"""Comprueba que el bot se construye y registra sus comandos, SIN conectarse a Discord."""
import asyncio
import dataclasses
import discord

from kame.bot.app import KameBot
from kame.bot.cogs.compania import CompaniaCog
from kame.bot.cogs.expediciones import ExpedicionesCog
from kame.bot.cogs.habilidades import HabilidadesCog
from kame.bot.cogs.inventario import ConfirmSellView, InventarioCog
from kame.bot.cogs.mazmorra import ACTIONS, MazmorraCog
from kame.bot.cogs.tienda import ConfirmRespecView, TiendaCog
from kame.bot.cogs.personaje import PersonajeCog
from kame.bot.cogs.estadisticas import EstadisticasCog
from kame.bot.embeds import profile_embed
from kame.config import load_settings
from kame.services import characters


def test_cog_registers_expected_commands(conn, content, tmp_path):
    settings = load_settings(tmp_path, load_env_file=False)

    async def run():
        bot = KameBot(settings, content, conn)
        await bot.add_cog(PersonajeCog(bot))
        await bot.add_cog(ExpedicionesCog(bot))
        await bot.add_cog(InventarioCog(bot))
        await bot.add_cog(HabilidadesCog(bot))
        await bot.add_cog(CompaniaCog(bot))
        await bot.add_cog(MazmorraCog(bot))
        await bot.add_cog(TiendaCog(bot))
        names = {c.name for c in bot.tree.get_commands()}
        await bot.close()
        return names

    assert asyncio.run(run()) == {
        "crear", "perfil", "atributos", "ayuda", "mecanicas", "expedicion", "reclamar",
        "inventario", "equipo", "equipar", "desequipar", "vender", "habilidades",
        "compania", "mazmorra", "tienda", "combate",
    }


def test_profile_embed_renders_for_every_class(conn, content):
    for i, class_id in enumerate(content.classes, start=1):
        c = characters.create_character(conn, content, i, f"Heroe{'abc'[i-1]}", class_id)
        embed = profile_embed(c, content)
        assert embed.title == c.name
        assert len(embed.fields) >= 4


def test_expedition_embeds_render(conn, content):
    from kame.bot.embeds import (
        active_expedition_embed,
        claim_embed,
        expedition_list_embed,
        format_duration,
    )
    from kame.services import expeditions

    c = characters.create_character(conn, content, 1, "Aldric", "guerrero")
    assert len(expedition_list_embed(content, 1).fields) == len(content.expeditions)
    expeditions.start_expedition(conn, content, 1, "cripta", now=1000)
    active = expeditions.get_active_expedition(conn, content, 1, now=1000 + 3 * 3600)
    embed = active_expedition_embed(active)
    assert embed.title.startswith("En expedición")
    # Verify the encounters bar format appears in a field value
    has_bar = any(
        "⚔️" in f.value and "/" in f.value
        for f in embed.fields
    )
    assert has_bar, "Encounters bar with ⚔️ emojis should be present in embed field"
    result = expeditions.claim_expedition(conn, content, 1, now=1000 + 3 * 3600)
    embed = claim_embed(c.name, result, content)
    assert embed.title and any(f.name == "Experiencia" for f in embed.fields)
    assert format_duration(3700) == "1 h 1 min" and format_duration(5) == "menos de 1 min"
    # Si el personaje cayó durante la expedición, aparece la sección "Vencido por".
    if result.outcome.defeated_by:
        assert "Vencido por" in [f.name for f in embed.fields]


def test_item_and_skill_embeds_render(conn, content):
    from kame.bot.embeds import (
        claim_embed, equipment_embed, inventory_embed, item_choice_label, item_detail, loadout_embed,
    )
    from kame.db.database import transaction
    from kame.engine.items import ItemDrop
    from kame.services import expeditions, items, skills

    c = characters.create_character(conn, content, 1, "Aldric", "guerrero")
    with transaction(conn):
        conn.execute("UPDATE characters SET level = 12 WHERE id = ?", (c.id,))
    added = None
    for template_id in ("hacha_del_osario", "colmillo_del_verdugo", "sello_del_caido"):
        t = content.item_templates[template_id]
        added = items.plan_new_items(conn, content, c.id, (ItemDrop(template_id, dict(t.stats)),))
        with transaction(conn):
            items.insert_items_tx(conn, c.id, added.kept, "test")
    inventory = items.list_inventory(conn, content, 1)
    items.equip_item(conn, content, 1, inventory[0].id)
    inventory = items.list_inventory(conn, content, 1)
    embed = inventory_embed(inventory, 1, 8, 50, None)
    assert len(embed.fields) == 3 and "3/50" in embed.footer.text
    assert inventory_embed([], 1, 8, 50, "Arma").description
    assert all(len(item_choice_label(i)) <= 100 for i in inventory)
    assert "✦" in item_detail(inventory[0], content)  # los legendarios muestran sus efectos

    c = characters.get_character(conn, 1)
    build = items.current_build(conn, content, c)
    eq = equipment_embed(build, items.get_equipment(conn, content, 1), content)
    assert len(eq.fields) >= 6
    assert profile_embed(c, content, None, build).fields
    assert loadout_embed(skills.get_loadout(conn, content, 1), content).fields

    rich_exp = dataclasses.replace(content.expeditions["cripta"], item_chance=1.0)
    rich = dataclasses.replace(content, expeditions={**content.expeditions, "cripta": rich_exp})
    expeditions.start_expedition(conn, rich, 1, "cripta", now=1000)
    result = expeditions.claim_expedition(conn, rich, 1, now=1000 + 8 * 3600)
    names = [f.name for f in claim_embed(c.name, result, rich).fields]
    assert "Objetos" in names


def test_confirm_sell_view_only_accepts_its_owner(conn, content):
    class FakeBot:
        pass

    async def run():
        bot = FakeBot()
        bot.conn, bot.content = conn, content
        view = ConfirmSellView(bot, 123, "abc")
        assert view.timeout == 30 and len(view.children) == 2
        return [c.label for c in view.children]

    assert asyncio.run(run()) == ["Vender", "Cancelar"]


def test_group_commands_expose_their_subcommands(conn, content, tmp_path):
    settings = load_settings(tmp_path, load_env_file=False)

    async def run():
        bot = KameBot(settings, content, conn)
        await bot.add_cog(PersonajeCog(bot))
        await bot.add_cog(ExpedicionesCog(bot))
        await bot.add_cog(InventarioCog(bot))
        await bot.add_cog(HabilidadesCog(bot))
        await bot.add_cog(CompaniaCog(bot))
        await bot.add_cog(MazmorraCog(bot))
        await bot.add_cog(TiendaCog(bot))
        groups = {c.name: {s.name for s in c.commands} for c in bot.tree.get_commands()}
        bot.get_cog("MazmorraCog").check_runs.cancel()
        await bot.close()
        return groups

    groups = asyncio.run(run())
    assert groups["mazmorra"] == {
        "info", "crear", "unirse", "iniciar", "estado", "accion", "abandonar"
    }

    settings = load_settings(tmp_path, load_env_file=False)

    async def run():
        bot = KameBot(settings, content, conn)
        await bot.add_cog(HabilidadesCog(bot))
        await bot.add_cog(CompaniaCog(bot))
        await bot.add_cog(MazmorraCog(bot))
        await bot.add_cog(TiendaCog(bot))
        groups = {c.name: {s.name for s in c.commands} for c in bot.tree.get_commands()}
        bot.get_cog("MazmorraCog").check_runs.cancel()
        await bot.close()
        return groups

    groups = asyncio.run(run())
    assert groups["compania"] == {"ver", "donar", "mejorar"}
    assert groups["mazmorra"] == {"info", "crear", "unirse", "iniciar", "estado", "accion", "abandonar"}
    assert groups["tienda"] == {"ver", "comprar", "mochila", "reiniciar"}
    assert groups["habilidades"] == {"ver", "detallar"}


def test_action_names_cover_every_engine_action():
    from kame.engine.dungeon import ACTION_KINDS

    assert set(ACTIONS.values()) == set(ACTION_KINDS)


def test_company_and_dungeon_embeds_render(conn, content):
    from kame.bot.embeds import company_embed, dungeon_list_embed, finish_embed, run_embed
    from kame.db.database import transaction
    from kame.services import company, dungeons

    for did, cls in ((1, "guerrero"), (2, "mago")):
        characters.create_character(conn, content, did, "Aldric" if did == 1 else "Brenna", cls)
        with transaction(conn):
            conn.execute("UPDATE characters SET level = 8, gold = 500 WHERE id = ?", (did,))
    company.contribute(conn, content, 1, "gold", 200)
    embed = company_embed(company.get_company(conn, content), content, company.get_ledger(conn))
    assert any("Armería" in f.name for f in embed.fields) and any("Almacén" == f.name for f in embed.fields)

    view = dungeons.create_run(conn, content, 1, "cripta_del_rey_hueco", 5, 1000)
    assert dungeon_list_embed(content, dungeons.list_open_runs(conn, content)).fields
    assert run_embed(view, content).fields
    dungeons.join_run(conn, content, 2, view.id, 1000)
    event = dungeons.start_run(conn, content, 1, 1000)
    active = run_embed(event.view, content, characters.get_character(conn, 1).id)
    names = [f.name for f in active.fields]
    assert {"Enemigos", "Héroes"} <= set(names) and "El enemigo prepara…" in names and "Tus acciones" in names
    assert len(active.title) < 256 and all(len(f.value) <= 1024 for f in active.fields)
    # una partida terminada muestra su resumen
    easy_enemies = {k: dataclasses.replace(e, hp_k=0.05) for k, e in content.dungeon_enemies.items()}
    summary = dungeons.FinishSummary("win", ("Sala",), (dungeons.ParticipantResult("Aldric", "active", 10, 5, 0.5, 1, (), 3),
                                                       dungeons.ParticipantResult("Brenna", "left", 0, 0, 0.0, 0, (), 0)),
                                     {"gold": 50, "sello_del_sepulcro": 3})
    embed = finish_embed(summary, content)
    assert len(embed.fields) == 3 and "×½" in embed.fields[0].value


def test_bar_helper_is_bounded():
    from kame.bot.embeds import bar

    assert bar(0, 10) == "▱" * 10 and bar(10, 10) == "▰" * 10 and bar(-5, 10) == "▱" * 10
    assert bar(5, 0) in ("▰" * 10, "▱" * 10) and len(bar(999, 10)) == 10


def test_help_text_lists_detallar_and_is_bounded():
    from kame.bot.embeds import HELP_TEXT

    assert "/habilidades detallar" in HELP_TEXT
    assert len(HELP_TEXT) <= 2000


def test_shop_embed_renders_every_state(conn, content):
    from kame.bot.embeds import shop_embed
    from kame.db.database import transaction
    from kame.services import shop

    now = 20_000 * 86_400 + 100
    characters.create_character(conn, content, 1, "Aldric", "guerrero")
    embed = shop_embed(shop.get_shop(conn, content, 1, now), content)
    names = [f.name for f in embed.fields]
    assert "Arma" in names and "Mochila" in names and "Maestro de entrenamiento" in names
    assert all(len(f.value) <= 1024 for f in embed.fields) and "Tu oro" in embed.description
    assert "No tienes puntos gastados" in embed.fields[-1].value
    with transaction(conn):
        conn.execute("UPDATE characters SET gold = 9999, level = 12")
    characters.spend_points(conn, 1, "fuerza", 2)
    offer = next(o for o in shop.get_shop(conn, content, 1, now).offers if o.level_ok)
    shop.buy_offer(conn, content, 1, offer.offer.key, now)
    for _ in range(len(content.shop.bag_prices)):
        shop.buy_bag_upgrade(conn, content, 1)
    embed = shop_embed(shop.get_shop(conn, content, 1, now), content)
    text = "\n".join(f.value for f in embed.fields)
    assert "✅ comprado" in text and "Mochila al máximo" in text and "gratis" in text


def test_inventory_embed_uses_the_real_capacity_with_bag_upgrades(conn, content):
    from kame.db.database import transaction
    from kame.services import items, shop

    c = characters.create_character(conn, content, 1, "Aldric", "guerrero")
    with transaction(conn):
        conn.execute("UPDATE characters SET gold = 9999")
    shop.buy_bag_upgrade(conn, content, 1)
    cap = items.inventory_cap(conn, content, c.id)
    assert cap == content.config.items.inventory_cap + content.shop.bag_slots
    from kame.bot.embeds import inventory_embed
    assert f"0/{cap}" in inventory_embed([], 1, 8, cap, None).footer.text


def test_respec_confirmation_view_builds():
    class FakeBot:
        pass

    async def run():
        view = ConfirmRespecView(FakeBot(), 1)
        return view.timeout, [c.label for c in view.children]

    assert asyncio.run(run()) == (30, ["Reiniciar atributos", "Cancelar"])
