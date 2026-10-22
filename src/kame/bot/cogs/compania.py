"""Comandos de la compañía: /compania ver | donar | mejorar."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import _resource_name, company_embed, cost_text
from kame.engine.company import GOLD
from kame.services import company as company_service
from kame.services import characters
from kame.services.errors import StorageShort, UpgradeMaxLevel


class ConfirmUpgradeView(discord.ui.View):
    """Confirmación para comprar una mejora cara o la última de su tipo."""

    def __init__(self, bot, user_id: int, upgrade_id: str):
        super().__init__(timeout=30)
        self.bot, self.user_id, self.upgrade_id = bot, user_id, upgrade_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esta confirmación no es tuya.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sí, comprar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        content = self.bot.content
        try:
            level, cost = company_service.buy_upgrade(
                self.bot.conn, content, self.user_id, self.upgrade_id
            )
        except StorageShort as error:
            missing = ", ".join(f"{n} {_resource_name(content, r)}" for r, n in error.missing.items())
            await interaction.response.edit_message(
                content=f"Al almacén le falta: {missing}. Usa `/compania donar` para aportar.",
                view=None
            )
            self.stop()
            return
        except UpgradeMaxLevel:
            await interaction.response.edit_message(
                content="Esta mejora ya está en el nivel máximo.",
                view=None
            )
            self.stop()
            return
        upgrade = next(u for u in content.company_upgrades.values()
                       if u.id == self.upgrade_id.strip().lower() or u.name.lower() == self.upgrade_id.strip().lower())
        step = upgrade.levels[level - 1]
        await interaction.response.edit_message(
            content=(
                f"🏰 **{upgrade.name}** sube al nivel **{level}**: +{step.xp_bonus:.0%} XP y +{step.gold_bonus:.0%} "
                f"oro en las expediciones de todos. (Coste: {cost_text(content, cost)})"
            ),
            view=None
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content="Mejora cancelada.", view=None)


class CompaniaCog(commands.Cog):
    compania = app_commands.Group(name="compania", description="Almacén compartido y mejoras de la sede")

    def __init__(self, bot):
        self.bot = bot

    @compania.command(name="ver", description="Mira el almacén y las mejoras de la compañía")
    async def ver(self, interaction: discord.Interaction):
        conn, content = self.bot.conn, self.bot.content
        company_service.get_company  # asegura que la compañía existe (migración 004)
        view = company_service.get_company(conn, content)
        embed = company_embed(view, content, company_service.get_ledger(conn))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @compania.command(name="donar", description="Dona oro o materiales al almacén de la compañía")
    @app_commands.describe(recurso="Qué donas", cantidad="Cuánto")
    async def donar(self, interaction: discord.Interaction, recurso: str,
                    cantidad: app_commands.Range[int, 1, 1_000_000]):
        content = self.bot.content
        total = company_service.contribute(self.bot.conn, content, interaction.user.id, recurso, cantidad)
        name = _resource_name(content, recurso)
        # Obtener oro restante del jugador
        character = characters.get_character(self.bot.conn, interaction.user.id)
        await interaction.response.send_message(
            f"{interaction.user.display_name} dona **{cantidad} {name}** a la compañía. "
            f"El almacén tiene ahora **{total}**. Tu oro: **{character.gold}**."
        )

    @donar.autocomplete("recurso")
    async def donar_autocomplete(self, interaction: discord.Interaction, current: str):
        content = self.bot.content
        options = [(GOLD, "Oro")] + [(m.id, m.name) for m in content.materials.values()]
        current = current.lower()
        return [app_commands.Choice(name=n, value=i) for i, n in options if current in n.lower()][:25]

    @compania.command(name="mejorar", description="Compra el siguiente nivel de una mejora con el almacén")
    @app_commands.describe(mejora="Mejora de la sede")
    async def mejorar(self, interaction: discord.Interaction, mejora: str):
        content = self.bot.content
        key = (mejora or "").strip().lower()
        upgrade = content.company_upgrades.get(key)
        if upgrade is None:
            upgrade = next((u for u in content.company_upgrades.values() if u.name.lower() == key), None)
        if upgrade is None:
            await interaction.response.send_message("Mejora no encontrada.", ephemeral=True)
            return

        # Obtener nivel actual y coste del siguiente nivel
        current_level = company_service._upgrades(self.bot.conn).get(upgrade.id, 0)
        if current_level >= upgrade.max_level:
            await interaction.response.send_message(f"**{upgrade.name}** ya está en el nivel máximo.", ephemeral=True)
            return

        next_step = upgrade.levels[current_level]
        gold_cost = next_step.cost.get(GOLD, 0)
        is_last_level = current_level == upgrade.max_level - 1

        # Pedir confirmación si el coste en oro es alto (>1000) o es la última mejora
        if gold_cost > 1000 or is_last_level:
            warning = []
            if gold_cost > 1000:
                warning.append(f"cuesta **{gold_cost} de oro**")
            if is_last_level:
                warning.append("es el **último nivel** de esta mejora")
            await interaction.response.send_message(
                f"⚠️ Confirmar compra: **{upgrade.name}** Nivel {current_level + 1} "
                f"({' y '.join(warning)}). ¿Continuar?",
                view=ConfirmUpgradeView(self.bot, interaction.user.id, upgrade.id),
                ephemeral=True
            )
            return

        # Compra directa si no requiere confirmación
        try:
            level, cost = company_service.buy_upgrade(self.bot.conn, content, interaction.user.id, upgrade.id)
        except StorageShort as error:
            missing = ", ".join(f"{n} {_resource_name(content, r)}" for r, n in error.missing.items())
            await interaction.response.send_message(
                f"Al almacén le falta: {missing}. Usa `/compania donar` para aportar.", ephemeral=True)
            return
        step = upgrade.levels[level - 1]
        await interaction.response.send_message(
            f"🏰 **{upgrade.name}** sube al nivel **{level}**: +{step.xp_bonus:.0%} XP y +{step.gold_bonus:.0%} "
            f"oro en las expediciones de todos. (Coste: {cost_text(content, cost)})"
        )

    @mejorar.autocomplete("mejora")
    async def mejorar_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [app_commands.Choice(name=u.name, value=u.id)
                for u in self.bot.content.company_upgrades.values() if current in u.name.lower()][:25]
