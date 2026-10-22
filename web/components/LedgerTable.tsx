"use client";

import React, { useState, useEffect } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Clock,
  XCircle,
  RefreshCw,
  Search,
  ExternalLink,
  ChevronRight,
  ShieldAlert,
} from "lucide-react";
import { Verification, Verdict } from "@/types/countersign";

interface LedgerTableProps {
  verifications: Verification[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRecheck: (id: string) => Promise<void>;
  isRecheckingId: string | null;
}

export function LedgerTable({
  verifications,
  selectedId,
  onSelect,
  onRecheck,
  isRecheckingId,
}: LedgerTableProps) {
  const [filter, setFilter] = useState<string>("ALL");
  const [search, setSearch] = useState<string>("");
  const [, setNow] = useState(Date.now());

  // Update countdown every second for scheduled re-checks
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const filtered = verifications.filter((v) => {
    const verdict = v.result?.verdict;
    if (filter === "VERIFIED" && verdict !== "VERIFIED") return false;
    if (filter === "DISPUTED" && verdict !== "DISPUTED") return false;
    if (filter === "INCONCLUSIVE" && verdict !== "INCONCLUSIVE") return false;
    if (filter === "FAILED" && v.status !== "failed") return false;

    if (search.trim()) {
      const q = search.toLowerCase();
      const codeMatch = v.tracking_code?.toLowerCase().includes(q);
      const idMatch = v.id.toLowerCase().includes(q);
      const reasonMatch = v.result?.reason?.toLowerCase().includes(q);
      return Boolean(codeMatch || idMatch || reasonMatch);
    }
    return true;
  });

  const getVerdictBadge = (v: Verification) => {
    if (v.status === "failed") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950/70 text-rose-300 border border-rose-800/80">
          <XCircle className="w-3.5 h-3.5 text-rose-400" />
          <span>FAILED (NO VERDICT)</span>
        </span>
      );
    }

