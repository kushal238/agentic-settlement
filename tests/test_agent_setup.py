"""Tests for cli.agent_client `setup` subcommand and do_bootstrap.

Drives do_bootstrap() against an in-process facilitator app via TestClient
to verify the full first-run flow: generate keypair on disk, register the
account on every validator, return current state.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cli.agent_client import Narrator, do_bootstrap, main
from cli.wallet import Wallet, load_or_generate
from src.facilitator_server.main import create_app


@pytest.fixture
def facilitator_app():
    return create_app()


def _silent_narrator(prefix: str = "bootstrap") -> Narrator:
    return Narrator(prefix, use_color=False, quiet=True)


# ---------------------------------------------------------------------------
# do_bootstrap unit-level
# ---------------------------------------------------------------------------

def test_bootstrap_registers_fresh_account(tmp_path: Path, facilitator_app):
    wallet, _ = load_or_generate(tmp_path / "k.json", account_id="setup-test-1")
    with TestClient(facilitator_app) as fac_client:
        state = do_bootstrap(fac_client, wallet, initial_balance=500,
                             narrator=_silent_narrator())
    assert state["account_id"] == "setup-test-1"
    assert state["pubkey_b64"] == wallet.pubkey_b64
    assert state["balance"] == 500
    assert state["nonce"] == 0


def test_bootstrap_idempotent(tmp_path: Path, facilitator_app):
    """Re-running bootstrap with the same wallet returns the existing state
    unchanged. The new initial_balance is ignored on the second call."""
    wallet, _ = load_or_generate(tmp_path / "k.json", account_id="setup-test-2")
    with TestClient(facilitator_app) as fac_client:
        first = do_bootstrap(fac_client, wallet, initial_balance=100,
                             narrator=_silent_narrator())
        second = do_bootstrap(fac_client, wallet, initial_balance=9999,
                              narrator=_silent_narrator())
    assert first == second
    assert second["balance"] == 100  # not 9999


def test_bootstrap_fatal_on_account_id_with_different_pubkey(tmp_path: Path, facilitator_app):
    """If the account_id is already registered with a different pubkey, the
    agent can't recover -- its identity IS its key. Surface as SystemExit."""
    wallet_a, _ = load_or_generate(tmp_path / "a.json", account_id="setup-test-3")
    wallet_b, _ = load_or_generate(tmp_path / "b.json", account_id="setup-test-3")
    assert wallet_a.pubkey_b64 != wallet_b.pubkey_b64
    with TestClient(facilitator_app) as fac_client:
        do_bootstrap(fac_client, wallet_a, narrator=_silent_narrator())
        with pytest.raises(SystemExit) as exc:
            do_bootstrap(fac_client, wallet_b, narrator=_silent_narrator())
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# main() end-to-end with setup subcommand
# ---------------------------------------------------------------------------

def test_main_setup_writes_keyfile_and_returns_zero(tmp_path: Path, monkeypatch):
    """End-to-end: `python -m cli.agent_client setup` against a live-ish
    facilitator generates a key, registers the account, exits 0."""
    keyfile = tmp_path / "agent_key.json"
    monkeypatch.setenv("AGENTIC_WALLET_PATH", str(keyfile))

    # We patch httpx.Client to route requests through TestClient on the
    # facilitator app. This is the same pattern the buy commit will use to
    # cover the api_server too.
    from src.facilitator_server.main import create_app as create_facilitator_app
    fac_app = create_facilitator_app()

    import cli.agent_client as ac

    class _RoutingClient:
        def __init__(self, base_url: str, **kwargs):
            self._tc = TestClient(fac_app)
            self._tc.__enter__()  # trigger lifespan

        def close(self):
            self._tc.__exit__(None, None, None)

        def post(self, path, **kwargs):
            return self._tc.post(path, **kwargs)

        def get(self, path, **kwargs):
            return self._tc.get(path, **kwargs)

    monkeypatch.setattr(ac.httpx, "Client", _RoutingClient)

    rc = ac.main(["setup", "--quiet", "--no-color", "--as", "main-setup-agent"])
    assert rc == 0
    assert keyfile.exists()
    on_disk = json.loads(keyfile.read_text())
    assert on_disk["account_id"] == "main-setup-agent"
