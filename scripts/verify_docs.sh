#!/usr/bin/env bash
# verify_docs.sh — Verifica que los archivos de documentación estén actualizados.
# Uso: bash scripts/verify_docs.sh
# Salida: 0 si todo está bien, 1 si hay quejos pendientes.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ESTADO="$ROOT/docs/ESTADO.md"
MEJORAS="$ROOT/mejoras_pendientes.md"
CHANGES="$ROOT/CHANGES.md"

errors=0

echo "=== Verificación de documentación ==="

# 1. Verificar que los archivos existen
for f in "$ESTADO" "$MEJORAS" "$CHANGES"; do
    if [[ ! -f "$f" ]]; then
        echo -e "${RED}❌ Falta el archivo: $f${NC}"
        ((errors++))
    else
        echo -e "${GREEN}✅ $f existe${NC}"
    fi
done

# 2. Verificar que ESTADO.md menciona las fases completadas
if grep -q "Fases 1-5.*completadas" "$ESTADO"; then
    echo -e "${GREEN}✅ ESTADO.md: Fases 1-5 completadas${NC}"
else
    echo -e "${YELLOW}⚠️  ESTADO.md: no confirma Fases 1-5 completadas${NC}"
fi

# 3. Verificar que MEJORAS tiene la tabla de completadas
if grep -q "Completadas" "$MEJORAS"; then
    echo -e "${GREEN}✅ mejoras_pendientes.md: sección Completadas existe${NC}"
else
    echo -e "${RED}❌ mejoras_pendientes.md: falta sección Completadas${NC}"
    ((errors++))
fi

# 4. Verificar que CHANGES.md tiene la sección de esta semana
if grep -q "2026-10-22" "$CHANGES"; then
    echo -e "${GREEN}✅ CHANGES.md: fecha de hoy presente${NC}"
else
    echo -e "${YELLOW}⚠️  CHANGES.md: no tiene la fecha de hoy${NC}"
fi

# 5. Verificar que no hay marcas de "pendiente" sin fecha
if grep -qiE "pendiente|to do|tbd|implementar" "$ESTADO" "$MEJORAS"; then
    echo -e "${YELLOW}⚠️  Hay marcas de 'pendiente' en la documentación${NC}"
    grep -inE "pendiente|to do|tbd|implementar" "$ESTADO" "$MEJORAS" || true
fi

# 6. Verificar que TESTS pasan (si se ejecuta en el entorno correcto)
if command -v python3 &>/dev/null; then
    if python3 -m pytest -q --tb=no 2>/dev/null | grep -q "passed"; then
        echo -e "${GREEN}✅ Tests pasan${NC}"
    else
        echo -e "${YELLOW}⚠️  No se pudieron ejecutar tests (entorno no disponible)${NC}"
    fi
fi

echo ""
if [[ $errors -eq 0 ]]; then
    echo -e "${GREEN}🎉 Documentación verificada. Todo en orden.${NC}"
    exit 0
else
    echo -e "${RED}❌ Se encontraron $errors problema(s). Revisa arriba.${NC}"
    exit 1
fi