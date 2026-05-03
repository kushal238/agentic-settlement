import * as ed from '@noble/ed25519';

// Fixed demo seed — NOT a secret; for classroom demo only.
// Matches genesis.json pubkey ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ
export const DEMO_SEED = new Uint8Array([
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
  17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
]);

let _cachedPubKey: Uint8Array | null = null;

export async function getPublicKey(): Promise<Uint8Array> {
  if (!_cachedPubKey) {
    _cachedPubKey = await ed.getPublicKeyAsync(DEMO_SEED);
  }
  return _cachedPubKey;
}

export async function signPayload(payload: Uint8Array): Promise<Uint8Array> {
  return ed.signAsync(payload, DEMO_SEED);
}

// In-memory nonce — must match the backend validator's account nonce.
// Reset to 0 whenever the backend is restarted with a fresh genesis.
let _nonce = 0;

export function getCurrentNonce(): number {
  return _nonce;
}

export function consumeNonce(): number {
  return _nonce++;
}

export function resetNonce(): void {
  _nonce = 0;
}
