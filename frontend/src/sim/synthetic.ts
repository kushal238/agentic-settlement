import type { SimEvent, ActorId, WorldSnapshot, ValidatorPhase } from './types';
import type { QuorumResult } from '../protocol/types';

// Timing constants as fractions of W = t1_us - t0_us
// Fan-out is truly concurrent (ThreadPoolExecutor in facilitator.py),
// so stride is near-zero — just network jitter between dispatches.
export const FANOUT_STRIDE_FRAC = 0.005;
export const FANOUT_JITTER_FRAC = 0.008;
export const PROC_LOGNORMAL_MU_FRAC = 0.40;
export const PROC_SIGMA = 0.20;
export const PROC_MIN_FRAC = 0.10;
export const PROC_MAX_FRAC = 0.85;
export const EVALUATE_OFFSET_FRAC = 0.02;
export const SETTLE_START_OFFSET_FRAC = 0.01;
export const SETTLE_STRIDE_FRAC = 0.005;

// Minimal seeded LCG for deterministic synthetic timing.
class LCG {
  private s: number;
  constructor(seed: number) {
    this.s = (seed ^ 0xdeadbeef) >>> 0;
  }
  next(): number {
    this.s = Math.imul(this.s, 1664525) + 1013904223;
    this.s >>>= 0;
    return this.s / 4294967296;
  }
}

function lognormalSample(rng: LCG, mu: number, sigma: number): number {
  const u1 = Math.max(1e-10, rng.next());
  const u2 = rng.next();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return Math.exp(mu + sigma * z);
}

function seedFromResult(result: QuorumResult): number {
  const str = `${result.success_count}:${result.dead.join(',')}:${Object.keys(result.certificates).sort().join(',')}`;
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(31, h) + str.charCodeAt(i);
    h >>>= 0;
  }
  return h;
}

let _idCounter = 0;
function nextId(): string {
  return `synth-${_idCounter++}`;
}

/**
 * Derive all validator IDs involved in this round from the QuorumResult.
 * Covers certified, rejected, and dead validators — works for any n=3f+1.
 */
function validatorIdsFromResult(result: QuorumResult): string[] {
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const vid of [
    ...Object.keys(result.certificates),
    ...Object.keys(result.rejections),
    ...result.dead,
  ]) {
    if (!seen.has(vid)) {
      seen.add(vid);
      ids.push(vid);
    }
  }
  // Sort by numeric index for stable ordering
  ids.sort((a, b) => {
    const ai = parseInt(a.replace('validator-', ''));
    const bi = parseInt(b.replace('validator-', ''));
    return ai - bi;
  });
  return ids;
}

