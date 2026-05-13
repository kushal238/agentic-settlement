"""Tests for cli.agent_client `buy` subcommand and run_buy.

Drives the full x402 buy flow end-to-end against in-process facilitator
and api_server apps via TestClient. The agent:
  1. Bootstraps (registers itself with the facilitator)
  2. GETs /resource → 402 with payment requirements
  3. GETs /account/{me} → reads its current nonce
  4. Builds and signs a claim, POSTs /settle → receives quorum proof
  5. Retries GET /resource with X-Payment-Proof header → 200 with payload
  6. Verifies payload hash against advertised hint

Real signatures, real quorum, real verification. No mocks.

The test sets GENESIS_ACCOUNTS_PATH=genesis.json so the validators have
the 'server-recipient' account (which the api_server's PAYMENT_RECIPIENT
points at by default) at startup. The agent registers itself dynamically.
"""

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cli.agent_client import Narrator, do_bootstrap, run_buy
from cli.wallet import load_or_generate


def _silent(prefix: str) -> Narrator:
    return Narrator(prefix, use_color=False, quiet=True)


@pytest.fixture
def apps(monkeypatch):
    """Build both apps with genesis loaded so server-recipient exists, and
    return their TestClients (lifespan already triggered)."""
    monkeypatch.setenv("GENESIS_ACCOUNTS_PATH", "genesis.json")

    # Reload configs so the module-level constants pick up the env var.
    from src.facilitator_server import config as fac_cfg
    from src.api_server import config as api_cfg
    importlib.reload(fac_cfg)
    importlib.reload(api_cfg)

    from src.facilitator_server import main as fac_main
    from src.api_server import main as api_main
    importlib.reload(fac_main)
    importlib.reload(api_main)

    fac_tc = TestClient(fac_main.create_app())
    api_tc = TestClient(api_main.create_app())
    fac_tc.__enter__()
    api_tc.__enter__()
    try:
        yield fac_tc, api_tc
    finally:
        fac_tc.__exit__(None, None, None)
        api_tc.__exit__(None, None, None)


def test_run_buy_happy_path(tmp_path: Path, apps):
    fac_tc, api_tc = apps
    wallet, _ = load_or_generate(tmp_path / "wallet.json", account_id="test-buyer-1")

    # Step 0: bootstrap (registers the agent's account with the validators).
    do_bootstrap(fac_tc, wallet, initial_balance=1000, narrator=_silent("bootstrap"))

    result = run_buy(
        api_client=api_tc,
        facilitator_client=fac_tc,
        wallet=wallet,
        api_url_for_display="http://test-api",
        facilitator_url_for_display="http://test-fac",
        narrator=_silent("buy"),
    )

    assert result.success is True, f"buy failed: {result.failure_reason}"
    assert result.quorum_size == 4
    assert result.payload is not None
    assert result.payload["data"]["data"] == "This is the valuable information you paid for."
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0


def test_run_buy_increments_nonce_for_next_run(tmp_path: Path, apps):
    """After a successful buy the agent's nonce should be 1. A second buy
    must use nonce=1 (read from /account/{me}), not nonce=0."""
    fac_tc, api_tc = apps
    wallet, _ = load_or_generate(tmp_path / "wallet.json", account_id="test-buyer-2")
    do_bootstrap(fac_tc, wallet, initial_balance=1000, narrator=_silent("bootstrap"))

    first = run_buy(
        api_client=api_tc, facilitator_client=fac_tc, wallet=wallet,
        api_url_for_display="http://test-api",
        facilitator_url_for_display="http://test-fac",
        narrator=_silent("buy"),
    )
    assert first.success

    # Background-task settle increments the nonce asynchronously; poll briefly.
    import time
    deadline = time.time() + 2.0
    while time.time() < deadline:
        nonce_now = fac_tc.get(f"/account/{wallet.account_id}").json()["nonce"]
        if nonce_now == 1:
            break
        time.sleep(0.05)
    assert nonce_now == 1, f"expected nonce=1 after first buy, got {nonce_now}"

    second = run_buy(
        api_client=api_tc, facilitator_client=fac_tc, wallet=wallet,
        api_url_for_display="http://test-api",
        facilitator_url_for_display="http://test-fac",
        narrator=_silent("buy"),
    )
    assert second.success, f"second buy failed: {second.failure_reason}"


