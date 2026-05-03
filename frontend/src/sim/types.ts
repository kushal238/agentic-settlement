export type ActorId =
  | 'client'
  | 'resource-server'
  | 'facilitator'
  | 'validator-0'
  | 'validator-1'
  | 'validator-2'
  | 'validator-3'
  | 'validator-4'
  | 'validator-5'
  | 'validator-6'
  | 'validator-7'
  | 'validator-8'
  | 'validator-9'
  | 'validator-10'
  | 'validator-11'
  | 'validator-12'
  | 'validator-13'
  | 'validator-14'
  | 'validator-15';

export type ValidatorPhase =
  | 'idle'
  | 'verifying'
  | 'certified'
  | 'rejected'
  | 'settling'
  | 'settled'
  | 'dead'
  /** Quorum was met but this validator did not certify — state has diverged from the settled majority */
  | 'divergent';

export type ProtocolStep = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11;

export interface SimEvent {
  id: string;
  t_start_us: number;
  t_end_us: number;
  step: ProtocolStep;
  kind: string;
  from: ActorId;
  to: ActorId | null;
  label: string;
  payload?: unknown;
  outcome?: 'ok' | 'error' | 'timeout';
}

export interface ClientSnapshot {
  nonce: number;
  balance: number;
  pending_claim: string | null;
  last_proof_quorum: number | null;
}

export interface ResourceServerSnapshot {
  recipient: string;
  required_amount: number;
  last_status: 402 | 200 | null;
  payload_hash: string | null;
}

export interface FacilitatorSnapshot {
  f: number;
  quorum_threshold: number;
  certificates_collected: number;
  phase: 'idle' | 'collecting' | 'evaluating' | 'settled' | 'failed';
}

export interface ValidatorSnapshot {
  validator_id: string;
  nonce_for_agent: number | null;
  balance_of_agent: number | null;
  phase: ValidatorPhase;
}

export interface WorldSnapshot {
  client: ClientSnapshot;
  resourceServer: ResourceServerSnapshot;
  facilitator: FacilitatorSnapshot;
  validators: Record<string, ValidatorSnapshot>;
}
