"use client";

import React, { useEffect, useState, useRef } from "react";
import {
  Activity,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  Clock,
  Radio,
  FileCode,
  Shield,
  Eye,
  Cpu,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  ExternalLink,
  Code,
} from "lucide-react";
import { TraceEvent } from "@/types/countersign";

interface TracePanelProps {
  selectedVerificationId: string | null;
  onOpenWebhookPayload: (payload: any) => void;
}

export function TracePanel({
  selectedVerificationId,
  onOpenWebhookPayload,
}: TracePanelProps) {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [filterToCurrent, setFilterToCurrent] = useState(true);
  const [expandedSeq, setExpandedSeq] = useState<Record<number, boolean>>({});
  const lastSeqRef = useRef<number>(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Connect to SSE stream
  useEffect(() => {
    let isCancelled = false;

    const connectSSE = async () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        const query = new URLSearchParams();
        if (selectedVerificationId && filterToCurrent) {
          query.set("verification_id", selectedVerificationId);
        }
        if (lastSeqRef.current > 0) {
          query.set("last_event_id", lastSeqRef.current.toString());
        }
        query.set("follow", "true");

        const response = await fetch(`/api/trace?${query.toString()}`, {
          signal: controller.signal,
          headers: {
            "Accept": "text/event-stream",
            ...(lastSeqRef.current > 0 ? { "Last-Event-ID": lastSeqRef.current.toString() } : {}),
          },
        });

        if (!response.ok || !response.body) {
          throw new Error(`SSE failed with status ${response.status}`);
        }

        if (isCancelled) return;
        setIsConnected(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const block of lines) {
            if (!block.trim()) continue;

            const blockLines = block.split("\n");
            let eventType = "message";
            let eventData = "";
            let eventId: number | null = null;

            for (const line of blockLines) {
              if (line.startsWith("event: ")) {
                eventType = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                eventData += line.slice(6);
              } else if (line.startsWith("id: ")) {
                const parsed = parseInt(line.slice(4).trim(), 10);
                if (!isNaN(parsed)) eventId = parsed;
              }
            }

            if (eventType === "lagged") {
              // Reconnect from last seen ID
              console.warn("SSE stream lagged, reconnecting...");
              setIsConnected(false);
              setTimeout(() => {
                if (!isCancelled) connectSSE();
              }, 500);
              return;
            }

            if (eventType === "trace" && eventData) {
              try {
                const parsed: TraceEvent = JSON.parse(eventData);
                if (eventId !== null) {
                  parsed.seq = eventId;
                  lastSeqRef.current = Math.max(lastSeqRef.current, eventId);
                } else if (parsed.seq) {
                  lastSeqRef.current = Math.max(lastSeqRef.current, parsed.seq);
                }

                setEvents((prev) => {
                  if (prev.some((e) => e.seq === parsed.seq)) return prev;
                  const updated = [...prev, parsed];
                  return updated.sort((a, b) => a.seq - b.seq);
                });
              } catch (e) {
                console.error("Failed to parse trace event", e);
              }
            }
          }
        }
      } catch (err: any) {
        if (err.name === "AbortError") return;
        console.warn("SSE connection closed or error, will retry", err);
        setIsConnected(false);
        if (!isCancelled) {
          setTimeout(connectSSE, 3000);
        }
      }
    };

    connectSSE();

    return () => {
      isCancelled = true;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [selectedVerificationId, filterToCurrent]);

  // Auto scroll to bottom of trace
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  const toggleExpand = (seq: number) => {
    setExpandedSeq((prev) => ({ ...prev, [seq]: !prev[seq] }));
  };

  const displayedEvents = events.filter((ev) => {
    if (!filterToCurrent || !selectedVerificationId) return true;
    return ev.verification_id === selectedVerificationId;
  });

  const getStageIcon = (stage: string, status: string) => {
    if (status === "error") return <AlertCircle className="w-3.5 h-3.5 text-rose-400" />;
    switch (stage) {
      case "webhook_received":
        return <FileCode className="w-3.5 h-3.5 text-blue-400" />;
      case "verification_started":
        return <Activity className="w-3.5 h-3.5 text-amber-400" />;
      case "device_discovery":
      case "encryption_check":
        return <Shield className="w-3.5 h-3.5 text-cyan-400" />;
      case "whep_session":
        return <Radio className="w-3.5 h-3.5 text-indigo-400" />;
      case "frame_sampled":
        return <Eye className="w-3.5 h-3.5 text-purple-400" />;
      case "bedrock_call":
        return <Cpu className="w-3.5 h-3.5 text-orange-400" />;
      case "judgment":
        return <Activity className="w-3.5 h-3.5 text-emerald-400" />;
      case "policy_rule":
      case "verification_complete":
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
      case "recheck_scheduled":
      case "recheck_started":
      case "recheck_complete":
        return <Clock className="w-3.5 h-3.5 text-amber-400" />;
      default:
        return <Activity className="w-3.5 h-3.5 text-slate-400" />;
    }
  };

  const formatStageTitle = (stage: string) => {
    return stage
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  };

  const renderStageSummary = (ev: TraceEvent) => {
    const d = ev.data || {};
    switch (ev.stage) {
      case "webhook_received":
        return (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-slate-300">
              tracking: {d.tracking_code || "EZ4000000004"}
            </span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-950 text-blue-300 font-mono">
              status={d.carrier_status || "delivered"}
            </span>
            {d.payload && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenWebhookPayload(d.payload);
                }}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 text-[10px] border border-amber-500/30"
              >
                <Code className="w-3 h-3" />
                <span>View Raw Payload</span>
              </button>
            )}
          </div>
        );

      case "device_discovery":
        return (
          <span className="font-mono text-slate-300 text-xs">
            device_id={d.device_id || "d1"} {d.simulated ? "(simulated playground)" : ""}
          </span>
        );

      case "encryption_check":
        return (
          <span className="font-mono text-slate-300 text-xs">
            e2e_encryption_enabled={String(d.e2e_encryption_enabled ?? false)} (verified unencrypted)
          </span>
        );

      case "whep_session":
        return (
          <span className="font-mono text-slate-300 text-xs">
            state={d.state} {d.device_id ? `device=${d.device_id}` : ""} {d.detail ? `(${d.detail})` : ""}
          </span>
        );

      case "frame_sampled":
        return (
          <span className="font-mono text-slate-300 text-xs">
            frame_id={d.frame_id} source={d.source}
          </span>
        );

      case "bedrock_call":
        return (
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span className="font-mono text-orange-300">
              model={d.model_id || "anthropic.claude-3-5-sonnet"}
            </span>
            {d.request_id && (
              <span className="font-mono text-slate-500 text-[10px]">
                req_id={d.request_id}
              </span>
            )}
            {d.latency_ms !== undefined && (
              <span className="font-mono text-amber-300 text-[10px] px-1 rounded bg-slate-950">
                {d.latency_ms}ms
              </span>
            )}
          </div>
        );

      case "judgment":
        return (
          <div className="flex items-center gap-2 flex-wrap text-xs font-mono">
            <span className={d.parcel_visible ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>
              parcel_visible={String(d.parcel_visible)}
            </span>
            <span className="text-slate-400">conf={Math.round((d.confidence || 0) * 100)}%</span>
            <span className="text-slate-400">loc={d.location || "porch"}</span>
            {d.watermark_ts && (
              <span className="text-amber-300 text-[10px]">wm={d.watermark_ts.slice(11, 19)}</span>
            )}
          </div>
        );

      case "policy_rule":
      case "verification_complete":
        return (
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span
              className={`font-mono font-bold px-1.5 py-0.2 rounded ${
                d.verdict === "VERIFIED"
                  ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                  : d.verdict === "DISPUTED"
                  ? "bg-rose-950 text-rose-300 border border-rose-800"
                  : "bg-amber-950 text-amber-300 border border-amber-800"
              }`}
            >
              {d.verdict}
            </span>
            <span className="font-mono text-slate-400 text-[11px]">rule={d.rule}</span>
            <span className="text-slate-300 text-xs italic">"{d.reason}"</span>
          </div>
        );

      case "recheck_scheduled":
        return (
          <span className="font-mono text-amber-300 text-xs">
            delay={d.delay_s}s due_at={d.due_at?.slice(11, 19)} (provisional until re-check)
          </span>
        );

      case "verification_failed":
        return <span className="font-mono text-rose-400 text-xs">{d.error}</span>;

      default:
        return (
          <span className="font-mono text-slate-400 text-xs">
            {Object.entries(d)
              .filter(([k]) => k !== "payload")
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(" ")}
          </span>
        );
    }
  };

  return (
    <div className="bg-slate-900/90 rounded-xl border border-slate-800 flex flex-col h-[520px] shadow-xl overflow-hidden">
      {/* Panel Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
            <Radio className="w-4 h-4 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white tracking-tight">
                Live Pipeline Trace
              </h3>
              <span
                className={`w-2 h-2 rounded-full ${
                  isConnected ? "bg-emerald-400 animate-pulse" : "bg-slate-600"
                }`}
                title={isConnected ? "SSE Connected" : "Connecting..."}
              />
            </div>
            <p className="text-[11px] font-mono text-slate-400">
              GET /api/trace {isConnected ? "(streaming events)" : "(connecting...)"}
            </p>
          </div>
        </div>

        {/* Filter controls */}
        <div className="flex items-center gap-2 text-xs">
          {selectedVerificationId && (
            <label className="flex items-center gap-1.5 text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={filterToCurrent}
                onChange={(e) => setFilterToCurrent(e.target.checked)}
                className="rounded bg-slate-950 border-slate-700 text-amber-500 focus:ring-0"
              />
              <span>Selected verification only</span>
            </label>
          )}

          <button
            type="button"
            onClick={() => {
              lastSeqRef.current = 0;
              setEvents([]);
            }}
            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200"
            title="Clear Trace Backlog"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Trace Log Body */}
      <div
        ref={scrollRef}
        className="flex-1 p-4 overflow-y-auto space-y-2 bg-slate-950/40 font-mono text-xs select-text"
      >
        {displayedEvents.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500 space-y-2">
            <Activity className="w-8 h-8 text-slate-700 animate-pulse" />
            <p className="text-xs">No pipeline trace events captured yet.</p>
            <p className="text-[11px] text-slate-600 max-w-xs">
              When a webhook arrives or a verification runs, the SSE pipeline stream will output step-by-step audit events here.
            </p>
          </div>
        ) : (
          displayedEvents.map((ev) => {
            const isExpanded = !!expandedSeq[ev.seq];
            const tsShort = ev.ts ? ev.ts.slice(11, 19) : "";

            return (
              <div
                key={ev.seq}
                className="rounded-lg border border-slate-800/80 bg-slate-900/60 p-2.5 transition-colors hover:bg-slate-900"
              >
                <div
                  className="flex items-start justify-between gap-3 cursor-pointer"
                  onClick={() => toggleExpand(ev.seq)}
                >
                  <div className="flex items-start gap-2 flex-1 min-w-0">
                    <span className="mt-0.5 shrink-0">{getStageIcon(ev.stage, ev.status)}</span>
                    <div className="space-y-1 min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-slate-200">
                          {formatStageTitle(ev.stage)}
                        </span>
                        <span
                          className={`text-[10px] px-1 rounded uppercase ${
                            ev.status === "ok"
                              ? "bg-emerald-950 text-emerald-400"
                              : ev.status === "error"
                              ? "bg-rose-950 text-rose-400"
                              : "bg-slate-800 text-slate-400"
                          }`}
                        >
                          {ev.status}
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono">
                          seq #{ev.seq}
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono ml-auto">
                          {tsShort}
                        </span>
                      </div>
                      <div className="text-slate-300 font-mono text-[11px] leading-relaxed">
                        {renderStageSummary(ev)}
                      </div>
                    </div>
                  </div>

                  <span className="text-slate-600 mt-1">
                    {isExpanded ? (
                      <ChevronDown className="w-3.5 h-3.5" />
                    ) : (
                      <ChevronRight className="w-3.5 h-3.5" />
                    )}
                  </span>
                </div>

                {/* Expanded Raw JSON */}
                {isExpanded && (
                  <div className="mt-2 pt-2 border-t border-slate-800/80 text-[11px] text-emerald-300/90 bg-slate-950 p-2.5 rounded overflow-x-auto">
                    <pre>{JSON.stringify(ev, null, 2)}</pre>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer info bar */}
      <div className="px-4 py-2 border-t border-slate-800 bg-slate-950/80 text-[10px] font-mono text-slate-500 flex items-center justify-between">
        <span>Event stream protocol: Server-Sent Events (SSE) with Last-Event-ID replay</span>
        <span>{displayedEvents.length} events</span>
      </div>
    </div>
  );
}
