"""Construcción de los mensajes bonitos (embeds) de Discord."""
from __future__ import annotations

import discord

from kame.content import Content
from kame.engine.build import PlayerBuild, build_stats, effective_attributes, item_effects
from kame.engine.effects import describe_effect
from kame.engine.items import (
    RARITY_ICONS,
    RARITY_LABELS,
    SLOT_LABELS,
    SLOTS,
    STAT_LABELS,
)
from kame.engine.models import ATTRIBUTES, Character
from kame.engine.progression import xp_to_next_level
from kame.engine.skills import ULTIMATE_MODE_LABELS
from kame.engine.stats import derive_stats

DARK_RED = discord.Color.from_rgb(139, 26, 26)

RARITY_RGB = {
    "common": (180, 180, 180),
    "uncommon": (80, 200, 80),
    "rare": (80, 160, 255),
    "epic": (180, 80, 255),
    "legendary": (255, 180, 0),
}

ATTRIBUTE_LABELS = {
    "fuerza": "Fuerza",
    "inteligencia": "Inteligencia",
    "vitalidad": "Vitalidad",
    "destreza": "Destreza",
    "suerte": "Suerte",
}


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return "menos de 1 min"


# URLs de thumbnail por clase (placeholder - se pueden reemplazar por assets reales)
CLASS_THUMBNAILS = {
    "Guerrero": "https://cdn.discordapp.com/attachments/placeholder/guerrero.png",
    "Mago": "https://cdn.discordapp.com/attachments/placeholder/mago.png",
    "Pícaro": "https://cdn.discordapp.com/attachments/placeholder/picaro.png",
}


def profile_embed(
    character: Character,
    content: Content,
    materials: dict[str, int] | None = None,
    build: PlayerBuild | None = None,
) -> discord.Embed:
    class_def = content.classes[character.class_id]
    rules = content.config.progression
    need = xp_to_next_level(character.level, rules)
    xp_text = f"{character.xp} / {need}" if need else "Nivel máximo"

    embed = discord.Embed(
        title=character.name,
        description=f"**{class_def.name}** · Nivel {character.level}",
        color=DARK_RED,
    )
    # Thumbnail de clase
    thumb_url = CLASS_THUMBNAILS.get(class_def.name)
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)
    embed.add_field(name="Experiencia", value=xp_text, inline=True)
    embed.add_field(name="Oro", value=str(character.gold), inline=True)
    embed.add_field(name="Puntos libres", value=str(character.unspent_points), inline=True)

    effective = effective_attributes(build) if build else character.attributes
    lines = []
    for attr in ATTRIBUTES:
        star = " ★" if attr in class_def.primary else ""
        bonus = effective[attr] - character.attributes[attr]
        extra = f" (+{bonus} equipo)" if bonus else ""
        lines.append(f"{ATTRIBUTE_LABELS[attr]}: **{effective[attr]}**{extra}{star}")
    embed.add_field(name="Atributos", value="\n".join(lines), inline=False)

    s = build_stats(build) if build else derive_stats(character.level, character.attributes)
    embed.add_field(
        name="Estadísticas",
        value=(
            f"Vida: **{s.max_hp}**\n"
            f"Poder físico: **{s.physical_power}** · Poder mágico: **{s.magic_power}**\n"
            f"Defensa: **{s.defense}**\n"
            f"Crítico: **{s.crit_chance}%** · Bonus de botín: **{s.loot_bonus}%**"
        ),
        inline=False,
    )
    if materials:
        lines = [
            f"{content.materials[m].name}: **{n}**" if m in content.materials else f"{m}: **{n}**"
            for m, n in materials.items()
        ]
        embed.add_field(name="Materiales", value="\n".join(lines), inline=False)
    embed.set_footer(text="★ = atributo principal de tu clase")
    return embed


def expedition_list_embed(content: Content, character_level: int) -> discord.Embed:
    rules = content.config.expeditions
    embed = discord.Embed(
        title="Expediciones",
        description=(
            f"Tu personaje avanza solo hasta **{rules.max_accumulation_hours:g} h**. "
            "Si cae en combate, se retira y conserva lo ganado hasta ese momento. "
            "Empieza una con `/expedicion destino:<nombre>`."
        ),
        color=DARK_RED,
    )
    for exp in content.expeditions.values():
        locked = character_level < exp.min_level
        title = f"{exp.name} — {exp.risk}" + ("  🔒" if locked else "")
        detail = f"Nivel recomendado: {exp.recommended_level}"
        if locked:
            detail += f" · Requiere nivel {exp.min_level}"
        embed.add_field(name=title, value=f"{exp.description}\n*{detail}*", inline=False)
    return embed


