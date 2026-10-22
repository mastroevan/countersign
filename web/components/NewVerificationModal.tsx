"use client";

import React, { useState } from "react";
import {
  X,
  Play,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Package,
  Layers,
  Sparkles,
  ArrowRight,
  ShieldCheck,
} from "lucide-react";

interface NewVerificationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (verificationId: string) => void;
}

export function NewVerificationModal({
  isOpen,
  onClose,
  onCreated,
}: NewVerificationModalProps) {
  const [tab, setTab] = useState<"scenarios" | "manual">("scenarios");
  const [trackingCode, setTrackingCode] = useState("EZ4000000004");
  const [deliveredAt, setDeliveredAt] = useState(() => new Date().toISOString().slice(0, 16));
  const [simulate, setSimulate] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  // Run a quick staged demo scenario
  const handleRunScenario = async (stream: "package" | "motion" | "timeout", name: string) => {
    setIsSubmitting(true);
    setError(null);
    try {
      const trackerId = `trk_ui_${Math.random().toString(36).substring(2, 10)}`;
      const nowIso = new Date().toISOString();

      // 1. Bind tracker key to stream on backend (if COUNTERSIGN_SCENARIOS is enabled)
      try {
        await fetch("/api/bindings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: trackerId,
            stream,
            offline: true,
          }),
        });
      } catch (e) {
        // bindings may be disabled if COUNTERSIGN_SCENARIOS=false; fallback to /verify
      }

      // 2. Post webhook event or /verify
      const webhookPayload = {
        id: `evt_ui_${Math.random().toString(36).substring(2, 10)}`,
        object: "Event",
        mode: "test",
        description: "tracker.updated",
        result: {
          id: trackerId,
          object: "Tracker",
          mode: "test",
          tracking_code: `EZ${stream.toUpperCase()}${Math.floor(1000 + Math.random() * 9000)}`,
          status: "delivered",
          tracking_details: [{ status: "delivered", datetime: nowIso }],
        },
      };

      const webhookRes = await fetch("/webhooks/easypost", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(webhookPayload),
      });

      if (webhookRes.ok) {
        const data = await webhookRes.json();
        onCreated(data.id);
        onClose();
        return;
      }

      // Fallback to manual /verify
      const verifyRes = await fetch("/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          delivered_at: nowIso,
          tracking_code: `EZ${stream.toUpperCase()}4000`,
          simulate: true,
        }),
      });

      if (!verifyRes.ok) {
        throw new Error(`Verification start failed: ${verifyRes.status}`);
      }
      const verifyData = await verifyRes.json();
      onCreated(verifyData.id);
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to start scenario");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Run manual verification
  const handleManualVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const dt = new Date(deliveredAt);
      const res = await fetch("/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          delivered_at: dt.toISOString(),
          tracking_code: trackingCode.trim() || undefined,
          simulate,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Verification failed: ${res.status}`);
      }

      const data = await res.json();
      onCreated(data.id);
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to start verification");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-slate-900 rounded-2xl border border-slate-800 p-6 shadow-2xl space-y-6 animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400">
              <Play className="w-5 h-5 fill-amber-400" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-white">Start Delivery Verification</h3>
              <p className="text-xs text-slate-400">
                Trigger carrier scan and door camera audit workflow
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab switch */}
        <div className="flex p-1 rounded-xl bg-slate-950 border border-slate-800">
          <button
            type="button"
            onClick={() => setTab("scenarios")}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-colors flex items-center justify-center gap-2 ${
              tab === "scenarios"
                ? "bg-slate-800 text-amber-400 shadow-sm"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Preset Demo Scenarios</span>
          </button>
          <button
            type="button"
            onClick={() => setTab("manual")}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-colors flex items-center justify-center gap-2 ${
              tab === "manual"
                ? "bg-slate-800 text-amber-400 shadow-sm"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Custom Check</span>
          </button>
        </div>

        {error && (
          <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-xs text-rose-300">
            {error}
          </div>
        )}

        {/* Scenarios Mode */}
        {tab === "scenarios" ? (
          <div className="space-y-3">
            <p className="text-xs text-slate-400">
              Select one of the three core test scenarios defined in the hackathon strategy:
            </p>

            {/* Scenario 1: VERIFIED */}
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleRunScenario("package", "delivered_seen")}
              className="w-full text-left p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 hover:border-emerald-500/60 hover:bg-emerald-950/20 transition-all group flex items-start justify-between gap-3 disabled:opacity-50"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-white text-xs group-hover:text-emerald-300">
                    Case 1: delivered_seen
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800">
                    Expects VERIFIED
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Carrier marks delivered, camera samples Package stream, parcel is visible on step.
                </p>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-emerald-400 group-hover:translate-x-1 transition-all mt-1" />
            </button>

            {/* Scenario 2: DISPUTED */}
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleRunScenario("motion", "delivered_not_seen")}
              className="w-full text-left p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 hover:border-rose-500/60 hover:bg-rose-950/20 transition-all group flex items-start justify-between gap-3 disabled:opacity-50"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-white text-xs group-hover:text-rose-300">
                    Case 2: delivered_not_seen
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-950 text-rose-300 border border-rose-800">
                    Expects DISPUTED
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Carrier marks delivered, camera samples Motion stream, no parcel on step. Schedules 60s re-check.
                </p>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-rose-400 group-hover:translate-x-1 transition-all mt-1" />
            </button>

            {/* Scenario 3: INCONCLUSIVE */}
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleRunScenario("timeout", "unreadable")}
              className="w-full text-left p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 hover:border-amber-500/60 hover:bg-amber-950/20 transition-all group flex items-start justify-between gap-3 disabled:opacity-50"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-white text-xs group-hover:text-amber-300">
                    Case 3: unreadable
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-950 text-amber-300 border border-amber-800">
                    Expects INCONCLUSIVE
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Camera feed times out or is obstructed. Policy returns "I can't see the step clearly. Please check."
                </p>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-amber-400 group-hover:translate-x-1 transition-all mt-1" />
            </button>
          </div>
        ) : (
          <form onSubmit={handleManualVerify} className="space-y-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-300">
                Tracking Code
              </label>
              <input
                type="text"
                value={trackingCode}
                onChange={(e) => setTrackingCode(e.target.value)}
                placeholder="e.g. EZ4000000004"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-white placeholder-slate-500 focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-300">
                Carrier Delivered Timestamp (Local)
              </label>
              <input
                type="datetime-local"
                value={deliveredAt}
                onChange={(e) => setDeliveredAt(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-white placeholder-slate-500 focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="pt-2">
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={simulate}
                  onChange={(e) => setSimulate(e.target.checked)}
                  className="rounded bg-slate-950 border-slate-700 text-amber-500 focus:ring-0"
                />
                <span>Simulate doorbell stream (offline synthetic frames)</span>
              </label>
            </div>

            <div className="pt-3 border-t border-slate-800 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-white hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 hover:from-amber-600 hover:to-orange-600 transition-colors disabled:opacity-50"
              >
                {isSubmitting ? "Starting..." : "Start Check"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
