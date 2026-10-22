"""Ajuste de dificultad de expediciones: prueba factores sobre los enemigos sin tocar el disco.

Uso: python scripts/tune_expeditions.py [factor]
Multiplica hp/power/defense/resistance de cada enemigo por `factor` (en memoria) y muestra la
probabilidad de victoria a nivel recomendado con equipo típico, para cada expedición y clase.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kame.config import BASE_DIR  # noqa: E402
from kame.content import load_content  # noqa: E402
from kame.engine.expeditions import ExpeditionDef, EnemyDef  # noqa: E402
from kame.engine.simulation import standard_build, win_rate_build  # noqa: E402


def scaled_enemy(e: EnemyDef, factor: float) -> EnemyDef:
    return EnemyDef(
        id=e.id, name=e.name, hp=max(1, round(e.hp * factor)), power=e.power * factor,
        damage_type=e.damage_type, defense=e.defense * factor, resistance=e.resistance * factor,
        xp=e.xp, gold=e.gold, drops=e.drops, elite=e.elite,
    )


def main() -> None:
    factor = float(sys.argv[1]) if len(sys.argv) > 1 else 1.4
    content = load_content(BASE_DIR / "content")
    enemies = {eid: scaled_enemy(e, factor) for eid, e in content.enemies.items()}
    rules = content.config.expeditions
    for exp in content.expeditions.values():
        print(f"\n== {exp.name} (nv {exp.recommended_level}) factor {factor}")
        for class_id in content.classes:
            build = standard_build(content, class_id, exp.recommended_level, True)
            wr = win_rate_build(build, exp, enemies, rules, fights=400)
            print(f"  {class_id:9s} prob {wr:6.1%}")


if __name__ == "__main__":
    main()