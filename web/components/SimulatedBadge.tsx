import React from "react";
import { ShieldAlert } from "lucide-react";

interface SimulatedBadgeProps {
  className?: string;
  showTooltip?: boolean;
}

export function SimulatedBadge({ className = "", showTooltip = true }: SimulatedBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-950/80 text-purple-300 border border-purple-700/60 shadow-sm ${className}`}
      title={showTooltip ? "Synthetic/simulated evidence: cannot back a claim or packet" : undefined}
    >
      <ShieldAlert className="w-3.5 h-3.5 text-purple-400" />
      <span>Simulated Evidence</span>
    </span>
  );
}

export function RingPlaygroundNotice({ className = "" }: { className?: string }) {
  return (
    <div
      className={`flex items-center gap-2 px-3 py-1.5 rounded-md bg-amber-950/40 border border-amber-600/40 text-amber-300 text-xs font-medium tracking-wide ${className}`}
    >
      <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
      <span>Ring Developer Playground: simulated streams</span>
    </div>
  );
}
