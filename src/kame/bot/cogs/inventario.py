"""Comandos de inventario y equipo: /inventario /equipo /equipar /desequipar /vender."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import (
    equipment_embed,
    inventory_embed,
    item_choice_label,
    item_detail,
    item_title,
)
from kame.engine.items import RARITIES, SLOT_LABELS
from kame.services import characters, items
from kame.services.errors import GameError

SLOT_BY_ES = {
    "arma": "weapon", "casco": "helmet", "armadura": "armor",
    "guantes": "gloves", "botas": "boots", "amuleto": "amulet",
}
SLOT_CHOICES = [app_commands.Choice(name=name.capitalize(), value=name) for name in SLOT_BY_ES]
CONFIRM_FROM_RARITY = RARITIES.index("rare")
PER_PAGE = 8


class ConfirmSellView(discord.ui.View):
    """Confirmación para vender objetos raros o mejores."""

    def __init__(self, bot, user_id: int, item_id: str):
        super().__init__(timeout=30)
        self.bot, self.user_id, self.item_id = bot, user_id, item_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esta confirmación no es tuya.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Vender", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        try:
            item, gold = items.sell_item(self.bot.conn, self.bot.content, self.user_id, self.item_id)
            text = f"Vendido **{item.template.name}** por **{gold}** de oro."
        except GameError as error:
            text = error.message
        self.stop()
        await interaction.response.edit_message(content=text, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content="Venta cancelada.", view=None)


class InventarioCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _item_autocomplete(self, interaction: discord.Interaction, current: str, only_unequipped=False):
        try:
            inventory = items.list_inventory(self.bot.conn, self.bot.content, interaction.user.id)
        except GameError:
            return []
        current = current.lower()
        return [
            app_commands.Choice(name=item_choice_label(i), value=i.id)
            for i in inventory
            if (not only_unequipped or not i.equipped) and current in i.template.name.lower()
        ][:25]

    @app_commands.command(name="inventario", description="Lista tus objetos")
    @app_commands.describe(ranura="Filtra por ranura", pagina="Página (8 objetos por página)")
    @app_commands.choices(ranura=SLOT_CHOICES)
    async def inventario(
        self, interaction: discord.Interaction,
        ranura: app_commands.Choice[str] | None = None,
        pagina: app_commands.Range[int, 1, 100] = 1,
    ):
        slot = SLOT_BY_ES[ranura.value] if ranura else None
        inventory = items.list_inventory(self.bot.conn, self.bot.content, interaction.user.id, slot)
        character = characters.get_character(self.bot.conn, interaction.user.id)
        embed = inventory_embed(
            inventory, pagina, PER_PAGE,
            items.inventory_cap(self.bot.conn, self.bot.content, character.id),
            SLOT_LABELS[slot] if slot else None,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="equipo", description="Muestra lo que llevas puesto")
    async def equipo(self, interaction: discord.Interaction):
        character = characters.get_character(self.bot.conn, interaction.user.id)
        build = items.current_build(self.bot.conn, self.bot.content, character)
        equipped = items.get_equipment(self.bot.conn, self.bot.content, interaction.user.id)
        await interaction.response.send_message(
            embed=equipment_embed(build, equipped, self.bot.content), ephemeral=True
        )

    @app_commands.command(name="equipar", description="Equipa un objeto de tu inventario")
    @app_commands.describe(objeto="Objeto a equipar")
    async def equipar(self, interaction: discord.Interaction, objeto: str):
        equipped, replaced = items.equip_item(self.bot.conn, self.bot.content, interaction.user.id, objeto)
        text = f"Equipado: **{item_title(equipped)}**\n{item_detail(equipped, self.bot.content)}"
        if replaced:
            text += f"\n\nVuelve al inventario: {item_title(replaced)}"
        await interaction.response.send_message(text, ephemeral=True)

    @equipar.autocomplete("objeto")
    async def equipar_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._item_autocomplete(interaction, current)

    @app_commands.command(name="desequipar", description="Quita el objeto de una ranura")
    @app_commands.describe(ranura="Ranura a vaciar")
    @app_commands.choices(ranura=SLOT_CHOICES)
    async def desequipar(self, interaction: discord.Interaction, ranura: app_commands.Choice[str]):
        item = items.unequip_slot(
            self.bot.conn, self.bot.content, interaction.user.id, SLOT_BY_ES[ranura.value]
        )
        await interaction.response.send_message(
            f"Has guardado **{item_title(item)}** en el inventario.", ephemeral=True
        )

    @app_commands.command(name="vender", description="Vende un objeto no equipado por oro")
    @app_commands.describe(objeto="Objeto a vender")
    async def vender(self, interaction: discord.Interaction, objeto: str):
        conn, content = self.bot.conn, self.bot.content
        character = characters.get_character(conn, interaction.user.id)
        match = next(
            (i for i in items.list_inventory(conn, content, interaction.user.id) if i.id == objeto), None
        )
        if match is None:
            raise items.ItemNotFound()
        if match.equipped:
            raise items.ItemEquippedCannotSell()
        price = content.config.items.sell_values[match.template.rarity]
        if RARITIES.index(match.template.rarity) >= CONFIRM_FROM_RARITY:
            view = ConfirmSellView(self.bot, interaction.user.id, match.id)
            await interaction.response.send_message(
                f"¿Vender **{item_title(match)}** por **{price}** de oro?\n{item_detail(match, content)}",
                view=view, ephemeral=True,
            )
            return
        item, gold = items.sell_item(conn, content, interaction.user.id, objeto)
        await interaction.response.send_message(
            f"Vendido **{item.template.name}** por **{gold}** de oro. Oro total: {character.gold + gold}.",
            ephemeral=True,
        )

    @vender.autocomplete("objeto")
    async def vender_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._item_autocomplete(interaction, current, only_unequipped=True)
