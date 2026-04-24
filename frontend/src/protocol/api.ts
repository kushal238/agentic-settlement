import type { ClaimRequest, QuorumResult } from './types';

const API_BASE = 'http://localhost:8000';
const FACILITATOR_BASE = 'http://localhost:8001';

export interface RawResponse {
  status: number;
  body: unknown;
  headers: Record<string, string>;
}

export async function getResource(proofHeader?: string): Promise<RawResponse> {
  const headers: Record<string, string> = {};
  if (proofHeader) headers['X-Payment-Proof'] = proofHeader;

  const res = await fetch(`${API_BASE}/resource`, { headers });
  const body = await res.json();
  const hdrs: Record<string, string> = {};
  res.headers.forEach((v, k) => {
    hdrs[k] = v;
  });
  return { status: res.status, body, headers: hdrs };
}

export async function postSettle(req: ClaimRequest): Promise<QuorumResult> {
  const res = await fetch(`${FACILITATOR_BASE}/settle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST /settle failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<QuorumResult>;
}

export async function getFaultState(): Promise<Record<string, boolean>> {
  const res = await fetch(`${FACILITATOR_BASE}/debug/fault`);
  if (!res.ok) return {};
  return res.json() as Promise<Record<string, boolean>>;
}

export async function setFault(validatorId: string, faulty: boolean): Promise<void> {
  const method = faulty ? 'POST' : 'DELETE';
  await fetch(`${FACILITATOR_BASE}/debug/fault/${validatorId}`, { method });
}