def active_expedition_embed(active) -> discord.Embed:
    exp = active.definition
    embed = discord.Embed(title=f"En expedición: {exp.name}", description=exp.description, color=DARK_RED)
    # Progress bar for elapsed time vs limit
    max_seconds = active.elapsed_seconds + active.seconds_to_full if active.seconds_to_full else active.elapsed_seconds
    progress = progress_bar(active.elapsed_seconds, max_seconds, 10)
    embed.add_field(name="Progreso", value=f"{progress} {format_duration(active.elapsed_seconds)} / {format_duration(max_seconds)}", inline=False)
    embed.add_field(name="Tiempo fuera", value=format_duration(active.elapsed_seconds), inline=True)
    embed.add_field(
        name="Encuentros",
        value=encounter_bar(active.encounters_ready, active.max_encounters),
        inline=True,
    )
    if active.seconds_to_full > 0:
        embed.add_field(name="Límite en", value=format_duration(active.seconds_to_full), inline=True)
    else:
        embed.add_field(name="Límite", value="alcanzado: no acumula más", inline=True)
    embed.set_footer(text="Usa /reclamar para recoger los resultados (puedes hacerlo cuando quieras).")
    return embed


def combat_log_embed(active) -> discord.Embed:
    """Embed para mostrar el último combate resuelto en /expedicion combate."""
    exp = active.definition
    log = active.last_combat_log

    if not log:
        return discord.Embed(
            title=f"⚔️ {exp.name} — Sin combates resueltos",
            description="Aún no se ha resuelto ningún combate.",
            color=DARK_RED
        )

    # Determinar estado del último combate
    won = active.last_player_won
    title_emoji = "✅" if won else "❌"
    title = f"{title_emoji} Combate resuelto: {active.last_enemy_name}"

    # HP bars
    enemy_hp_pct = active.last_enemy_hp / max(1, active.last_enemy_max_hp) if active.last_enemy_max_hp > 0 else 0
    player_hp_pct = active.last_player_hp / max(1, active.last_player_max_hp) if active.last_player_max_hp > 0 else 0

    enemy_bar = progress_bar(int(enemy_hp_pct * 10), 10, 10)
    player_bar = progress_bar(int(player_hp_pct * 10), 10, 10)

    embed = discord.Embed(title=title, color=DARK_RED)
    embed.add_field(
        name=f"👾 {active.last_enemy_name}",
        value=f"{enemy_bar} {active.last_enemy_hp}/{active.last_enemy_max_hp} HP",
        inline=True
    )
    embed.add_field(
        name=f"⚔️ Tu personaje",
        value=f"{player_bar} {active.last_player_hp}/{active.last_player_max_hp} HP",
        inline=True
    )
    embed.add_field(name="​", value="​", inline=False)

    # Construir el log de combate
    lines = []
    current_round = 0
    for entry in log:
        if entry.round != current_round:
            current_round = entry.round
            lines.append(f"**Ronda {current_round}**")

        if entry.turn == "player":
            if entry.action == "stunned":
                lines.append(f"  😵 Tú estás aturdido")
            elif entry.action == "basic_attack":
                crit = " 💥" if entry.is_crit else ""
                lines.append(f"  ⚔️ Ataque básico → **{entry.damage}**{crit}")
            elif entry.is_heal:
                lines.append(f"  💚 {entry.action.capitalize()} → **+{entry.heal_amount} HP**")
            else:
                # Skill o ultimate
                emoji = "✨" if entry.action == "ultimate" else "🔮"
                crit = " 💥" if entry.is_crit else ""
                effect = f" ({entry.effect})" if entry.effect else ""
                dmg_text = f" → **{entry.damage}**{crit}" if entry.damage > 0 else ""
                lines.append(f"  {emoji} {entry.action}{dmg_text}{effect}")
        else:  # enemy
            if entry.action == "stunned":
                lines.append(f"  😵 {active.last_enemy_name} está aturdido")
            elif entry.action == "basic_attack":
                lines.append(f"  👾 {active.last_enemy_name} ataca → **{entry.damage}**")
            elif entry.action == "poison_damage":
                lines.append(f"  💧 Veneno en {active.last_enemy_name} → **{entry.damage}**")
            else:
                lines.append(f"  👾 {active.last_enemy_name} → {entry.action}")

    # Truncar si es muy largo
    log_text = "\n".join(lines)
    if len(log_text) > 1024:
        log_text = log_text[:1020] + "..."

    embed.add_field(name="📋 Desarrollo del combate", value=log_text or "Sin detalles", inline=False)
    embed.set_footer(text=f"Encuentro #{active.encounters_ready} de {active.max_encounters} · Usa /reclamar para recoger recompensas")
    return embed


