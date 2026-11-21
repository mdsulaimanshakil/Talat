import pytest


@pytest.fixture(autouse=True)
def own_settings_folder(tmp_path, monkeypatch):
    """Every test starts from the default look and never touches the real ~/.talat settings."""
    monkeypatch.setenv("TALAT_SETTINGS_DIR", str(tmp_path / "settings"))
