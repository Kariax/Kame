"""Configuración del entorno (token, base de datos...). Los secretos vienen de .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]


class SettingsError(Exception):
    """Falta o es incorrecta alguna variable de entorno."""


@dataclass(frozen=True)
class Settings:
    # repr=False: el token nunca aparece si alguien imprime el objeto por error.
    discord_token: str | None = field(repr=False)
    dev_guild_id: int | None
    db_path: Path
    content_dir: Path
    migrations_dir: Path

    def require_token(self) -> str:
        if not self.discord_token or self.discord_token.startswith("pega_aqui"):
            raise SettingsError(
                "Falta DISCORD_TOKEN. Copia .env.example como .env y pega el token del bot."
            )
        return self.discord_token


def load_settings(base_dir: Path = BASE_DIR, load_env_file: bool = True) -> Settings:
    if load_env_file:
        load_dotenv(base_dir / ".env")
    guild_raw = os.getenv("DEV_GUILD_ID", "").strip()
    if guild_raw and not guild_raw.isdigit():
        raise SettingsError("DEV_GUILD_ID debe ser un número (el ID de tu servidor).")
    db_path = Path(os.getenv("DB_PATH", "data/kame.db"))
    if not db_path.is_absolute():
        db_path = base_dir / db_path
    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN") or None,
        dev_guild_id=int(guild_raw) if guild_raw else None,
        db_path=db_path,
        content_dir=base_dir / "content",
        migrations_dir=base_dir / "migrations",
    )
