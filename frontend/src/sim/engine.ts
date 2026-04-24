import type { SimEvent, WorldSnapshot, ActorId, ProtocolStep } from './types';
import { monotonic, measureAsync } from './clock';
import { interpolateValidatorEvents } from './synthetic';
import { buildClaimRequest, SENDER, RECIPIENT, AMOUNT } from '../protocol/claim';
import { buildProofHeader } from '../protocol/proof';
import { getResource, postSettle } from '../protocol/api';
import { consumeNonce } from '../protocol/wallet';
import { useSimStore } from '../store/simStore';

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

// Snapshot builders — derive world state from accumulated events
const INITIAL_BALANCE = 10000;

function buildInitialSnapshot(): WorldSnapshot {
  return {
    client: { nonce: 0, balance: INITIAL_BALANCE, pending_claim: null, last_proof_quorum: null },
    resourceServer: { recipient: RECIPIENT, required_amount: AMOUNT, last_status: null, payload_hash: null },
    facilitator: { f: 1, quorum_threshold: 3, certificates_collected: 0, phase: 'idle' },
    validators: {
      'validator-0': { validator_id: 'validator-0', nonce_for_agent: 0, balance_of_agent: INITIAL_BALANCE, phase: 'idle' },
      'validator-1': { validator_id: 'validator-1', nonce_for_agent: 0, balance_of_agent: INITIAL_BALANCE, phase: 'idle' },
      'validator-2': { validator_id: 'validator-2', nonce_for_agent: 0, balance_of_agent: INITIAL_BALANCE, phase: 'idle' },
      'validator-3': { validator_id: 'validator-3', nonce_for_agent: 0, balance_of_agent: INITIAL_BALANCE, phase: 'idle' },
    },
  };
}

function applyEvent(prev: WorldSnapshot, ev: SimEvent, nonce: number, digest: string, quorumCount: number): WorldSnapshot {
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
    s.validators[vid] = { ...s.validators[vid]!, phase: 'verifying' };
  } else if (kind.startsWith('certificate_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    s.validators[vid] = { ...s.validators[vid]!, phase: 'certified' };
    s.facilitator.certificates_collected += 1;
  } else if (kind.startsWith('rejection_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    s.validators[vid] = { ...s.validators[vid]!, phase: 'rejected' };
  } else if (kind.startsWith('timeout_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    s.validators[vid] = { ...s.validators[vid]!, phase: 'dead' };
  } else if (kind === 'evaluate_round') {
    s.facilitator.phase = 'evaluating';
  } else if (kind === 'quorum_met') {
    s.facilitator.phase = 'settled';
  } else if (kind === 'quorum_failed') {
    s.facilitator.phase = 'failed';
  } else if (kind.startsWith('settle_')) {
    const idx = parseInt(kind.split('_')[1]!);
    const vid = `validator-${idx}`;
    s.validators[vid] = { ...s.validators[vid]!, phase: 'settling' };
  } else if (kind === 'return_result') {
    s.client.last_proof_quorum = quorumCount;
  } else if (kind === 'retry_request') {
    // no change
  } else if (kind === 'verify_proof') {
    // no change
  } else if (kind === 'return_200') {
    s.resourceServer.last_status = 200;
    s.client.pending_claim = null;
    s.client.balance -= AMOUNT;
    // validators update balance after settle
    for (const vid of Object.keys(s.validators)) {
      s.validators[vid] = {
        ...s.validators[vid]!,
        nonce_for_agent: nonce + 1,
        balance_of_agent: INITIAL_BALANCE - AMOUNT,
        phase: 'settled',
      };
    }
  }

  return s;
}

function buildSnapshots(events: SimEvent[], nonce: number, digest: string, quorumCount: number): WorldSnapshot[] {
  const snapshots: WorldSnapshot[] = [];
  let current = buildInitialSnapshot();
  for (const ev of events) {
    current = applyEvent(current, ev, nonce, digest, quorumCount);
    snapshots.push(structuredClone(current));
  }
  return snapshots;
}

export async function runSimulation(): Promise<void> {
  const store = useSimStore.getState();
  store.reset();
  store.setStatus('running');
  _eventCounter = 0;

  const allEvents: SimEvent[] = [];

  try {
    const nonce = consumeNonce();

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

    // Step 3a: build + sign claim
    const t3s = monotonic();
    const { request: claimReq, digest } = await buildClaimRequest(nonce);
    const t3mid = monotonic();
    allEvents.push(makeEvent('build_claim', 'client', null, t3s, t3mid, 3,
      'client.build_claim', { nonce, digest }));

    const t3sign = monotonic();
    allEvents.push(makeEvent('sign_claim', 'client', null, t3mid, t3sign, 3,
      `client.sign_claim (nonce=${nonce})`, { nonce }));

    // Step 3b: POST /settle
    const { result: qr, t_start_us: tSettleS, t_end_us: tSettleE } = await measureAsync(() =>
      postSettle(claimReq),
    );
    allEvents.push(makeEvent('post_settle', 'client', 'facilitator', t3sign, tSettleS, 3,
      'client.post_settle → facilitator', { sender: SENDER, nonce }));

    // Steps 4-6: synthetic intra-facilitator events
    const initialSnap = buildInitialSnapshot();
    const { events: synthEvents } = interpolateValidatorEvents(qr, tSettleS, tSettleE, initialSnap);
    allEvents.push(...synthEvents);

    // Step 7: return settlement result
    allEvents.push(makeEvent('return_result', 'facilitator', 'client', tSettleE, tSettleE + 500, 7,
      'facilitator.return_result → client', { quorum_met: qr.quorum_met, success_count: qr.success_count }));

    if (!qr.quorum_met) {
      throw new Error(`Quorum not met — only ${qr.success_count} certificates.`);
    }

    const proofHeader = buildProofHeader(qr.payment_proof!);

    // Step 8: retry GET /resource with proof
    const t8pre = tSettleE + 1000;
    const { result: res2, t_start_us: t8s, t_end_us: t8e } = await measureAsync(() =>
      getResource(proofHeader),
    );
    allEvents.push(makeEvent('retry_request', 'client', 'resource-server', t8pre, t8s, 8,
      'client.retry_request → resource-server'));

    // Steps 9-10: server verifies proof (approximated in the RTT window)
    const verifyStart = t8s;
    const verifyEnd = t8e - 500;
    allEvents.push(makeEvent('verify_proof', 'resource-server', null, verifyStart, verifyEnd, 9,
      'resource-server.verify_proof', { valid: res2.status === 200 }));

    // Step 11: return 200
    allEvents.push(makeEvent('return_200', 'resource-server', 'client', verifyEnd, t8e, 11,
      'resource-server.return_200 → client', res2.body,
      res2.status === 200 ? 'ok' : 'error'));

    // Sort all events by start time, assign final snapshots
    allEvents.sort((a, b) => a.t_start_us - b.t_start_us);
    const snapshots = buildSnapshots(allEvents, nonce, digest, qr.success_count);

    store.setEvents(allEvents, snapshots);
    store.setStatus('done');
    store.play();
  } catch (err) {
    allEvents.sort((a, b) => a.t_start_us - b.t_start_us);
    if (allEvents.length > 0) {
      const snapshots = buildSnapshots(allEvents, 0, '', 0);
      store.setEvents(allEvents, snapshots);
    }
    store.setError(err instanceof Error ? err.message : String(err));
  }
}
