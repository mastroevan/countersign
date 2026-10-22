"use client";

import React, { useState } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  FileText,
  FileArchive,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  UserCheck,
  Lock,
  Copy,
  Check,
  RefreshCw,
} from "lucide-react";
import { Verification, Action } from "@/types/countersign";
import { SimulatedBadge } from "./SimulatedBadge";

interface ApprovalControlsProps {
  verification: Verification;
  onRefresh: () => Promise<void>;
  onRecheck: (id: string) => Promise<void>;
  isRechecking: boolean;
}

export function ApprovalControls({
  verification,
  onRefresh,
  onRecheck,
  isRechecking,
}: ApprovalControlsProps) {
  const v = verification;
  const [approverName, setApproverName] = useState("");
  const [approverError, setApproverError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [copiedHash, setCopiedHash] = useState(false);
  const [copiedDraft, setCopiedDraft] = useState(false);

  const isDisputed = v.result?.verdict === "DISPUTED";
  const isProvisional = isDisputed && v.recheck_state !== "done";
  const isSynthetic = v.synthetic || v.simulate;

  // Record human approval/rejection
  const handleRecordApproval = async (action: Action, approved: boolean) => {
    if (!approverName.trim()) {
      setApproverError("Approver name is required to record authorization.");
      return;
    }
    setApproverError("");
    setActionError(null);
    setIsSubmitting(`approval-${action}`);

    try {
      const res = await fetch(`/verifications/${v.id}/approvals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          approved,
          approver: approverName.trim(),
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Approval failed with status ${res.status}`);
      }

      await onRefresh();
    } catch (err: any) {
      setActionError(err.message || "Failed to record approval");
    } finally {
      setIsSubmitting(null);
    }
  };

  // Generate Claim Draft
  const handleGenerateClaimDraft = async () => {
    setActionError(null);
    setIsSubmitting("claim-draft");
    try {
      const res = await fetch(`/verifications/${v.id}/claim-draft`, {
        method: "POST",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail?.error || data.detail || `Failed to generate draft: ${res.status}`);
      }
      await onRefresh();
    } catch (err: any) {
      setActionError(err.message);
    } finally {
      setIsSubmitting(null);
    }
  };

  // Generate Evidence Packet
  const handleGenerateEvidencePacket = async () => {
    setActionError(null);
    setIsSubmitting("evidence-packet");
    try {
      const res = await fetch(`/verifications/${v.id}/evidence-packet`, {
        method: "POST",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail?.error || data.detail || `Failed to create packet: ${res.status}`);
      }
      await onRefresh();
    } catch (err: any) {
      setActionError(err.message);
    } finally {
      setIsSubmitting(null);
    }
  };

  const claimApproval = v.approvals?.claim_draft;
  const packetApproval = v.approvals?.evidence_packet;

  return (
    <div className="bg-slate-900/90 rounded-xl border border-slate-800 p-5 space-y-6 shadow-xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-amber-400" />
            <h3 className="text-base font-bold text-white">
              Human-in-the-Loop Approval Gate
            </h3>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Strict safety requirement: claims and packets require explicit human authorization
          </p>
        </div>

        {isSynthetic && <SimulatedBadge />}
      </div>

      {/* Synthetic Warning */}
      {isSynthetic && (
        <div className="p-3.5 rounded-xl bg-purple-950/40 border border-purple-800/80 text-xs text-purple-200 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-purple-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-purple-300">
              Synthetic Evidence Policy Gate Active
            </p>
            <p className="text-purple-300/80 leading-relaxed">
              This verification was produced using synthetic/simulated frames. Per security policy,
              simulated evidence can never back an insurance claim or export an S3 evidence packet. Actions are disabled.
            </p>
          </div>
        </div>
      )}

      {/* Provisional DISPUTED Warning & Recheck Countdown */}
      {isDisputed && isProvisional && (
        <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-800/80 text-xs text-amber-200 space-y-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-1 flex-1">
              <p className="font-semibold text-amber-300 text-sm">
                Provisional DISPUTED Verdict — Re-check Pending
              </p>
              <p className="text-amber-200/90 leading-relaxed">
                Carrier scans sometimes precede parcel placement by several minutes. To prevent false disputes,
                claims and packets are held until a re-check is completed.
              </p>
              {v.recheck_due_at && (
                <div className="flex items-center gap-1.5 font-mono text-amber-400 pt-1">
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                  <span>Scheduled re-check due at: {new Date(v.recheck_due_at).toLocaleTimeString()}</span>
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center justify-end">
            <button
              type="button"
              onClick={() => onRecheck(v.id)}
              disabled={isRechecking}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors shadow-md disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRechecking ? "animate-spin" : ""}`} />
              <span>{isRechecking ? "Re-checking door now..." : "Run Re-check Now"}</span>
            </button>
          </div>
        </div>
      )}

      {/* Error Message */}
      {actionError && (
        <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-xs text-rose-300 flex items-center justify-between">
          <span>{actionError}</span>
          <button type="button" onClick={() => setActionError(null)} className="text-rose-400 hover:text-white">
            Dismiss
          </button>
        </div>
      )}

      {/* Approver Identity Input */}
      <div className="rounded-xl bg-slate-950/60 border border-slate-800 p-4 space-y-3">
        <label className="block space-y-1">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
            <span className="flex items-center gap-1.5">
              <UserCheck className="w-3.5 h-3.5 text-amber-400" />
              <span>Authorizing Human Approver Name</span>
            </span>
            <span className="text-[11px] text-slate-500 font-normal">Required for audit log</span>
          </div>
          <input
            type="text"
            value={approverName}
            onChange={(e) => {
              setApproverName(e.target.value);
              if (e.target.value.trim()) setApproverError("");
            }}
            placeholder="e.g. Evan Mastro (Door Supervisor)"
            disabled={isSynthetic}
            className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors disabled:opacity-50 font-mono"
          />
        </label>
        {approverError && (
          <p className="text-[11px] text-rose-400 font-medium">{approverError}</p>
        )}
      </div>

      {/* Action 1: Claim Draft */}
      <div className="rounded-xl bg-slate-950/40 border border-slate-800 p-4 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/60 pb-3">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-blue-400" />
            <div>
              <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                1. Merchant / Carrier Claim Draft
              </h4>
              <p className="text-[11px] text-slate-400">
                Formal dispute document with carrier timeline and timestamped camera observations
              </p>
            </div>
          </div>

          {/* Status badge */}
          <div>
            {claimApproval ? (
              claimApproval.approved ? (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  <span>Approved by {claimApproval.approver}</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950 text-rose-300 border border-rose-800">
                  <XCircle className="w-3 h-3 text-rose-400" />
                  <span>Rejected by {claimApproval.approver}</span>
                </span>
              )
            ) : (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400">
                <span>Not Approved</span>
              </span>
            )}
          </div>
        </div>

        {/* Buttons */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => handleRecordApproval("claim_draft", true)}
            disabled={isSynthetic || isProvisional || !isDisputed || isSubmitting !== null}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-40 disabled:hover:bg-emerald-600"
          >
            {isSubmitting === "approval-claim_draft" ? "Recording..." : "Approve Claim Draft"}
          </button>
          <button
            type="button"
            onClick={() => handleRecordApproval("claim_draft", false)}
            disabled={isSynthetic || isProvisional || !isDisputed || isSubmitting !== null}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-rose-950 text-slate-300 hover:text-rose-300 border border-slate-700 hover:border-rose-800 transition-colors disabled:opacity-40"
          >
            Reject
          </button>

          {claimApproval?.approved && (
            <button
              type="button"
              onClick={handleGenerateClaimDraft}
              disabled={isSubmitting !== null}
              className="ml-auto px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              {isSubmitting === "claim-draft" ? "Generating..." : "Generate Claim Draft Text"}
            </button>
          )}
        </div>

        {/* Claim Draft Output */}
        {v.claim_draft && (
          <div className="mt-3 p-3.5 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-300">Generated Claim Draft:</span>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(v.claim_draft?.draft_text || "");
                  setCopiedDraft(true);
                  setTimeout(() => setCopiedDraft(false), 2000);
                }}
                className="flex items-center gap-1 text-[11px] text-amber-400 hover:text-amber-300"
              >
                {copiedDraft ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>{copiedDraft ? "Copied" : "Copy Draft"}</span>
              </button>
            </div>
            <pre className="font-mono text-xs text-slate-300 whitespace-pre-wrap leading-relaxed bg-slate-950 p-3 rounded border border-slate-800 max-h-48 overflow-y-auto">
              {v.claim_draft.draft_text}
            </pre>
            <p className="text-[11px] text-slate-500 italic">
              * Notice: Countersign never automatically sends claims. An authorized human must review and submit to merchant.
            </p>
          </div>
        )}
      </div>

      {/* Action 2: S3 Evidence Packet */}
      <div className="rounded-xl bg-slate-950/40 border border-slate-800 p-4 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/60 pb-3">
          <div className="flex items-center gap-2">
            <FileArchive className="w-4 h-4 text-purple-400" />
            <div>
              <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                2. Cryptographic S3 Evidence Packet
              </h4>
              <p className="text-[11px] text-slate-400">
                Audit bundle containing raw Ring frames, policy trace log, and SHA-256 integrity hash
              </p>
            </div>
          </div>

          {/* Status badge */}
          <div>
            {packetApproval ? (
              packetApproval.approved ? (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  <span>Approved by {packetApproval.approver}</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950 text-rose-300 border border-rose-800">
                  <XCircle className="w-3 h-3 text-rose-400" />
                  <span>Rejected by {packetApproval.approver}</span>
                </span>
              )
            ) : (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400">
                <span>Not Approved</span>
              </span>
            )}
          </div>
        </div>

        {/* Buttons */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => handleRecordApproval("evidence_packet", true)}
            disabled={isSynthetic || isProvisional || isSubmitting !== null}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-40 disabled:hover:bg-emerald-600"
          >
            {isSubmitting === "approval-evidence_packet" ? "Recording..." : "Approve Evidence Packet"}
          </button>
          <button
            type="button"
            onClick={() => handleRecordApproval("evidence_packet", false)}
            disabled={isSynthetic || isProvisional || isSubmitting !== null}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-rose-950 text-slate-300 hover:text-rose-300 border border-slate-700 hover:border-rose-800 transition-colors disabled:opacity-40"
          >
            Reject
          </button>

          {packetApproval?.approved && (
            <button
              type="button"
              onClick={handleGenerateEvidencePacket}
              disabled={isSubmitting !== null}
              className="ml-auto px-3 py-1.5 rounded-lg text-xs font-semibold bg-purple-600 hover:bg-purple-500 text-white transition-colors disabled:opacity-50"
            >
              {isSubmitting === "evidence-packet" ? "Packaging..." : "Build S3 Packet"}
            </button>
          )}
        </div>

        {/* Packet Location and SHA-256 Output */}
        {v.evidence_location && v.evidence_sha256 && (
          <div className="mt-3 p-3.5 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-300">Evidence Packet Built:</span>
              <span className="font-mono text-[11px] text-emerald-400">Status: Stored in S3</span>
            </div>
            <div className="space-y-1.5 font-mono text-xs">
              <div className="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
                <span className="text-slate-400 text-[11px]">Location:</span>
                <span className="text-slate-200 truncate ml-2" title={v.evidence_location}>
                  {v.evidence_location}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
                <span className="text-slate-400 text-[11px]">SHA-256:</span>
                <div className="flex items-center gap-2">
                  <span className="text-amber-300 text-[11px] font-bold truncate max-w-[260px]" title={v.evidence_sha256}>
                    {v.evidence_sha256}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      navigator.clipboard.writeText(v.evidence_sha256 || "");
                      setCopiedHash(true);
                      setTimeout(() => setCopiedHash(false), 2000);
                    }}
                    className="p-1 hover:bg-slate-800 rounded text-slate-400 hover:text-white"
                    title="Copy SHA-256"
                  >
                    {copiedHash ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