export function interpolateValidatorEvents(
  result: QuorumResult,
  t0_us: number,
  t1_us: number,
  initialSnapshot: WorldSnapshot,
): { events: SimEvent[]; finalSnapshot: WorldSnapshot } {
  const W = t1_us - t0_us;
  const rng = new LCG(seedFromResult(result));
  const events: SimEvent[] = [];

  const validatorIds = validatorIdsFromResult(result);
  const checks = ['check_signature', 'check_identity', 'check_sanity', 'check_replay', 'check_balance'];

  // Per-validator timing
  const vTimes: Record<string, { fanoutStart: number; procEnd: number; outcome: 'certified' | 'rejected' | 'timeout' }> = {};
  let maxProcEnd = t0_us;

  for (let i = 0; i < validatorIds.length; i++) {
    const vid = validatorIds[i]!;
    const fanoutStart = t0_us + i * FANOUT_STRIDE_FRAC * W + rng.next() * FANOUT_JITTER_FRAC * W;

    let outcome: 'certified' | 'rejected' | 'timeout';
    if (result.certificates[vid]) {
      outcome = 'certified';
    } else if (result.rejections[vid]) {
      outcome = 'rejected';
    } else {
      outcome = 'timeout';
    }

    let procEnd: number;
    if (outcome === 'timeout') {
      procEnd = t1_us - 0.01 * W;
    } else {
      const mu = Math.log(PROC_LOGNORMAL_MU_FRAC * W);
      const raw = lognormalSample(rng, mu, PROC_SIGMA);
      const clamped = Math.min(Math.max(raw, PROC_MIN_FRAC * W), PROC_MAX_FRAC * W);
      procEnd = fanoutStart + clamped;
    }

    vTimes[vid] = { fanoutStart, procEnd, outcome };
    if (procEnd > maxProcEnd) maxProcEnd = procEnd;

    // Fan-out event: facilitator → validator-i
    events.push({
      id: nextId(),
      t_start_us: fanoutStart,
      t_end_us: fanoutStart + 0.005 * W,
      step: 4,
      kind: `fanout_validator_${i}`,
      from: 'facilitator',
      to: vid as ActorId,
      label: `facilitator.fanout → ${vid}`,
      outcome: 'ok',
    });

    // 5 equal sub-checks within [fanoutStart, procEnd]
    const checkDuration = (procEnd - fanoutStart - 0.005 * W) / checks.length;
    for (let ci = 0; ci < checks.length; ci++) {
      const cs = fanoutStart + 0.005 * W + ci * checkDuration;
      events.push({
        id: nextId(),
        t_start_us: cs,
        t_end_us: cs + checkDuration,
        step: 4,
        kind: `${checks[ci]}_${i}`,
        from: vid as ActorId,
        to: null,
        label: `${vid}.${checks[ci]}`,
        outcome: 'ok',
      });
    }

    // Certificate / rejection / timeout event: validator-i → facilitator
    const certKind = outcome === 'certified' ? `certificate_${i}` : outcome === 'rejected' ? `rejection_${i}` : `timeout_${i}`;
    const certOutcome = outcome === 'certified' ? 'ok' : outcome === 'timeout' ? 'timeout' : 'error';
    events.push({
      id: nextId(),
      t_start_us: procEnd,
      t_end_us: procEnd + 0.005 * W,
      step: 5,
      kind: certKind,
      from: vid as ActorId,
      to: 'facilitator',
      label: `${vid}.${certKind.replace(`_${i}`, '')} → facilitator`,
      payload: outcome === 'certified' ? result.certificates[vid] : outcome === 'rejected' ? { reason: result.rejections[vid] } : { reason: 'timeout' },
      outcome: certOutcome,
    });
  }

  // evaluate_round: facilitator decides quorum
  const evalStart = maxProcEnd + EVALUATE_OFFSET_FRAC * W;
  events.push({
    id: nextId(),
    t_start_us: evalStart,
    t_end_us: evalStart + 0.02 * W,
    step: 5,
    kind: 'evaluate_round',
    from: 'facilitator',
    to: null,
    label: 'facilitator.evaluate_round',
    payload: { success_count: result.success_count, quorum_met: result.quorum_met },
    outcome: result.quorum_met ? 'ok' : 'error',
  });

  const quorumEventEnd = evalStart + 0.02 * W;
  events.push({
    id: nextId(),
    t_start_us: quorumEventEnd,
    t_end_us: quorumEventEnd + 0.01 * W,
    step: 5,
    kind: result.quorum_met ? 'quorum_met' : 'quorum_failed',
    from: 'facilitator',
    to: null,
    label: result.quorum_met ? 'facilitator.quorum_met' : 'facilitator.quorum_failed',
    payload: { success_count: result.success_count },
    outcome: result.quorum_met ? 'ok' : 'error',
  });

  // settle events — only for certified validators
  if (result.quorum_met) {
    const settleBase = quorumEventEnd + SETTLE_START_OFFSET_FRAC * W;
    const certified = Object.keys(result.certificates);
    certified.forEach((vid, idx) => {
      const i = validatorIds.indexOf(vid);
      events.push({
        id: nextId(),
        t_start_us: settleBase + idx * SETTLE_STRIDE_FRAC * W,
        t_end_us: settleBase + idx * SETTLE_STRIDE_FRAC * W + 0.01 * W,
        step: 6,
        kind: `settle_${i}`,
        from: 'facilitator',
        to: vid as ActorId,
        label: `facilitator.settle → ${vid}`,
        outcome: 'ok',
      });
    });

    // divergent marker events — non-certifying validators when quorum IS met
    // These fire after quorum so the UI shows state divergence prominently
    const divergentBase = quorumEventEnd + SETTLE_START_OFFSET_FRAC * W + 0.005 * W;
    for (const vid of validatorIds) {
      if (!result.certificates[vid]) {
        const i = validatorIds.indexOf(vid);
        events.push({
          id: nextId(),
          t_start_us: divergentBase,
          t_end_us: divergentBase + 0.01 * W,
          step: 6,
          kind: `divergent_${i}`,
          from: 'facilitator',
          to: null,
          label: `${vid} — state divergent (did not settle)`,
          payload: {
            validator_id: vid,
            reason: result.rejections[vid] ?? (result.dead.includes(vid) ? 'timeout' : 'unknown'),
          },
          outcome: 'error',
        });
      }
    }
  }

  events.sort((a, b) => a.t_start_us - b.t_start_us);

  // Build final snapshot by applying phase transitions
  const snap = structuredClone(initialSnapshot);

  for (const vid of validatorIds) {
    const vt = vTimes[vid];
    if (!vt) continue;

    let phase: ValidatorPhase;
    if (vt.outcome === 'certified') {
      phase = result.quorum_met ? 'settled' : 'certified';
    } else if (result.quorum_met) {
      // Quorum was met but this validator didn't certify — its state has diverged
      phase = 'divergent';
    } else {
      phase = vt.outcome === 'rejected' ? 'rejected' : 'dead';
    }

    snap.validators[vid] = {
      ...snap.validators[vid]!,
      phase,
    };
  }

  if (result.quorum_met) {
    snap.facilitator = {
      ...snap.facilitator,
      certificates_collected: result.success_count,
      phase: 'settled',
    };
  } else {
    snap.facilitator = {
      ...snap.facilitator,
      certificates_collected: result.success_count,
      phase: 'failed',
    };
  }

  return { events, finalSnapshot: snap };
}
