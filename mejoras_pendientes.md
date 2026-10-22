# Mejoras Pendientes - Kame Bot

> Estado: **En progreso**  
> Última actualización: 2026-10-22 18:00  
> Total: **34** | **Completadas: 33** | **En progreso: 0** | **Pendientes: 1

---
  
## ✅ Completadas (22)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Estado |
|---|--------|-----------|----------|------------|--------|
| 1 | `/tienda` autocomplete | Quick Win | 🟢 | `tienda.py` | N/A (sin params) |
| 2 | `/compañia mejorar` confirmación | Quick Win | 🟢 | `compania.py` | ✅ View Sí/No |
| 3 | `/compañia donar` muestra oro | Quick Win | 🟢 | `compania.py` | ✅ |
| 4 | `/ perfil publico` param opcional | Quick Win | 🟢 | `personaje.py` | ✅ |
| 5 | `/reclamar` feedback subida nivel | Quick Win | 🟢 | `embeds.py` | ✅ 🎉 |
| 6 | `/habilidades definitiva` autocomplete | Quick Win | 🟢 | `habilidades.py` | ✅ |
| 7 | Vista previa daño en `/habilidades` | Medio | 🟡 | `skills.py` | ✅ dmg~420 |
| 8 | Sección fórmulas en `/ayuda` → `/mecanicas` | Quick Win | 🟢 | `embeds.py`, `personaje.py` | ✅ |
| 8b | **Comando `/diaria` dashboard** | UX Core | ✅ | Nuevo cog `daily.py`, embed en `embeds.py` | Dashboard con estadísticas diarias, progreso de expediciones activas, tienda (ofertas, mochila, respec), mazmorras abiertas (con jugadores) |
| 9 | `/clasificacion` (MVP opcional) | Feature | 🟡 | `ranking.py`, `clasificacion.py`, migración 006 | ✅ |
| 10 | Migración 006 + tests | Infra | 🟢 | `test_ranking.py`, `test_migrations.py` | ✅ |
| 11 | Fix HELP_TEXT > 2000 chars | Bugfix | 🟢 | `embeds.py`, `test_bot_wiring.py` | ✅ |
| 26 | **Barra de progreso visual en `/expedicion`** | Visual | 🟢 | `embeds.py` (`active_expedition_embed`) | ✅ |
| 27 | **Iconos de clase en `/clasificacion`** | Visual | 🟢 | `clasificacion.py` (`_ranking_embed`) | ✅ ⚔️🗡️🔮 |
| 28 | **Color de rareza en bordes embed tienda/inventario** | Visual | 🟢 | `embeds.py` (`shop_embed`, `inventory_embed`) | ✅ RARITY_RGB |
| 29 | **Thumbnail del personaje en `/perfil`** | Visual | 🟢 | `embeds.py` (`profile_embed`) | ✅ CLASS_THUMBNAILS |
| 17 | **`/estadisticas` totales personales** | Feature | ✅ | Nuevo servicio `statistics.py` | Expediciones ganadas/perdidas, mazmorras, oro, enemigos, objeto más raro |
| 30 | **Preview antes de reclamar `/reclamar`** | UX Premium | 🟡 | `expediciones.py`, `embeds.py` | ✅ Parámetro `preview: bool`; `preview_resolve_expedition` (read-only) + `preview_expedition_embed` (🔎 Preview, color azul). |

---

## 📋 Pendientes (1) - Por prioridad

### Nuevas propuestas: Expediciones más interactivas (1)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Detalle |
|---|--------|-----------|----------|------------|---------|
| **31-32** | **Simulación detallada de combate y barra de animación de encuentros** | UX Premium | ✅ | `expediciones.py`, `embeds.py` | La finalidad de la mejora es que la expedición sea más atractiva visualmente para el jugador. Cuando uses `/expedicion combate`, podrás ver el último combate como se ha resuelto, incluyendo los ataques realizados y recibidos, el daño realizado, las habilidades usadas, y una barra de animación de encuentros que muestra el progreso con emojis de espada por encuentro completado. |