def claim_embed(character_name: str, result, content: Content) -> discord.Embed:
    o = result.outcome
    exp = result.definition
    if o.retreated:
        title = f"🎉 {character_name} se retiró herido de {exp.name}"
        description = (
            f"Ganó {o.victories} de {o.encounters} combates antes de caer y tuvo que replegarse. "
            "Conserva todo lo ganado hasta entonces."
        )
    else:
        title = f"🎉 {character_name} regresa de {exp.name}"
        description = f"Superó los {o.victories} encuentros del viaje."
    embed = discord.Embed(title=title, description=description, color=DARK_RED)
    xp_text = f"+{o.xp + result.bonus_xp}" + (f" (incl. +{result.bonus_xp} de la Armería)" if result.bonus_xp else "")
    gold_text = f"+{o.gold + result.bonus_gold}" + (f" (incl. +{result.bonus_gold} de la Armería)" if result.bonus_gold else "")
    embed.add_field(name="Experiencia", value=xp_text, inline=True)
    embed.add_field(name="Oro", value=gold_text, inline=True)
    if o.materials:
        embed.add_field(
            name="Materiales",
            value="\n".join(
                f"{content.materials[m].name}: +{n}" for m, n in sorted(o.materials.items())
            ),
            inline=False,
        )
    if o.kills:
        embed.add_field(
            name="Enemigos derrotados",
            value="\n".join(
                f"{content.enemies[e].name}: {n}" for e, n in sorted(o.kills.items())
            ),
            inline=False,
        )
    if result.items:
        embed.add_field(
            name="Objetos",
            value="\n".join(f"{item_title(i)} ({SLOT_LABELS[i.template.slot]})" for i in result.items),
            inline=False,
        )
    if result.overflow_items:
        embed.add_field(
            name="Inventario lleno",
            value=(
                f"{len(result.overflow_items)} objeto(s) se vendieron solos por "
                f"+{result.overflow_gold} de oro."
            ),
            inline=False,
        )
    if result.xp_result.levels_gained:
        embed.add_field(
            name="¡Subida de nivel!",
            value=f"Nivel **{result.xp_result.level}** (+{result.xp_result.points_gained} puntos libres)",
            inline=False,
        )
        # Celebration in title
        embed.title = f"🎉 {embed.title}"
        embed.description += f"\n🎉 **¡HAS SUBIDO DE NIVEL!** Ahora eres nivel **{result.xp_result.level}**."
    return embed


def preview_expedition_embed(character_name: str, result, content: Content) -> discord.Embed:
    """Embed de previsualización de `/reclamar`.

    Muestra exactamente los mismos datos que `claim_embed` pero con un estilo
    claramente distinguible (título con prefijo 🔎 Preview, color azul) para que
    el jugador sepa que son solo una simulación y que aún no se ha reclamado.
    """
    o = result.outcome
    exp = result.definition
    if o.retreated:
        title = f"🔎 Preview – {character_name} se retiró herido de {exp.name}"
        description = (
            f"Ganó {o.victories} de {o.encounters} combates antes de caer y tuvo que replegarse. "
            "Conserva todo lo ganado hasta ese momento."
        )
    else:
        title = f"🔎 Preview – {character_name} regresa de {exp.name}"
        description = f"Superó los {o.victories} encuentros del viaje."
    embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
    embed.set_footer(text="Esta es una previsualización: no se ha reclamado nada. Usa /reclamar para cobrar.")

    xp_text = f"+{o.xp + result.bonus_xp}" + (f" (incl. +{result.bonus_xp} de la Armería)" if result.bonus_xp else "")
    gold_text = f"+{o.gold + result.bonus_gold}" + (f" (incl. +{result.bonus_gold} de la Armería)" if result.bonus_gold else "")
    embed.add_field(name="Experiencia", value=xp_text, inline=True)
    embed.add_field(name="Oro", value=gold_text, inline=True)
    if o.materials:
        embed.add_field(
            name="Materiales",
            value="\n".join(
                f"{content.materials[m].name}: +{n}" for m, n in sorted(o.materials.items())
            ),
            inline=False,
        )
    if o.kills:
        embed.add_field(
            name="Enemigos derrotados",
            value="\n".join(
                f"{content.enemies[e].name}: {n}" for e, n in sorted(o.kills.items())
            ),
            inline=False,
        )
    if result.items:
        embed.add_field(
            name="Objetos",
            value="\n".join(f"{item_title(i)} ({SLOT_LABELS[i.template.slot]})" for i in result.items),
            inline=False,
        )
    if result.overflow_items:
        embed.add_field(
            name="Inventario lleno",
            value=(
                f"{len(result.overflow_items)} objeto(s) se vendieron solos por "
                f"+{result.overflow_gold} de oro."
            ),
            inline=False,
        )
    if result.xp_result.levels_gained:
        embed.add_field(
            name="Subida de nivel (simulada)",
            value=f"Nivel **{result.xp_result.level}** (+{result.xp_result.points_gained} puntos libres)",
            inline=False,
        )
    return embed


