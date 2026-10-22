"use client";

import React from "react";
import {
  Package,
  Clock,
  Video,
  FileCheck2,
  FileX2,
  HelpCircle,
  Code2,
  Shield,
  ArrowRight,
  ExternalLink,
} from "lucide-react";
import { Verification } from "@/types/countersign";
import { SimulatedBadge } from "./SimulatedBadge";

interface CarrierTimelineProps {
  verification: Verification;
  onOpenWebhookDrawer?: () => void;
  hasWebhookPayload?: boolean;
}

export function CarrierTimeline({
  verification,
  onOpenWebhookDrawer,
  hasWebhookPayload,
}: CarrierTimelineProps) {
  const v = verification;
  const res = v.result;

  const formatDateTime = (iso: string) => {
    try {
      const dt = new Date(iso);
      return {
        time: dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        date: dt.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }),
      };
    } catch {
      return { time: iso, date: "" };
    }
  };

  const carrierScan = formatDateTime(v.delivered_at);
  const createdScan = formatDateTime(v.created_at);
  const checkedScan = v.checked_at ? formatDateTime(v.checked_at) : null;

  return (
    <div className="bg-slate-900/90 rounded-xl border border-slate-800 p-5 space-y-6 flex flex-col justify-between">
      <div className="space-y-6">
        {/* Header & Badges */}
        <div className="flex items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Independent Carrier Audit
              </span>
              {v.synthetic && <SimulatedBadge />}
            </div>
            <h3 className="text-lg font-bold text-white mt-0.5 flex items-center gap-2 font-mono">
              {v.tracking_code || "No tracking code"}
            </h3>
          </div>

          {hasWebhookPayload && onOpenWebhookDrawer && (
            <button
              type="button"
              onClick={onOpenWebhookDrawer}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
              title="Inspect raw webhook JSON payload"
            >
              <Code2 className="w-3.5 h-3.5 text-amber-400" />
              <span>Raw Webhook JSON</span>
            </button>
          )}
        </div>

        {/* Carrier Claim vs Doorbell Witness summary box */}
        <div className="rounded-xl bg-slate-950/70 border border-slate-800 p-4 space-y-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
            <span>Reconciliation Summary</span>
            <span className="text-[11px] font-mono text-slate-500">
              Rule: {res?.verdict ? (res as any).rule || "policy.decide" : "pending"}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            {/* Carrier Column (Note: Generic neutral label, no carrier trademarks) */}
            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between text-slate-400 font-medium">
                <span className="flex items-center gap-1.5">
                  <Package className="w-3.5 h-3.5 text-blue-400" />
                  <span>Carrier Scan Claim</span>
                </span>
                <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-950 text-blue-300 font-mono">
                  Delivered
                </span>
              </div>
              <p className="text-sm font-semibold text-white font-mono">
                {carrierScan.time}
              </p>
              <p className="text-[11px] text-slate-400">
                Carrier marked parcel as delivered at the door.
              </p>
            </div>

            {/* Doorbell Camera Column */}
            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between text-slate-400 font-medium">
                <span className="flex items-center gap-1.5">
                  <Video className="w-3.5 h-3.5 text-amber-400" />
                  <span>Doorbell Camera Witness</span>
                </span>
                <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-950 text-amber-300 font-mono">
                  {res?.verdict ?? "Observing"}
                </span>
              </div>
              <p className="text-sm font-semibold text-white font-mono">
                {checkedScan ? checkedScan.time : "In progress..."}
              </p>
              <p className="text-[11px] text-slate-400">
                {res?.verdict === "VERIFIED" && "Parcel confirmed on the step after scan."}
                {res?.verdict === "DISPUTED" && "Camera observed step: no parcel visible."}
                {res?.verdict === "INCONCLUSIVE" && "Camera step view obstructed or unavailable."}
                {(!res || v.status === "pending") && "Sampling live view frames..."}
              </p>
            </div>
          </div>

          {/* Verdict Banner */}
          {res && (
            <div
              className={`p-3 rounded-lg border flex items-start gap-3 ${
                res.verdict === "VERIFIED"
                  ? "bg-emerald-950/40 border-emerald-800 text-emerald-200"
                  : res.verdict === "DISPUTED"
                  ? "bg-rose-950/40 border-rose-800 text-rose-200"
                  : "bg-amber-950/40 border-amber-800 text-amber-200"
              }`}
            >
              {res.verdict === "VERIFIED" && <FileCheck2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />}
              {res.verdict === "DISPUTED" && <FileX2 className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />}
              {res.verdict === "INCONCLUSIVE" && <HelpCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />}

              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm tracking-wide">
                    Verdict: {res.verdict}
                  </span>
                  {res.confidence !== undefined && (
                    <span className="text-xs font-mono opacity-80">
                      ({Math.round(res.confidence * 100)}% confidence)
                    </span>
                  )}
                </div>
                <p className="text-xs leading-relaxed opacity-90">
                  {res.verdict === "INCONCLUSIVE"
                    ? "I can't see the step clearly. Please check. (" + res.reason + ")"
                    : res.reason}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Vertical timeline */}
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Event Audit Timeline
          </h4>

          <div className="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
            {/* Event 1: Webhook Received */}
            <div className="relative group">
              <span className="absolute -left-6 top-1 w-2.5 h-2.5 rounded-full bg-blue-500 border-2 border-slate-900" />
              <div className="space-y-0.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-200">Carrier Webhook Received</span>
                  <span className="font-mono text-slate-500 text-[11px]">{createdScan.time}</span>
                </div>
                <p className="text-xs text-slate-400">
                  Source: <span className="font-mono text-slate-300">{v.source}</span>
                  {v.tracker_id && <span className="ml-2 font-mono text-slate-500">({v.tracker_id})</span>}
                </p>
              </div>
            </div>

            {/* Event 2: Carrier scan timestamp */}
            <div className="relative group">
              <span className="absolute -left-6 top-1 w-2.5 h-2.5 rounded-full bg-amber-500 border-2 border-slate-900" />
              <div className="space-y-0.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-200">Carrier Marked Delivered</span>
                  <span className="font-mono text-slate-500 text-[11px]">{carrierScan.time}</span>
                </div>
                <p className="text-xs text-slate-400 font-mono">
                  {carrierScan.date} — Carrier claimed delivery complete.
                </p>
              </div>
            </div>

            {/* Event 3: Verification Pipeline */}
            <div className="relative group">
              <span
                className={`absolute -left-6 top-1 w-2.5 h-2.5 rounded-full border-2 border-slate-900 ${
                  v.status === "complete"
                    ? "bg-emerald-500"
                    : v.status === "failed"
                    ? "bg-rose-500"
                    : "bg-blue-500 animate-ping"
                }`}
              />
              <div className="space-y-0.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-200">Doorbell Camera Checked</span>
                  <span className="font-mono text-slate-500 text-[11px]">
                    {checkedScan ? checkedScan.time : "Running..."}
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  {v.runs} {v.runs === 1 ? "capture run" : "capture runs"} completed. Bedrock Converse vision model evaluated porch step.
                </p>
              </div>
            </div>

            {/* Event 4: Re-check if scheduled or completed */}
            {v.recheck_state !== "none" && (
              <div className="relative group">
                <span
                  className={`absolute -left-6 top-1 w-2.5 h-2.5 rounded-full border-2 border-slate-900 ${
                    v.recheck_state === "done" ? "bg-emerald-500" : "bg-amber-500 animate-pulse"
                  }`}
                />
                <div className="space-y-0.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-200">
                      Re-check {v.recheck_state === "done" ? "Completed" : "Scheduled"}
                    </span>
                    <span className="font-mono text-slate-500 text-[11px]">
                      {v.recheck_due_at ? formatDateTime(v.recheck_due_at).time : "Done"}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">
                    {v.recheck_state === "done"
                      ? "Second door check finished; frames combined into verdict."
                      : "Provisional dispute waiting for timed re-check capture."}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Audit provenance note */}
      <div className="p-3 rounded-lg bg-slate-950/50 border border-slate-800/80 text-[11px] text-slate-400 space-y-1">
        <div className="flex items-center gap-1.5 text-slate-300 font-medium">
          <Shield className="w-3.5 h-3.5 text-amber-400" />
          <span>Deterministic Audit Guarantee</span>
        </div>
        <p className="text-slate-400 leading-normal">
          The vision model produces frame observations only. The final verdict is computed deterministically in Python (policy.py).
        </p>
      </div>
    </div>
  );
}
