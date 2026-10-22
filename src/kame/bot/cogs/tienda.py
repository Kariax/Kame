"""Comandos de la tienda: /tienda ver | comprar | mochila | reiniciar."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import item_detail, item_title, shop_embed
from kame.engine.items import RARITY_LABELS, SLOT_LABELS
from kame.services import shop
from kame.services.errors import GameError


class ConfirmRespecView(discord.ui.View):
    """Confirmación para reiniciar atributos (cuesta oro y cambia tu build)."""

    def __init__(self, bot, user_id: int):
        super().__init__(timeout=30)
        self.bot, self.user_id = bot, user_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esta confirmación no es tuya.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Reiniciar atributos", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        try:
            result = shop.respec_attributes(self.bot.conn, self.bot.content, self.user_id)
            cost = "gratis" if result.cost == 0 else f"por {result.cost} de oro"
            text = (f"Atributos reiniciados ({cost}). Recuperas **{result.refunded}** puntos: "
                    f"ahora tienes **{result.character.unspent_points}** libres. Usa `/atributos`.")
        except GameError as error:
            text = error.message
        self.stop()
        await interaction.response.edit_message(content=text, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content="Reinicio cancelado.", view=None)


class TiendaCog(commands.Cog):
    tienda = app_commands.Group(name="tienda", description="Gasta tu oro: equipo, mochila y entrenamiento")

    def __init__(self, bot):
        self.bot = bot

    @tienda.command(name="ver", description="Mira las ofertas del día y los servicios")
    async def ver(self, interaction: discord.Interaction):
        view = shop.get_shop(self.bot.conn, self.bot.content, interaction.user.id)
        await interaction.response.send_message(embed=shop_embed(view, self.bot.content), ephemeral=True)

    @tienda.command(name="comprar", description="Compra un objeto del equipo del día")
    @app_commands.describe(oferta="Objeto a comprar")
    async def comprar(self, interaction: discord.Interaction, oferta: str):
        item, price = shop.buy_offer(self.bot.conn, self.bot.content, interaction.user.id, oferta)
        await interaction.response.send_message(
            f"Compras **{item_title(item)}** por **{price}** de oro. Está en tu inventario.\n"
            f"{item_detail(item, self.bot.content)}", ephemeral=True)

    @comprar.autocomplete("oferta")
    async def comprar_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            view = shop.get_shop(self.bot.conn, self.bot.content, interaction.user.id)
        except GameError:
            return []
        current = current.lower()
        choices = []
        for ov in view.offers:
            if ov.bought or current not in ov.template.name.lower():
                continue
            t = ov.template
            label = f"{t.name} [{RARITY_LABELS[t.rarity]}] {SLOT_LABELS[t.slot]} — {ov.offer.price} oro"
            if not ov.level_ok:
                label += f" (nv {t.min_level})"
            choices.append(app_commands.Choice(name=label[:100], value=ov.offer.key))
        return choices[:25]

    @tienda.command(name="mochila", description="Amplía tu inventario")
    async def mochila(self, interaction: discord.Interaction):
        level, cap, price = shop.buy_bag_upgrade(self.bot.conn, self.bot.content, interaction.user.id)
        await interaction.response.send_message(
            f"Mochila ampliada (nivel {level}) por **{price}** de oro: ahora tienes **{cap}** huecos.",
            ephemeral=True)

    @tienda.command(name="reiniciar", description="Recupera tus puntos de atributo para repartirlos de nuevo")
    async def reiniciar(self, interaction: discord.Interaction):
        view = shop.get_shop(self.bot.conn, self.bot.content, interaction.user.id)
        if not view.refundable:
            raise shop.NothingToRespec()
        cost = "gratis (tu primer reinicio)" if view.respec_is_free else f"**{view.respec_cost}** de oro"
        await interaction.response.send_message(
            f"Recuperarás **{view.refundable}** puntos de atributo y tus atributos volverán a los de partida de "
            f"tu clase. Cuesta {cost}. ¿Continuar?",
            view=ConfirmRespecView(self.bot, interaction.user.id), ephemeral=True)
