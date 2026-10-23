# Kame Bot — Instrucciones de Proyecto

## Flujo de trabajo de ramas (norma obligatoria)

**Está totalmente prohibido implementar cambios directamente en la rama `master`.**
Todos los cambios se deben implementar en una rama de feature y luego fusionarla a `master`.

### Reglas

1. **Rama de feature**: cada cambio o mejora se hace en una rama con nombre `feature/<cambio_nombre>`.
   El `<cambio_nombre>` es un slug descriptivo (ej: `mejora-31-32-combate-visual`,
   `preview-daño-habilidades`, `fix-tienda-autocomplete`).
2. **Una cosa por rama**: una rama de feature debe tratar **un solo cambio o mejora** a la vez.
   Dos cambios significativos requieren dos ramas diferentes.
3. **Creación automática**: si la rama de feature no existe, la crearé automáticamente
   (`git checkout -b feature/<nombre>` desde `master`).
4. **Integración**: cuando el cambio esté completo y los tests pasen, se fusiona a
   `master` (preferiblemente con merge commit, no fast-forward, para preservar la historia).
5. **Limpieza**: tras integrar, se borra la rama de feature (`git branch -d feature/<nombre>`).

### Procedimiento

- Antes de empezar cualquier cambio: verificar la rama actual (`git branch`).
  Si estás en `master`, cambiar a la rama de feature (creándola si hace falta).
- Nunca hagas `git commit` ni `git checkout master` para trabajar en un cambio.
- Al terminar: fusionar a `master` y borrar la rama de feature.

## Trigger automático de documentación

**Cada vez que se implemente una nueva funcionalidad o mejora, debes actualIZAR AUTOMATICAMENTE estos dos archivos:**

1. **`docs/ESTADO.md`** — Añadir una línea en "Estado de implementación" y en "Pruebas ejecutadas" (número total de tests).
2. **`mejoras_pendientes.md`** — Mover la mejora de "Pendientes" a "Completadas", incrementar el total de completadas y decrementar el de pendientes. Actualizar la fecha de última modificación.

### Formato de actualización

**ESTADO.md:**
- Añadir: `- <Nombre de la funcionalidad>: implementada. <Detalles>.`
- Añadir a "Pruebas ejecutadas": `<Nuevos tests> pruebas automáticas pasan: <lista>`

**mejoras_pendientes.md:**
- Mover la fila de la tabla de "Pendientes" a "Completadas"
- Actualizar cabeceras: `Total: **35** | **Completadas: X** | **En progreso: Y** | **Pendientes: Z**`
- Actualizar `> Última actualización: <fecha>`

### Regla de oro
No terminar nunca una tarea sin haber actualizado ambos archivos. Si un subagente completa una mejora, tú debes marcarla como completada en `mejoras_pendientes.md` y en `docs/ESTADO.md` antes de reportar el éxito.

### Delegación (importa)
**SIEMPRE** que el usuario me mande implementar una mejora listada en `mejoras_pendientes.md`, uso un subagente para hacer el trabajo. **Nunca implemento yo mismo una mejora pendiente**.