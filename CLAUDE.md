# Kame Bot — Instrucciones de Proyecto

## Flujo de trabajo con GitHub (norma obligatoria)

La rama `main` está **protegida en GitHub**: solo admite cambios mediante Pull Request (PR) aprobado y mezclado por el usuario. Todo el trabajo se hace en ramas de feature y se sube a GitHub para abrir un PR.

### Prohibiciones absolutas

- **Nunca** hacer `git commit` estando en `main`.
- **Nunca** hacer `git push` a `main` (ni `git push origin HEAD:main`).
- **Nunca** usar `git push --force` / `--force-with-lease` sobre ramas compartidas, ni borrar `main`.
- **Nunca** mezclar un PR ni hacer `git merge` hacia `main`: la integración la hace **el usuario** desde GitHub.
- **Nunca** modificar la configuración de protección de ramas del repositorio.

### Ramas

1. **Nombre**: `feature/<slug-descriptivo>` (ej: `feature/preview-dano-habilidades`, `feature/fix-tienda-autocomplete`). Para tareas que no son funcionalidad, se pueden usar `fix/<slug>`, `docs/<slug>` o `chore/<slug>`.
2. **Una cosa por rama**: cada rama trata un solo cambio o mejora. Dos cambios significativos requieren dos ramas y dos PRs.
3. **Creación automática**: si la rama no existe, crearla siempre desde un `main` actualizado:
   ```
   git switch main
   git pull origin main
   git switch -c feature/<slug>
   ```
4. **Antes de empezar cualquier cambio**: comprobar la rama actual (`git branch --show-current`). Si estás en `main`, cambiar a la rama de feature (creándola si hace falta) antes de tocar ningún archivo.

### Procedimiento al terminar un cambio

1. Ejecutar las pruebas (`pytest`) y comprobar que pasan. No afirmar que pasan si no se han ejecutado.
2. Actualizar la documentación (ver sección siguiente) **en la misma rama**.
3. Antes de hacer commit, revisar `git status` y `git diff --staged` (ver "Seguridad").
4. Hacer commits claros y pequeños, con mensajes en español que expliquen el cambio.
5. Traer los últimos cambios de `main` para evitar conflictos:
   ```
   git fetch origin
   git merge origin/main
   ```
   Si hay conflictos, resolverlos, volver a ejecutar las pruebas y avisar al usuario de qué se ha resuelto.
6. Subir la rama:
   ```
   git push -u origin feature/<slug>
   ```
7. Abrir el PR hacia `main`:
   - Si `gh` (GitHub CLI) está instalado y autenticado: `gh pr create --base main --fill`, mejorando el título y la descripción.
   - Si no, indicar al usuario la URL para abrirlo desde GitHub.
   - La descripción del PR debe incluir: qué cambia, por qué, cómo se ha probado y si afecta a la base de datos (migraciones).
8. **Parar aquí.** Informar al usuario de que el PR está listo para revisión. No mezclarlo.

### Después de que el usuario mezcle el PR

Solo cuando el usuario confirme que el PR está mezclado:

```
git switch main
git pull origin main
git branch -d feature/<slug>
```

(La rama remota se borra desde GitHub al mezclar; si no, `git push origin --delete feature/<slug>`.)

## Seguridad y datos sensibles

El repositorio es **público**: todo lo que se haga commit queda visible y permanece en el historial.

- **Nunca** incluir en commits: `.env`, tokens, claves, contraseñas, IDs de servidores o usuarios reales, bases de datos (`*.db`, `*.sqlite3`), copias de seguridad ni datos de jugadores.
- Antes de cada commit, revisar `git status` y `git diff --staged`. Si aparece algo de lo anterior, **parar, no hacer commit y avisar al usuario**.
- Si se detecta que un secreto ya se subió a una rama, avisar de inmediato: hay que regenerar el token, no basta con borrar el archivo.
- Las variables de configuración nuevas se documentan en `.env.example` **sin valores reales**.
- No modificar ni eliminar los archivos de licencia (`LICENSE`, `LICENSE-CONTENT`) salvo petición expresa del usuario.

## Trigger automático de documentación

**Cada vez que se implemente una nueva funcionalidad o mejora, actualizar automáticamente estos dos archivos, dentro de la misma rama y del mismo PR:**

1. **`docs/ESTADO.md`** — Añadir una línea en "Estado de implementación" y en "Pruebas ejecutadas" (número total de tests).
2. **`mejoras_pendientes.md`** — Mover la mejora de "Pendientes" a "Completadas", incrementar el total de completadas y decrementar el de pendientes. Actualizar la fecha de última modificación.

### Formato de actualización

**ESTADO.md:**
- Añadir: `- <Nombre de la funcionalidad>: implementada. <Detalles>.`
- Añadir a "Pruebas ejecutadas": `<Nuevos tests> pruebas automáticas pasan: <lista>`

**mejoras_pendientes.md:**
- Mover la fila de la tabla de "Pendientes" a "Completadas".
- Actualizar cabeceras: `Total: **35** | **Completadas: X** | **En progreso: Y** | **Pendientes: Z**`
- Actualizar `> Última actualización: <fecha>`

### Regla de oro
No terminar nunca una tarea sin haber actualizado ambos archivos y sin haber ejecutado las pruebas. Si un subagente completa una mejora, el agente principal debe marcarla como completada en `mejoras_pendientes.md` y en `docs/ESTADO.md` antes de reportar el éxito.

### Conflictos en estos dos archivos
Como todas las ramas editan `ESTADO.md` y `mejoras_pendientes.md`, son propensos a conflictos. Para reducirlos: actualizarlos al final del trabajo (justo antes del paso 5 del procedimiento) y, si hay conflicto al traer `main`, recalcular los totales a partir de las filas reales de las tablas en lugar de elegir una de las dos versiones.

## Delegación (importa)
**SIEMPRE** que el usuario mande implementar una mejora listada en `mejoras_pendientes.md`, usar un subagente para hacer el trabajo. **Nunca implementar directamente una mejora pendiente.** El subagente trabaja en la rama de feature correspondiente, y las reglas de este documento (ramas, PR, seguridad) también le aplican.

## Despliegue

El bot corre en una Raspberry Pi, que se actualiza desde `main` una vez mezclado el PR. El agente **no** accede a la Raspberry ni la despliega; solo prepara el código y el PR. Si un cambio requiere una migración de base de datos o una variable nueva en el `.env` de la Raspberry, indicarlo de forma explícita en la descripción del PR.
