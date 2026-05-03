import type { SimEvent, WorldSnapshot, ActorId, ProtocolStep } from './types';
import { monotonic, measureAsync } from './clock';
import { interpolateValidatorEvents } from './synthetic';
import { buildClaimRequest, SENDER, RECIPIENT, AMOUNT } from '../protocol/claim';
import { buildProofHeader } from '../protocol/proof';
import { getResource, postSettle } from '../protocol/api';
import { consumeNonce, getCurrentNonce } from '../protocol/wallet';
import { useSimStore } from '../store/simStore';
import { getScenario } from './scenarios';

let _eventCounter = 0;
function eid(): string {
  return `evt-${_eventCounter++}`;
}

function makeEvent(
  kind: string,
  from: ActorId,
  to: ActorId | null,
  t_start_us: number,
  t_end_us: number,
  step: ProtocolStep,
  label: string,
  payload?: unknown,
  outcome: 'ok' | 'error' | 'timeout' = 'ok',
): SimEvent {
  return { id: eid(), t_start_us, t_end_us, step, kind, from, to, label, payload, outcome };
}

const INITIAL_BALANCE = 10000;

function buildInitialSnapshot(f: number): WorldSnapshot {
  const n = 3 * f + 1;
  const validators: Record<string, { validator_id: string; nonce_for_agent: number; balance_of_agent: number; phase: 'idle' }> = {};
  for (let i = 0; i < n; i++) {
    const vid = `validator-${i}`;
    validators[vid] = { validator_id: vid, nonce_for_agent: 0, balance_of_agent: INITIAL_BALANCE, phase: 'idle' };
  }
  return {
    client: { nonce: 0, balance: INITIAL_BALANCE, pending_claim: null, last_proof_quorum: null },
    resourceServer: { recipient: RECIPIENT, required_amount: AMOUNT, last_status: null, payload_hash: null },
    facilitator: { f, quorum_threshold: 2 * f + 1, certificates_collected: 0, phase: 'idle' },
    validators,
  };
}

