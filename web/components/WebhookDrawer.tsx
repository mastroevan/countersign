"use client";

import React, { useState } from "react";
import { X, Copy, Check, Code, ShieldCheck } from "lucide-react";

interface WebhookDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  payload: Record<string, any> | null;
}

export function WebhookDrawer({ isOpen, onClose, payload }: WebhookDrawerProps) {
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const jsonString = payload ? JSON.stringify(payload, null, 2) : "No raw webhook payload available.";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonString);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error("Failed to copy", e);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex justify-end"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl h-full bg-slate-900 border-l border-slate-800 p-6 shadow-2xl flex flex-col justify-between overflow-hidden animate-in slide-in-from-right duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
              <Code className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Raw Webhook Event</h3>
              <p className="text-xs text-slate-400">
                Carrier test-mode event payload received via POST /webhooks/easypost
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-slate-400" />
                  <span>Copy JSON</span>
                </>
              )}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* JSON Content */}
        <div className="flex-1 my-4 overflow-y-auto rounded-xl bg-slate-950 p-4 border border-slate-800/80 font-mono text-xs text-emerald-300 leading-relaxed">
          <pre>{jsonString}</pre>
        </div>

        {/* Notice */}
        <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-400 flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-amber-400 shrink-0" />
          <span>
            Test-mode payloads include full carrier tracker metadata. Production webhooks verify HMAC-SHA256 signatures.
          </span>
        </div>
      </div>
    </div>
  );
}
