"""Comandos de estadísticas diarias: /daily."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import DARK_RED
from kame.services import characters
from kame.services import statistics as daily_statistics


class DailyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="diaria", description="Consulta las estadísticas diarias de tu personaje")
    @app_commands.describe(publico="Mostrar en el canal para que todos lo vean")
    async def daily(self, interaction: discord.Interaction, publico: bool = False):
        character = characters.get_character(self.bot.conn, interaction.user.id)
        stats = daily_statistics.get_statistics(self.bot.conn, self.bot.content, character.id)
        embed = _daily_embed(character.name, stats, self.bot.content)
        await interaction.response.send_message(embed=embed, ephemeral=not publico)


def _daily_embed(name: str, stats: daily_statistics.StatisticsView, content) -> discord.Embed:
    embed = discord.Embed(
        title=f"📅 Estadísticas diarias de {name}",
        description="Resumen de tus actividades de hoy.",
        color=DARK_RED,
    )

    # Expediciones
    exped_text = (
        f"• Completadas: **{stats.expeditions_completed}**\n"
        f"• Victorias: **{stats.expeditions_won}**\n"
        f"• Derrotas/Retiradas: **{stats.expeditions_lost}**"
    )
    embed.add_field(name="🗺️ Expediciones", value=exped_text, inline=True)

    # Encuentros y combate
    combat_text = (
        f"• Encuentros totales: **{stats.total_encounters}**\n"
        f"• Encuentros ganados: **{stats.total_victories}**\n"
        f"• Mazmorras finalizadas: **{stats.dungeons_completed}**"
    )
    embed.add_field(name="⚔️ Combates", value=combat_text, inline=True)

    # Recursos
    resources_text = (
        f"• Oro ganado: **{stats.total_gold}**\n"
        f"• XP ganada: **{stats.total_xp}**"
    )
    embed.add_field(name="💰 Recursos obtenidos", value=resources_text, inline=False)

    # Enemigos derrotados
    if stats.enemies_killed:
        enemy_lines = []
        for enemy_id, count in sorted(stats.enemies_killed.items(), key=lambda item: (-item[1], item[0])):
            enemy_name = content.enemies[enemy_id].name if enemy_id in content.enemies else enemy_id
            enemy_lines.append(f"• {enemy_name}: **{count}**")
        # Truncar si son demasiadas líneas para caber limpiamente en un field
        value_text = "\n".join(enemy_lines)
        if len(value_text) > 1024:
            value_text = value_text[:1020] + "..."
        embed.add_field(name="👾 Enemigos derrotados", value=value_text, inline=False)
    else:
        embed.add_field(name="👾 Enemigos derrotados", value="Ninguno todavía.", inline=False)

    embed.set_footer(text="¡Sigue explorando y completando mazmorras para mejorar tus estadísticas!")
    return embed