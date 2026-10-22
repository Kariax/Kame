"""Informe de equilibrio.  Uso:  python scripts/simulate.py

Para cada expedición y clase, con una build típica (puntos repartidos, habilidades por
defecto y equipo de rareza media para ese nivel), muestra en distintos niveles:
 - prob.: probabilidad de ganar cada encuentro
 - retira: % de expediciones que terminan en retirada antes de acumular todo
 - XP / oro / objetos de media por expedición completa (8 h)
Al final compara con personajes sin equipo.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kame.config import BASE_DIR  # noqa: E402
from kame.content import load_content  # noqa: E402
from kame.engine.build import build_combatant, build_stats  # noqa: E402
from kame.engine.expeditions import encounters_available, resolve_expedition  # noqa: E402
from kame.engine.simulation import standard_build, win_rate_build  # noqa: E402

RUNS = 200


def report(content, exp, level, gear, rng):
    cfg = content.config
    rules = cfg.expeditions
    full = encounters_available(rules.max_accumulation_hours * 3600, exp, rules)
    for class_def in content.classes.values():
        build = standard_build(content, class_def.id, level, gear)
        p = win_rate_build(build, exp, content.enemies, rules, fights=400)
        player = build_combatant(build)
        bonus = build_stats(build).loot_bonus
        xp = gold = wins = retreats = items = 0
        for _ in range(RUNS):
            o = resolve_expedition(
                expedition=exp, enemies=content.enemies, player=player, player_level=level,
                loot_bonus=bonus, encounters=full, seed=rng.getrandbits(62), rules=rules,
                templates=content.item_templates, item_rules=cfg.items)
            xp += o.xp
            gold += o.gold
            wins += o.victories
            retreats += o.retreated
            items += len(o.items)
        print(f"  nv {level:2d} {class_def.name:9s} prob {p:5.1%}  retira {retreats / RUNS:5.1%}"
              f"  XP {xp / RUNS:7.0f}  oro {gold / RUNS:6.0f}  objetos {items / RUNS:4.1f}"
              f"  victorias {wins / RUNS:5.1f}")


def main() -> None:
    content = load_content(BASE_DIR / "content")
    rng = random.Random(7)
    for exp in content.expeditions.values():
        print(f"\n== {exp.name} (recomendado nv {exp.recommended_level}, {exp.risk}) con equipo típico")
        levels = sorted({exp.min_level, exp.recommended_level, exp.recommended_level + 3,
                         exp.recommended_level + 6})
        for level in levels:
            report(content, exp, level, True, rng)
    print("\n== Sin equipo, al nivel recomendado")
    for exp in content.expeditions.values():
        print(f" {exp.name}")
        report(content, exp, exp.recommended_level, False, rng)


if __name__ == "__main__":
    main()
