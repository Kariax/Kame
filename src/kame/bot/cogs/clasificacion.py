"""Comandos de clasificación: /clasificacion."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kame.services import ranking


class ClasificacionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clasificacion", description="Muestra el ranking de personajes por puntuación")
    @app_commands.describe(limite="Cuántos personajes mostrar (1-20, por defecto 10)")
    async def clasificacion(
        self,
        interaction: discord.Interaction,
        limite: app_commands.Range[int, 1, 20] = 10,
    ):
        entries = ranking.get_ranking(self.bot.conn, self.bot.content, limite)
        await interaction.response.send_message(
            embed=_ranking_embed(entries, self.bot.content), ephemeral=True
        )



CLASS_ICONS = {"Guerrero": "⚔️", "Mago": "🔮", "Pícaro": "🗡️"}

def _ranking_embed(entries: list[ranking.RankEntry], content) -> discord.Embed:
    embed = discord.Embed(title="Clasificación de personajes", color=discord.Color.purple())
    if not entries:
        embed.description = "Aún no hay datos de clasificación. ¡Sé el primero en subir de nivel!"
        return embed
    lines = []
    for e in entries:
        lines.append(
            f"**#{e.rank}** {CLASS_ICONS.get(e.class_name, '')} {e.name} — {e.class_name} (nv {e.level}) · **{e.score}** pts"
        )
    embed.description = "\n".join(lines)
    embed.set_footer(text="La puntuación refleja nivel, atributos y estadísticas derivadas.")
    return embed
