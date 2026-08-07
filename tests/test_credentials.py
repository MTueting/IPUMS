"""Key resolution, storage and masking.

The resolution order is the contract other people rely on: a key set one way
must not be silently shadowed by one set another way.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def creds(tmp_path, monkeypatch):
    """A credentials module pointed at a throwaway config dir and repo root."""
    monkeypatch.setenv("IPUMSI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("IPUMS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from ipumsi import credentials

    module = importlib.reload(credentials)
    monkeypatch.setattr(module, "ROOT", tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    # Legacy dotfiles live in the real home directory; point them at tmp too.
    monkeypatch.setattr(
        module.KeySpec, "legacy_path",
        property(lambda self: tmp_path / "home" / self.legacy_file),
    )
    (tmp_path / "home").mkdir()
    yield module
    importlib.reload(credentials)


def test_nothing_set(creds):
    key, source = creds.find_key("IPUMS_API_KEY")
    assert key is None and source == "not set"
    assert not creds.has_key("IPUMS_API_KEY")
    with pytest.raises(creds.MissingKey):
        creds.get_key("IPUMS_API_KEY")


def test_save_roundtrip_and_forget(creds):
    path = creds.save_key("IPUMS_API_KEY", "  abc123  ")
    assert json.loads(path.read_text())["IPUMS_API_KEY"] == "abc123"

    key, source = creds.find_key("IPUMS_API_KEY")
    assert key == "abc123"
    assert str(path) in source

    assert creds.delete_key("IPUMS_API_KEY") is True
    assert creds.find_key("IPUMS_API_KEY")[0] is None
    assert creds.delete_key("IPUMS_API_KEY") is False


def test_resolution_order(creds, monkeypatch, tmp_path):
    """Later sources must never shadow earlier ones."""
    creds.save_key("IPUMS_API_KEY", "from-store")
    assert creds.find_key("IPUMS_API_KEY")[0] == "from-store"

    (creds.ROOT / ".env").write_text("IPUMS_API_KEY=from-dotenv\n", encoding="utf-8")
    assert creds.find_key("IPUMS_API_KEY")[0] == "from-dotenv"

    monkeypatch.setenv("IPUMS_API_KEY", "from-env")
    assert creds.find_key("IPUMS_API_KEY")[0] == "from-env"

    assert creds.find_key("IPUMS_API_KEY", explicit="from-arg")[0] == "from-arg"


def test_dotenv_placeholder_is_not_a_key(creds):
    """.env.example ships `your_key_here`; that must not read as configured."""
    (creds.ROOT / ".env").write_text("IPUMS_API_KEY=your_key_here\n", encoding="utf-8")
    assert creds.find_key("IPUMS_API_KEY")[0] is None


def test_dotenv_handles_quotes_and_other_lines(creds):
    (creds.ROOT / ".env").write_text(
        "# a comment\nOTHER=1\nIPUMS_API_KEY='quoted-key'\n", encoding="utf-8"
    )
    assert creds.find_key("IPUMS_API_KEY")[0] == "quoted-key"


def test_legacy_dotfile_still_read(creds):
    legacy = creds.SPECS["ANTHROPIC_API_KEY"].legacy_path
    legacy.write_text("sk-ant-legacy\n", encoding="utf-8")
    key, source = creds.find_key("ANTHROPIC_API_KEY")
    assert key == "sk-ant-legacy"
    assert str(legacy) in source


def test_keys_are_independent(creds):
    creds.save_key("IPUMS_API_KEY", "ipums")
    creds.save_key("ANTHROPIC_API_KEY", "sk-ant-x")
    assert creds.find_key("IPUMS_API_KEY")[0] == "ipums"
    assert creds.find_key("ANTHROPIC_API_KEY")[0] == "sk-ant-x"
    creds.delete_key("IPUMS_API_KEY")
    assert creds.find_key("ANTHROPIC_API_KEY")[0] == "sk-ant-x"


def test_rejects_unknown_names_and_empty_values(creds):
    with pytest.raises(KeyError):
        creds.find_key("NOT_A_KEY")
    with pytest.raises(KeyError):
        creds.save_key("NOT_A_KEY", "x")
    with pytest.raises(ValueError):
        creds.save_key("IPUMS_API_KEY", "   ")


def test_mask_is_ascii_and_hides_the_middle(creds):
    masked = creds.mask("sk-ant-api03-SECRETSECRETSECRET-1234")
    assert masked == "sk-ant...1234"
    assert masked.isascii()  # printed to non-UTF-8 Windows consoles
    assert "SECRET" not in masked
    assert creds.mask("short") == "*****"


def test_anthropic_prefix_is_checked_before_any_network_call(creds):
    ok, message = creds.verify_key("ANTHROPIC_API_KEY", "not-an-anthropic-key")
    assert ok is False
    assert "sk-ant-" in message


def test_empty_key_never_verifies(creds):
    for name in creds.SPECS:
        ok, _ = creds.verify_key(name, "   ")
        assert ok is False
