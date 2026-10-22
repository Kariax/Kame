import pytest

from kame.config import SettingsError, load_settings

SECRET = "TOKEN-SUPER-SECRETO-123"


def test_token_never_appears_in_repr(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", SECRET)
    settings = load_settings(tmp_path, load_env_file=False)
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert settings.require_token() == SECRET


def test_missing_token_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    settings = load_settings(tmp_path, load_env_file=False)
    with pytest.raises(SettingsError) as e:
        settings.require_token()
    assert "DISCORD_TOKEN" in str(e.value)


def test_placeholder_token_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "pega_aqui_el_token_del_bot")
    with pytest.raises(SettingsError):
        load_settings(tmp_path, load_env_file=False).require_token()


def test_guild_id_must_be_numeric(monkeypatch, tmp_path):
    monkeypatch.setenv("DEV_GUILD_ID", "abc")
    with pytest.raises(SettingsError):
        load_settings(tmp_path, load_env_file=False)


def test_relative_db_path_is_resolved_against_base_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", "data/x.db")
    monkeypatch.delenv("DEV_GUILD_ID", raising=False)
    settings = load_settings(tmp_path, load_env_file=False)
    assert settings.db_path == tmp_path / "data" / "x.db"
    assert settings.dev_guild_id is None
