"""Comando /habilidades: consultar y configurar habilidades y modo de la definitiva."""
from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import loadout_embed, skill_detail_embed
from kame.content import Content
from kame.engine.models import Character
from kame.engine.skills import SkillDef
from kame.services import skills

MODE_BY_ES = {"siempre": "always", "enemigo_fuerte": "elite", "vida_baja": "low_hp", "nunca": "never"}
ModeChoice = Literal["siempre", "enemigo_fuerte", "vida_baja", "nunca"]


def _estimate_skill_damage(skill: SkillDef, character: Character, content: Content) -> int:
    """Estima el daño base de una habilidad para mostrar en el autocompletado.

    Fórmula aproximada: power * multiplier, donde:
    - poder físico ≈ 2 * fuerza + destreza + nivel
    - poder mágico ≈ 2 * inteligencia + nivel
    """
    if skill.multiplier <= 0:
        return 0
    class_def = content.classes[character.class_id]
    is_physical = class_def.basic_attack.damage_type == "physical"
    attrs = character.attributes
    if is_physical:
        power = 2 * attrs.get("fuerza", 0) + attrs.get("destreza", 0) + character.level
    else:
        power = 2 * attrs.get("inteligencia", 0) + character.level
    return int(power * skill.multiplier)


class HabilidadesCog(commands.Cog):
    habilidades = app_commands.Group(
        name="habilidades", description="Mira o configura tus habilidades y tu definitiva"
    )

    def __init__(self, bot):
        self.bot = bot

    @habilidades.command(name="ver", description="Mira o configura tus habilidades y tu definitiva")
    @app_commands.describe(
        habilidad1="Habilidad de prioridad 1",
        habilidad2="Habilidad de prioridad 2",
        definitiva="Cuándo usar la definitiva en combates automáticos",
    )
    async def ver(
        self,
        interaction: discord.Interaction,
        habilidad1: str | None = None,
        habilidad2: str | None = None,
        definitiva: ModeChoice | None = None,
    ):
        conn, content = self.bot.conn, self.bot.content
        if habilidad1 is None and habilidad2 is None and definitiva is None:
            view = skills.get_loadout(conn, content, interaction.user.id)
        else:
            view = skills.set_loadout(
                conn, content, interaction.user.id, habilidad1, habilidad2,
                MODE_BY_ES[definitiva] if definitiva else None,
            )
        await interaction.response.send_message(embed=loadout_embed(view, content), ephemeral=True)

    @habilidades.command(name="detallar", description="Muestra la descripción detallada de una habilidad")
    @app_commands.describe(habilidad="Habilidad que quieres ver en detalle")
    async def detallar(self, interaction: discord.Interaction, habilidad: str):
        conn, content = self.bot.conn, self.bot.content
        view = skills.get_loadout(conn, content, interaction.user.id)
        skill = content.skills.get(habilidad)
        if skill is None:
            await interaction.response.send_message(
                f"❌ No encontré la habilidad `{habilidad}`.", ephemeral=True
            )
            return
        embed = skill_detail_embed(skill, view.character, content)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _skill_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            view = skills.get_loadout(self.bot.conn, self.bot.content, interaction.user.id)
        except Exception:
            return []
        current = current.lower()
        return [
            app_commands.Choice(
                name=f"{s.name} (reutilización {s.cooldown}, mult: ×{s.multiplier:g}, dmg~{_estimate_skill_damage(s, view.character, self.bot.content)})"[:100],
                value=s.id
            )
            for s in view.available
            if current in s.name.lower()
        ][:25]

    @ver.autocomplete("habilidad1")
    async def habilidad1_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._skill_autocomplete(interaction, current)

    @ver.autocomplete("habilidad2")
    async def habilidad2_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._skill_autocomplete(interaction, current)

    @ver.autocomplete("definitiva")
    async def definitiva_autocomplete(self, interaction: discord.Interaction, current: str):
        """Autocomplete for the 'definitiva' parameter with descriptive choices."""
        choices = [
            app_commands.Choice(name="Siempre que esté ready ⚔️", value="siempre"),
            app_commands.Choice(name="Solo contra enemigos fuertes 💪", value="enemigo_fuerte"),
            app_commands.Choice(name="Solo con vida baja (< 50%) ❤️", value="vida_baja"),
            app_commands.Choice(name="Nunca 🛑", value="nunca"),
        ]
        if not current:
            return choices
        lower = current.lower()
        return [c for c in choices if lower in c.name.lower() or lower in c.value.lower()]

    @detallar.autocomplete("habilidad")
    async def detallar_autocomplete(self, interaction: discord.Interaction, current: str):
        """Autocomplete for the 'habilidad' parameter of /habilidades detallar."""
        try:
            view = skills.get_loadout(self.bot.conn, self.bot.content, interaction.user.id)
        except Exception:
            return []
        current = current.lower()
        return [
            app_commands.Choice(name=f"{s.name} (reutilización {s.cooldown}, mult: ×{s.multiplier:g})"[:100], value=s.id)
            for s in view.available
            if current in s.name.lower()
        ][:25]
