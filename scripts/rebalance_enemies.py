"""Rebalance: multiplica hp/power/defense/resistance de enemigos por un factor (solo cambia stats).

NO toca xp, gold, drops, elite ni risk.
Uso: python scripts/rebalance_enemies.py [factor]
"""
import re
import sys
from pathlib import Path

FACTOR = float(sys.argv[1]) if len(sys.argv) > 1 else 1.3

PATH = Path(__file__).resolve().parents[1] / "content" / "enemies.toml"
NUM_RE = re.compile(r"^(\s*([\w]+)\s*=\s*)([-\d.]+)(\s*)$")

STAT_KEYS = {"hp", "power", "defense", "resistance"}
# stats que NO queremos escalar: xp, gold, elite, damage_type, name, drops
forbidden = {"xp", "gold", "elite", "damage_type", "name", "drops"}

lines = PATH.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    m = NUM_RE.match(line)
    if m and m.group(2) in STAT_KEYS and m.group(2) not in forbidden:
        try:
            val = float(m.group(3))
        except ValueError:
            out.append(line)
            continue
        new = val * FACTOR
        if m.group(2) == "hp":
            new = round(new)
        else:
            new = round(new, 1)
        out.append(f"{m.group(1)}{new}{m.group(4)}")
    else:
        out.append(line)
PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"Factor {FACTOR} aplicado a {PATH}")