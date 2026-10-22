# Kame – RPG cooperativo para Discord (Fase 5)

Guía para **Windows**. Todos los comandos se escriben en una ventana de **PowerShell**
(dentro de la carpeta del proyecto: clic derecho en la carpeta > "Abrir en Terminal").

## 1. Requisitos (una sola vez)

1. Instala **Python 3.12** desde https://www.python.org/downloads/
   - En el instalador marca la casilla **"Add python.exe to PATH"**.
   - Comprueba con `python --version` (debe decir 3.12.x; evita la 3.13 por ahora).
2. Descomprime este proyecto en una carpeta sencilla, por ejemplo `C:\Kame`.

## 2. Instalación (una sola vez)

```
cd C:\Kame
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si PowerShell dice que la ejecución de scripts está deshabilitada, ejecuta una vez:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repite el paso `Activate.ps1`.

Cada vez que abras una terminal nueva, activa el entorno con `.venv\Scripts\Activate.ps1`
(verás `(.venv)` al principio de la línea).

## 3. Crear el bot en Discord (una sola vez)

1. Entra en https://discord.com/developers/applications > **New Application** (ponle nombre).
2. Menú **Bot** > **Reset Token** > copia el token. **Es una contraseña: no lo compartas.**
   No hace falta activar ningún "Privileged Gateway Intent".
3. Menú **OAuth2 > URL Generator**: marca los scopes `bot` y `applications.commands`;
   en permisos del bot marca `Send Messages` y `Embed Links`.
4. Abre la URL generada y añade el bot a tu servidor.
5. ID de tu servidor: en Discord, Ajustes > Avanzado > activa **Modo desarrollador**;
   luego clic derecho sobre el icono del servidor > **Copiar ID del servidor**.

## 4. Configurar

1. Copia `.env.example` como `.env` (`copy .env.example .env`).
2. Abre `.env` con el Bloc de notas y rellena `DISCORD_TOKEN` y `DEV_GUILD_ID`.

## 5. Ejecutar

```
python run_bot.py
```

Verás "Bot conectado como ...". En Discord prueba `/crear`, `/perfil`, `/atributos`, `/expedicion`, `/reclamar`, `/inventario`, `/equipo`, `/equipar`, `/desequipar`, `/vender`, `/habilidades`, `/compania`, `/mazmorra`, `/tienda` y `/ayuda`.

**Actualizando desde la Fase 1:** copia los archivos nuevos encima de tu carpeta (mantén tu `.env` y `data\kame.db`). Al arrancar, el bot aplica solo la migración 005. Haz antes una copia con `python scripts\backup.py`.
Para apagarlo: `Ctrl + C`. La base de datos se crea sola en `data\kame.db`.

## 6. Pruebas y copias de seguridad

```
python -m pytest
python scripts\backup.py
python scripts\simulate.py
python scripts\simulate_dungeon.py
```

`simulate.py` imprime un informe de equilibrio de las expediciones y `simulate_dungeon.py` el de las mazmorras (por tamaño de grupo, mezcla de clases, nivel y ausencias).

Las copias se guardan en `data\backups\` (se conservan las 14 últimas).
Para migrar a otro equipo en el futuro: copia la carpeta del proyecto y `data\kame.db`.

## Dónde tocar el equilibrio

- `content\config.toml`: nivel máximo, puntos por nivel, curva de XP, longitud de nombres.
- `content\classes.toml`: clases, atributos iniciales y ataque básico.
- `content\enemies.toml`, `content\expeditions.toml`, `content\materials.toml`: enemigos, destinos y materiales.
- `content\shop.toml`: la tienda (qué rarezas vende, precios, coste del reinicio de atributos y de la mochila).
- `content\skills.toml`: habilidades de clase (4 normales + 1 definitiva por clase).
- `content\items.toml`: objetos (56 plantillas). `[items]`, `[loot]` y `[sell]` de `config.toml`: inventario, probabilidades de rareza y precios.

Tras cambiar números de combate, ejecuta `python -m pytest`: las pruebas de equilibrio avisan si una clase o un perfil de riesgo se desajusta.

## Cómo se juega una mazmorra (resumen para el grupo)

1. Alguien con nivel 6+ escribe `/mazmorra crear` y los demás `/mazmorra unirse`. El líder usa `/mazmorra iniciar` (mínimo 2 jugadores).
2. Cada ronda, el bot anuncia lo que va a hacer el enemigo ("prepara «Golpe de cetro» contra Brenna"). Cada jugador elige UNA acción con `/mazmorra accion`: atacar, habilidad1, habilidad2, definitiva, defender o proteger (a un aliado, por su número en la lista).
3. En cuanto todos han elegido, la ronda se resuelve. Si alguien tarda, se resuelve al vencer el plazo (12 h) y quien no actuó **defiende**.
4. Ausencias: 2 rondas seguidas sin actuar = el juego juega por ti (modo auto); 4 = quedas fuera sin recompensas. Si alguien se va, los enemigos se reajustan al grupo que queda. Si quedan menos de 2 jugadores, la partida termina y quien siga cobra las salas ya superadas.
5. Recompensas: XP, oro y botín por cada sala superada (cada jugador tira su botín aparte) y recursos para la compañía una sola vez por sala. Quien actuó menos de la mitad de las rondas cobra la mitad.
6. Con `/compania donar` aportáis oro y materiales al almacén, y con `/compania mejorar` compráis mejoras de la sede entre todos (la Armería sube el XP y el oro de las expediciones de todos).

Si el bot estuvo apagado, los plazos de las partidas abiertas se prorrogan el tiempo que estuvo caído. Mientras el bot esté encendido, una tarea revisa los plazos cada minuto y anuncia en el canal de la partida lo que ocurra.

## La tienda del mercader (`/tienda`)

- `/tienda ver`: ofertas del día y servicios. La oferta se renueva sola a las 00:00 UTC y es **la misma para todos**; cada jugador puede comprar cada oferta **una vez al día** (nadie compite por existencias).
- `/tienda comprar`: equipo básico (común y poco común, 2 ofertas por ranura). Siempre cuesta más que lo que se obtiene al venderlo, y llega con las estadísticas base. Lo raro, épico y legendario solo se consigue en las aventuras. Si tu inventario está lleno, la compra se rechaza (no vende nada por ti).
- `/tienda mochila`: +10 huecos de inventario por ampliación (4 ampliaciones, cada vez más caras).
- `/tienda reiniciar`: te devuelve los puntos de atributo gastados para repartirlos de nuevo (el primer reinicio es gratis; después cuesta 100 + 40 por nivel). Pide confirmación con un botón.
