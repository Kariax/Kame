"""Copia de seguridad de la base de datos.  Uso:  python scripts/backup.py

Crea data/backups/kame-AAAAMMDD-HHMMSS.db y conserva las 14 más recientes.
Es seguro ejecutarlo aunque el bot esté encendido.
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kame.config import load_settings  # noqa: E402

KEEP = 14


def main() -> None:
    settings = load_settings()
    if not settings.db_path.exists():
        print(f"No existe la base de datos en {settings.db_path}. Nada que copiar.")
        return
    backup_dir = settings.db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"kame-{datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(settings.db_path)
    dest = sqlite3.connect(target)
    with dest:
        source.backup(dest)
    dest.close()
    source.close()
    print(f"Copia creada: {target}")
    for old in sorted(backup_dir.glob("kame-*.db"))[:-KEEP]:
        old.unlink()


if __name__ == "__main__":
    main()
