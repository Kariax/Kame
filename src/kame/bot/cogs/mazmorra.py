"""Comandos de mazmorras cooperativas: /mazmorra info | crear | unirse | iniciar | estado | accion | abandonar."""
from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from kame.bot.embeds import dungeon_list_embed, finish_embed, run_embed
from kame.services import characters, dungeons
from kame.services.dungeons import RunEvent

log = logging.getLogger("kame")

ACTIONS = {
    "atacar": "attack", "habilidad1": "skill1", "habilidad2": "skill2",
    "definitiva": "ultimate", "defender": "defend", "proteger": "protect",
}
ACTION_CHOICES = [app_commands.Choice(name=k, value=k) for k in ACTIONS]


class MazmorraCog(commands.Cog):

    class DungeonActionView(discord.ui.View):
        """View with interactive buttons for dungeon actions."""
        def __init__(self, bot, run_id: int, character_id: int, timeout: float = 60):
            self.bot = bot
            self.run_id = run_id
            self.character_id = character_id
            super().__init__(timeout=timeout)
            # Define button specs: (label, style, action_kind)
            button_defs = [
                ("⚔️ Atacar", discord.ButtonStyle.primary, "attack"),
                ("✨ Habilidad 1", discord.ButtonStyle.success, "skill1"),
                ("✨ Habilidad 2", discord.ButtonStyle.success, "skill2"),
                ("⚡ Definitiva", discord.ButtonStyle.danger, "ultimate"),
                ("🛡️ Defender", discord.ButtonStyle.secondary, "defend"),
            ]
            for label, style, kind in button_defs:
                btn = discord.ui.Button(label=label, style=style, custom_id=f"dungeon_action:{run_id}:{kind}")
                async def callback(interaction: discord.Interaction, kind=kind):
                    # Submit action without target
                    dungeons.submit_action(self.bot.conn, self.bot.content, interaction.user.id, kind, None)
                    await interaction.response.defer()
                btn.callback = callback
                self.add_item(btn)
            # Add a select for ally choice when protect is used
            select = discord.ui.Select(placeholder="Elige aliado a proteger", min_values=1, max_values=1)
            # Options will be populated lazily; placeholder for now
            async def select_callback(interaction: discord.Interaction):
                target = int(interaction.data["values"][0])
                dungeons.submit_action(self.bot.conn, self.bot.content, interaction.user.id, "protect", target)
                await interaction.response.defer()
            select.callback = select_callback
            self.add_item(select)

    mazmorra = app_commands.Group(name="mazmorra", description="Mazmorras cooperativas por rondas")

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.check_runs.start()

    async def cog_unload(self) -> None:
        self.check_runs.cancel()

    # ---------- anuncios ----------

    def _embeds_for(self, event: RunEvent) -> list[discord.Embed]:
        content = self.bot.content
        embeds: list[discord.Embed] = []
        if event.view is not None and event.kind in ("started", "round", "left", "cancelled"):
            embed = run_embed(event.view, content)
            if event.lines and event.kind != "round":
                embed.description = (embed.description or "") + "\n" + "\n".join(event.lines)
            embeds.append(embed)
        if event.summary is not None:
            embeds.append(finish_embed(event.summary, content))
        return embeds

    async def announce(self, events: list[RunEvent], fallback: discord.abc.Messageable | None = None) -> None:
        for event in events:
            if event.kind == "action":
                continue
            embeds = self._embeds_for(event)
            if not embeds:
                continue
            channel = self.bot.get_channel(event.channel_id) if event.channel_id else None
            channel = channel or fallback
            if channel is None:
                continue
            try:
                await channel.send(embeds=embeds)
            except discord.DiscordException:
                log.warning("No se pudo anunciar el evento de la partida %s", event.run_id)

    @tasks.loop(seconds=60)
    async def check_runs(self) -> None:
        try:
            events = dungeons.process_due(self.bot.conn, self.bot.content)
            dungeons.touch_heartbeat(self.bot.conn)
            await self.announce(events)
        except Exception:  # la tarea nunca debe morir por un error puntual
            log.exception("Error al procesar plazos de mazmorra")

    @check_runs.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def _respond(self, interaction: discord.Interaction, events: list[RunEvent], ack: str | None = None):
        """Responde al jugador (en privado) y anuncia lo que pase en el canal de la partida."""
        public = [e for e in events if e.kind != "action"]
        if ack is not None or not public:
            await interaction.response.send_message(ack or "Hecho.", ephemeral=True)
        else:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("Hecho.", ephemeral=True)
        await self.announce(public, fallback=interaction.channel)

    # ---------- comandos ----------

    @mazmorra.command(name="info", description="Mazmorras disponibles y partidas que reúnen grupo")
    async def info(self, interaction: discord.Interaction):
        dungeons.process_due(self.bot.conn, self.bot.content)
        embed = dungeon_list_embed(self.bot.content, dungeons.list_open_runs(self.bot.conn, self.bot.content))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mazmorra.command(name="crear", description="Empieza a reunir un grupo para una mazmorra")
    @app_commands.describe(mazmorra="Mazmorra a la que ir")
    async def crear(self, interaction: discord.Interaction, mazmorra: str):
        view = dungeons.create_run(self.bot.conn, self.bot.content, interaction.user.id, mazmorra,
                                   interaction.channel_id)
        await interaction.response.send_message(
            "⚔️ Se abre una partida. ¡Que se una quien quiera!", embed=run_embed(view, self.bot.content))

    @crear.autocomplete("mazmorra")
    async def crear_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [app_commands.Choice(name=f"{d.name} (nv {d.min_level}+)"[:100], value=d.id)
                for d in self.bot.content.dungeons.values() if current in d.name.lower()][:25]

    @mazmorra.command(name="unirse", description="Únete a una partida que está reuniendo grupo")
    @app_commands.describe(partida="Partida (déjalo vacío si solo hay una)")
    async def unirse(self, interaction: discord.Interaction, partida: int | None = None):
        view = dungeons.join_run(self.bot.conn, self.bot.content, interaction.user.id, partida)
        await interaction.response.send_message(
            f"**{interaction.user.display_name}** se une a la partida.", embed=run_embed(view, self.bot.content))

    @unirse.autocomplete("partida")
    async def unirse_autocomplete(self, interaction: discord.Interaction, current: str):
        runs = dungeons.list_open_runs(self.bot.conn, self.bot.content)
        return [app_commands.Choice(
                    name=f"#{r.id} {r.dungeon_name} — {r.leader_name} ({r.players}/{r.max_players})"[:100],
                    value=r.id) for r in runs][:25]

    @mazmorra.command(name="iniciar", description="(Líder) Empieza la mazmorra con el grupo actual")
    async def iniciar(self, interaction: discord.Interaction):
        event = dungeons.start_run(self.bot.conn, self.bot.content, interaction.user.id)
        await interaction.response.send_message(
            "🕯️ ¡La partida comienza!", embed=run_embed(event.view, self.bot.content))

    @mazmorra.command(name="estado", description="Mira el estado de tu partida")
    async def estado(self, interaction: discord.Interaction):
        events = dungeons.process_due(self.bot.conn, self.bot.content)
        character = characters.get_character(self.bot.conn, interaction.user.id)
        view = dungeons.get_my_run(self.bot.conn, self.bot.content, interaction.user.id)
        await interaction.response.send_message(
            embed=run_embed(view, self.bot.content, character.id), ephemeral=True)
        await self.announce(events, fallback=interaction.channel)

    @mazmorra.command(name="accion", description="Elige tu acción de esta ronda")
    @app_commands.describe(
        tipo="Qué haces esta ronda",
        objetivo="Nº del enemigo (atacar/habilidades) o del aliado (proteger). Vacío = el primero",
    )
    @app_commands.choices(tipo=ACTION_CHOICES)
    async def accion(self, interaction: discord.Interaction, tipo: app_commands.Choice[str],
                     objetivo: app_commands.Range[int, 1, 20] | None = None):
        events = dungeons.submit_action(self.bot.conn, self.bot.content, interaction.user.id,
                                        ACTIONS[tipo.value], objetivo)
        resolved = any(e.kind == "round" for e in events)
        ack = f"Acción registrada: **{tipo.value}**." + ("" if resolved else " Se resolverá cuando todos actúen o llegue el plazo.")
        await self._respond(interaction, events, ack)

    @mazmorra.command(name="abandonar", description="Abandona tu partida (sin recompensas)")
    async def abandonar(self, interaction: discord.Interaction):
        events = dungeons.leave_run(self.bot.conn, self.bot.content, interaction.user.id)
        await self._respond(interaction, events, "Has abandonado la partida.")
