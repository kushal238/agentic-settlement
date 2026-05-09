"""Tests for cli.wallet -- keypair generation, persistence, load."""

import json
from pathlib import Path

from nacl.signing import SigningKey

from cli.wallet import Wallet, load_or_generate, wallet_path


def test_wallet_to_dict_roundtrip():
    sk = SigningKey.generate()
    w1 = Wallet(account_id="agent-test", signing_key=sk)
    w2 = Wallet.from_dict(w1.to_dict())
    assert w2.account_id == "agent-test"
    assert bytes(w2.signing_key) == bytes(sk)
    assert bytes(w2.verify_key) == bytes(sk.verify_key)
    assert w2.pubkey_b64 == w1.pubkey_b64


def test_load_or_generate_creates_file_on_first_call(tmp_path: Path):
    p = tmp_path / "subdir" / "agent_key.json"
    assert not p.exists()
    wallet, was_generated = load_or_generate(p)
    assert was_generated is True
    assert p.exists()
    on_disk = json.loads(p.read_text())
    assert on_disk["account_id"] == wallet.account_id
    assert on_disk["pubkey_b64"] == wallet.pubkey_b64
    assert "private_key_b64" in on_disk


def test_load_or_generate_loads_existing_file_unchanged(tmp_path: Path):
    p = tmp_path / "agent_key.json"
    first, _ = load_or_generate(p)
    second, was_generated = load_or_generate(p)
    assert was_generated is False
    assert second.account_id == first.account_id
    assert bytes(second.signing_key) == bytes(first.signing_key)


def test_load_or_generate_account_id_only_honored_on_first_call(tmp_path: Path):
    """`account_id` is only used when generating. Re-loading an existing file
    keeps the on-disk identity even if a different name is requested."""
    p = tmp_path / "agent_key.json"
    first, _ = load_or_generate(p, account_id="alice")
    second, _ = load_or_generate(p, account_id="bob")
    assert first.account_id == "alice"
    assert second.account_id == "alice"  # not bob


def test_random_account_id_format(tmp_path: Path):
    p = tmp_path / "agent_key.json"
    wallet, _ = load_or_generate(p)
    assert wallet.account_id.startswith("agent-")
    suffix = wallet.account_id[len("agent-"):]
    assert len(suffix) == 8
    int(suffix, 16)  # must be hex


def test_wallet_path_honors_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_wallet.json"
    monkeypatch.setenv("AGENTIC_WALLET_PATH", str(custom))
    assert wallet_path() == custom


def test_wallet_path_defaults_to_home(monkeypatch):
    monkeypatch.delenv("AGENTIC_WALLET_PATH", raising=False)
    p = wallet_path()
    assert p.name == "agent_key.json"
    assert ".agentic-settlement" in str(p)
