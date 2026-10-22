"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck, Mic, LayoutDashboard, Plus, RefreshCw, Cpu } from "lucide-react";

interface NavbarProps {
  onOpenNewModal?: () => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function Navbar({ onOpenNewModal, onRefresh, isRefreshing }: NavbarProps) {
  const pathname = usePathname();
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const checkHealth = async () => {
      try {
        const res = await fetch("/healthz");
        if (mounted) {
          setBackendOk(res.ok);
        }
      } catch {
        if (mounted) {
          setBackendOk(false);
        }
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800 bg-slate-950/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Product info */}
          <div className="flex items-center gap-6">
            <Link href="/" className="flex items-center gap-3 group">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center shadow-lg shadow-orange-500/20 group-hover:scale-105 transition-transform">
                <ShieldCheck className="w-6 h-6 text-slate-950 font-bold" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-lg tracking-tight text-white group-hover:text-amber-400 transition-colors">
                    Countersign
                  </span>
                  <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                    Dual Track
                  </span>
                </div>
                <p className="text-xs text-slate-400 hidden sm:block">
                  Doorbell Camera Delivery Verification
                </p>
              </div>
            </Link>

            {/* Navigation tabs */}
            <nav className="flex items-center gap-1 sm:gap-2 ml-2 sm:ml-6">
              <Link
                href="/"
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  pathname === "/"
                    ? "bg-slate-800 text-amber-400 border border-slate-700 shadow-sm"
                    : "text-slate-400 hover:text-white hover:bg-slate-900"
                }`}
              >
                <LayoutDashboard className="w-4 h-4" />
                <span>Dashboard</span>
              </Link>
              <Link
                href="/alexa"
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  pathname === "/alexa"
                    ? "bg-slate-800 text-amber-400 border border-slate-700 shadow-sm"
                    : "text-slate-400 hover:text-white hover:bg-slate-900"
                }`}
              >
                <Mic className="w-4 h-4" />
                <span>Alexa+ Simulator</span>
                <span className="hidden md:inline-flex text-[10px] font-semibold px-1.5 py-0.2 rounded bg-purple-900/60 text-purple-300 border border-purple-700/50">
                  MCP
                </span>
              </Link>
            </nav>
          </div>

          {/* Right actions: Backend status & New Check */}
          <div className="flex items-center gap-3">
            {/* Backend status badge */}
            <div
              className={`hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                backendOk === true
                  ? "bg-emerald-950/60 text-emerald-300 border-emerald-800/60"
                  : backendOk === false
                  ? "bg-rose-950/60 text-rose-300 border-rose-800/60"
                  : "bg-slate-900 text-slate-400 border-slate-800"
              }`}
              title={
                backendOk === true
                  ? "Backend connected (FastAPI / Bedrock / Ring WHEP)"
                  : "Backend disconnected (Check http://localhost:8000)"
              }
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  backendOk === true
                    ? "bg-emerald-400 animate-pulse"
                    : backendOk === false
                    ? "bg-rose-500"
                    : "bg-slate-500"
                }`}
              />
              <span className="flex items-center gap-1">
                <Cpu className="w-3 h-3 opacity-70" />
                {backendOk === true ? "Backend Online" : backendOk === false ? "Backend Offline" : "Connecting..."}
              </span>
            </div>

            {onRefresh && (
              <button
                type="button"
                onClick={onRefresh}
                disabled={isRefreshing}
                className="p-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition-colors disabled:opacity-50"
                title="Refresh Ledger"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-amber-400" : ""}`} />
              </button>
            )}

            {onOpenNewModal && (
              <button
                type="button"
                onClick={onOpenNewModal}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-slate-950 font-semibold text-sm shadow-md shadow-orange-500/10 hover:shadow-orange-500/20 transition-all active:scale-95"
              >
                <Plus className="w-4 h-4 stroke-[2.5]" />
                <span className="hidden sm:inline">New Verification</span>
                <span className="sm:hidden">New</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