def test_run_buy_returns_per_phase_timings(tmp_path: Path, apps):
    """BuyResult.timings_ms is the per-phase breakdown we publish in the
    BUY COMPLETE block. All seven phases must appear, all non-negative."""
    fac_tc, api_tc = apps
    wallet, _ = load_or_generate(tmp_path / "wallet.json", account_id="timings-buyer")
    do_bootstrap(fac_tc, wallet, initial_balance=1000, narrator=_silent("bootstrap"))

    result = run_buy(
        api_client=api_tc, facilitator_client=fac_tc, wallet=wallet,
        api_url_for_display="http://test-api",
        facilitator_url_for_display="http://test-fac",
        narrator=_silent("buy"),
    )
    assert result.success
    assert result.timings_ms is not None
    expected_phases = {"ask", "nonce", "sign", "settle", "encode", "redeem", "verify"}
    assert set(result.timings_ms.keys()) == expected_phases
    assert all(ms >= 0 for ms in result.timings_ms.values())
    # The work total should match the elapsed_ms field within rounding.
    assert sum(result.timings_ms.values()) == result.elapsed_ms


def test_run_buy_step_mode_pauses_between_steps(tmp_path: Path, apps):
    """With step_mode=True, the narrator's input_fn is called once after
    each of the first six steps (step 7 has no following pause since the
    buy completes right after). Stubbed input avoids reading from stdin."""
    fac_tc, api_tc = apps
    wallet, _ = load_or_generate(tmp_path / "wallet.json", account_id="step-buyer")
    do_bootstrap(fac_tc, wallet, initial_balance=1000, narrator=_silent("bootstrap"))

    from cli.agent_client import Narrator
    call_count = {"n": 0}

    def stub_input(prompt):
        call_count["n"] += 1
        return ""

    stepping = Narrator("buy", use_color=False, quiet=False,
                        step_mode=True, input_fn=stub_input,
                        stream=open("/dev/null", "w"))
    result = run_buy(
        api_client=api_tc, facilitator_client=fac_tc, wallet=wallet,
        api_url_for_display="http://test-api",
        facilitator_url_for_display="http://test-fac",
        narrator=stepping,
    )
    assert result.success
    assert call_count["n"] == 6  # one pause after each of steps 1..6


def test_run_buy_fails_cleanly_if_account_unknown(tmp_path: Path, apps):
    """If the agent skips bootstrap, the validators have no account for it.
    submit_claim will fail quorum (all validators reject), and run_buy must
    surface that as a clean failure rather than a crash."""
    fac_tc, api_tc = apps
    wallet, _ = load_or_generate(tmp_path / "wallet.json", account_id="never-registered")
    # Deliberately NOT calling do_bootstrap.

    result = run_buy(
        api_client=api_tc, facilitator_client=fac_tc, wallet=wallet,
        api_url_for_display="http://test-api",
        facilitator_url_for_display="http://test-fac",
        narrator=_silent("buy"),
    )

    # The /account read will 404 since the agent never registered.
    assert result.success is False
    assert "account read failed" in (result.failure_reason or "")


# ---------------------------------------------------------------------------
# main() end-to-end with `buy` subcommand
# ---------------------------------------------------------------------------

def test_main_buy_end_to_end(tmp_path: Path, monkeypatch, apps):
    """python -m cli.agent_client buy ... returns 0 and writes the keyfile."""
    fac_tc, api_tc = apps
    keyfile = tmp_path / "agent_key.json"
    monkeypatch.setenv("AGENTIC_WALLET_PATH", str(keyfile))

    import cli.agent_client as ac

    def routing_client(base_url, **kwargs):
        # Choose the routing target based on the configured base_url.
        if "8000" in base_url or "api" in base_url:
            return _PassthroughClient(api_tc)
        return _PassthroughClient(fac_tc)

    monkeypatch.setattr(ac.httpx, "Client", routing_client)

    rc = ac.main(["buy", "--quiet", "--no-color", "--as", "main-buy-agent"])
    assert rc == 0
    assert keyfile.exists()
    on_disk = json.loads(keyfile.read_text())
    assert on_disk["account_id"] == "main-buy-agent"


class _PassthroughClient:
    """httpx.Client-shaped wrapper around an already-entered TestClient.
    Doesn't drive lifespan -- the apps fixture owns that."""

    def __init__(self, tc: TestClient):
        self._tc = tc

    def close(self): pass
    def get(self, path, **kwargs): return self._tc.get(path, **kwargs)
    def post(self, path, **kwargs): return self._tc.post(path, **kwargs)