HELP_TEXT = (
    "**Comandos disponibles**\n"
    "`/crear` – crea tu personaje (nombre y clase). Solo uno por jugador.\n"
    "`/perfil` – consulta tu nivel, atributos y estadísticas.\n"
    "`/atributos` – gasta tus puntos libres en un atributo.\n"
    "`/expedicion` – mira los destinos, el estado de tu expedición o empieza una nueva.\n"
    "`/reclamar` – recoge XP, oro, materiales y objetos de tu expedición.\n"
    "`/inventario` – lista tus objetos (filtra por ranura).\n"
    "`/equipo` – muestra lo que llevas puesto y sus bonificaciones.\n"
    "`/equipar` / `/desequipar` – cambia tu equipo.\n"
    "`/vender` – vende un objeto no equipado por oro.\n"
    "`/habilidades` – mira y configuras tus habilidades y cuándo usar la definitiva.\n"
    "`/compania` – almacén compartido: `ver`, `donar` y `mejorar` la sede.\n"
    "`/tienda` – gasta tu oro: `ver`, `comprar` equipo del día, `mochila` y `reiniciar` atributos.\n"
    "`/mazmorra` – cooperativo: `info`, `crear`, `unirse`, `iniciar`, `estado`, `accion`, `abandonar`.\n"
    "`/clasificacion` – ranking de personajes por puntuación.\n"
    "`/mecanicas` – fórmulas de atributos, daño, habilidades y combate.\n"
    "`/diaria` – estadísticas y progreso diario de tu personaje.\n"
    "`/ayuda` – muestra este mensaje.\n\n"
    "Las mazmorras se juegan por rondas: cuando todos eligen acción se resuelve al instante; si no, al llegar el plazo."
)


