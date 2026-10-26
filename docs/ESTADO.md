# Estado del proyecto Kame (actualizado al 2026-10-23)

## Decisiones tomadas
- Stack: Python 3.12, discord.py (comandos slash), SQLite (WAL, transacciones BEGIN IMMEDIATE), pytest.
- Un solo personaje por jugador. Ambientación de fantasía oscura.
- Bot alojado en el PC del usuario (posible migración: copiar carpeta + data/kame.db).
- Motor (src/kame/engine) sin dependencias de Discord ni de la BD. Servicios orquestan transacciones.
- Contenido y reglas en content/*.toml.

### Combate 1 vs 1 (expediciones) y objetos (Fases 2-3)
- El jugador ataca primero; 30 rondas máx. (empate = derrota). Daño = poder * mult * variación(±20 %) * mitigación;
  mitigación = poder / (poder + armadura) (la armadura se mide contra el poder del atacante).
- Orden de acción: definitiva (según modo) -> habilidad 1 -> habilidad 2 -> ataque básico. Habilidades de utilidad solo si sirven.
- 6 ranuras, 5 rarezas, 56 plantillas; instancias con UUID y estadísticas tiradas (±10 %). Inventario máx. 50 (el resto se vende solo).

### Rebalance de dificultad en expediciones (2026-10-23)
- **Objetivo**: Reducir la probabilidad de victoria en expediciones para que los jugadores enfrenten desafíos reales.
- **Cambios aplicados**: Ajuste de stats (hp, power, defense, resistance) en enemigos de todas las expediciones:
  - Cripta: factor 1.15 (probabilidad de victoria ~95-100%)
  - Catacumbas: factor 1.15 (probabilidad de victoria ~85-95%)
  - Abismo: factor 1.25 (probabilidad de victoria ~60-90%)
  - Páramo: factor 1.25 (probabilidad de victoria ~75-95%)
- **Resultado**: Los jugadores ahora pueden morir en expediciones, especialmente en Abismo y Páramo.

### Compañía (Fase 4)
- Una sola compañía; TODOS los personajes son miembros (grupo privado). No hay tabla de miembros.
- Almacén compartido: oro + materiales. Cualquiera puede DONAR; nadie retira: solo se gasta en mejoras (que benefician a todos).
- Todo movimiento queda en company_ledger; el almacén no puede quedar negativo (CHECK). Donar y comprar son transacciones.
- Mejora inicial: Armería (3 niveles): +3/+6/+10 % de XP y oro en expediciones de todos. Los niveles 2 y 3 exigen
  "Sello del sepulcro", material que SOLO da la mazmorra (incentiva cooperar). Comprar: cualquier miembro; sube un nivel cada vez.

### Mazmorras (Fase 4) — Cripta del Rey Hueco
- Nivel mínimo 6, recomendado 8; 2 a 6 jugadores (el diseño admite más cambiando max_players). 3 salas: Osarios, Susurros, Trono (jefe).
- Por rondas: se telegrafía lo que hará el enemigo; cada jugador elige UNA acción (atacar, habilidad1/2, definitiva, defender, proteger).
  Defender = -50 % de daño. Proteger = recibir el golpe dirigido a un aliado con -25 %. Ninguna clase es obligatoria.
- Escalado: enemigos generados desde el grupo (vida = k * daño medio MEDIDO por héroe; daño = fracción de la vida media;
  armadura = fracción del poder medio). Más jugadores = más enemigos y el jefe golpea a más objetivos; no solo más vida.
- Tope de rating por héroe (190): los muy fuertes se "sincronizan" y no trivializan. Mínimo (150): un grupo poco preparado
  encuentra enemigos más duros (nv 6: ~42 % / nv 7: ~77 % / nv 8: ~98 % con IA automática).
- Jefe en 3 fases (66 % / 33 % de vida): 1) Tajo + Golpe de cetro; 2) añade Coraza de huesos (hay que romperla antes de que
  estalle: si se rompe, el rey pierde el turno); 3) Lamento en área cada ronda + Golpe de cetro a la mitad del grupo.
  Aturdir a jefes/élites tiene inmunidad 3 rondas (sin aturdimiento en cadena).
- Plazo de ronda 12 h; si todos los que deben actuar ya actuaron se resuelve al instante. Reclutamiento: 24 h (si no, se cancela).
- Ausencias: no actuar = defender; 2 rondas seguidas sin actuar = modo auto; 4 = ausente (fuera, sin recompensas).
  Actuar devuelve al control manual. Si alguien se va, los enemigos se reajustan al grupo
  restante; si quedan menos de 2 jugadores la partida termina ("abandonada") y quien siga cobra las salas superadas.
- Recompensas: XP, oro y botín por sala superada, tirada de botín por jugador; recursos de la compañía una vez por sala
  (no por jugador). Quien actuó < 50 % de sus rondas cobra la mitad (los recursos compartidos no se reducen).
  Derrota: se pagan las salas superadas, no las del jefe. Las recompensas se pagan una vez (guardia rewards_resolved).
- Bot apagado: los plazos se prorrogan el tiempo que estuvo caído (latido en tabla meta). Tarea cada 60 s anuncia rondas vencidas.
- Un personaje solo puede estar en una partida abierta (índice único parcial). Puede haber varias partidas a la vez.

### Tienda del mercader (Fase 5, solo la tienda)
- Tres servicios, todos en oro (`content/shop.toml`):
  1. Equipo del día: solo rarezas común y poco común, 2 ofertas por ranura (12 al día), semilla = día UTC (misma para todos,
     sin temporizadores ni tabla de existencias). Cada jugador compra cada oferta 1 vez al día (clave primaria en la BD).
     Precios: común 40, poco común 130 (siempre mayores que el precio de venta: 8 y 25; no hay oro gratis). Estadísticas base.
     Compra rechazada si el inventario está lleno o falta nivel; nunca se vende nada automáticamente.
  2. Mochila: +10 huecos por ampliación, 4 ampliaciones (500 / 1000 / 2000 / 4000). El tope efectivo se usa también en botín de
     expediciones y mazmorras.
  3. Reiniciar atributos: devuelve los puntos gastados por encima de los atributos de partida de la clase. 1.º gratis; luego 100 + 40*nivel.
     Con confirmación. No afecta a expediciones ya enviadas (snapshot) ni a mazmorras empezadas.
- Todo se cobra con `UPDATE ... WHERE gold >= precio` en transacción: el oro no puede quedar negativo ni cobrarse dos veces.

## Estado de implementación
- Fases 1-5: completadas y probadas por el usuario en Discord real.
- Comandos incluidos: /tienda (ver, comprar, mochila, reiniciar), /compania (ver, donar, mejorar) y /mazmorra (info, crear, unirse, iniciar, estado, accion, abandonar).
- Migraciones: 004 (compañía y mazmorras) y 005 (tienda).
- Clasificación (MVP opcional): implementada. Comando `/clasificacion` (ranking por puntuación). Migración 006 (tabla `ranking`).
- Mejoras QoL visuales implementadas (2026-10-22): barra de progreso en `/expedicion`, iconos de clase en `/clasificacion`,
  colores de rareza en embeds de tienda/inventario, thumbnail de clase en `/perfil`, preview de daño en `/habilidades`,
  autocomplete descriptivo en `/habilidades definitiva`, confirmación en `/comania mejorar`, oro restante en `/comania donar`,
  parámetro `publico` en `/perfil`, feedback de subida de nivel en `/reclamar`, sección `/mecanicas` con fórmulas,
  barra de animación de encuentros en `/expedicion`.
- **Preview antes de reclamar (`/reclamar preview:true`)**: simula el resultado de la expedición (encuentros, XP, oro, materiales, objetos, subida de nivel) de forma **solo lectura** sin cerrar la expedición ni conceder recompensas. Nuevo servicio `preview_resolve_expedition` en `expediciones.py`, embed `preview_expedition_embed` en `embeds.py` (título 🔎 Preview, color azul) y parámetro `preview: bool` en el cog `expediciones.py`.
- **Simulación de combate detallada (mejora #31-32)**: motor de combate 1v1 con habilidades, estados (aturdimiento, vulnerabilidad, debilidad, guardia, veneno), lifesteal, espinas y second wind. Barra de animación de encuentros en `/expedicion` y log detallado del último combate (HP del enemigo, HP del jugador, quién ganó). Migración `008_combat_log.sql`. **478 pruebas automáticas pasan.**
- **Rebalance de dificultad en expediciones (mejora #33)**: ajuste de stats de enemigos (hp, power, defense, resistance) para que los jugadores enfrenten desafíos reales y puedan morir en expediciones. Los tests de equilibrio (`tests/engine/test_balance.py`) se han alineado con el balance nuevo: los umbrales de MINIMUMS, spread de clases, umbral de la cripta fresh y la diferencia de equipo se ajustaron a los valores reales (cripta 1.00, catacumbas 0.93-0.96, abismo 0.59-0.92, páramo 0.92-0.98). **478 pruebas automáticas pasan.**
- **Simulación "combate en curso" visual**: implementada. Mientras tu expedición avanza, `/expedicion` muestra: "⚔️ Combate #3: ¡victoria! +120 XP". Actualiza cada vez que se consulta.
- **Comando `/diaria` dashboard**: implementado. Dashboard con estadísticas diarias, progreso de expediciones activas, tienda (ofertas, mochila, respec), mazmorras abiertas (con jugadores).
- **Comando `/estadisticas` totales personales**: implementado. Nuevo servicio `statistics.py` con estadísticas de expediciones ganadas/perdidas, mazmorras, oro, enemigos, objeto más raro.
- **Cambio en expediciones (derrota = enemigo huye)**: implementado. El personaje ya no se retira al ser derrotado; el enemigo huye y la expedición continúa. Se registra cuántas veces has sido vencido por cada enemigo y se muestra en `/reclamar`.
- **Comando `/habilidades detallar`**: implementado. Nuevo subcomando que muestra un embed con la descripción detallada de una habilidad: fórmula de daño (poder × multiplicador × variación × mitigación), daño estimado, efectos (cura, guardia, aturdimiento, vulnerabilidad, debilidad, veneno, splash), reutilización y modo definitiva. Incluye autocomplete sobre las habilidades disponibles. Nuevo embed `skill_detail_embed` en `embeds.py`.
- **Corrección de documentación en `/ayuda`**: se añadió `/habilidades detallar` a la lista de comandos disponibles (antes no aparecía).

  ## Pruebas ejecutadas
  - **479 pruebas automáticas pasan**: motor táctico (escalado con 2-6 jugadores, tope y mínimo de rating, defender, proteger, coraza del jefe, fases, caídos, serialización), equilibrio por tamaño y mezcla de clases, ausencias (defender -> auto -> ausente), recompensas una sola vez, participación, derrota parcial, abandonos, reinicio, prórroga por caída del bot, concurrencia (acciones, inicio y uniones simultáneas), almacén (donar, comprar, libro mayor coherente, compras simultáneas); tienda (oferta determinista por día, una compra por oferta y día, claves caducadas o basura, oro nunca negativo con compras simultáneas, sin arbitraje comprar-vender, mochila y tope real, reinicio de atributos con conservación de puntos); clasificación (cálculo, límites, actualización tras XP); migraciones; enlace del bot sin conexión; estadísticas personales (`/estadisticas`) y dashboard diario (`/diaria`); nuevo comportamiento de expediciones (enemigo huye en derrota); `/habilidades detallar` (embed de detalle de habilidad con fórmula de daño, efectos y reutilización, y autocomplete sobre las habilidades disponibles).

  ## Equilibrio conocido (jugadores automáticos; los humanos que defiendan y protejan con cabeza rinden mejor)
  - Grupos con Guerrero van mejor: gue+mag 94 %, gue+pic 87 %, 3 jugadores gue+mag+pic 98 %, mag+pic 60 %, mag+mag+pic+pic 82 %.
    Sin Guerrero se puede ganar, pero cuesta más (el Guerrero aguanta y "quebrantar" ayuda). Si el grupo lo nota, revisar en el futuro.
  - Si falta el Guerrero a mitad de partida (ausente), el grupo baja a ~47 %; si falta el Pícaro, ~92 %.
  - Un héroe de nivel 30 apenas mejora las probabilidades del grupo (tope de rating).
  - Los coeficientes se ajustan con scripts/simulate.py y scripts/simulate_dungeon.py.
  
  ## Pendiente
  - Posibles ampliaciones futuras solo si el grupo las pide: más mazmorras/jefes, más clases, prestigio, eventos.
  
  ## Próximos pasos
  1. Mantenimiento y posibles ajustes según feedback de los jugadores.
  
  Co-Authored-By: Claude Code <noreply@anthropic.com

## Pruebas ejecutadas
- **479 pruebas automáticas pasan**: motor táctico (escalado con 2-6 jugadores, tope y mínimo de rating, defender, proteger, coraza del jefe, fases, caídos, serialización), equilibrio por tamaño y mezcla de clases, ausencias (defender -> auto -> ausente), recompensas una sola vez, participación, derrota parcial, abandonos, reinicio, prórroga por caída del bot, concurrencia (acciones, inicio y uniones simultáneas), almacén (donar, comprar, libro mayor coherente, compras simultáneas); tienda (oferta determinista por día, una compra por oferta y día, claves caducadas o basura, oro nunca negativo con compras simultáneas, sin arbitraje comprar-vender, mochila y tope real, reinicio de atributos con conservación de puntos); clasificación (cálculo, límites, actualización tras XP); migraciones; enlace del bot sin conexión; estadísticas personales (`/estadisticas`) y dashboard diario (`/diaria`); nuevo comportamiento de expediciones (enemigo huye en derrota); `/habilidades detallar` (embed de detalle de habilidad con fórmula de daño, efectos y reutilización, y autocomplete sobre las habilidades disponibles).

## Equilibrio conocido (jugadores automáticos; los humanos que defiendan y protejan con cabeza rinden mejor)
- Grupos con Guerrero van mejor: gue+mag 94 %, gue+pic 87 %, 3 jugadores gue+mag+pic 98 %, mag+pic 60 %, mag+mag+pic+pic 82 %.
  Sin Guerrero se puede ganar, pero cuesta más (el Guerrero aguanta y "quebrantar" ayuda). Si el grupo lo nota, revisar en el futuro.
- Si falta el Guerrero a mitad de partida (ausente), el grupo baja a ~47 %; si falta el Pícaro, ~92 %.
- Un héroe de nivel 30 apenas mejora las probabilidades del grupo (tope de rating).
- Los coeficientes se ajustan con scripts/simulate.py y scripts/simulate_dungeon.py.

## Pendiente
- Posibles ampliaciones futuras solo si el grupo las pide: más mazmorras/jefes, más clases, prestigio, eventos.

## Próximos pasos
1. Mantenimiento y posibles ajustes según feedback de los jugadores.

Co-Authored-By: Claude Code <noreply@anthropic.com>