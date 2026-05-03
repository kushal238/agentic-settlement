/**
 * Generates genesis.json for the backend from the fixed demo keypair.
 * Run with: npm run gen-genesis
 * Copy the output to genesis.json in the project root.
 */
import * as ed from '@noble/ed25519';
import { sha512 } from '@noble/hashes/sha512';

// Configure sync sha512 for noble-ed25519 (Node.js environment)
ed.etc.sha512Sync = (...m) =>
  sha512(m.reduce((a, b) => {
    const c = new Uint8Array(a.length + b.length);
    c.set(a);
    c.set(b, a.length);
    return c;
  }, new Uint8Array(0)));

const DEMO_SEED = new Uint8Array([
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
  17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
]);

function b64urlEncode(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64url');
}

const pubKey = ed.getPublicKey(DEMO_SEED);
const pubKeyB64 = b64urlEncode(pubKey);

const genesis = [
  { account_id: 'agent-1', pubkey_b64: pubKeyB64, balance: 10000 },
  { account_id: 'server-recipient', pubkey_b64: pubKeyB64, balance: 0 },
];

console.log(JSON.stringify(genesis, null, 2));
