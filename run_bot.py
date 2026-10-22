"""Punto de entrada: ejecuta  python run_bot.py  para arrancar el bot."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kame.bot.app import main  # noqa: E402

if __name__ == "__main__":
    main()
