"use client";

import React, { useState } from "react";
import Image from "next/image";
import {
  Camera,
  CheckCircle2,
  XCircle,
  Clock,
  MapPin,
  Sparkles,
  Maximize2,
  X,
  AlertCircle,
  Eye,
} from "lucide-react";
import { FrameEvidence } from "@/types/countersign";
import { RingPlaygroundNotice } from "./SimulatedBadge";

interface EvidenceFramesProps {
  verificationId: string;
  evidence: FrameEvidence[];
  isSynthetic?: boolean;
}

export function EvidenceFrames({
  verificationId,
  evidence,
  isSynthetic,
}: EvidenceFramesProps) {
  const [activeFrame, setActiveFrame] = useState<FrameEvidence | null>(null);

  const formatWatermarkTime = (iso: string | null) => {
    if (!iso) return "Watermark: Unread";
    try {
      const dt = new Date(iso);
      return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return iso;
    }
  };

  return (
    <div className="bg-slate-900/90 rounded-xl border border-slate-800 p-5 space-y-5">
      {/* Required Banner: Ring Developer Playground label */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Camera className="w-4 h-4 text-amber-400" />
            <h3 className="text-base font-bold text-white">Doorbell Camera Evidence</h3>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Sampled live view frames with embedded Ring audit watermark
          </p>
        </div>

        {/* The required playground notice */}
        <RingPlaygroundNotice />
      </div>

      {/* Frame Grid */}
      {evidence.length === 0 ? (
        <div className="py-12 px-4 rounded-xl border border-dashed border-slate-800 text-center space-y-2">
          <Camera className="w-8 h-8 text-slate-600 mx-auto" />
          <p className="text-sm font-medium text-slate-400">No camera frames sampled yet</p>
          <p className="text-xs text-slate-500 max-w-sm mx-auto">
            Live WHEP stream captures frames when a carrier delivery scan is processed.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {evidence.map((frame, idx) => {
            const frameUrl = `/verifications/${verificationId}/frames/${frame.frame_id}.jpg`;
            const isVisible = frame.parcel_visible === true;
            const isDisputed = frame.parcel_visible === false;
            const conf = frame.confidence !== null ? Math.round(frame.confidence * 100) : null;

            return (
              <div
                key={frame.frame_id}
                className="group relative rounded-xl overflow-hidden bg-slate-950 border border-slate-800 hover:border-amber-500/50 transition-all shadow-md"
              >
                {/* Image Container with Watermark notice */}
                <div className="relative aspect-video w-full bg-slate-950 overflow-hidden">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={frameUrl}
                    alt={`Door camera frame ${frame.frame_id}`}
                    className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                  />

                  {/* Frame index badge */}
                  <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-slate-950/80 backdrop-blur-sm text-[10px] font-mono text-slate-300 border border-slate-700/60">
                    Frame #{idx + 1}
                  </div>

                  {/* Watermark audit badge (top-right) */}
                  <div className="absolute top-2 right-2 px-2 py-0.5 rounded bg-slate-950/80 backdrop-blur-sm text-[10px] font-mono text-amber-300 border border-amber-700/60 flex items-center gap-1">
                    <Clock className="w-2.5 h-2.5 text-amber-400" />
                    <span>{formatWatermarkTime(frame.watermark_ts)}</span>
                  </div>

                  {/* Zoom click button */}
                  <button
                    type="button"
                    onClick={() => setActiveFrame(frame)}
                    className="absolute inset-0 bg-slate-950/0 group-hover:bg-slate-950/30 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100"
                    title="Click to view full resolution"
                  >
                    <span className="p-2 rounded-full bg-slate-900/90 text-white shadow-lg border border-slate-700">
                      <Maximize2 className="w-4 h-4" />
                    </span>
                  </button>
                </div>

                {/* Observation / Judgment details bar */}
                <div className="p-3 bg-slate-900/90 border-t border-slate-800 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    {/* Parcel visible status */}
                    <div className="flex items-center gap-1.5">
                      {isVisible && (
                        <span className="flex items-center gap-1 font-semibold text-emerald-400">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          <span>Parcel Visible</span>
                        </span>
                      )}
                      {isDisputed && (
                        <span className="flex items-center gap-1 font-semibold text-rose-400">
                          <XCircle className="w-3.5 h-3.5 text-rose-400" />
                          <span>No Parcel</span>
                        </span>
                      )}
                      {frame.parcel_visible === null && (
                        <span className="flex items-center gap-1 font-medium text-slate-400">
                          <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
                          <span>Unreadable</span>
                        </span>
                      )}
                    </div>

                    {/* Confidence score */}
                    {conf !== null && (
                      <span className="font-mono text-xs text-slate-300">
                        {conf}% conf
                      </span>
                    )}
                  </div>

                  {/* Location & watermark audit status */}
                  <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-800/60">
                    <span className="flex items-center gap-1 font-mono text-slate-300">
                      <MapPin className="w-3 h-3 text-slate-500" />
                      {frame.location || "none"}
                    </span>
                    <span className="text-slate-500 font-mono text-[10px]">
                      {frame.source}
                    </span>
                  </div>

                  {frame.watermark_discarded && (
                    <p className="text-[10px] text-amber-400 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/40">
                      Watermark skew: {Math.round(frame.watermark_skew_seconds || 0)}s (discarded)
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Frame audit footer note */}
      <div className="text-[11px] text-slate-500 flex items-center justify-between border-t border-slate-800/80 pt-3">
        <span>* Preserves device watermark for timestamp audit only; never treated as parcel evidence.</span>
        <span>Privacy: Step/porch area only.</span>
      </div>

      {/* Fullscreen Frame Lightbox Modal */}
      {activeFrame && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-md flex items-center justify-center p-4 sm:p-6"
          onClick={() => setActiveFrame(null)}
        >
          <div
            className="relative max-w-4xl w-full bg-slate-900 rounded-2xl border border-slate-800 overflow-hidden shadow-2xl space-y-4 p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-bold text-white font-mono">
                  Frame ID: {activeFrame.frame_id}
                </span>
                <span className="text-xs text-slate-400 font-mono">
                  ({activeFrame.source})
                </span>
              </div>
              <button
                type="button"
                onClick={() => setActiveFrame(null)}
                className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="relative aspect-video w-full rounded-xl overflow-hidden bg-black">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/verifications/${verificationId}/frames/${activeFrame.frame_id}.jpg`}
                alt="Full resolution frame"
                className="w-full h-full object-contain"
              />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs bg-slate-950 p-3 rounded-xl border border-slate-800">
              <div>
                <span className="text-slate-500 block text-[10px] uppercase">Parcel Visible</span>
                <span className={`font-semibold ${activeFrame.parcel_visible ? "text-emerald-400" : "text-rose-400"}`}>
                  {activeFrame.parcel_visible ? "Yes (Detected)" : "No (Empty Step)"}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px] uppercase">Confidence</span>
                <span className="font-mono text-slate-200">
                  {activeFrame.confidence !== null ? `${Math.round(activeFrame.confidence * 100)}%` : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px] uppercase">Watermark Timestamp</span>
                <span className="font-mono text-amber-300">
                  {formatWatermarkTime(activeFrame.watermark_ts)}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px] uppercase">Location</span>
                <span className="font-mono text-slate-200">
                  {activeFrame.location || "none"}
                </span>
              </div>
            </div>

            <RingPlaygroundNotice />
          </div>
        </div>
      )}
    </div>
  );
}
