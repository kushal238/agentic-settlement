export type ScenarioId = 'happy' | 'replay' | 'balance' | 'recipient';

export interface ClaimOverride {
  amount?: number;
  recipient?: string;
  forceNonce?: number;
}

export interface Scenario {
  id: ScenarioId;
  label: string;
  description: string;
  claimOverride?: ClaimOverride;
  /** Which validator check is expected to fail for educational labelling */
  failedCheck?: 'check_replay' | 'check_balance' | 'check_sanity';
}

export const SCENARIOS: Scenario[] = [
  {
    id: 'happy',
    label: 'Happy Path',
    description: 'Normal successful settlement — all checks pass',
  },
  {
    id: 'replay',
    label: 'Replay Attack',
    description: 'Reuse a consumed nonce — nonce (replay) check fails on all validators',
    claimOverride: { forceNonce: 99999 },
    failedCheck: 'check_replay',
  },
  {
    id: 'balance',
    label: 'Insufficient Balance',
    description: 'Claim amount exceeds sender balance — balance check fails on all validators',
    claimOverride: { amount: 99999 },
    failedCheck: 'check_balance',
  },
  {
    id: 'recipient',
    label: 'Invalid Recipient',
    description: "Recipient account doesn't exist — sanity check fails on all validators",
    claimOverride: { recipient: 'nonexistent-user-404' },
    failedCheck: 'check_sanity',
  },
];

export function getScenario(id: ScenarioId): Scenario {
  return SCENARIOS.find((s) => s.id === id) ?? SCENARIOS[0]!;
}
