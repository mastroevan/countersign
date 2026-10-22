"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Navbar } from "@/components/Navbar";
import { LedgerTable } from "@/components/LedgerTable";
import { CarrierTimeline } from "@/components/CarrierTimeline";
import { EvidenceFrames } from "@/components/EvidenceFrames";
import { TracePanel } from "@/components/TracePanel";
import { ApprovalControls } from "@/components/ApprovalControls";
import { WebhookDrawer } from "@/components/WebhookDrawer";
import { NewVerificationModal } from "@/components/NewVerificationModal";
import { Verification } from "@/types/countersign";
import { ShieldCheck, Video, Activity, Sparkles, Layers } from "lucide-react";

export default function DashboardPage() {
  const [verifications, setVerifications] = useState<Verification[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRecheckingId, setIsRecheckingId] = useState<string | null>(null);

  // Webhook drawer state
  const [webhookDrawerOpen, setWebhookDrawerOpen] = useState(false);
  const [rawWebhookPayload, setRawWebhookPayload] = useState<any>(null);

  // New verification modal
  const [newModalOpen, setNewModalOpen] = useState(false);

  // Fetch ledger entries
  const fetchLedger = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const res = await fetch("/api/ledger");
      if (res.ok) {
        const data: Verification[] = await res.json();
        setVerifications(data);

        // Select first item by default if nothing selected yet
        if (!selectedId && data.length > 0) {
          setSelectedId(data[0].id);
        }
      }
    } catch (err) {
      console.error("Failed to fetch ledger", err);
    } finally {
      setIsRefreshing(false);
    }
  }, [selectedId]);

  useEffect(() => {
    fetchLedger();
    const interval = setInterval(fetchLedger, 4000);
    return () => clearInterval(interval);
  }, [fetchLedger]);

  // Selected verification object
  const selectedVerification = verifications.find((v) => v.id === selectedId) || null;

  // Handle re-check
  const handleRecheck = async (id: string) => {
    setIsRecheckingId(id);
    try {
      const res = await fetch(`/verifications/${id}/recheck`, {
        method: "POST",
      });
      if (res.ok) {
        await fetchLedger();
      } else {
        const data = await res.json().catch(() => ({}));
        alert(data.detail || `Re-check failed: ${res.status}`);
      }
    } catch (err: any) {
      alert(`Re-check failed: ${err.message}`);
    } finally {
      setIsRecheckingId(null);
    }
  };

  const handleOpenWebhookDrawerWithPayload = (payload: any) => {
    setRawWebhookPayload(payload);
    setWebhookDrawerOpen(true);
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <Navbar
        onOpenNewModal={() => setNewModalOpen(true)}
        onRefresh={fetchLedger}
        isRefreshing={isRefreshing}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Top Hero / Summary Banner */}
        <div className="rounded-2xl bg-gradient-to-r from-slate-900 via-slate-900 to-slate-950 border border-slate-800 p-6 shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-96 h-96 bg-amber-500/5 rounded-full blur-3xl pointer-events-none" />
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Dual-Witness Engine
                </span>
                <span className="text-xs text-slate-400">
                  Ring Partner API • Amazon Bedrock • Deterministic Policy
                </span>
              </div>
              <h1 className="text-2xl font-black text-white tracking-tight sm:text-3xl">
                Carrier Scan vs Doorbell Witness
              </h1>
              <p className="text-xs sm:text-sm text-slate-400 max-w-2xl leading-relaxed">
                "Carrier says delivered. Your door says no." Countersign reconciles third-party delivery claims
                against watermarked doorbell frames, computing strict verdicts through deterministic code.
              </p>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => setNewModalOpen(true)}
                className="px-4 py-2.5 rounded-xl font-semibold text-xs bg-amber-500 hover:bg-amber-400 text-slate-950 transition-all shadow-lg shadow-amber-500/10 active:scale-95 flex items-center gap-2"
              >
                <Sparkles className="w-4 h-4 fill-slate-950" />
                <span>Run Demo Scenario</span>
              </button>
            </div>
          </div>
        </div>

        {/* Section 1: Ledger Table */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
              <Layers className="w-4 h-4 text-amber-400" />
              <span>Delivery Ledger</span>
            </h2>
            <span className="text-xs font-mono text-slate-500">
              {verifications.length} {verifications.length === 1 ? "record" : "records"}
            </span>
          </div>

          <LedgerTable
            verifications={verifications}
            selectedId={selectedId}
            onSelect={(id) => setSelectedId(id)}
            onRecheck={handleRecheck}
            isRecheckingId={isRecheckingId}
          />
        </div>

        {/* Section 2: Split-screen Detail View (Left: Carrier Timeline, Right: Evidence Frames) */}
        {selectedVerification ? (
          <div className="space-y-6 pt-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <Video className="w-4 h-4 text-amber-400" />
                <span>Verification Audit Detail</span>
              </h2>
              <span className="text-xs font-mono text-slate-400">
                Selected: {selectedVerification.tracking_code || selectedVerification.id.slice(0, 8)}
              </span>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* Left Column: Carrier & Tracker Timeline */}
              <div className="lg:col-span-5">
                <CarrierTimeline
                  verification={selectedVerification}
                  onOpenWebhookDrawer={() => setWebhookDrawerOpen(true)}
                  hasWebhookPayload={Boolean(rawWebhookPayload)}
                />
              </div>

              {/* Right Column: Evidence Frames with Ring Playground notice */}
              <div className="lg:col-span-7">
                <EvidenceFrames
                  verificationId={selectedVerification.id}
                  evidence={selectedVerification.result?.evidence || []}
                  isSynthetic={selectedVerification.synthetic}
                />
              </div>
            </div>

            {/* Section 3: Trace Panel & Approval UI */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start pt-2">
              {/* Left: Live SSE Trace Panel */}
              <div className="lg:col-span-6">
                <TracePanel
                  selectedVerificationId={selectedVerification.id}
                  onOpenWebhookPayload={handleOpenWebhookDrawerWithPayload}
                />
              </div>

              {/* Right: Approval Gate Controls */}
              <div className="lg:col-span-6">
                <ApprovalControls
                  verification={selectedVerification}
                  onRefresh={fetchLedger}
                  onRecheck={handleRecheck}
                  isRechecking={isRecheckingId === selectedVerification.id}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="p-8 rounded-2xl border border-dashed border-slate-800 text-center space-y-2 bg-slate-900/40">
            <ShieldCheck className="w-10 h-10 text-slate-600 mx-auto" />
            <p className="text-sm font-medium text-slate-400">No verification selected</p>
            <p className="text-xs text-slate-500">
              Click a verification in the ledger table above or start a new check to view evidence.
            </p>
          </div>
        )}
      </main>

      {/* Raw Webhook JSON Drawer */}
      <WebhookDrawer
        isOpen={webhookDrawerOpen}
        onClose={() => setWebhookDrawerOpen(false)}
        payload={rawWebhookPayload}
      />

      {/* New Verification Modal */}
      <NewVerificationModal
        isOpen={newModalOpen}
        onClose={() => setNewModalOpen(false)}
        onCreated={(id) => {
          setSelectedId(id);
          fetchLedger();
        }}
      />
    </div>
  );
}
