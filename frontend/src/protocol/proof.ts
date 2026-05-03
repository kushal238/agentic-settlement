import type { PaymentProofOut } from './types';
import { b64urlEncode } from './b64';

export function buildProofHeader(proof: PaymentProofOut): string {
  const json = JSON.stringify(proof);
  return b64urlEncode(new TextEncoder().encode(json));
}