### Alto impacto / Esfuerzo medio (4)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Detalle |
|---|--------|-----------|----------|------------|---------|
| 13 | **Botones interactivos en mazmorra** | UX Core | 🔴 | `mazmorra.py`, `embeds.py` | View con 6 botones (Attack, Skill1, Skill2, Ultimate, Defend, Protect) |
| 18 | **`/historial` últimas reclamaciones** | Feature | 🟡 | `activity_log` ya existe | Últimas 5 expediciones/mazmorras con XP/oro/objetos |
| 19 | **Desglose puntuación en `/clasificacion`** | Feature | 🟡 | `ranking.py`, `clasificacion.py` | Click o `/mis-puntos`: "Nivel 12×100=1200, Atributos+15×2=30..." |
| 10 | **Filtro rareza en `/inventario`** | UX | 🟢 | `inventario.py` | Param `rareza: Literal[...]` opcional |
| 11 | **Ordenar inventario (botones)** | UX | 🟡 | `embeds.py`, `inventario.py` | Botones ▲ Rareza ▼, ▲ Ranura ▼, ▲ Nivel ▼ |

### UX Mazmorras (4)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Detalle |
|---|--------|-----------|----------|------------|---------|
| 14 | **Temporizador visible en embed mazmorra** | UX | 🟡 | `mazmorra.py`, `tasks.loop` | "⏳ Plazo: 2h 15m" se actualiza editando mensaje |
| 15 | **Tooltip en `/mazmorra accion`** | UX | 🟢 | `mazmorra.py` | Choices con descripción: "Atacar ⚔️: daño básico" |
| 16 | **Alerta "te toca actuar" (DM/mención)** | UX | 🟡 | `dungeons.py`, `check_runs` | Opcional, configurable |
| 9 | **Notificación DM al terminar mazmorra** | UX | ✅ | `dungeons.py:announce` | DM a cada participante con botín personal |

### Información y transparencia (3)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Detalle |
|---|--------|-----------|----------|------------|---------|
| 20 | **Comparativa clases en `/ayuda`** | Docs | 🟢 | `embeds.py:HELP_TEXT` | "Guerrero: tanque, Mago: burst, Pícaro: crit/loot" |
| 17b | **Ranking por clase** | Feature | 🟡 | `ranking.py` | `/clasificacion clase:guerrero` |
| 19b | **Historial de ranking** | Feature | 🟡 | Nueva tabla | Ver evolución semanal |

### Técnico / Mantenibilidad (5)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Detalle |
|---|--------|-----------|----------|------------|---------|
| 21 | **Particionar `activity_log` por mes** | Infra | 🔴 | Migración + servicio | Evita tabla gigante |
| 22 | **Denormalizar `acted` en `dungeon_participants`** | Perf | 🟡 | Migración + `dungeons.py` | Evita join en `_required` |
| 23 | **Cache `content` con TTL / hot-reload** | Infra | 🟡 | `content.py` | Si se añade recarga en caliente |
| 24 | **Endpoint `/metrics` Prometheus** | Infra | 🟡 | Nuevo módulo | `prometheus-client` ligero |
| 25 | **Test carga concurrente 50 jugadores** | QA | 🟡 | `test_dungeons_service.py` | Ampliar test de concurrencia existente |

---
  
## 📝 Notas de implementación

### Para tareas visuales (26-29):
- Usar `discord.Color.from_rgb()` para colores exactos
- `RARITY_RGB = {"common": (180,180,180), "uncommon": (80,200,80), "rare": (80,160,255), "epic": (180,80,255), "legendary": (255,180,0)}`
- Thumbnail: si no hay asset server, usar `attachment://` o URL placeholder

### Para botones mazmorra (#13):
```python
class DungeonActionView(discord.ui.View):
    def __init__(self, bot, run_id, character_id):
        # 6 botones: Attack, Skill1, Skill2, Ultimate, Defend, Protect
        # Deshabilitar si en cooldown / aturdido
        # Callback llama a submit_action
```

### Para `/diaria` (#8):
```python
@app_commands.command(name="diaria", description="Resumen diario: expediciones, tienda, mazmorras")
async def diaria(self, interaction):
    # 1 embed con 3 secciones
```

---
  
## 🎯 Próximos pasos

1. **Implementar #31-32 (Simulación detallada de combate y barra de animación de encuentros)** — UX Premium, esfuerzo medio. Mejora visual de la expedición.
2. Luego #13 (botones mazmorra).