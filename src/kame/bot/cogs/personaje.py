"""Comandos de personaje: /crear, /perfil, /atributos, /ayuda."""
from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from kame.bot.embeds import ATTRIBUTE_LABELS, HELP_TEXT, mechanics_embed, profile_embed
from kame.services import characters, items

AttributeChoice = Literal["fuerza", "inteligencia", "vitalidad", "destreza", "suerte"]


class PersonajeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="crear", description="Crea tu personaje")
    @app_commands.describe(nombre="Nombre de tu personaje", clase="Clase de tu personaje")
    async def crear(self, interaction: discord.Interaction, nombre: str, clase: str):
        character = characters.create_character(
            self.bot.conn, self.bot.content, interaction.user.id, nombre, clase
        )
        class_def = self.bot.content.classes[character.class_id]
        await interaction.response.send_message(
            f"**{character.name}**, {class_def.name}, se une a la compañía. "
            "Usa `/perfil` para verlo y `/atributos` para gastar tus puntos libres.",
            embed=profile_embed(character, self.bot.content),
        )

    @crear.autocomplete("clase")
    async def crear_clase_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [
            app_commands.Choice(name=c.name, value=c.id)
            for c in self.bot.content.classes.values()
            if current in c.name.lower() or current in c.id
        ][:25]

    @app_commands.command(name="perfil", description="Consulta tu personaje")
    @app_commands.describe(publico="Mostrar en el canal para que todos lo vean")
    async def perfil(self, interaction: discord.Interaction, publico: bool = False):
        character = characters.get_character(self.bot.conn, interaction.user.id)
        materials = characters.get_materials(self.bot.conn, character.id)
        build = items.current_build(self.bot.conn, self.bot.content, character)
        await interaction.response.send_message(
            embed=profile_embed(character, self.bot.content, materials, build),
            ephemeral=not publico
        )

    @app_commands.command(name="atributos", description="Gasta puntos libres en un atributo")
    @app_commands.describe(atributo="Atributo a mejorar", cantidad="Puntos a gastar (1 por defecto)")
    async def atributos(
        self,
        interaction: discord.Interaction,
        atributo: AttributeChoice,
        cantidad: app_commands.Range[int, 1, 100] = 1,
    ):
        character = characters.spend_points(self.bot.conn, interaction.user.id, atributo, cantidad)
        await interaction.response.send_message(
            f"+{cantidad} en {ATTRIBUTE_LABELS[atributo]}. Puntos libres restantes: "
            f"{character.unspent_points}.",
            embed=profile_embed(character, self.bot.content),
            ephemeral=True,
        )

    @app_commands.command(name="ayuda", description="Muestra los comandos disponibles")
    async def ayuda(self, interaction: discord.Interaction):
        await interaction.response.send_message(HELP_TEXT, ephemeral=True)

    @app_commands.command(name="mecanicas", description="Fórmulas de atributos, daño, habilidades y combate")
    async def mecanicas(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=mechanics_embed(), ephemeral=True)
