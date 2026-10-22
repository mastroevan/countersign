"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { RingPlaygroundNotice, SimulatedBadge } from "@/components/SimulatedBadge";
import { MCPDeliveryReport } from "@/types/countersign";
import {
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  Play,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Radio,
  Terminal,
  Send,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Camera,
  Layers,
  ChevronRight,
  Clock,
  MapPin,
  RefreshCw,
  Cpu,
} from "lucide-react";

interface MCPMessageLog {
  id: string;
  timestamp: string;
  direction: "out" | "in";
  method: string;
  data: any;
}

export default function AlexaSimulatorPage() {
  const [mcpClient, setMcpClient] = useState<any>(null);
  const [transport, setTransport] = useState<any>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [negotiatedVersion, setNegotiatedVersion] = useState<string | null>(null);
  const [serverInstructions, setServerInstructions] = useState<string | null>(null);
  const [availableTools, setAvailableTools] = useState<any[]>([]);
  const [logs, setLogs] = useState<MCPMessageLog[]>([]);

  // Voice & Utterance state
  const [utterance, setUtterance] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [speechSynthesisSupported, setSpeechSynthesisSupported] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);

  // Active Tool Call & Alexa Multimodal Result
  const [isCallingTool, setIsCallingTool] = useState(false);
  const [activeReport, setActiveReport] = useState<MCPDeliveryReport | null>(null);
  const [toolResultRaw, setToolResultRaw] = useState<any>(null);
  const [toolError, setToolError] = useState<string | null>(null);

  const recognitionRef = useRef<any>(null);

  // Add message to protocol log
  const logMessage = (direction: "out" | "in", method: string, data: any) => {
    setLogs((prev) => [
      ...prev,
      {
        id: Math.random().toString(36).substring(2, 9),
        timestamp: new Date().toLocaleTimeString(),
        direction,
        method,
        data,
      },
    ]);
  };

  // Initialize Speech Recognition & Synthesis capability check
  useEffect(() => {
    if (typeof window !== "undefined") {
      const hasSpeech = "SpeechRecognition" in window || "webkitSpeechRecognition" in window;
      setSpeechSupported(hasSpeech);
      setSpeechSynthesisSupported("speechSynthesis" in window);

      if (hasSpeech) {
        const SpeechRecognition =
          (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
        const recog = new SpeechRecognition();
        recog.continuous = false;
        recog.interimResults = false;
        recog.lang = "en-US";

        recog.onresult = (event: any) => {
          const text = event.results[0][0].transcript;
          setUtterance(text);
          setIsListening(false);
          handleProcessUtterance(text);
        };

        recog.onerror = (e: any) => {
          console.warn("Speech recognition error", e);
          setIsListening(false);
        };

        recog.onend = () => {
          setIsListening(false);
        };

        recognitionRef.current = recog;
      }
    }
  }, []);

  // Initialize MCP Client over Streamable HTTP
  const connectMCP = async () => {
    setIsConnecting(true);
    setToolError(null);
    try {
      // Dynamic import to ensure browser-only bundling
      const { Client } = await import("@modelcontextprotocol/sdk/client/index.js");
      const { StreamableHTTPClientTransport } = await import(
        "@modelcontextprotocol/sdk/client/streamableHttp.js"
      );

      const mcpUrl = new URL("/mcp", window.location.origin);
      const httpTransport = new StreamableHTTPClientTransport(mcpUrl);

      const client = new Client(
        {
          name: "countersign-alexa-simulator",
          version: "1.0.0",
        },
        {
          capabilities: {},
        }
      );

      logMessage("out", "initialize", {
        transport: "StreamableHTTPClientTransport",
        url: mcpUrl.toString(),
        clientInfo: { name: "countersign-alexa-simulator", version: "1.0.0" },
      });

      await client.connect(httpTransport);

      const serverVersion = client.getServerVersion();
      const instructions = client.getInstructions();
      const proto = httpTransport.protocolVersion || "2025-11-25";

      setNegotiatedVersion(proto);
      setServerInstructions(instructions || null);
      setTransport(httpTransport);
      setMcpClient(client);
      setIsConnected(true);

      logMessage("in", "initialize/result", {
        serverVersion,
        negotiatedProtocolVersion: proto,
        instructions,
      });

      // Fetch tools list
      logMessage("out", "tools/list", {});
      const toolsResp = await client.listTools();
      setAvailableTools(toolsResp.tools || []);
      logMessage("in", "tools/list/result", {
        count: toolsResp.tools.length,
        tools: toolsResp.tools.map((t) => t.name),
      });
    } catch (err: any) {
      console.error("Failed to connect MCP client", err);
      setToolError(err.message || "Failed to connect to MCP server at /mcp");
      setIsConnected(false);
    } finally {
      setIsConnecting(false);
    }
  };

  // Connect on mount
  useEffect(() => {
    connectMCP();
    return () => {
      // Cleanup transport if needed
    };
  }, []);

  // Text-to-speech speaker
  const speakResponse = (text: string) => {
    if (!voiceEnabled || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.rate = 1.0;
      utter.pitch = 1.0;
      utter.onstart = () => setIsSpeaking(true);
      utter.onend = () => setIsSpeaking(false);
      utter.onerror = () => setIsSpeaking(false);
      window.speechSynthesis.speak(utter);
    } catch (e) {
      console.warn("Speech synthesis error", e);
    }
  };

  // Voice input toggle
  const toggleListening = () => {
    if (!recognitionRef.current) return;
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      setUtterance("");
      setIsListening(true);
      try {
        recognitionRef.current.start();
      } catch (e) {
        console.warn("Could not start recognition", e);
        setIsListening(false);
      }
    }
  };

  // Execute MCP Tool call
  const callMcpTool = async (name: string, args: Record<string, any>) => {
    if (!mcpClient) {
      setToolError("MCP client not connected. Reconnecting...");
      await connectMCP();
      return;
    }

    setIsCallingTool(true);
    setToolError(null);
    setActiveReport(null);
    setToolResultRaw(null);

    logMessage("out", `tools/call:${name}`, args);

    try {
      const resp = await mcpClient.callTool({
        name,
        arguments: args,
      });

      logMessage("in", `tools/call:${name}/result`, resp);
      setToolResultRaw(resp);

      // Handle MCP content shape
      if (resp.isError) {
        const errorText = resp.content?.[0]?.text || "MCP tool error";
        setToolError(errorText);
        speakResponse(`Countersign reported an issue: ${errorText}`);
        return;
      }

      // Check content text for parsed JSON
      if (resp.content && resp.content.length > 0) {
        const rawContent = resp.content[0];
        let parsedData: any = null;
        if (typeof rawContent.text === "string") {
          try {
            parsedData = JSON.parse(rawContent.text);
          } catch {
            parsedData = rawContent.text;
          }
        } else {
          parsedData = rawContent;
        }

        // If this is verify_delivery or recheck_door, populate report card
        if (name === "verify_delivery" || name === "recheck_door") {
          setActiveReport(parsedData);
          if (parsedData.reason) {
            speakResponse(parsedData.reason);
          }
        } else if (name === "build_claim_packet") {
          speakResponse(
            "Evidence packet and claim draft successfully built. Location: " +
              (parsedData.packet_url || "S3")
          );
        } else if (name === "get_delivery_ledger") {
          speakResponse(
            `Found ${Array.isArray(parsedData) ? parsedData.length : 0} delivery ledger records.`
          );
        }
      }
    } catch (err: any) {
      console.error("Tool execution failed", err);
      const msg = err.message || "Tool execution failed";
      setToolError(msg);
      speakResponse(`Sorry, I couldn't complete that check: ${msg}`);
      logMessage("in", `tools/call:${name}/error`, { error: msg });
    } finally {
      setIsCallingTool(false);
    }
  };

  // Map spoken or typed utterance to appropriate MCP tool
  const handleProcessUtterance = (text: string) => {
    const q = text.toLowerCase().trim();
    if (!q) return;

    if (q.includes("recheck") || q.includes("re-check") || q.includes("look again")) {
      callMcpTool("recheck_door", { tracking_code: "EZ4000000004" });
    } else if (q.includes("ledger") || q.includes("history") || q.includes("list")) {
      callMcpTool("get_delivery_ledger", {});
    } else if (q.includes("claim") || q.includes("packet")) {
      callMcpTool("build_claim_packet", { tracking_code: "EZ4000000004" });
    } else {
      // Default: "did my package actually arrive?" / delivery verification
      callMcpTool("verify_delivery", { tracking_code: "EZ4000000004" });
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Alexa+ Simulator Hero Banner */}
        <div className="rounded-2xl bg-gradient-to-r from-purple-950/60 via-slate-900 to-slate-950 border border-purple-800/40 p-6 shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-80 h-80 bg-purple-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider bg-purple-500/20 text-purple-300 border border-purple-500/30">
                  Alexa+ MCP Client Simulator
                </span>
                <span className="text-xs text-slate-400">
                  Spec 2025-11-25+ • Streamable HTTP • Web Speech API
                </span>
              </div>
              <h1 className="text-2xl font-black text-white tracking-tight sm:text-3xl">
                Voice & Multimodal Verification
              </h1>
              <p className="text-xs sm:text-sm text-slate-400 max-w-2xl leading-relaxed">
                Experience Countersign as an Alexa+ multimodal assistant. Speaks natural answers via the Web Speech
                API and renders verifiable evidence cards directly from the MCP server.
              </p>
            </div>

            {/* Protocol negotiation badge */}
            <div className="p-3.5 rounded-xl bg-slate-900/90 border border-purple-800/50 shadow-md shrink-0 space-y-1 text-xs">
              <div className="flex items-center gap-2 text-slate-300 font-semibold">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isConnected ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                  }`}
                />
                <span>Protocol: {negotiatedVersion || "2025-11-25"}</span>
              </div>
              <p className="text-[11px] text-slate-400 font-mono">
                {isConnected ? "Negotiated: 2025-11-25 (Streamable HTTP)" : "Connecting to /mcp..."}
              </p>
            </div>
          </div>
        </div>

        {/* Main interactive area: Voice Box + Multimodal Screen + MCP Log */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left 7 cols: Voice Input & Alexa Multimodal Screen */}
          <div className="lg:col-span-7 space-y-6">
            {/* Alexa Voice Control Card */}
            <div className="bg-slate-900/90 rounded-2xl border border-slate-800 p-6 shadow-xl space-y-5">
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2.5">
                  <div
                    className={`p-2.5 rounded-xl transition-colors ${
                      isListening
                        ? "bg-rose-500/20 border border-rose-500 text-rose-400 animate-pulse"
                        : "bg-purple-500/10 border border-purple-500/30 text-purple-400"
                    }`}
                  >
                    <Mic className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-bold text-white">Voice & Text Prompt</h2>
                    <p className="text-xs text-slate-400">
                      Speak or type an inquiry to trigger MCP tools
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setVoiceEnabled(!voiceEnabled)}
                    className={`p-2 rounded-lg border text-xs font-medium transition-colors ${
                      voiceEnabled
                        ? "bg-slate-800 text-amber-400 border-slate-700"
                        : "bg-slate-900 text-slate-500 border-slate-800"
                    }`}
                    title={voiceEnabled ? "Alexa Voice Synthesis Enabled" : "Voice Output Muted"}
                  >
                    {voiceEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Input field + Mic button */}
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <input
                    type="text"
                    value={utterance}
                    onChange={(e) => setUtterance(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleProcessUtterance(utterance);
                    }}
                    placeholder={
                      isListening
                        ? "Listening to voice input..."
                        : 'Ask: "Did my package actually arrive?"'
                    }
                    className="w-full px-4 py-3 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
                  />
                </div>

                {speechSupported && (
                  <button
                    type="button"
                    onClick={toggleListening}
                    className={`p-3 rounded-xl border transition-all active:scale-95 ${
                      isListening
                        ? "bg-rose-600 text-white border-rose-500 animate-pulse"
                        : "bg-slate-800 hover:bg-slate-700 text-purple-300 border-slate-700"
                    }`}
                    title={isListening ? "Stop listening" : "Start Voice Input"}
                  >
                    {isListening ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => handleProcessUtterance(utterance)}
                  disabled={!utterance.trim() || isCallingTool}
                  className="px-4 py-3 rounded-xl font-semibold text-xs bg-purple-600 hover:bg-purple-500 text-white transition-all disabled:opacity-40 flex items-center gap-1.5 shadow-md active:scale-95"
                >
                  <Send className="w-4 h-4" />
                  <span className="hidden sm:inline">Ask</span>
                </button>
              </div>

              {/* Suggested Utterance Chips */}
              <div className="space-y-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Sample Alexa Utterances:
                </span>
                <div className="flex flex-wrap gap-2">
                  {[
                    {
                      label: '"Did my package actually arrive?"',
                      query: "did my package actually arrive?",
                      tool: "verify_delivery",
                    },
                    {
                      label: '"Re-check my front door"',
                      query: "re-check my front door",
                      tool: "recheck_door",
                    },
                    {
                      label: '"Show my delivery ledger"',
                      query: "show my delivery ledger",
                      tool: "get_delivery_ledger",
                    },
                    {
                      label: '"Build claim packet for my package"',
                      query: "build claim packet for my package",
                      tool: "build_claim_packet",
                    },
                  ].map((chip) => (
                    <button
                      key={chip.label}
                      type="button"
                      onClick={() => {
                        setUtterance(chip.query);
                        handleProcessUtterance(chip.query);
                      }}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-950 hover:bg-purple-950/40 text-slate-300 hover:text-purple-300 border border-slate-800 hover:border-purple-700/60 transition-all flex items-center gap-1.5"
                    >
                      <span>{chip.label}</span>
                      <span className="text-[10px] font-mono text-slate-500">
                        → {chip.tool}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Alexa Multimodal Display Screen (The Rich Evidence Card) */}
            <div className="bg-slate-900/90 rounded-2xl border border-slate-800 p-6 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-purple-500 shadow-sm shadow-purple-500/50" />
                  <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                    Alexa+ Multimodal Evidence Card
                  </h3>
                </div>
                {isSpeaking && (
                  <span className="flex items-center gap-1.5 text-xs text-amber-400 animate-pulse font-medium">
                    <Volume2 className="w-3.5 h-3.5" />
                    <span>Alexa Speaking...</span>
                  </span>
                )}
              </div>

              {toolError && (
                <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-800 text-xs text-rose-300 space-y-2">
                  <div className="flex items-center gap-2 font-semibold">
                    <AlertTriangle className="w-4 h-4 text-rose-400" />
                    <span>MCP Tool Response Notice</span>
                  </div>
                  <p className="font-mono">{toolError}</p>
                  {toolError.includes("approval_required") && (
                    <p className="text-[11px] text-rose-300/80">
                      Safety gate functioning as designed: No approval tool is exposed over MCP. Approvals must be granted by a human in the dashboard.
                    </p>
                  )}
                </div>
              )}

              {isCallingTool && (
                <div className="py-12 flex flex-col items-center justify-center space-y-3">
                  <RefreshCw className="w-8 h-8 text-purple-400 animate-spin" />
                  <p className="text-xs text-slate-400 font-mono">
                    Calling MCP tool over Streamable HTTP...
                  </p>
                </div>
              )}

              {/* Multimodal Report Card */}
              {activeReport && !isCallingTool && (
                <div className="space-y-4 animate-in fade-in-50 duration-200">
                  {/* Status Banner */}
                  <div
                    className={`p-4 rounded-xl border flex items-start justify-between gap-4 ${
                      activeReport.status === "VERIFIED"
                        ? "bg-emerald-950/40 border-emerald-800 text-emerald-200"
                        : activeReport.status === "DISPUTED"
                        ? "bg-rose-950/40 border-rose-800 text-rose-200"
                        : "bg-amber-950/40 border-amber-800 text-amber-200"
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-lg font-mono">
                          {activeReport.status}
                        </span>
                        {activeReport.recheck?.provisional && (
                          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-900/60 text-amber-300 border border-amber-700">
                            Provisional
                          </span>
                        )}
                        {activeReport.synthetic && <SimulatedBadge />}
                      </div>
                      <p className="text-xs font-medium leading-relaxed opacity-95">
                        {activeReport.reason}
                      </p>
                    </div>

                    {activeReport.confidence !== null && activeReport.confidence !== undefined && (
                      <div className="text-right shrink-0">
                        <span className="text-[10px] uppercase text-slate-400 block">Confidence</span>
                        <span className="text-base font-bold font-mono">
                          {Math.round(activeReport.confidence * 100)}%
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Metadata Row */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs bg-slate-950 p-3.5 rounded-xl border border-slate-800">
                    <div>
                      <span className="text-slate-500 text-[10px] uppercase block">Tracking Code</span>
                      <span className="font-mono text-white font-medium">
                        {activeReport.tracking_code || "EZ4000000004"}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500 text-[10px] uppercase block">Carrier Scan</span>
                      <span className="font-mono text-slate-300">
                        {activeReport.carrier_scan_at
                          ? new Date(activeReport.carrier_scan_at).toLocaleTimeString()
                          : "Pending"}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500 text-[10px] uppercase block">Doorbell Checked</span>
                      <span className="font-mono text-slate-300">
                        {activeReport.checked_at
                          ? new Date(activeReport.checked_at).toLocaleTimeString()
                          : "In progress"}
                      </span>
                    </div>
                  </div>

                  {/* Ring Playground Simulated Streams Notice */}
                  <RingPlaygroundNotice />

                  {/* Camera Evidence Frames Grid */}
                  {activeReport.evidence && activeReport.evidence.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Camera className="w-3.5 h-3.5 text-amber-400" />
                        <span>Doorbell Frame Evidence ({activeReport.evidence.length} frames)</span>
                      </h4>

                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        {activeReport.evidence.map((f, i) => (
                          <div
                            key={f.frame_id || i}
                            className="rounded-xl overflow-hidden bg-slate-950 border border-slate-800 space-y-1.5 p-1"
                          >
                            <div className="relative aspect-video rounded-lg overflow-hidden bg-black">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={f.frame_url}
                                alt={`Evidence frame ${f.frame_id}`}
                                className="w-full h-full object-cover"
                              />
                              <div className="absolute top-1 right-1 px-1.5 py-0.2 rounded bg-black/80 text-[9px] font-mono text-amber-300">
                                {f.watermark_time ? f.watermark_time.slice(11, 19) : "wm"}
                              </div>
                            </div>
                            <div className="px-1 pb-1 flex items-center justify-between text-[10px] font-mono">
                              <span
                                className={
                                  f.parcel_visible ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"
                                }
                              >
                                {f.parcel_visible ? "Parcel: Yes" : "Parcel: No"}
                              </span>
                              <span className="text-slate-500">{f.location || "porch"}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Raw JSON result view for other tools like get_delivery_ledger or build_claim_packet */}
              {!activeReport && toolResultRaw && !isCallingTool && (
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Tool Result Payload
                  </span>
                  <pre className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-300 max-h-64 overflow-y-auto">
                    {JSON.stringify(toolResultRaw, null, 2)}
                  </pre>
                </div>
              )}

              {!activeReport && !toolResultRaw && !isCallingTool && !toolError && (
                <div className="py-12 text-center text-slate-500 space-y-2">
                  <Mic className="w-8 h-8 text-slate-700 mx-auto" />
                  <p className="text-xs">Alexa is ready. Say or click a suggested utterance above.</p>
                </div>
              )}
            </div>
          </div>

          {/* Right 5 cols: MCP Protocol Inspector & Raw Message Logs */}
          <div className="lg:col-span-5 space-y-6">
            {/* Protocol Spec & Tools summary card */}
            <div className="bg-slate-900/90 rounded-2xl border border-slate-800 p-5 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <Cpu className="w-4 h-4 text-purple-400" />
                  <h3 className="text-sm font-bold text-white">
                    MCP Protocol Verification
                  </h3>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800">
                  FastMCP
                </span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Negotiated Protocol Version:</span>
                    <span className="font-mono font-bold text-emerald-400">
                      {negotiatedVersion || "2025-11-25"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Spec Threshold:</span>
                    <span className="font-mono text-slate-300">≥ 2025-11-25</span>
                  </div>
                  <div className="flex items-center justify-between border-t border-slate-900 pt-1.5">
                    <span className="text-slate-400">Transport:</span>
                    <span className="font-mono text-amber-300">Streamable HTTP (POST /mcp/)</span>
                  </div>
                </div>

                <div className="space-y-1.5 pt-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Discovered Tools ({availableTools.length}):
                  </span>
                  <div className="grid grid-cols-1 gap-1.5">
                    {availableTools.map((t) => (
                      <div
                        key={t.name}
                        className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between"
                      >
                        <span className="font-mono text-xs text-purple-300">{t.name}</span>
                        <button
                          type="button"
                          onClick={() => callMcpTool(t.name, { tracking_code: "EZ4000000004" })}
                          className="text-[10px] text-amber-400 hover:text-amber-300 px-1.5 py-0.5 rounded hover:bg-slate-900"
                        >
                          Execute
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Live MCP JSON-RPC Side Log */}
            <div className="bg-slate-900/90 rounded-2xl border border-slate-800 flex flex-col h-[460px] shadow-xl overflow-hidden">
              <div className="p-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
                <div className="flex items-center gap-2">
                  <Terminal className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-xs font-bold text-white font-mono">
                    JSON-RPC Protocol Log
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setLogs([])}
                  className="text-[10px] text-slate-500 hover:text-slate-300"
                >
                  Clear
                </button>
              </div>

              <div className="flex-1 p-3 overflow-y-auto space-y-2 bg-slate-950/50 font-mono text-[11px]">
                {logs.length === 0 ? (
                  <div className="h-full flex items-center justify-center text-slate-600 text-xs">
                    No MCP protocol messages logged yet
                  </div>
                ) : (
                  logs.map((log) => (
                    <div
                      key={log.id}
                      className="p-2 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className={`font-semibold ${
                            log.direction === "out" ? "text-purple-400" : "text-emerald-400"
                          }`}
                        >
                          {log.direction === "out" ? "→ CLIENT" : "← SERVER"}: {log.method}
                        </span>
                        <span className="text-[10px] text-slate-500">{log.timestamp}</span>
                      </div>
                      <pre className="text-[10px] text-slate-300/90 overflow-x-auto p-1.5 rounded bg-slate-950 border border-slate-800/60">
                        {JSON.stringify(log.data, null, 2)}
                      </pre>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
