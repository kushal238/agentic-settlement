export interface ClaimRequest {
  sender: string;
  recipient: string;
  amount: number;
  nonce: number;
  sender_pubkey: string;
  signature: string;
}

export interface CertificateOut {
  validator_id: string;
  validator_signature: string;
  validator_pubkey: string;
}

export interface PaymentProofOut {
  claim: ClaimRequest;
  claim_digest: string;
  success_count: number;
  quorum_threshold: number;
  certificates: Record<string, CertificateOut>;
}

export interface FaultEventOut {
  kind: string;
  validator_id: string;
  detail: string;
}

export interface QuorumResult {
  quorum_met: boolean;
  success_count: number;
  certificates: Record<string, CertificateOut>;
  rejections: Record<string, string>;
  dead: string[];
  faults: FaultEventOut[];
  payment_proof: PaymentProofOut | null;
}

export interface PaymentRequirements {
  recipient: string;
  amount: number;
  instructions: string;
}
