import pytest

from cvcue_mcp import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in list(__import__("os").environ):
        if k.startswith("CVCUE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "_SECRETS_DIR", tmp_path / "secrets")
    monkeypatch.setattr(config, "_DEFAULT_INI", tmp_path / "missing.ini")
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path / "noproj")
    monkeypatch.chdir(tmp_path)


def test_env_api_key(monkeypatch):
    monkeypatch.setenv("CVCUE_BASE_URL", "https://x.example.com/wifi/api/")
    monkeypatch.setenv("CVCUE_KEY_ID", "KEY-1")
    monkeypatch.setenv("CVCUE_KEY_VALUE", "secret")
    cfg = config.load_config()
    c = cfg.credentials
    assert c.base_url == "https://x.example.com/wifi/api"
    assert c.auth_type == "apikeycredentials"
    assert c.session_body()["keyId"] == "KEY-1"
    assert cfg.enable_writes is False
    assert cfg.openapi_spec_path.endswith("cvcue_openapi.json")


def test_api_key_without_base_url_is_allowed(monkeypatch):
    monkeypatch.setenv("CVCUE_KEY_ID", "KEY-1")
    monkeypatch.setenv("CVCUE_KEY_VALUE", "secret")
    assert config.load_config().credentials.base_url == ""


def test_password_requires_base_url(monkeypatch):
    monkeypatch.setenv("CVCUE_USERNAME", "admin")
    monkeypatch.setenv("CVCUE_PASSWORD", "pw")
    with pytest.raises(SystemExit):
        config.load_config()
    monkeypatch.setenv("CVCUE_BASE_URL", "https://onprem/wifi/api")
    c = config.load_config().credentials
    assert c.session_body()["type"] == "usernamepasswordcredentials"


def test_dotenv_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "# comment\nCVCUE_KEY_ID=KEY-2\nCVCUE_KEY_VALUE='v'\nexport CVCUE_ENABLE_WRITES=true\n"
    )
    cfg = config.load_config()
    assert cfg.credentials.key_id == "KEY-2"
    assert cfg.credentials.key_value == "v"
    assert cfg.enable_writes is True


def test_env_beats_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("CVCUE_KEY_ID=from-file\nCVCUE_KEY_VALUE=v\n")
    monkeypatch.setenv("CVCUE_KEY_ID", "from-env")
    assert config.load_config().credentials.key_id == "from-env"


def test_ini_file(tmp_path, monkeypatch):
    ini = tmp_path / "creds.ini"
    ini.write_text("[cvcue]\nbase_url=https://h/wifi/api\nkey_id=K\nkey_value=V%x\nverify_ssl=false\n")
    monkeypatch.setenv("CVCUE_CREDENTIALS_FILE", str(ini))
    c = config.load_config().credentials
    assert c.key_value == "V%x" and c.verify_ssl is False


def test_no_credentials_exits():
    with pytest.raises(SystemExit):
        config.load_config()
