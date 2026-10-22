export type Verdict = "VERIFIED" | "DISPUTED" | "INCONCLUSIVE";
export type Status = "pending" | "complete" | "failed";
export type RecheckState = "none" | "scheduled" | "done";
export type Action = "claim_draft" | "evidence_packet";

export interface Approval {
  approved: boolean;
  approver: string;
  at: string;
}

export interface FrameEvidence {
  frame_id: string;
  source: string;
  captured_at: string;
  error: string | null;
  watermark_skew_seconds: number | null;
  watermark_discarded: boolean;
  parcel_visible: boolean | null;
  confidence: number | null;
  location: string | null;
  watermark_ts: string | null;
}

export interface VerificationResult {
  verdict: Verdict;
  reason: string;
  requires_approval: boolean;
  synthetic: boolean;
  positive_frames: number;
  negative_frames: number;
  confidence: number;
  considered_frames: number;
  excluded_synthetic: number;
  unusable_timestamps: number;
  delivered_at: string;
  device_id: string;
  frames_requested: number;
  partial_capture: boolean;
  evidence: FrameEvidence[];
}

export interface ClaimDraft {
  draft_text: string;
  recipient_email?: string;
  tracking_code?: string;
  [key: string]: unknown;
}

export interface Verification {
  id: string;
  source: string;
  status: Status;
  created_at: string;
  delivered_at: string;
  tracking_code: string | null;
  tracker_id: string | null;
  event_id: string | null;
  simulate: boolean;
  synthetic: boolean;
  error: string | null;
  result: VerificationResult | null;
  requires_approval: boolean;
  approvals: Record<string, Approval>;
  claim_draft: ClaimDraft | null;
  evidence_location: string | null;
  evidence_sha256: string | null;
  checked_at: string | null;
  recheck_state: RecheckState;
  recheck_due_at: string | null;
  recheck_error: string | null;
  runs: number;
}

export interface TraceEvent {
  seq: number;
  ts: string;
  verification_id: string | null;
  stage: string;
  status: "started" | "ok" | "error" | "info" | string;
  data: Record<string, any>;
}

export interface MCPReportEvidence {
  frame_url: string;
  frame_id: string;
  watermark_time: string | null;
  parcel_visible: boolean | null;
  location: string | null;
  source: string;
  error: string | null;
}

export interface MCPDeliveryReport {
  verification_id?: string;
  tracking_code: string | null;
  status: "VERIFIED" | "DISPUTED" | "INCONCLUSIVE" | "PENDING";
  carrier_scan_at: string | null;
  checked_at: string | null;
  confidence: number | null;
  reason: string;
  synthetic?: boolean;
  requires_approval?: boolean;
  recheck?: {
    state: RecheckState;
    due_at: string | null;
    provisional: boolean;
  };
  evidence?: MCPReportEvidence[];
}
