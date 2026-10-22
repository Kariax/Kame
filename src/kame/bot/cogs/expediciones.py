"""Comandos de expediciones: /expedicion y /reclamar."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import (
    active_expedition_embed,
    claim_embed,
    expedition_list_embed,
    preview_expedition_embed,
    combat_log_embed,
)
from kame.services import characters, expeditions


class ExpedicionesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="expedicion", description="Mira los destinos o envía a tu personaje de expedición"
    )
    @app_commands.describe(destino="Destino al que enviar a tu personaje (déjalo vacío para ver la lista)")
    async def expedicion(self, interaction: discord.Interaction, destino: str | None = None):
        conn, content = self.bot.conn, self.bot.content
        character = characters.get_character(conn, interaction.user.id)
        if destino is None:
            active = expeditions.get_active_expedition(conn, content, interaction.user.id)
            embed = (
                active_expedition_embed(active)
                if active
                else expedition_list_embed(content, character.level)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        definition = expeditions.start_expedition(conn, content, interaction.user.id, destino)
        hours = content.config.expeditions.max_accumulation_hours
        text = (
            f"**{character.name}** parte hacia **{definition.name}**. Acumulará progreso "
            f"durante {hours:g} h como máximo; usa `/reclamar` cuando vuelvas."
        )
        if character.unspent_points:
            text += (
                f"\n⚠️ Tienes **{character.unspent_points}** puntos de atributo sin gastar: "
                "usa `/atributos` para que cuenten en tus próximas expediciones."
            )
        await interaction.response.send_message(text)

    @expedicion.autocomplete("destino")
    async def expedicion_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [
            app_commands.Choice(
                name=f"{e.name} (nv {e.recommended_level}, {e.risk})"[:100], value=e.id
            )
            for e in self.bot.content.expeditions.values()
            if current in e.name.lower() or current in e.id
        ][:25]

    @app_commands.command(name="combate", description="Ver el último combate resuelto de tu expedición activa")
    async def combate(self, interaction: discord.Interaction):
        conn, content = self.bot.conn, self.bot.content
        active = expeditions.get_active_expedition(conn, content, interaction.user.id)
        if active is None:
            await interaction.response.send_message("No tienes ninguna expedición en curso.", ephemeral=True)
            return
        if not active.last_combat_log:
            await interaction.response.send_message(
                "Aún no se ha resuelto ningún combate en esta expedición. "
                "Los combates se resuelven al usar `/reclamar`.",
                ephemeral=True
            )
            return
        embed = combat_log_embed(active)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="reclamar", description="Recoge los resultados de tu expedición")
    @app_commands.describe(preview="Simular el resultado sin reclamar (solo lectura)")
    async def reclamar(self, interaction: discord.Interaction, preview: bool = False):
        conn, content = self.bot.conn, self.bot.content
        if preview:
            result = expeditions.preview_resolve_expedition(conn, content, interaction.user.id)
            character = characters.get_character(conn, interaction.user.id)
            await interaction.response.send_message(
                embed=preview_expedition_embed(character.name, result, content),
                ephemeral=True,
            )
            return
        result = expeditions.claim_expedition(conn, content, interaction.user.id)
        character = characters.get_character(conn, interaction.user.id)
        await interaction.response.send_message(embed=claim_embed(character.name, result, content))