function applyEvent(
  prev: WorldSnapshot,
  ev: SimEvent,
  nonce: number,
  digest: string,
  quorumCount: number,
  claimAmount: number,
): WorldSnapshot {
  const s = structuredClone(prev);
  const kind = ev.kind;

  if (kind === 'get_resource') {
    // no visible state change yet
  } else if (kind === 'return_402') {
    s.resourceServer.last_status = 402;
  } else if (kind === 'build_claim') {
    s.client.pending_claim = digest;
    s.client.nonce = nonce;
  } else if (kind === 'sign_claim') {
    // no change
  } else if (kind === 'post_settle') {
    s.facilitator.phase = 'collecting';
  } else if (kind.startsWith('fanout_validator_')) {
    const idx = parseInt(kind.split('_')[2]!);
    const vid = `validator-${idx}`;
    if (s.validators[vid]) s.validators[vid] = { ...s.validators[vid]!, phase: 'verifying' };
  } else if (kind.startsWith('certificate_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    if (s.validators[vid]) s.validators[vid] = { ...s.validators[vid]!, phase: 'certified' };
    s.facilitator.certificates_collected += 1;
  } else if (kind.startsWith('rejection_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    if (s.validators[vid]) s.validators[vid] = { ...s.validators[vid]!, phase: 'rejected' };
  } else if (kind.startsWith('timeout_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    if (s.validators[vid]) s.validators[vid] = { ...s.validators[vid]!, phase: 'dead' };
  } else if (kind.startsWith('divergent_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    if (s.validators[vid]) s.validators[vid] = { ...s.validators[vid]!, phase: 'divergent' };
  } else if (kind === 'evaluate_round') {
    s.facilitator.phase = 'evaluating';
  } else if (kind === 'quorum_met') {
    s.facilitator.phase = 'settled';
  } else if (kind === 'quorum_failed') {
    s.facilitator.phase = 'failed';
  } else if (kind.startsWith('settle_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    if (s.validators[vid]) s.validators[vid] = { ...s.validators[vid]!, phase: 'settling' };
  } else if (kind === 'return_result') {
    s.client.last_proof_quorum = quorumCount;
  } else if (kind === 'retry_request') {
    // no change
  } else if (kind === 'verify_proof') {
    // no change
  } else if (kind === 'return_200') {
    s.resourceServer.last_status = 200;
    s.client.pending_claim = null;
    s.client.balance -= claimAmount;
    // Only update validators that actually participated in settlement (phase 'settling').
    // Divergent/rejected/dead validators intentionally keep their pre-settlement state.
    for (const vid of Object.keys(s.validators)) {
      if (s.validators[vid]!.phase === 'settling') {
        s.validators[vid] = {
          ...s.validators[vid]!,
          nonce_for_agent: nonce + 1,
          balance_of_agent: INITIAL_BALANCE - claimAmount,
          phase: 'settled',
        };
      }
    }
  }

  return s;
}

function buildSnapshots(
  events: SimEvent[],
  nonce: number,
  digest: string,
  quorumCount: number,
  f: number,
  claimAmount: number,
): WorldSnapshot[] {
  const snapshots: WorldSnapshot[] = [];
  let current = buildInitialSnapshot(f);
  for (const ev of events) {
    current = applyEvent(current, ev, nonce, digest, quorumCount, claimAmount);
    snapshots.push(structuredClone(current));
  }
  return snapshots;
}

export async function runSimulation(): Promise<void> {
  const store = useSimStore.getState();
  const scenarioId = store.scenario;
  const f = store.f;
  const scenario = getScenario(scenarioId);

  store.reset();
  store.setStatus('running');
  _eventCounter = 0;

  // Pre-warm: Python/uvicorn adds ~300ms cold-start latency to the first request.
  // Fire a silent GET before the timer starts so the measured simulation is clean.
  try { await getResource(); } catch { /* ignore — server may not be up yet */ }

  const allEvents: SimEvent[] = [];

  try {
    // Only advance the wallet nonce for happy path — failing scenarios use
    // override parameters and are always rejected, so the backend nonce never
    // increments. Consuming the counter for them would desync future happy paths.
    const nonce = scenarioId === 'happy' ? consumeNonce() : getCurrentNonce();

    // Step 1: GET /resource (no proof)
    const { result: res1, t_start_us: t1s, t_end_us: t1e } = await measureAsync(() =>
      getResource(),
    );
    allEvents.push(makeEvent('get_resource', 'client', 'resource-server', t1s, t1e, 1,
      'client.get_resource → resource-server', res1.body));

    if (res1.status !== 402) {
      throw new Error(`Expected 402 from resource server, got ${res1.status}`);
    }
    allEvents.push(makeEvent('return_402', 'resource-server', 'client', t1e, t1e + 500, 2,
      'resource-server.return_402 → client', res1.body));

    // Step 3a: build + sign claim (with scenario overrides)
    const t3s = monotonic();
    const { request: claimReq, payload: claimPayloadBytes, digest, effectiveNonce, effectiveAmount, effectiveRecipient } = await buildClaimRequest(
      nonce,
      scenario.claimOverride,
    );
    const canonicalPayload = new TextDecoder().decode(claimPayloadBytes);
    const t3mid = monotonic();
    allEvents.push(makeEvent('build_claim', 'client', null, t3s, t3mid, 3,
      'client.build_claim', {
        sender: claimReq.sender,
        recipient: effectiveRecipient,
        amount: effectiveAmount,
        nonce: effectiveNonce,
        sender_pubkey_b64: claimReq.sender_pubkey,
        canonical_payload: canonicalPayload,
        digest,
        encoding: 'length-prefixed: "len:field" joined by | (delimiter-collision-safe)',
        scenario: scenarioId !== 'happy' ? scenarioId : undefined,
      }));

    const t3sign = monotonic();
    allEvents.push(makeEvent('sign_claim', 'client', null, t3mid, t3sign, 3,
      `client.sign_claim (nonce=${effectiveNonce})`, {
        algorithm: 'Ed25519',
        signed_bytes: canonicalPayload,
        signature_b64: claimReq.signature,
        nonce: effectiveNonce,
        note: 'sender_pubkey is sent alongside but is NOT part of the signed payload',
      }));

    // Step 3b: POST /settle
    const { result: qr, t_start_us: tSettleS, t_end_us: tSettleE } = await measureAsync(() =>
      postSettle(claimReq),
    );
    allEvents.push(makeEvent('post_settle', 'client', 'facilitator', t3sign, tSettleS, 3,
      'client.post_settle → facilitator', {
        endpoint: 'POST http://localhost:8001/settle',
        request_body: {
          sender: claimReq.sender,
          recipient: claimReq.recipient,
          amount: claimReq.amount,
          nonce: claimReq.nonce,
          sender_pubkey_b64: claimReq.sender_pubkey,
          signature_b64: claimReq.signature,
        },
        claim_digest: digest,
        scenario: scenarioId !== 'happy' ? scenarioId : undefined,
      }));

    // Steps 4-6: synthetic intra-facilitator events.
    // Settle now runs as a BackgroundTask on the backend (after /settle returns),
    // so place settle events AFTER tSettleE to match the real protocol order:
    // quorum → return proof to client → settle validators in parallel with retry.
    const initialSnap = buildInitialSnapshot(f);
    const { events: synthEvents } = interpolateValidatorEvents(qr, tSettleS, tSettleE, initialSnap, {
      settleStartUs: tSettleE + 200,
    });
    allEvents.push(...synthEvents);

    // Build payment proof — happens AFTER quorum is reached but BEFORE the response goes out.
    // Anchored to tSettleE working backwards (proof building is the last thing before return).
    if (qr.quorum_met && qr.proof_build_us != null && qr.proof_build_us > 0) {
      const proofEnd = tSettleE - 50;
      const proofStart = Math.max(tSettleS + 1, proofEnd - qr.proof_build_us);
      allEvents.push(makeEvent('build_payment_proof', 'facilitator', null, proofStart, proofEnd, 6,
        'facilitator.build_payment_proof', {
          duration_us: qr.proof_build_us,
          timing_source: 'measured by backend (time.perf_counter_ns around build_payment_proof + Pydantic serialization)',
          actions: [
            'sha256(canonical_claim_payload).hex() → claim_digest',
            'b64url-encode each validator signature + pubkey',
            'pack { claim, claim_digest, success_count, quorum_threshold, certificates } into JSON',
            'Pydantic model serialization for FastAPI response',
          ],
          note: 'proof depends only on certificates (gathered during quorum), NOT on settle. Built before return so the response carries it.',
        }));
    }

    // Step 7: return settlement result
    allEvents.push(makeEvent('return_result', 'facilitator', 'client', tSettleE, tSettleE + 500, 7,
      'facilitator.return_result → client', {
        quorum_met: qr.quorum_met,
        success_count: qr.success_count,
        quorum_threshold: 2 * f + 1,
        n_validators: 3 * f + 1,
        certificates: qr.certificates,
        rejections: qr.rejections,
        dead: qr.dead,
        payment_proof: qr.payment_proof,
        protocol_note: 'returned the moment quorum was met and the proof was built. settle on signing validators is scheduled as a FastAPI BackgroundTask and runs AFTER this response is on the wire — visible as settle_* events below.',
        cert_signature_note: 'each certificate is Ed25519 over the canonical claim payload, signed by that validator\'s key',
      }));

    // For failing scenarios (or any quorum failure) — show the simulation as complete without continuing
    if (!qr.quorum_met) {
      allEvents.sort((a, b) => a.t_start_us - b.t_start_us);
      const snapshots = buildSnapshots(allEvents, effectiveNonce, digest, qr.success_count, f, effectiveAmount);
      store.setEvents(allEvents, snapshots);
      store.setStatus('done');
      store.play();
      return;
    }

    const proofHeader = buildProofHeader(qr.payment_proof!);

    // Step 8: retry GET /resource with proof
    const { result: res2, t_start_us: t8s, t_end_us: t8e } = await measureAsync(() =>
      getResource(proofHeader),
    );
    // retry_request must display strictly after return_result and before verify_proof.
    // Anchor retry to the gap between return_result end (~tSettleE + 500) and t8s (real
    // start of GET /resource). If JS busy-time was tiny (t8s ≈ tSettleE), force a
    // 100µs slot so the sort still lands retry → verify → 200 in order.
    const retryStart = tSettleE + 600;
    const retryEnd = Math.max(retryStart + 100, t8s);
    allEvents.push(makeEvent('retry_request', 'client', 'resource-server', retryStart, retryEnd, 8,
      'client.retry_request → resource-server', {
        endpoint: 'GET http://localhost:8000/resource',
        header: 'X-Payment-Proof: <base64url-encoded JSON>',
        proof_header_b64_truncated: proofHeader.length > 80 ? `${proofHeader.slice(0, 80)}…(${proofHeader.length} chars)` : proofHeader,
        decoded_proof: qr.payment_proof,
      }));

    // Steps 9-10: server verifies proof (approximated in the RTT window)
    const verifyStart = retryEnd;
    const verifyEnd = Math.max(verifyStart + 200, t8e - 500);
    allEvents.push(makeEvent('verify_proof', 'resource-server', null, verifyStart, verifyEnd, 9,
      'resource-server.verify_proof', {
        valid: res2.status === 200,
        checks: [
          'sender Ed25519 signature over canonical claim payload',
          'sha256(payload) == claim_digest',
          'each validator certificate signature verifies',
          `success_count >= quorum_threshold (${2 * f + 1})`,
          'recipient matches expected (server-recipient)',
          'amount >= price (10)',
        ],
        note: 'fully offline, no callback to facilitator or validators',
      }));

    // Step 11: return 200
    const return200End = Math.max(verifyEnd + 100, t8e);
    allEvents.push(makeEvent('return_200', 'resource-server', 'client', verifyEnd, return200End, 11,
      'resource-server.return_200 → client', res2.body,
      res2.status === 200 ? 'ok' : 'error'));

    allEvents.sort((a, b) => a.t_start_us - b.t_start_us);
    const snapshots = buildSnapshots(allEvents, effectiveNonce, digest, qr.success_count, f, effectiveAmount);

    store.setEvents(allEvents, snapshots);
    store.setStatus('done');
    store.play();
  } catch (err) {
    allEvents.sort((a, b) => a.t_start_us - b.t_start_us);
    if (allEvents.length > 0) {
      const snapshots = buildSnapshots(allEvents, 0, '', 0, f, AMOUNT);
      store.setEvents(allEvents, snapshots);
    }
    store.setError(err instanceof Error ? err.message : String(err));
  }
}
