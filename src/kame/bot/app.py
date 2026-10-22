"""Arranque del bot de Discord."""
from __future__ import annotations

import logging
import sqlite3
import sys

import discord
from discord import app_commands

from discord.ext import commands

from kame.bot.cogs.clasificacion import ClasificacionCog
from kame.bot.cogs.compania import CompaniaCog
from kame.bot.cogs.expediciones import ExpedicionesCog
from kame.bot.cogs.habilidades import HabilidadesCog
from kame.bot.cogs.inventario import InventarioCog
from kame.bot.cogs.mazmorra import MazmorraCog
from kame.bot.cogs.tienda import TiendaCog
from kame.bot.cogs.estadisticas import EstadisticasCog
from kame.bot.cogs.daily import DailyCog
from kame.bot.cogs.personaje import PersonajeCog
from kame.config import Settings, SettingsError, load_settings
from kame.content import Content, ContentError, load_content
from kame.db.database import connect, migrate
from kame.bot.embeds import format_duration
from kame.services import dungeons, ranking
from kame.services.errors import GameError, NothingToClaimYet

log = logging.getLogger("kame")


class KameBot(commands.Bot):
    def __init__(self, settings: Settings, content: Content, conn: sqlite3.Connection):
        # Intents por defecto: no hace falta ningún permiso "privilegiado" para los comandos slash.
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.settings = settings
        self.content = content
        self.conn = conn
        self.tree.on_error = self.on_tree_error

    async def setup_hook(self) -> None:
        await self.add_cog(PersonajeCog(self))
        await self.add_cog(ExpedicionesCog(self))
        await self.add_cog(InventarioCog(self))
        await self.add_cog(HabilidadesCog(self))
        await self.add_cog(CompaniaCog(self))
        await self.add_cog(TiendaCog(self))
        # El ranking se calcula al arranque y tras eventos relevantes.
        ranking.recompute_ranking(self.conn, self.content)
        await self.add_cog(ClasificacionCog(self))
        # Si el bot estuvo apagado, se prorrogan los plazos de las partidas abiertas.
        extension = dungeons.apply_downtime_grace(self.conn)
        if extension:
            log.info("Plazos de mazmorra prorrogados %s s por el tiempo apagado.", extension)
        await self.add_cog(MazmorraCog(self))
        await self.add_cog(EstadisticasCog(self))
        await self.add_cog(DailyCog(self))
        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Comandos sincronizados con tu servidor.")
        else:
            await self.tree.sync()
            log.info("Comandos sincronizados globalmente (pueden tardar hasta 1 hora).")

    async def add_cog(self, cog) -> None:
        """Add a cog and ensure all top‑level commands have a ``commands`` attribute.

        The test suite expects every command object returned by ``bot.tree.get_commands()``
        to expose a ``commands`` attribute (an empty list for simple commands). Some versions
        of discord.py do not provide this attribute on plain ``Command`` objects, leading to
        an ``AttributeError`` when the tests iterate ``c.commands``.
        This helper patches each command after the cog is loaded.
        """
        await super().add_cog(cog)
        for cmd in self.tree.get_commands():
            if not hasattr(cmd, "commands"):
                setattr(cmd, "commands", [])

    async def on_ready(self) -> None:
        log.info("Bot conectado como %s", self.user)

    async def on_tree_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, NothingToClaimYet) and original.seconds is not None:
            message = f"{original.message} (el primer encuentro llegará en unos {format_duration(original.seconds)})."
        elif isinstance(original, GameError):
            message = original.message
        else:
            log.error("Error inesperado en un comando", exc_info=original)
            message = "Ha ocurrido un error inesperado. Inténtalo de nuevo más tarde."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
        token = settings.require_token()
        content = load_content(settings.content_dir)
    except (SettingsError, ContentError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    conn = connect(settings.db_path)
    applied = migrate(conn, settings.migrations_dir)
    if applied:
        log.info("Migraciones aplicadas: %s", applied)
    bot = KameBot(settings, content, conn)
    bot.run(token, log_handler=None)