    if (v.status === "pending" || !v.result) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-950/70 text-blue-300 border border-blue-800/80">
          <RefreshCw className="w-3 h-3 text-blue-400 animate-spin" />
          <span>PENDING</span>
        </span>
      );
    }

    const verdict = v.result.verdict;
    const isProvisional = verdict === "DISPUTED" && v.recheck_state !== "done";

    if (verdict === "VERIFIED") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-700/80 shadow-sm shadow-emerald-900/30">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          <span>VERIFIED</span>
        </span>
      );
    }

    if (verdict === "DISPUTED") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950/80 text-rose-300 border border-rose-700/80 shadow-sm shadow-rose-900/30">
          <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
          <span>DISPUTED {isProvisional ? "(Provisional)" : ""}</span>
        </span>
      );
    }

    if (verdict === "INCONCLUSIVE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-950/80 text-amber-300 border border-amber-700/80 shadow-sm shadow-amber-900/30">
          <HelpCircle className="w-3.5 h-3.5 text-amber-400" />
          <span>INCONCLUSIVE</span>
        </span>
      );
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-300">
        {verdict}
      </span>
    );
  };

  const getRecheckCell = (v: Verification) => {
    if (v.recheck_state === "none") {
      return <span className="text-xs text-slate-500">—</span>;
    }

    if (v.recheck_state === "done") {
      return (
        <div className="flex items-center gap-1.5 text-xs text-slate-300">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          <span>Re-checked ({v.runs} {v.runs === 1 ? "run" : "runs"})</span>
        </div>
      );
    }

    if (v.recheck_state === "scheduled") {
      let secondsLeft = 0;
      if (v.recheck_due_at) {
        const dueMs = new Date(v.recheck_due_at).getTime();
        secondsLeft = Math.max(0, Math.ceil((dueMs - Date.now()) / 1000));
      }

      return (
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-amber-300 font-mono">
            <Clock className="w-3.5 h-3.5 text-amber-400 animate-pulse" />
            <span>{secondsLeft > 0 ? `${secondsLeft}s left` : "Due now"}</span>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onRecheck(v.id);
            }}
            disabled={isRecheckingId === v.id}
            className="px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 transition-colors disabled:opacity-50"
            title="Trigger re-check now instead of waiting"
          >
            {isRecheckingId === v.id ? "Rechecking..." : "Re-check Now"}
          </button>
        </div>
      );
    }

    return null;
  };

  const formatTimestamp = (iso: string) => {
    try {
      const dt = new Date(iso);
      return (
        <span className="font-mono text-xs text-slate-300">
          {dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          <span className="text-slate-500 ml-1 text-[11px]">
            {dt.toLocaleDateString([], { month: "short", day: "numeric" })}
          </span>
        </span>
      );
    } catch {
      return <span className="font-mono text-xs text-slate-400">{iso}</span>;
    }
  };

  return (
    <div className="bg-slate-900/90 rounded-xl border border-slate-800 shadow-xl overflow-hidden">
      {/* Table toolbar / filters */}
      <div className="p-4 border-b border-slate-800 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-slate-950/40">
        <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 overflow-x-auto">
          {["ALL", "VERIFIED", "DISPUTED", "INCONCLUSIVE", "FAILED"].map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setFilter(tab)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                filter === tab
                  ? "bg-slate-800 text-amber-400 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="relative min-w-[200px] sm:min-w-[260px]">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter tracking code or reason..."
            className="w-full pl-9 pr-3 py-1.5 bg-slate-950 rounded-lg text-xs text-slate-200 border border-slate-800 placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors"
          />
        </div>
      </div>

      {/* Table list */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-950/60">
              <th className="py-3 px-4">Tracking Code</th>
              <th className="py-3 px-4">Carrier Scan</th>
              <th className="py-3 px-4">Verdict</th>
              <th className="py-3 px-4">Confidence</th>
              <th className="py-3 px-4">Re-check State</th>
              <th className="py-3 px-4 text-right">Evidence</th>
              <th className="py-3 px-4 text-center">Select</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-sm">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-12 text-center text-slate-500">
                  <div className="max-w-md mx-auto space-y-2">
                    <p className="text-base font-medium text-slate-400">No verifications in ledger</p>
                    <p className="text-xs text-slate-500">
                      Use the "New Verification" button or trigger a demo scenario to see live verification.
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              filtered.map((v) => {
                const isSelected = v.id === selectedId;
                const framesCount = v.result?.evidence?.length ?? 0;

                return (
                  <tr
                    key={v.id}
                    onClick={() => onSelect(v.id)}
                    className={`cursor-pointer transition-colors group ${
                      isSelected
                        ? "bg-amber-950/20 border-l-4 border-l-amber-500 hover:bg-amber-950/30"
                        : "hover:bg-slate-850/50 hover:bg-slate-800/40"
                    }`}
                  >
                    {/* Tracking Code */}
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium text-white group-hover:text-amber-400 transition-colors">
                          {v.tracking_code || <span className="text-slate-500 italic">No code</span>}
                        </span>
                        {v.synthetic && (
                          <span
                            className="inline-flex items-center text-[10px] font-semibold px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800"
                            title="Synthetic/Simulated run: cannot back claims"
                          >
                            SIM
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] font-mono text-slate-500 block truncate max-w-[140px]" title={v.id}>
                        id: {v.id.substring(0, 8)}...
                      </span>
                    </td>

                    {/* Carrier Scan Time */}
                    <td className="py-3.5 px-4">{formatTimestamp(v.delivered_at)}</td>

                    {/* Verdict */}
                    <td className="py-3.5 px-4">
                      {getVerdictBadge(v)}
                      {v.result?.verdict === "INCONCLUSIVE" && (
                        <p className="text-[11px] text-amber-400/90 mt-1 max-w-[260px] line-clamp-1">
                          "I can't see the step clearly. Please check."
                        </p>
                      )}
                    </td>

                    {/* Confidence */}
                    <td className="py-3.5 px-4">
                      {v.result?.confidence !== undefined && v.result?.confidence !== null ? (
                        <span className="font-mono text-xs text-slate-200">
                          {Math.round(v.result.confidence * 100)}%
                        </span>
                      ) : (
                        <span className="text-slate-500 text-xs">—</span>
                      )}
                    </td>

                    {/* Re-check State */}
                    <td className="py-3.5 px-4">{getRecheckCell(v)}</td>

                    {/* Evidence count */}
                    <td className="py-3.5 px-4 text-right">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-800 text-slate-300 border border-slate-700/60">
                        {framesCount} {framesCount === 1 ? "frame" : "frames"}
                      </span>
                    </td>

                    {/* Chevron */}
                    <td className="py-3.5 px-4 text-center">
                      <ChevronRight
                        className={`w-4 h-4 mx-auto transition-transform ${
                          isSelected ? "text-amber-400 translate-x-1" : "text-slate-600 group-hover:text-slate-400"
                        }`}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