def mechanics_embed() -> discord.Embed:
    """Embed con las fórmulas y mecánicas del juego (para /mecanicas)."""
    embed = discord.Embed(
        title="📖 Fórmulas y mecánicas",
        description="Cómo se calculan tus estadísticas y funciona el combate.",
        color=DARK_RED,
    )
    embed.add_field(
        name="Atributos base",
        value=(
            "• **Fuerza** → Poder físico (ataques físicos)\n"
            "• **Inteligencia** → Poder mágico (ataques mágicos)\n"
            "• **Vitalidad** → Vida máxima + Defensa\n"
            "• **Destreza** → Poder físico + Crítico\n"
            "• **Suerte** → Crítico + Bonus de botín"
        ),
        inline=False,
    )
    embed.add_field(
        name="Estadísticas derivadas (nivel L, atributos A)",
        value=(
            "• **Vida** = 40 + 5×L + 10×Vitalidad + Vida_equipo\n"
            "• **Poder físico** = 2×Fuerza + Destreza + L + Poder_equipo\n"
            "• **Poder mágico** = 2×Inteligencia + L + Poder_equipo\n"
            "• **Defensa** = Vitalidad + L/2 + Defensa_equipo\n"
            "• **Crítico** = 5% + 0.4×Destreza + 0.2×Suerte + Crítico_equipo (máx 60%)\n"
            "• **Bonus botín** = 0.5×Suerte + Botín_equipo"
        ),
        inline=False,
    )
    embed.add_field(
        name="Combate automático (orden de prioridad)",
        value=(
            "1. **Definitiva** (según tu modo: siempre / fuerte / vida baja / nunca)\n"
            "2. **Habilidad 1** (si está lista y es útil)\n"
            "3. **Habilidad 2** (si está lista y es útil)\n"
            "4. **Ataque básico** (si nada más está listo)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Habilidades — qué hace cada campo",
        value=(
            "• **Multiplier > 1** = daño (× poder tuyo)\n"
            "• **Guard** = reduce daño recibido (ej. 0.5 = -50% por X turnos)\n"
            "• **Heal** = cura % de tu vida máxima\n"
            "• **Stun** = enemigo pierde turno\n"
            "• **Vulnerable/Weaken** = enemigo recibe más daño / hace menos daño\n"
            "• **Poison** = daño por turno que ignora armadura\n"
            "• **Ignore armor** = atraviesa % de defensa enemiga\n"
            "• **Always crit** = golpe crítico garantizado"
        ),
        inline=False,
    )
    embed.add_field(
        name="Fórmula de daño",
        value=(
            "**Daño** = Poder × Multiplier × Variación(±20%) × Mitigación\n"
            "**Mitigación** = Poder / (Poder + Armadura_enemigo)"
        ),
        inline=False,
    )
    return embed


# ---------------------------------------------------------------------------
# Objetos, equipo y habilidades
# ---------------------------------------------------------------------------

def stat_text(stats: dict) -> str:
    parts = []
    for key, value in stats.items():
        label = STAT_LABELS.get(key, key)
        number = f"{value:g}" if isinstance(value, float) else str(value)
        parts.append(f"{label} +{number}")
    return " · ".join(parts)


def item_title(item) -> str:
    t = item.template
    return f"{RARITY_ICONS[t.rarity]} {t.name}"


def item_detail(item, content: Content) -> str:
    t = item.template
    skill_names = {k: v.name for k, v in content.skills.items()}
    lines = [f"{RARITY_LABELS[t.rarity]} · {SLOT_LABELS[t.slot]} · nivel {t.min_level}", stat_text(item.stats)]
    for effect in t.effects:
        lines.append(f"✦ {describe_effect(effect, skill_names)}")
    return "\n".join(lines)


def item_choice_label(item) -> str:
    t = item.template
    tag = " (equipado)" if item.equipped else ""
    return f"{t.name} [{RARITY_LABELS[t.rarity]}] {SLOT_LABELS[t.slot]} nv{t.min_level}{tag}"[:100]


def inventory_embed(items: list, page: int, per_page: int, cap: int, slot_label: str | None) -> discord.Embed:
    pages = max(1, -(-len(items) // per_page))
    page = min(max(1, page), pages)
    chunk = items[(page - 1) * per_page : page * per_page]
    title = "Inventario" + (f" — {slot_label}" if slot_label else "")
    color = DARK_RED
    if items:
        rarity_order = {"legendary": 5, "epic": 4, "rare": 3, "uncommon": 2, "common": 1}
        max_rarity = max(items, key=lambda i: rarity_order[i.template.rarity]).template.rarity
        color = discord.Color.from_rgb(*RARITY_RGB[max_rarity])
    embed = discord.Embed(title=title, color=color)
    if not chunk:
        embed.description = "No tienes objetos."
    for item in chunk:
        t = item.template
        mark = "  ✅ equipado" if item.equipped else ""
        effects = f"  ✦ {len(t.effects)} efecto(s)" if t.effects else ""
        embed.add_field(
            name=f"{item_title(item)}{mark}",
            value=f"{SLOT_LABELS[t.slot]} · nv {t.min_level}{effects}\n{stat_text(item.stats)}",
            inline=False,
        )
    embed.set_footer(text=f"Página {page}/{pages} · {len(items)}/{cap} objetos · usa /equipar o /vender")
    return embed


def equipment_embed(build: PlayerBuild, equipped: dict, content: Content) -> discord.Embed:
    embed = discord.Embed(title=f"Equipo de {build.name}", color=DARK_RED)
    for slot in SLOTS:
        item = equipped.get(slot)
        if item is None:
            embed.add_field(name=f"{SLOT_LABELS[slot]}", value="— vacío —", inline=False)
        else:
            embed.add_field(name=f"{SLOT_LABELS[slot]}: {item_title(item)}", value=item_detail(item, content), inline=False)
    skill_names = {k: v.name for k, v in content.skills.items()}
    effects = [describe_effect(e, skill_names) for e in item_effects(build)]
    if effects:
        embed.add_field(name="Efectos activos", value="\n".join(f"✦ {e}" for e in effects), inline=False)
    return embed


def loadout_embed(view, content: Content) -> discord.Embed:
    class_def = content.classes[view.character.class_id]
    attack = class_def.basic_attack
    embed = discord.Embed(
        title=f"Habilidades de {view.character.name}",
        description=(
            f"**{class_def.name}** · Ataque básico: daño "
            f"{'físico' if attack.damage_type == 'physical' else 'mágico'}.\n"
            "Tu personaje usa, por orden: la definitiva (según su modo), la habilidad 1, "
            "la habilidad 2 y, si ninguna está lista, el ataque básico."
        ),
        color=DARK_RED,
    )
    for index, skill in enumerate(view.equipped, start=1):
        embed.add_field(
            name=f"Habilidad {index}: {skill.name} (reutilización {skill.cooldown})",
            value=skill.description, inline=False,
        )
    if view.ultimate:
        embed.add_field(
            name=f"Definitiva: {view.ultimate.name} (reutilización {view.ultimate.cooldown})",
            value=f"{view.ultimate.description}\n*Se usa: {ULTIMATE_MODE_LABELS[view.ultimate_mode]}.*",
            inline=False,
        )
    elif view.ultimate_locked:
        embed.add_field(
            name="Definitiva", value=f"Se desbloquea en el nivel {view.ultimate_locked.unlock_level}.",
            inline=False,
        )
    others = [s for s in view.available if s not in view.equipped]
    if others:
        embed.add_field(
            name="Disponibles para equipar",
            value="\n".join(f"**{s.name}** – {s.description}" for s in others), inline=False,
        )
    if view.locked:
        embed.add_field(
            name="Bloqueadas",
            value="\n".join(f"{s.name} (nivel {s.unlock_level})" for s in view.locked), inline=False,
        )
    embed.set_footer(text="Configura con /habilidades habilidad1:… habilidad2:… definitiva:…")
    return embed


# ---------------------------------------------------------------------------
# Compañía y mazmorras
# ---------------------------------------------------------------------------

def progress_bar(current: int, maximum: int, width: int = 10) -> str:
    """Return a simple progress bar using ▰ for filled and ▱ for empty.
    Mirrors the existing `bar` helper but uses explicit current/maximum.
    """
    maximum = max(1, maximum)
    filled = max(0, min(width, round(width * max(0, current) / maximum)))
    return "▰" * filled + "▱" * (width - filled)

def bar(value: int, maximum: int, width: int = 10) -> str:
    maximum = max(1, maximum)
    filled = max(0, min(width, round(width * max(0, value) / maximum)))
    return "▰" * filled + "▱" * (width - filled)


def encounter_bar(completed: int, total: int, width: int = 8) -> str:
    """Return an animated encounter progress bar using ⚔️ ems.

    Shows completed encounters with ⚔️ and remaining with blank space,
    followed by "completed/total" format.

    Example: encounter_bar(4, 8) → "⚔️⚔️⚔️⚔️       4/8"
    """
    filled = max(0, min(width, completed))
    empty = width - filled
    swords = "⚔️" * filled
    blanks = " " * empty
    return f"{swords}{blanks} {completed}/{total}"


def _resource_name(content: Content, resource_id: str) -> str:
    if resource_id == "gold":
        return "Oro"
    material = content.materials.get(resource_id)
    return material.name if material else resource_id


def cost_text(content: Content, cost: dict[str, int]) -> str:
    return ", ".join(f"{amount} {_resource_name(content, r)}" for r, amount in cost.items())


def dashboard_embed(character: Character, stats: dict, recent_activity: list, content: Content) -> discord.Embed:
    embed = discord.Embed(
        title=f"Dashboard de {character.name}",
        description=f"**{character.class_id.name}** · Nivel {character.level}",
        color=DARK_RED,
    )

    # Add fields for key stats
    embed.add_field(
        name="Resumen",
        value=f"XP: {character.xp} / {xp_to_next_level(character.level, content.config.progression)}\
"
              f"Oro: **{character.gold}**\n"
              f"Puntos libres: {character.unspent_points}",
        inline=False,
    )

    # Add a stats section
    stats_text = "\n".join(
        f"{ATTRIBUTE_LABELS[attr]}: **{stats[attr]}**"
        for attr in ATTRIBUTES
    )
    embed.add_field(name="Atributos", value=stats_text, inline=False)

    # Add recent activity (e.g., last 3 expeditions)
    if recent_activity:
        embed.add_field(
            name="Últimas actividades",
            value="\n".join(
                f"- {a['name']}: {a['duration']} ({a['reward']} XP)"
                for a in recent_activity[:3]
            ),
            inline=False,
        )

    # Footer with instructions
    embed.set_footer(text="Usa /perfil para detalles completos.")
    return embed


def company_embed(view, content: Content, ledger: list) -> discord.Embed:
    embed = discord.Embed(title=view.name, color=DARK_RED,
                          description="Sede compartida de la compañía. Dona recursos y mejora la sede entre todos.")
    if view.storage:
        lines = [f"{_resource_name(content, r)}: **{n}**" for r, n in sorted(view.storage.items())]
    else:
        lines = ["Vacío. Usa `/compania donar` para aportar oro o materiales."]
    embed.add_field(name="Almacén", value="\n".join(lines), inline=False)
    for upgrade in content.company_upgrades.values():
        level = view.upgrades.get(upgrade.id, 0)
        if level >= upgrade.max_level:
            text = f"Nivel {level}/{upgrade.max_level} (máximo)"
        else:
            nxt = upgrade.levels[level]
            have = {r: view.storage.get(r, 0) for r in nxt.cost}
            ok = all(have[r] >= n for r, n in nxt.cost.items())
            text = (f"Nivel {level}/{upgrade.max_level}. Siguiente: +{nxt.xp_bonus:.0%} XP y +{nxt.gold_bonus:.0%} oro\n"
                    f"Coste: {cost_text(content, nxt.cost)}" + ("  ✅ disponible" if ok else ""))
        embed.add_field(name=f"{upgrade.name} — {upgrade.description}", value=text, inline=False)
    if view.xp_bonus or view.gold_bonus:
        embed.add_field(name="Bonus activo en expediciones",
                        value=f"+{view.xp_bonus:.0%} XP · +{view.gold_bonus:.0%} oro", inline=False)
    if ledger:
        rows = []
        for e in ledger[:6]:
            who = e.character_name or "Mazmorra"
            sign = "+" if e.delta > 0 else ""
            rows.append(f"{who}: {sign}{e.delta} {_resource_name(content, e.resource_id)}")
        embed.add_field(name="Últimos movimientos", value="\n".join(rows), inline=False)
    return embed


def dungeon_list_embed(content: Content, open_runs: list) -> discord.Embed:
    embed = discord.Embed(title="Mazmorras", color=DARK_RED,
                          description="Se juegan por rondas y en grupo. `/mazmorra crear` para empezar a reunir gente.")
    for d in content.dungeons.values():
        embed.add_field(
            name=d.name,
            value=(f"{d.description}\nNivel {d.min_level}+ (recomendado {d.recommended_level}) · "
                   f"{d.min_players}-{d.max_players} jugadores · {len(d.stages)} salas con jefe de "
                   f"{len(d.stages[-1].phases)} fases"),
            inline=False)
    if open_runs:
        lines = [f"**#{r.id}** {r.dungeon_name} — líder {r.leader_name} ({r.players}/{r.max_players}) · "
                 f"caduca <t:{r.recruit_deadline}:R>" for r in open_runs]
        embed.add_field(name="Partidas reuniendo grupo", value="\n".join(lines), inline=False)
    return embed


def _status_tags(unit) -> str:
    tags = []
    if unit.stun > 0:
        tags.append("😵")
    if unit.guard_turns > 0:
        tags.append("🛡️")
    if unit.vuln_turns > 0:
        tags.append("🎯")
    if unit.weaken_turns > 0:
        tags.append("⬇️")
    if unit.poison_turns > 0:
        tags.append("☠️")
    return " ".join(tags)


def run_embed(view, content: Content, viewer_character_id: int | None = None) -> discord.Embed:
    dungeon = view.dungeon
    parts = view.participants
    if view.state == "recruiting":
        embed = discord.Embed(title=f"Partida #{view.id} — {dungeon.name}", color=DARK_RED,
                              description=dungeon.description)
        active = [p for p in parts if p.state == "active"]
        embed.add_field(
            name=f"Grupo ({len(active)}/{dungeon.max_players}, mínimo {dungeon.min_players})",
            value="\n".join(f"{'👑 ' if p.character_id == view.leader_id else ''}{p.name}" for p in active),
            inline=False)
        embed.add_field(name="Reclutamiento", value=f"Caduca <t:{view.recruit_deadline}:R>", inline=False)
        embed.set_footer(text="Unirse: /mazmorra unirse · El líder empieza con /mazmorra iniciar")
        return embed

    st = view.battle
    if st is None:
        return discord.Embed(title=f"Partida #{view.id} — {dungeon.name}", description="Sin datos de combate.")
    stage = dungeon.stages[st.stage]
    title = f"Partida #{view.id} — {stage.name}"
    if st.phase:
        title += f" · Fase {st.phase}: {stage.phases[st.phase - 1].name}"
    color = discord.Color.dark_green() if view.outcome == "win" else DARK_RED
    embed = discord.Embed(title=title, color=color)
    if view.state == "active":
        embed.description = f"**Ronda {st.round}** · plazo <t:{view.round_deadline}:R>"
    else:
        label = {"win": "¡Victoria!", "loss": "Derrota", "abandoned": "Abandonada"}.get(view.outcome or "", view.state)
        embed.description = f"**{label}**"

    enemies = []
    for i, e in enumerate([u for u in st.enemies if u.alive], start=1):
        shield = f" 🛡️{e.shield}" if e.shield else ""
        enemies.append(f"`{i}.` **{e.name}** {bar(e.hp, e.c.max_hp)} {max(0, e.hp)}/{e.c.max_hp}{shield} {_status_tags(e)}")
    embed.add_field(name="Enemigos", value="\n".join(enemies) or "— ninguno —", inline=False)

    by_uid = {p.uid: p for p in parts}
    heroes = []
    for i, h in enumerate(st.heroes, start=1):
        p = by_uid.get(h.uid)
        if h.gone or (p and p.state != "active"):
            heroes.append(f"`{i}.` ~~{h.name}~~ (fuera)")
            continue
        mark = ""
        if view.state == "active" and p and h.alive:
            mark = " ✅" if p.acted else (" 🤖" if p.mode == "auto" else " ⏳")
        flags = " 💤 auto" if p and p.mode == "auto" else ""
        status = "💀" if not h.alive else f"{bar(h.hp, h.c.max_hp)} {h.hp}/{h.c.max_hp}"
        heroes.append(f"`{i}.` **{h.name}** {status} {_status_tags(h)}{flags}{mark}")
    embed.add_field(name="Héroes", value="\n".join(heroes), inline=False)

    if view.state == "active" and view.intent_lines:
        embed.add_field(name="El enemigo prepara…", value="\n".join(view.intent_lines)[:1024], inline=False)
    if viewer_character_id is not None and view.state == "active":
        me = next((h for h in st.heroes if h.uid == f"c{viewer_character_id}"), None)
        if me is not None and me.alive:
            lines = []
            for index, s in enumerate(me.c.skills, start=1):
                cd = me.cooldowns.get(s.id, 0)
                lines.append(f"habilidad{index}: {s.name} — " + ("lista" if cd == 0 else f"en {cd} ronda(s)"))
            if me.c.ultimate:
                cd = me.cooldowns.get(me.c.ultimate.id, 0)
                lines.append(f"definitiva: {me.c.ultimate.name} — " + ("lista" if cd == 0 else f"en {cd} ronda(s)"))
            embed.add_field(name="Tus acciones", value="\n".join(lines), inline=False)
    if st.log:
        embed.add_field(name="Última ronda", value="\n".join(st.log)[-1000:], inline=False)
    if view.state == "active":
        embed.set_footer(text="/mazmorra accion tipo:… objetivo:… · ✅ ya actuó · ⏳ pendiente · 🤖 modo automático")
    return embed


def finish_embed(summary, content: Content) -> discord.Embed:
    won = summary.outcome == "win"
    label = {"win": "¡La cripta ha sido purgada!", "loss": "El grupo ha caído", "abandoned": "Partida abandonada"}
    embed = discord.Embed(title=label.get(summary.outcome, "Fin de la partida"), color=
                          discord.Color.dark_green() if won else DARK_RED)
    if summary.cleared:
        embed.description = "Salas superadas: " + ", ".join(summary.cleared)
    for p in summary.participants:
        if p.state != "active":
            embed.add_field(name=p.name, value="Se marchó antes del final: sin recompensas.", inline=False)
            continue
        parts = [f"+{p.xp} XP", f"+{p.gold + p.overflow_gold} oro"]
        if p.levels_gained:
            parts.append("¡sube de nivel!")
        if p.factor < 1:
            parts.append("(×½ por ausencias)")
        if p.items:
            parts.append("Objetos: " + ", ".join(item_title(i) for i in p.items))
        if p.overflow_gold:
            parts.append(f"(inventario lleno: {p.overflow_gold} oro por ventas automáticas)")
        embed.add_field(name=p.name, value=" · ".join(parts), inline=False)
    if summary.shared:
        embed.add_field(name="Para la compañía",
                        value=", ".join(f"+{n} {_resource_name(content, r)}" for r, n in summary.shared.items()),
                        inline=False)
    return embed


# ---------------------------------------------------------------------------
# Tienda
# ---------------------------------------------------------------------------

def shop_embed(view, content: Content) -> discord.Embed:
    color = DARK_RED
    unpurchased = [ov for ov in view.offers if not ov.bought]
    if unpurchased:
        rarity_order = {"legendary": 5, "epic": 4, "rare": 3, "uncommon": 2, "common": 1}
        max_rarity = max(unpurchased, key=lambda ov: rarity_order[ov.template.rarity]).template.rarity
        color = discord.Color.from_rgb(*RARITY_RGB[max_rarity])
    embed = discord.Embed(
        title="Tienda del mercader", color=color,
        description=(f"Tu oro: **{view.gold}**\nLa oferta se renueva <t:{view.refresh_at}:R> y es la misma para "
                     "todos. Puedes comprar cada oferta una vez al día."),
    )
    by_slot: dict[str, list[str]] = {}
    for ov in view.offers:
        t = ov.template
        status = "✅ comprado" if ov.bought else (f"{ov.offer.price} oro" if ov.level_ok else f"🔒 nv {t.min_level}")
        number = len([x for x in by_slot.get(t.slot, [])]) + 1
        line = f"{RARITY_ICONS[t.rarity]} **{t.name}** — {status}\n    {stat_text(t.stats)}"
        by_slot.setdefault(t.slot, []).append(line)
    for slot in SLOTS:
        if slot in by_slot:
            embed.add_field(name=SLOT_LABELS[slot], value="\n".join(by_slot[slot]), inline=False)
    bag = f"Huecos: **{view.bag_used}/{view.bag_cap}**. "
    if view.bag_next_price is None:
        bag += "Mochila al máximo."
    else:
        bag += f"Ampliarla (+{view.bag_slots}) cuesta **{view.bag_next_price}** oro (`/tienda mochila`)."
    embed.add_field(name="Mochila", value=bag, inline=False)
    if view.refundable:
        cost = "gratis" if view.respec_is_free else f"**{view.respec_cost}** oro"
        respec = (f"Puedes recuperar **{view.refundable}** puntos de atributo para repartirlos de nuevo: {cost} "
                  "(`/tienda reiniciar`).")
    else:
        respec = "No tienes puntos gastados que recuperar."
    embed.add_field(name="Maestro de entrenamiento", value=respec, inline=False)
    embed.set_footer(text="El equipo raro, épico y legendario solo se consigue en las aventuras.")
    return embed