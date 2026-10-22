"""Informe de equilibrio de las mazmorras.  Uso:  python scripts/simulate_dungeon.py

Juega la mazmorra muchas veces con grupos "automáticos" (equipo típico y habilidades de equipo) y muestra
el % de victorias y las rondas medias para distintos tamaños de grupo, mezclas de clases, niveles y
ausencias. Un grupo humano que use "defender" y "proteger" con cabeza suele rendir mejor que este
baremo automático.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kame.config import BASE_DIR  # noqa: E402
from kame.content import load_content  # noqa: E402
from kame.engine.build import build_combatant  # noqa: E402
from kame.engine.dungeon import make_hero, simulate_auto  # noqa: E402
from kame.engine.simulation import TEAM_LOADOUT, standard_build  # noqa: E402

RUNS = 100


def rate(content, dungeon, classes, levels=None, absent=()):
    wins = rounds = 0
    for seed in range(RUNS):
        heroes = [
            make_hero(f"h{i}", f"{c}{i}",
                      build_combatant(standard_build(content, c, (levels or [dungeon.recommended_level] * len(classes))[i],
                                                     True, loadout=TEAM_LOADOUT[c])),
                      dungeon.hero_rating_cap)
            for i, c in enumerate(classes)
        ]
        outcome, r, _ = simulate_auto(dungeon, heroes, content.dungeon_enemies, seed,
                                      absent={f"h{i}" for i in absent})
        wins += outcome == "win"
        rounds += r
    return wins / RUNS, rounds / RUNS


def main() -> None:
    content = load_content(BASE_DIR / "content")
    for dungeon in content.dungeons.values():
        print(f"\n== {dungeon.name} (recomendado nv {dungeon.recommended_level}, mínimo nv {dungeon.min_level})")
        short = lambda cs: "+".join(c[:3] for c in cs)
        print(" Por tamaño y mezcla de clases:")
        for classes in (["guerrero", "mago"], ["guerrero", "picaro"], ["mago", "picaro"],
                        ["guerrero", "mago", "picaro"], ["mago", "mago", "picaro"],
                        ["guerrero", "guerrero", "mago", "picaro"], ["mago", "mago", "picaro", "picaro"],
                        ["guerrero", "guerrero", "mago", "mago", "picaro"],
                        ["guerrero", "guerrero", "mago", "mago", "picaro", "picaro"]):
            w, r = rate(content, dungeon, classes)
            print(f"  {len(classes)} jugadores {short(classes):22s} victorias {w:5.0%}  rondas {r:5.1f}")
        print(" Por nivel (guerrero+mago+pícaro):")
        for level in (dungeon.min_level, dungeon.min_level + 1, dungeon.recommended_level,
                      dungeon.recommended_level + 2, dungeon.recommended_level + 8):
            w, r = rate(content, dungeon, ["guerrero", "mago", "picaro"], [level] * 3)
            print(f"  nivel {level:2d}: victorias {w:5.0%}  rondas {r:5.1f}")
        print(" Un héroe mucho más fuerte (nv 30) con dos de nivel recomendado:")
        w, r = rate(content, dungeon, ["guerrero", "mago", "picaro"], [30, dungeon.recommended_level, dungeon.recommended_level])
        print(f"  victorias {w:5.0%}  rondas {r:5.1f}")
        print(" Con un jugador ausente (nunca actúa):")
        for absent, label in (((2,), "pícaro"), ((0,), "guerrero")):
            w, r = rate(content, dungeon, ["guerrero", "mago", "picaro"], absent=absent)
            print(f"  ausente el {label}: victorias {w:5.0%}  rondas {r:5.1f}")


if __name__ == "__main__":
    main()
