import type { ClaimRequest } from './types';
import type { ClaimOverride } from '../sim/scenarios';
import { b64urlEncode } from './b64';
import { getPublicKey, signPayload } from './wallet';

export const SENDER = 'agent-1';
export const RECIPIENT = 'server-recipient';
export const AMOUNT = 10;

export function buildPayload(
  sender: string,
  recipient: string,
  amount: number,
  nonce: number,
): Uint8Array {
  const parts = [sender, recipient, String(amount), String(nonce)];
  const joined = parts.map((p) => `${p.length}:${p}`).join('|');
  return new TextEncoder().encode(joined);
}

export async function buildClaimRequest(
  nonce: number,
  overrides?: ClaimOverride,
): Promise<{
  request: ClaimRequest;
  payload: Uint8Array;
  digest: string;
  effectiveAmount: number;
  effectiveRecipient: string;
  effectiveNonce: number;
}> {
  const effectiveNonce = overrides?.forceNonce ?? nonce;
  const effectiveAmount = overrides?.amount ?? AMOUNT;
  const effectiveRecipient = overrides?.recipient ?? RECIPIENT;

  const payload = buildPayload(SENDER, effectiveRecipient, effectiveAmount, effectiveNonce);
  const [sig, pubKey] = await Promise.all([signPayload(payload), getPublicKey()]);

  // Short hex digest for display
  const hashBuf = await crypto.subtle.digest('SHA-256', payload.buffer.slice(payload.byteOffset, payload.byteOffset + payload.byteLength) as ArrayBuffer);
  const hashArr = new Uint8Array(hashBuf);
  const digest = Array.from(hashArr.slice(0, 8))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');

  return {
    request: {
      sender: SENDER,
      recipient: effectiveRecipient,
      amount: effectiveAmount,
      nonce: effectiveNonce,
      sender_pubkey: b64urlEncode(pubKey),
      signature: b64urlEncode(sig),
    },
    payload,
    digest,
    effectiveAmount,
    effectiveRecipient,
    effectiveNonce,
  };
}
