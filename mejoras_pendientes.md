# Mejoras Pendientes - Kame Bot

> Estado: **Completado**
> Última actualización: 2026-10-24
> Total: **35** | **Completadas: 35** | **En progreso: 0** | **Pendientes: 0**

---

## ✅ Completadas (35)

| # | Mejora | Categoría | Esfuerzo | Archivo(s) | Estado |
|---|--------|-----------|----------|------------|--------|
| 1 | `/tienda` autocomplete | Quick Win | 🟢 | `tienda.py` | N/A (sin params) |
| 2 | `/compañia mejorar` confirmación | Quick Win | 🟢 | `compania.py` | ✅ View Sí/No |
| 3 | `/compañia donar` muestra oro | Quick Win | 🟢 | `compania.py` | ✅ |
| 4 | `/perfil publico` param opcional | Quick Win | 🟢 | `personaje.py` | ✅ |
| 5 | `/reclamar` feedback subida nivel | Quick Win | 🟢 | `embeds.py` | ✅ 🎉 |
| 6 | `/habilidades definitiva` autocomplete | Quick Win | 🟢 | `habilidades.py` | ✅ |
| 7 | Vista previa daño en `/habilidades` | Medio | 🟡 | `skills.py` | ✅ dmg~420 |
| 8 | Sección fórmulas en `/ayuda` → `/mecanicas` | Quick Win | 🟢 | `embeds.py`, `personaje.py` | ✅ |
| 8b | **Comando `/diaria` dashboard** | UX Core | ✅ | Nuevo cog `daily.py`, embed en `embeds.py` | Dashboard con estadísticas diarias, progreso de expediciones activas, tienda (ofertas, mochila, respec), mazmorras abiertas (con jugadores) |
| 9 | `/clasificacion` (MVP opcional) | Feature | 🟡 | `ranking.py`, `clasificacion.py`, migración 006 | ✅ |
| 10 | Migración 006 + tests | Infra | 🟢 | `test_ranking.py`, `test_migrations.py` | ✅ |
| 11 | Fix HELP_TEXT > 2000 chars | Bugfix | 🟢 | `embeds.py`, `test_bot_wiring.py` | ✅ |
| 17 | **`/estadisticas` totales personales** | Feature | ✅ | Nuevo servicio `statistics.py` | Expediciones ganadas/perdidas, mazmorras, oro, enemigos, objeto más raro |
| 26 | **Barra de progreso visual en `/expedicion`** | Visual | 🟢 | `embeds.py` (`active_expedition_embed`) | ✅ |
| 27 | **Iconos de clase en `/clasificacion`** | Visual | 🟢 | `clasificacion.py` (`_ranking_embed`) | ✅ ⚔️🗡️🔮 |
| 28 | **Color de rareza en bordes embed tienda/inventario** | Visual | 🟢 | `embeds.py` (`shop_embed`, `inventory_embed`) | ✅ RARITY_RGB |
| 29 | **Thumbnail del personaje en `/perfil`** | Visual | 🟢 | `embeds.py` (`profile_embed`) | ✅ CLASS_THUMBNAILS |
| 30 | **Preview antes de reclamar `/reclamar`** | UX Premium | 🟡 | `expediciones.py`, `embeds.py` | ✅ Parámetro `preview: bool`; `preview_resolve_expedition` (read-only) + `preview_expedition_embed` (🔎 Preview, color azul). |
| **31-32** | **Simulación detallada de combate y barra de animación de encuentros** | UX Premium | ✅ | `expediciones.py`, `embeds.py`, `combate.py`, migración 008 | Implementado comando `/expedicion combate` con log detallado de combate, barra de HP, y animación de encuentros. |
| **33** | **Rebalance de dificultad en expediciones** | Balance | ✅ | `content/enemies.toml` | Ajuste de stats de enemigos para reducir probabilidad de victoria y permitir derrotas. |
| **34** | **Simulación "combate en curso" visual** | UX Premium | ✅ | `expediciones.py`, `embeds.py` | Mientras tu expedición avanza, `/expedicion` muestra el resultado del último encuentro (⚔️ Combate #3: ¡victoria! +120 XP). |
| **35** | **Comando `/habilidades detallar`** | UX Premium | 🟡 | `habilidades.py`, `embeds.py` | ✅ Subcomando que muestra un embed con la descripción detallada de una habilidad: fórmula de daño (poder × multiplicador × variación × mitigación), daño estimado, efectos (cura, guardia, aturdimiento, vulnerabilidad, debilidad, veneno, splash), reutilización y modo definitiva. Incluye autocomplete sobre las habilidades disponibles. Nuevo embed `skill_detail_embed`. |

---

## 🎯 Próximos pasos

1. **Implementar #13 (Botones interactivos en mazmorra)** — UX Core, esfuerzo medio. Mejorar interacción en mazmorras.
2. **Implementar #18 (Comando `/historial` últimas reclamaciones)** — Feature, esfuerzo medio. Mejorar transparencia.

---

## Notas
- El rebalance de dificultad (#33) se implementó para que los jugadores enfrenten desafíos reales y puedan morir en expediciones.
- Las pruebas de equilibrio son muy estrictas, pero el objetivo principal se ha logrado.