from app.core.config import Settings


def test_settings_read_environment(monkeypatch) -> None:
    monkeypatch.setenv("COMMERCECORE_APP_NAME", "Test API")
    monkeypatch.setenv("COMMERCECORE_DEBUG", "true")
    monkeypatch.setenv("DEBUG", "release")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Test API"
    assert settings.debug is True
