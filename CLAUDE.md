# Kame Bot — Instrucciones de Proyecto

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