"use client"

import React, { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import {
  Layers,
  ShieldCheck,
  ArrowRight,
  Lock,
  GitCommit,
  GitPullRequest,
  FileCode,
  FileText,
  ChevronDown,
  Clock,
  Play,
  HelpCircle,
  BarChart3,
  RefreshCw,
  FolderGit2,
  Workflow,
  CheckCircle2,
  Scale,
  Terminal,
  Activity,
  Database
} from "lucide-react"

function HeroKnowledgeMotion() {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null)
  const containerRef = React.useRef<HTMLDivElement | null>(null)
  const mouseRef = React.useRef<{ x: number; y: number }>({ x: -9999, y: -9999 })

  React.useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let animationFrameId: number
    let width = 0
    let height = 0

    interface GraphNode {
      x: number
      y: number
      vx: number
      vy: number
      radius: number
      color: string
      pulse: number
      pulseSpeed: number
    }

    const nodeColors = [
      "#7C3AED", // violet
      "#8B5CF6", // purple
      "#6366F1", // indigo
      "#4F46E5", // deep indigo
      "#A855F7", // soft purple
      "#0284C7"  // subtle tech sky
    ]

    let nodes: GraphNode[] = []

    const initNodes = (w: number, h: number) => {
      const count = Math.max(26, Math.min(48, Math.floor(w / 30)))
      nodes = []
      for (let i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.45,
          vy: (Math.random() - 0.5) * 0.45,
          radius: Math.random() * 2 + 1.6,
          color: nodeColors[Math.floor(Math.random() * nodeColors.length)],
          pulse: Math.random() * Math.PI * 2,
          pulseSpeed: 0.02 + Math.random() * 0.03
        })
      }
    }

    const handleResize = () => {
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      width = rect.width
      height = rect.height
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.scale(dpr, dpr)
      initNodes(width, height)
    }

    handleResize()
    window.addEventListener("resize", handleResize)

    const handleMouseMove = (e: MouseEvent) => {
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      mouseRef.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      }
    }

    const handleMouseLeave = () => {
      mouseRef.current = { x: -9999, y: -9999 }
    }

    const parent = canvas.parentElement
    if (parent) {
      parent.addEventListener("mousemove", handleMouseMove)
      parent.addEventListener("mouseleave", handleMouseLeave)
    }

    const render = () => {
      ctx.clearRect(0, 0, width, height)

      const maxDist = 120
      const mouseMaxDist = 150

      for (let i = 0; i < nodes.length; i++) {
        const n1 = nodes[i]

        // Connect nearby nodes
        for (let j = i + 1; j < nodes.length; j++) {
          const n2 = nodes[j]
          const dx = n1.x - n2.x
          const dy = n1.y - n2.y
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist < maxDist) {
            const alpha = (1 - dist / maxDist) * 0.18
            ctx.beginPath()
            ctx.moveTo(n1.x, n1.y)
            ctx.lineTo(n2.x, n2.y)
            ctx.strokeStyle = `rgba(124, 58, 237, ${alpha})`
            ctx.lineWidth = 1
            ctx.stroke()
          }
        }

        // Connect to mouse cursor with magnetic pull
        const mdx = n1.x - mouseRef.current.x
        const mdy = n1.y - mouseRef.current.y
        const mdist = Math.sqrt(mdx * mdx + mdy * mdy)
        if (mdist < mouseMaxDist) {
          const alpha = (1 - mdist / mouseMaxDist) * 0.35
          ctx.beginPath()
          ctx.moveTo(n1.x, n1.y)
          ctx.lineTo(mouseRef.current.x, mouseRef.current.y)
          ctx.strokeStyle = `rgba(99, 102, 241, ${alpha})`
          ctx.lineWidth = 1.2
          ctx.stroke()

          n1.vx -= (mdx / mdist) * 0.018
          n1.vy -= (mdy / mdist) * 0.018
        }

        // Advance positions
        n1.x += n1.vx
        n1.y += n1.vy

        // Wrap boundaries softly
        if (n1.x < -10) n1.x = width + 10
        if (n1.x > width + 10) n1.x = -10
        if (n1.y < -10) n1.y = height + 10
        if (n1.y > height + 10) n1.y = -10

        // Speed dampening
        n1.vx *= 0.99
        n1.vy *= 0.99

        // Pulse
        n1.pulse += n1.pulseSpeed
        const currentRadius = n1.radius + Math.sin(n1.pulse) * 0.5

        // Draw node with soft ambient glow
        ctx.beginPath()
        ctx.arc(n1.x, n1.y, Math.max(0.8, currentRadius), 0, Math.PI * 2)
        ctx.fillStyle = n1.color
        ctx.shadowColor = n1.color
        ctx.shadowBlur = 6
        ctx.fill()
        ctx.shadowBlur = 0
      }

      animationFrameId = requestAnimationFrame(render)
    }

    render()

    return () => {
      cancelAnimationFrame(animationFrameId)
      window.removeEventListener("resize", handleResize)
      if (parent) {
        parent.removeEventListener("mousemove", handleMouseMove)
        parent.removeEventListener("mouseleave", handleMouseLeave)
      }
    }
  }, [])

  return (
    <div ref={containerRef} className="absolute inset-0 pointer-events-none overflow-hidden select-none">
      {/* Ambient Pulsing & Orbiting Glow Orbs */}
      <div className="absolute -top-32 left-1/4 w-[540px] h-[540px] rounded-full bg-gradient-to-tr from-violet-400/20 via-purple-300/12 to-transparent blur-[95px] animate-orbit-slow" />
      <div
        className="absolute -top-24 right-1/12 w-[480px] h-[480px] rounded-full bg-gradient-to-bl from-indigo-400/18 via-violet-400/10 to-transparent blur-[85px] animate-orbit-slow"
        style={{ animationDirection: "reverse", animationDuration: "25s" }}
      />
      <div className="absolute -bottom-20 left-1/2 -translate-x-1/2 w-[650px] h-[260px] rounded-full bg-violet-300/15 blur-[85px] animate-pulse-glow" />

      {/* Engineering Technical Grid with Vignette Mask */}
      <div
        className="absolute inset-0 bg-[radial-gradient(#7c3aed_1.2px,transparent_1.2px)] [background-size:28px_28px] opacity-[0.09]"
        style={{
          maskImage: "radial-gradient(ellipse 70% 60% at 50% 42%, black 25%, transparent 80%)",
          WebkitMaskImage: "radial-gradient(ellipse 70% 60% at 50% 42%, black 25%, transparent 80%)"
        }}
      />

      {/* Interactive Topology Graph Canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />

      {/* Floating Micro-Telemetry Badges in Peripheral Space (Desktop Only) */}
      <div className="absolute left-6 xl:left-14 top-24 hidden lg:flex items-center gap-2.5 px-3.5 py-2 rounded-2xl bg-white/80 backdrop-blur-md border border-violet-100 shadow-sm shadow-violet-900/5 text-xs text-slate-700 animate-float-slow">
        <div className="w-2 h-2 rounded-full bg-emerald-500 ring-4 ring-emerald-100" />
        <GitCommit className="w-3.5 h-3.5 text-violet-600" />
        <span className="font-bold text-slate-900">14,820</span>
        <span className="text-slate-500">Commits Parsed</span>
      </div>

      <div
        className="absolute left-8 xl:left-16 bottom-28 hidden lg:flex items-center gap-2.5 px-3.5 py-2 rounded-2xl bg-white/80 backdrop-blur-md border border-violet-100 shadow-sm shadow-violet-900/5 text-xs text-slate-700 animate-float-reverse"
        style={{ animationDelay: "1.4s" }}
      >
        <div className="w-2 h-2 rounded-full bg-violet-500 ring-4 ring-violet-100" />
        <Lock className="w-3.5 h-3.5 text-violet-600" />
        <span className="font-bold text-slate-900">SHA-256</span>
        <span className="text-slate-500">Ledger Verified</span>
      </div>

      <div
        className="absolute right-6 xl:right-14 top-24 hidden lg:flex items-center gap-2.5 px-3.5 py-2 rounded-2xl bg-white/80 backdrop-blur-md border border-violet-100 shadow-sm shadow-violet-900/5 text-xs text-slate-700 animate-float-reverse"
        style={{ animationDelay: "0.7s" }}
      >
        <div className="w-2 h-2 rounded-full bg-purple-500 ring-4 ring-purple-100" />
        <Workflow className="w-3.5 h-3.5 text-purple-600" />
        <span className="font-bold text-slate-900">16 / 16</span>
        <span className="text-slate-500">Sections Synced</span>
      </div>

      <div
        className="absolute right-8 xl:right-16 bottom-28 hidden lg:flex items-center gap-2.5 px-3.5 py-2 rounded-2xl bg-white/80 backdrop-blur-md border border-violet-100 shadow-sm shadow-violet-900/5 text-xs text-slate-700 animate-float-slow"
        style={{ animationDelay: "2.1s" }}
      >
        <div className="w-2 h-2 rounded-full bg-indigo-500 ring-4 ring-indigo-100" />
        <ShieldCheck className="w-3.5 h-3.5 text-indigo-600" />
        <span className="font-bold text-slate-900">RLS Isolated</span>
        <span className="text-slate-500">Zero Leakage</span>
      </div>
    </div>
  )
}

export default function LandingPage() {
  const router = useRouter()
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [activeStudioTab, setActiveStudioTab] = useState<"dossier" | "graph" | "evidence" | "simulator">("dossier")
  const [selectedSection, setSelectedSection] = useState<"summary" | "architecture" | "adr" | "tasks" | "roadmap">("summary")
  const [calculatorTier, setCalculatorTier] = useState<"small" | "mid" | "enterprise">("mid")
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [simRunning, setSimRunning] = useState(false)
  const [simStep, setSimStep] = useState(1)
  const [heroConsoleTab, setHeroConsoleTab] = useState<"terminal" | "adrs" | "readiness">("terminal")

  useEffect(() => {
    const hasAuth = Boolean(
      localStorage.getItem("obsidian_authenticated") ||
      localStorage.getItem("obsidian_user") ||
      localStorage.getItem("obsidian_token")
    )
    setIsAuthenticated(hasAuth)
  }, [])

  const goProtected = (path: string) => {
    if (isAuthenticated) {
      router.push(path === "/" ? "/dashboard" : path)
    } else {
      router.push("/login")
    }
  }

  const runSimulation = () => {
    setSimRunning(true)
    setSimStep(1)
    setTimeout(() => setSimStep(2), 1100)
    setTimeout(() => setSimStep(3), 2300)
    setTimeout(() => {
      setSimStep(4)
      setSimRunning(false)
    }, 3600)
  }

  const calculatorValues = {
    small: { devs: "15 Engineers", turnover: "3 departures/yr", ramp: "72% faster", savings: "$64,000 / yr" },
    mid: { devs: "75 Engineers", turnover: "12 departures/yr", ramp: "84% faster", savings: "$280,000 / yr" },
    enterprise: { devs: "250+ Engineers", turnover: "35+ departures/yr", ramp: "91% faster", savings: "$890,000 / yr" },
  }

  const faqs = [
    {
      q: "How does Team Obsidian reconstruct institutional knowledge without manual documentation?",
      a: "Obsidian connects directly via read-only integrations to your existing engineering systems: GitHub, GitLab, Slack, Jira, Confluence, and Notion. It analyzes commit histories, PR discussions, incident threads, and architectural review channels. Using contextual NLP and dependency parsing, it reconstructs architectural decisions (ADRs), unassigned ownerships, and critical operational knowledge into an audit-ready 16-section dossier automatically."
    },
    {
      q: "What is the 16-Section Autonomous Handover Dossier standard?",
      a: "It is an engineering governance standard covering: 1. Executive Summary, 2. System Architecture & Topology, 3. Architectural Decision Records (ADRs), 4. Critical Dependencies, 5. In-Flight Tasks & WIP, 6. Single-Points-of-Failure (SPOFs), 7. Knowledge Gap Heatmap, 8. Incident History & Playbooks, 9. External Integrations & API Credentials, 10. Security & Compliance Mandates, 11. Testing & Deployment Verification, 12. Successor 30-Day Onboarding Roadmap, 13. Cryptographic Evidence Ledger, 14. Formal Multi-Stakeholder Sign-Off, 15. Continuous Sync Log, and 16. Offline Export Archive."
    },
    {
      q: "Is our proprietary codebase and private company communication secure?",
      a: "Yes. Team Obsidian enforces strict enterprise security: PostgreSQL Row Level Security (RLS) ensures total workspace isolation, all communications are encrypted with TLS 1.3 in transit and AES-256 at rest, token revoking is tracked via memory-cached JTI validation, and your data is never used to train public foundation models."
    },
    {
      q: "What is the Successor Simulator feature?",
      a: "Before the transitioning specialist leaves the organization, Team Obsidian runs an automated 'dry-run' simulation. It poses real-world production incident scenarios, rollback steps, and architectural queries to the incoming successor. It scores successor readiness and highlights unresolved knowledge gaps while the offboarding engineer is still accessible for clarification."
    },
    {
      q: "Can we export the synthesized dossiers for compliance and audit requirements?",
      a: "Yes. Every dossier can be exported in one click to cryptographically signed Markdown, audit-ready PDF, or synced back directly into GitHub repositories or Confluence spaces."
    }
  ]

  return (
    <div className="min-h-screen bg-[#F8F9FD] text-slate-900 selection:bg-violet-100 selection:text-violet-900 relative font-sans">
      {/* Top Navbar */}
      <header className="max-w-7xl mx-auto px-6 h-18 flex items-center justify-between border-b border-slate-200/80 bg-white/80 backdrop-blur-md sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-[#1E1238] to-[#3B1A7A] p-2 flex items-center justify-center shadow-md shadow-purple-900/10">
            <Layers className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-sm tracking-tight text-slate-900">TEAM OBSIDIAN</span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 border border-violet-200">
                v2.4
              </span>
            </div>
            <p className="text-[10px] text-slate-500 hidden sm:block">Autonomous Knowledge Reconstruction</p>
          </div>
        </div>

        {/* Center Nav Links */}
        <nav className="hidden md:flex items-center gap-7 text-xs font-semibold text-slate-600">
          <a href="#studio" className="hover:text-slate-900 transition-colors">Handover Studio</a>
          <a href="#comparison" className="hover:text-slate-900 transition-colors">Why Obsidian</a>
          <a href="#calculator" className="hover:text-slate-900 transition-colors">ROI Calculator</a>
          <a href="#faq" className="hover:text-slate-900 transition-colors">FAQ</a>
        </nav>

        {/* Auth Actions */}
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <button
              onClick={() => router.push("/dashboard")}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-2 shadow-sm transition-all"
            >
              <span>Go to Dashboard</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <>
              <button
                onClick={() => router.push("/login")}
                className="text-xs font-semibold text-slate-600 hover:text-slate-900 px-3 py-1.5 transition-colors"
              >
                Sign In
              </button>
              <button
                onClick={() => router.push("/register")}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-2 shadow-sm transition-all"
              >
                <span>Launch Platform</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
      </header>

      {/* Hero Section with Motion Background (Hero Section Only) */}
      <section className="relative overflow-hidden border-b border-slate-200/60 bg-gradient-to-b from-white via-violet-50/25 to-[#F8F9FD]">
        <HeroKnowledgeMotion />

        <div className="max-w-5xl mx-auto px-6 pt-16 sm:pt-20 pb-16 text-center space-y-6 relative z-10">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-violet-50/90 backdrop-blur-md border border-violet-200 text-xs text-violet-700 font-semibold shadow-sm">
            <span>The Autonomous Knowledge Handover Platform</span>
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-slate-900 leading-[1.15]">
            Zero Knowledge Loss When <br className="hidden sm:inline" />
            <span className="bg-gradient-to-r from-violet-700 via-purple-700 to-indigo-700 bg-clip-text text-transparent">
              Specialists Transition
            </span>
          </h1>

          <p className="text-sm sm:text-base text-slate-600 max-w-2xl mx-auto leading-relaxed">
            Autonomous institutional memory reconstruction across GitHub, Slack, Notion, and uploaded Project Documents. Synthesizes verified, audit-ready 16-section handover dossiers with cryptographic evidence.
          </p>

          {/* Action Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
            <button
              onClick={() => goProtected("/dashboard")}
              className="w-full sm:w-auto px-6 py-3 rounded-xl text-xs font-bold bg-violet-600 hover:bg-violet-700 text-white flex items-center justify-center gap-2 shadow-md shadow-violet-600/20 transition-all hover:scale-[1.02]"
            >
              <span>Enter Enterprise Workspace</span>
              <ArrowRight className="w-4 h-4" />
            </button>
            <a
              href="#studio"
              className="w-full sm:w-auto px-6 py-3 rounded-xl text-xs font-bold bg-white/90 backdrop-blur-md hover:bg-white text-slate-800 border border-slate-200/90 flex items-center justify-center gap-2 shadow-sm transition-all"
            >
              <Play className="w-3.5 h-3.5 text-violet-600 fill-violet-600" />
              <span>View Handover Dossier</span>
            </a>
          </div>

          {/* Autonomous Ingestion Ecosystem Strip */}
          <div className="pt-2 pb-1 flex flex-wrap items-center justify-center gap-2 sm:gap-4 text-[11px] text-slate-500 font-medium">
            <span className="text-slate-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Ingesting live from
            </span>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-1 rounded-lg bg-white/80 border border-slate-200/90 shadow-2xs text-slate-700 flex items-center gap-1.5 font-semibold">
                <FolderGit2 className="w-3 h-3 text-slate-600" /> GitHub / GitLab
              </span>
              <span className="px-2.5 py-1 rounded-lg bg-white/80 border border-slate-200/90 shadow-2xs text-slate-700 flex items-center gap-1.5 font-semibold">
                <Workflow className="w-3 h-3 text-violet-600" /> Slack & Teams
              </span>
              <span className="px-2.5 py-1 rounded-lg bg-white/80 border border-slate-200/90 shadow-2xs text-slate-700 flex items-center gap-1.5 font-semibold">
                <FileText className="w-3 h-3 text-indigo-600" /> Notion & Confluence
              </span>
              <span className="px-2.5 py-1 rounded-lg bg-white/80 border border-slate-200/90 shadow-2xs text-slate-700 flex items-center gap-1.5 font-semibold hidden sm:flex">
                <Database className="w-3 h-3 text-purple-600" /> PostgreSQL Schema
              </span>
            </div>
          </div>

          {/* Hero Live Autonomous Console Preview (Theme & Vibes) */}
          <div className="pt-3 text-left">
            <div className="rounded-2xl border border-slate-800/90 bg-[#0B0F19] text-slate-100 shadow-2xl shadow-purple-950/25 overflow-hidden backdrop-blur-xl">
              {/* Terminal Window Header */}
              <div className="px-4 py-3 bg-[#111625] border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
                    <span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
                    <span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
                  </div>
                  <div className="h-4 w-px bg-slate-800 hidden sm:block" />
                  <div className="flex items-center gap-2">
                    <Terminal className="w-3.5 h-3.5 text-violet-400" />
                    <span className="font-mono text-xs text-slate-300 font-semibold tracking-tight">
                      obsidian-handover-protocol.sh
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 font-mono text-[10px] font-medium hidden sm:inline-flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      LIVE RECONSTRUCTION
                    </span>
                  </div>
                </div>

                {/* Console Tabs */}
                <div className="flex items-center gap-1 bg-[#090D16] p-1 rounded-xl border border-slate-800 text-[11px] font-medium">
                  <button
                    onClick={() => setHeroConsoleTab("terminal")}
                    className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                      heroConsoleTab === "terminal"
                        ? "bg-violet-600 text-white shadow-sm font-semibold"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Terminal className="w-3 h-3" />
                    <span>Protocol Execution</span>
                  </button>
                  <button
                    onClick={() => setHeroConsoleTab("adrs")}
                    className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                      heroConsoleTab === "adrs"
                        ? "bg-violet-600 text-white shadow-sm font-semibold"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <FileCode className="w-3 h-3" />
                    <span>Synthesized ADRs (42)</span>
                  </button>
                  <button
                    onClick={() => setHeroConsoleTab("readiness")}
                    className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                      heroConsoleTab === "readiness"
                        ? "bg-violet-600 text-white shadow-sm font-semibold"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Activity className="w-3 h-3" />
                    <span>Successor Audit</span>
                  </button>
                </div>
              </div>

              {/* Console Body */}
              <div className="p-4 sm:p-5 font-mono text-xs">
                {heroConsoleTab === "terminal" && (
                  <div className="space-y-2.5 text-slate-300">
                    <div className="flex items-center justify-between pb-2 border-b border-slate-800/80 text-[11px] text-slate-500 font-sans">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-400 font-semibold">TARGET SPECIALIST:</span>
                        <span className="text-violet-400 font-mono">@staff-infra-architect</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span>WORKSPACE: <strong className="text-slate-300">production-cluster-eu</strong></span>
                        <span className="text-emerald-400 font-medium">100% INGESTION COVERAGE</span>
                      </div>
                    </div>

                    <p className="text-slate-400">
                      <span className="text-violet-400">$</span> obsidian transition run --target=@staff-infra-architect --output=audit-ready
                    </p>
                    <div className="space-y-1.5 pl-2 text-slate-400 text-[11px] sm:text-xs">
                      <div className="flex items-start gap-2">
                        <span className="text-emerald-400 font-bold">[OK]</span>
                        <span>[00:01.1] Ingested 14,820 commits across 3 active repositories (auth-service, data-pipeline, edge-gw).</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="text-emerald-400 font-bold">[OK]</span>
                        <span>[00:02.4] Parsed 342 architectural discussion threads & RFCs; resolved 42 Architectural Decisions (ADRs).</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="text-emerald-400 font-bold">[OK]</span>
                        <span>[00:03.2] Mapped runtime service topology: 12 microservices, 4 queue workers, PostgreSQL RLS boundaries.</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="text-amber-400 font-bold">[WARN]</span>
                        <span>[00:03.9] Detected 2 Single-Points-of-Failure in DNS failover logic. Auto-generated successor runbook.</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="text-emerald-400 font-bold">[OK]</span>
                        <span>[00:04.6] Cryptographic hash calculated: <span className="text-violet-300">SHA-256 (3b8f2d...91a4)</span> - Verified immutable.</span>
                      </div>
                      <div className="flex items-start gap-2 text-violet-300 font-semibold pt-1">
                        <span className="text-emerald-400 font-bold">[READY]</span>
                        <span>Autonomous Handover Dossier v2.4 successfully synthesized. 16/16 sections sealed.</span>
                      </div>
                    </div>
                  </div>
                )}

                {heroConsoleTab === "adrs" && (
                  <div className="space-y-3 font-sans">
                    <div className="text-[11px] text-slate-400 font-mono flex items-center justify-between pb-1 border-b border-slate-800">
                      <span>AUTOMATICALLY EXTRACTED FROM COMMIT DIFFS & PR REVIEWS</span>
                      <span className="text-violet-400 font-semibold">42 ADRS TOTAL</span>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="p-3.5 rounded-xl bg-[#13192B] border border-slate-800 space-y-1.5 hover:border-violet-500/40 transition-colors">
                        <div className="flex items-center justify-between">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-violet-500/20 text-violet-300 font-bold">
                            ADR-041
                          </span>
                          <span className="text-[10px] text-slate-400 font-mono">PR #892 (Merged)</span>
                        </div>
                        <h4 className="text-xs font-bold text-slate-200">
                          Transition from REST to gRPC for Internal Edge Services
                        </h4>
                        <p className="text-[11px] text-slate-400 leading-relaxed">
                          Decision by @staff-infra-architect. Latency dropped from 48ms to 6ms under 20k rps peak load.
                        </p>
                        <div className="pt-1 flex items-center gap-2 text-[10px] text-slate-500 font-mono">
                          <span className="text-emerald-400">Verified</span>
                          <span>Proof: sha256:4b2e...9a12</span>
                        </div>
                      </div>

                      <div className="p-3.5 rounded-xl bg-[#13192B] border border-slate-800 space-y-1.5 hover:border-violet-500/40 transition-colors">
                        <div className="flex items-center justify-between">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-purple-500/20 text-purple-300 font-bold">
                            ADR-038
                          </span>
                          <span className="text-[10px] text-slate-400 font-mono">RFC #24 (Approved)</span>
                        </div>
                        <h4 className="text-xs font-bold text-slate-200">
                          PostgreSQL Row Level Security Tenant Boundary Model
                        </h4>
                        <p className="text-[11px] text-slate-400 leading-relaxed">
                          Decision by @sec-lead. Enforces zero-leakage workspace isolation directly in SQL engine rather than application code.
                        </p>
                        <div className="pt-1 flex items-center gap-2 text-[10px] text-slate-500 font-mono">
                          <span className="text-emerald-400">Verified</span>
                          <span>Proof: sha256:7c18...f803</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {heroConsoleTab === "readiness" && (
                  <div className="space-y-4 font-sans">
                    <div className="text-[11px] text-slate-400 font-mono flex items-center justify-between pb-1 border-b border-slate-800">
                      <span>SUCCESSOR ONBOARDING & SIMULATION READINESS SCORE</span>
                      <span className="text-emerald-400 font-semibold font-mono">94% AUDIT-READY</span>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                      <div className="p-3 rounded-xl bg-[#13192B] border border-slate-800">
                        <div className="text-xl font-extrabold text-violet-400 font-mono">16 / 16</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">Dossier Sections</div>
                      </div>
                      <div className="p-3 rounded-xl bg-[#13192B] border border-slate-800">
                        <div className="text-xl font-extrabold text-emerald-400 font-mono">0</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">Unresolved SPOFs</div>
                      </div>
                      <div className="p-3 rounded-xl bg-[#13192B] border border-slate-800">
                        <div className="text-xl font-extrabold text-slate-200 font-mono">4 Days</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">Ramp-up (vs 6 wks)</div>
                      </div>
                      <div className="p-3 rounded-xl bg-[#13192B] border border-slate-800">
                        <div className="text-xl font-extrabold text-indigo-400 font-mono">100%</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">SHA-256 Verified</div>
                      </div>
                    </div>

                    <div className="p-3 rounded-xl bg-[#13192B] border border-slate-800 flex items-center justify-between gap-3 text-xs">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                        <span className="text-slate-200 font-medium">Successor Dry-Run Scenario Completed: Incident Playbook #12</span>
                      </div>
                      <span className="text-[11px] text-emerald-400 font-mono font-semibold">Simulated: 0 Downtime</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Bottom Console Footer */}
              <div className="px-4 py-2.5 bg-[#090D16] border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400 font-mono">
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
                    Obsidian Autonomous Core v2.4
                  </span>
                  <span className="hidden sm:inline text-slate-600">|</span>
                  <span className="hidden sm:inline text-slate-400">Zero-Knowledge Storage Enforced</span>
                </div>
                <div className="flex items-center gap-2 text-violet-400 font-sans font-semibold">
                  <span>Interactive Live Preview</span>
                </div>
              </div>
            </div>
          </div>

          {/* Core Pillars */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-8 text-left">
            <div className="apple-card p-6 space-y-2 bg-white/90 backdrop-blur-sm">
              <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center font-bold">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-bold text-slate-900">Traceability</h3>
              <p className="text-xs text-slate-500 leading-relaxed">
                Every extracted architectural statement is cryptographically hashed with SHA-256 back to commit diffs and discussions.
              </p>
            </div>

            <div className="apple-card p-6 space-y-2 bg-white/90 backdrop-blur-sm">
              <div className="w-9 h-9 rounded-xl bg-slate-100 text-slate-700 flex items-center justify-center font-bold">
                <Workflow className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-bold text-slate-900">Actionability</h3>
              <p className="text-xs text-slate-500 leading-relaxed">
                Surfaces in-flight PRs, unfinished tasks, unassigned ownership, and concrete Day 1-30 successor roadmaps.
              </p>
            </div>

            <div className="apple-card p-6 space-y-2 bg-white/90 backdrop-blur-sm">
              <div className="w-9 h-9 rounded-xl bg-slate-100 text-slate-700 flex items-center justify-center font-bold">
                <Lock className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-bold text-slate-900">Permission Awareness</h3>
              <p className="text-xs text-slate-500 leading-relaxed">
                PostgreSQL Row Level Security (RLS) ensures sensitive credentials and workspace knowledge remain strictly compartmentalized.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Interactive Handover Studio Showcase */}
      <section id="studio" className="max-w-6xl mx-auto px-6 py-12">
        <div className="text-center space-y-2 mb-8">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-violet-50 text-violet-700 text-xs font-semibold border border-violet-200">
            <FileText className="w-3.5 h-3.5" />
            <span>Interactive Handover Studio</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
            See the 16-Section Dossier Engine in Action
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 max-w-xl mx-auto">
            Experience real synthesized architecture decisions, dependency topologies, and pre-departure simulations.
          </p>
        </div>

        {/* Studio Window */}
        <div className="apple-card overflow-hidden shadow-lg border border-slate-200">
          {/* Top Studio Bar */}
          <div className="px-5 py-3.5 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <FolderGit2 className="w-4 h-4 text-violet-600" />
              <span className="text-xs font-medium text-slate-600 flex items-center gap-1.5">
                <span>dossier / payments-engine-handover.json</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-semibold">
                  16 of 16 Sections Complete
                </span>
              </span>
            </div>

            {/* Studio Navigation Tabs */}
            <div className="flex items-center bg-white p-1 rounded-xl border border-slate-200 text-xs">
              <button
                onClick={() => setActiveStudioTab("dossier")}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                  activeStudioTab === "dossier" ? "bg-violet-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                16-Section Dossier
              </button>
              <button
                onClick={() => setActiveStudioTab("graph")}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                  activeStudioTab === "graph" ? "bg-violet-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Service Topology
              </button>
              <button
                onClick={() => setActiveStudioTab("evidence")}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                  activeStudioTab === "evidence" ? "bg-violet-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Evidence Ledger
              </button>
              <button
                onClick={() => setActiveStudioTab("simulator")}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                  activeStudioTab === "simulator" ? "bg-violet-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Readiness Simulator
              </button>
            </div>
          </div>

          {/* Studio Content */}
          <div className="p-6 sm:p-8 bg-white min-h-[420px]">
            {/* Tab 1: Dossier */}
            {activeStudioTab === "dossier" && (
              <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
                {/* Left Section Picker */}
                <div className="md:col-span-4 space-y-1.5 border-r border-slate-100 pr-4">
                  <div className="text-[10px] uppercase font-bold text-slate-400 px-3 py-1">
                    Handover Sections
                  </div>
                  {[
                    { id: "summary", title: "1. Executive Summary", status: "Verified", icon: FileText },
                    { id: "architecture", title: "2. Runtime Architecture", status: "Complete", icon: Workflow },
                    { id: "adr", title: "3. Architectural Decisions (ADR)", status: "12 ADRs", icon: Scale },
                    { id: "tasks", title: "5. In-Flight Tasks & WIP", status: "3 PRs", icon: GitPullRequest },
                    { id: "roadmap", title: "12. Successor 30-Day Plan", status: "Ready", icon: Clock },
                  ].map((s) => {
                    const Icon = s.icon
                    const isCur = selectedSection === s.id
                    return (
                      <button
                        key={s.id}
                        onClick={() => setSelectedSection(s.id as any)}
                        className={`w-full text-left px-3 py-2.5 rounded-xl text-xs font-semibold flex items-center justify-between transition-all ${
                          isCur
                            ? "bg-violet-50 text-violet-700 border border-violet-200 shadow-sm"
                            : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                        }`}
                      >
                        <div className="flex items-center gap-2 truncate">
                          <Icon className={`w-3.5 h-3.5 ${isCur ? "text-violet-600" : "text-slate-400"}`} />
                          <span className="truncate">{s.title}</span>
                        </div>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                          {s.status}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {/* Right Content */}
                <div className="md:col-span-8 p-5 rounded-2xl bg-slate-50/60 border border-slate-200/80 space-y-4">
                  {selectedSection === "summary" && (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between pb-3 border-b border-slate-200">
                        <div>
                          <h4 className="text-sm font-bold text-slate-900">Project: Enterprise Core Platform</h4>
                          <p className="text-xs text-slate-500">Departing Architect: Alex Vance (Staff) to Successor: Jordan Lee</p>
                        </div>
                        <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-bold border border-emerald-200">
                          Dossier Approved (98% Score)
                        </span>
                      </div>

                      <div className="grid grid-cols-3 gap-3 text-left">
                        <div className="p-3 rounded-xl bg-white border border-slate-200">
                          <div className="text-[10px] text-slate-400 font-bold uppercase">Services Ingested</div>
                          <div className="text-base font-bold text-slate-900 mt-0.5">14 Services</div>
                        </div>
                        <div className="p-3 rounded-xl bg-white border border-slate-200">
                          <div className="text-[10px] text-slate-400 font-bold uppercase">Decisions Captured</div>
                          <div className="text-base font-bold text-slate-900 mt-0.5">42 ADRs</div>
                        </div>
                        <div className="p-3 rounded-xl bg-white border border-slate-200">
                          <div className="text-[10px] text-slate-400 font-bold uppercase">SHA-256 Citations</div>
                          <div className="text-base font-bold text-violet-700 mt-0.5">100% Backed</div>
                        </div>
                      </div>

                      <div className="p-3.5 rounded-xl bg-violet-50 border border-violet-200 text-xs text-violet-900 space-y-1">
                        <div className="font-bold flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-violet-700" />
                          <span>Autonomous Handover Summary</span>
                        </div>
                        <p className="text-slate-600 leading-relaxed text-[11px]">
                          Reconstructed across 84 commits, 32 Slack threads, and 9 design docs. Zero single-points-of-failure unaddressed. All critical production runbooks attached to Section 8.
                        </p>
                      </div>
                    </div>
                  )}

                  {selectedSection === "architecture" && (
                    <div className="space-y-3">
                      <h4 className="text-sm font-bold text-slate-900">Runtime Topology and Infrastructure Layer</h4>
                      <p className="text-xs text-slate-500">Autonomous mapping across Frontend, Backend, Cache, and Database.</p>
                      <div className="p-3.5 rounded-xl bg-white border border-slate-200 font-mono text-[11px] text-slate-700 space-y-1.5 leading-relaxed">
                        <div className="text-emerald-700 font-bold">[Next.js 16 Web Client] (Port 3000)</div>
                        <div className="text-slate-500 pl-4">- TanStack Query v5 (Shared Client Cache, 60s TTL)</div>
                        <div className="text-violet-700 font-bold">[FastAPI Application Tier] (Port 8000)</div>
                        <div className="text-slate-500 pl-4">- JTI In-Memory Token Cache (_VALID_JTIS, 60s TTL)</div>
                        <div className="text-slate-500 pl-4">- Short-Circuit 3-Tier Access Verifier</div>
                        <div className="text-indigo-700 font-bold">[Supabase PostgreSQL + Auth] (AWS Mumbai ap-south-1)</div>
                        <div className="text-slate-500 pl-4">- 29 Covering Foreign Key Performance Indexes</div>
                        <div className="text-slate-500 pl-4">- Row Level Security (RLS) Tenant Isolation</div>
                      </div>
                    </div>
                  )}

                  {selectedSection === "adr" && (
                    <div className="space-y-2.5">
                      <h4 className="text-sm font-bold text-slate-900">Architectural Decision Records (ADRs)</h4>
                      <div className="p-3 rounded-xl bg-white border border-slate-200 space-y-1 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-900">ADR-042: Batched Project Metric Aggregations</span>
                          <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-bold">ACCEPTED</span>
                        </div>
                        <p className="text-slate-500 text-[11px]">
                          Replaced 5 sequential count queries per project with unified SQL aggregation, reducing dashboard latency by 64.6%.
                        </p>
                        <div className="text-[10px] font-mono text-violet-700">Evidence: commit 8988094, PR #182</div>
                      </div>
                      <div className="p-3 rounded-xl bg-white border border-slate-200 space-y-1 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-900">ADR-038: In-Memory JTI Validation Cache</span>
                          <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-bold">ACCEPTED</span>
                        </div>
                        <p className="text-slate-500 text-[11px]">
                          Thread-safe cache eliminating repeated database queries for non-revoked JWTs on every authenticated request.
                        </p>
                        <div className="text-[10px] font-mono text-violet-700">Evidence: Slack #arch-core, PR #164</div>
                      </div>
                    </div>
                  )}

                  {selectedSection === "tasks" && (
                    <div className="space-y-2.5">
                      <h4 className="text-sm font-bold text-slate-900">In-Flight Pull Requests and Tasks</h4>
                      <div className="p-3 rounded-xl bg-white border border-slate-200 flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2.5">
                          <GitPullRequest className="w-4 h-4 text-emerald-600" />
                          <div>
                            <div className="font-semibold text-slate-900">PR #204: Native TLS Relay for Password Reset</div>
                            <div className="text-[10px] text-slate-400">Merged and Verified in GitHub Actions CI</div>
                          </div>
                        </div>
                        <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">Successor Assigned</span>
                      </div>
                      <div className="p-3 rounded-xl bg-white border border-slate-200 flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2.5">
                          <GitPullRequest className="w-4 h-4 text-amber-600" />
                          <div>
                            <div className="font-semibold text-slate-900">Issue #118: Transaction Pooler Port 6543 Switch</div>
                            <div className="text-[10px] text-slate-400">Scheduled for successor testing on staging</div>
                          </div>
                        </div>
                        <span className="text-[10px] font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded">Day 7 Task</span>
                      </div>
                    </div>
                  )}

                  {selectedSection === "roadmap" && (
                    <div className="space-y-2.5">
                      <h4 className="text-sm font-bold text-slate-900">Successor 30-Day Transition Roadmap</h4>
                      <div className="space-y-2 text-xs">
                        <div className="p-2.5 rounded-xl bg-violet-50/60 border border-violet-200 flex gap-2.5">
                          <div className="w-5 h-5 rounded-full bg-violet-600 text-white flex items-center justify-center font-bold text-[10px] shrink-0">1</div>
                          <div>
                            <div className="font-bold text-slate-900">Days 1-7: Environment Verification and Safe Ops</div>
                            <div className="text-slate-500 text-[11px]">Run local dev suite, verify Supabase indexes, ship first low-risk PR with Alex shadowing.</div>
                          </div>
                        </div>
                        <div className="p-2.5 rounded-xl bg-white border border-slate-200 flex gap-2.5">
                          <div className="w-5 h-5 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-[10px] shrink-0">2</div>
                          <div>
                            <div className="font-bold text-slate-900">Days 8-14: Incident Triage and Dry Run</div>
                            <div className="text-slate-500 text-[11px]">Execute cache failover simulation and review remaining offboarder alert playbooks.</div>
                          </div>
                        </div>
                        <div className="p-2.5 rounded-xl bg-white border border-slate-200 flex gap-2.5">
                          <div className="w-5 h-5 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-[10px] shrink-0">3</div>
                          <div>
                            <div className="font-bold text-slate-900">Days 15-30: Autonomous On-Call Ownership</div>
                            <div className="text-slate-500 text-[11px]">Complete formal stakeholder approval and assume primary on-call rotation.</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tab 2: Graph */}
            {activeStudioTab === "graph" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between pb-2 border-b border-slate-200">
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">System and Knowledge Topology</h4>
                    <p className="text-xs text-slate-500">Autonomous mapping of dependencies, owners, and departure risks.</p>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-600 font-medium">
                    <span>Status: Monitored and Healthy</span>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 pt-1">
                  <div className="p-3.5 rounded-xl bg-white border border-slate-200 space-y-1.5">
                    <span className="text-xs font-bold text-slate-900">Web Client Tier</span>
                    <p className="text-[11px] text-slate-500">Next.js 16, Turbopack, 34 Static and Dynamic Routes</p>
                    <div className="text-[10px] text-emerald-700 font-semibold">0 Knowledge Gaps</div>
                  </div>

                  <div className="p-3.5 rounded-xl bg-white border border-slate-200 space-y-1.5">
                    <span className="text-xs font-bold text-slate-900">Backend API Gateway</span>
                    <p className="text-[11px] text-slate-500">FastAPI, Uvicorn, JWT Session Cache</p>
                    <div className="text-[10px] text-emerald-700 font-semibold">0 SPOF Risks</div>
                  </div>

                  <div className="p-3.5 rounded-xl bg-white border border-slate-200 space-y-1.5">
                    <span className="text-xs font-bold text-slate-900">Supabase PostgreSQL</span>
                    <p className="text-[11px] text-slate-500">AWS Mumbai, 29 Indexes, RLS Enabled</p>
                    <div className="text-[10px] text-amber-700 font-semibold">1 Task Pending: Port 6543</div>
                  </div>

                  <div className="p-3.5 rounded-xl bg-white border border-slate-200 space-y-1.5">
                    <span className="text-xs font-bold text-slate-900">Handover Synthesizer</span>
                    <p className="text-[11px] text-slate-500">NLP Entity Linker, SHA-256 Hasher</p>
                    <div className="text-[10px] text-emerald-700 font-semibold">42 ADRs Synthesized</div>
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 font-mono text-xs text-slate-600 flex items-center justify-between">
                  <span>Critical Path: Client to FastAPI Auth Router to Supabase RLS Policy to Handover Generator</span>
                  <span className="text-emerald-700 font-bold">100% Redundancy Verified</span>
                </div>
              </div>
            )}

            {/* Tab 3: Evidence */}
            {activeStudioTab === "evidence" && (
              <div className="space-y-3.5">
                <div className="flex items-center justify-between pb-2 border-b border-slate-200">
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">Cryptographic SHA-256 Evidence Ledger</h4>
                    <p className="text-xs text-slate-500">Every statement in the dossier links to immutable source artifacts.</p>
                  </div>
                  <span className="px-2.5 py-0.5 rounded-full bg-violet-100 text-violet-800 text-xs font-semibold">
                    100% Cryptographically Backed
                  </span>
                </div>

                <div className="space-y-2">
                  <div className="p-3 rounded-xl bg-white border border-slate-200 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div>
                      <div className="font-bold text-slate-900 flex items-center gap-1.5">
                        <GitCommit className="w-3.5 h-3.5 text-emerald-600" />
                        <span>Database Indexing Optimization</span>
                      </div>
                      <div className="font-mono text-[10px] text-slate-500">
                        SHA-256: 7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 text-[10px] font-bold">
                      COMMIT 8988094
                    </span>
                  </div>

                  <div className="p-3 rounded-xl bg-white border border-slate-200 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div>
                      <div className="font-bold text-slate-900 flex items-center gap-1.5">
                        <FileCode className="w-3.5 h-3.5 text-violet-600" />
                        <span>TanStack Query Navigation Cache Architecture</span>
                      </div>
                      <div className="font-mono text-[10px] text-slate-500">
                        SHA-256: c3ab8ff13720e8ad9047dd39466b3c8974e592c2fa383d4a3960714caef0c4f2
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-violet-50 text-violet-700 text-[10px] font-bold">
                      query-provider.tsx
                    </span>
                  </div>

                  <div className="p-3 rounded-xl bg-white border border-slate-200 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div>
                      <div className="font-bold text-slate-900 flex items-center gap-1.5">
                        <Lock className="w-3.5 h-3.5 text-indigo-600" />
                        <span>Multi-Tenant Row Level Security (RLS) Policy Check</span>
                      </div>
                      <div className="font-mono text-[10px] text-slate-500">
                        SHA-256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px] font-bold">
                      user_can_access_project
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 4: Simulator */}
            {activeStudioTab === "simulator" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between pb-2 border-b border-slate-200">
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">Successor Readiness Simulator</h4>
                    <p className="text-xs text-slate-500">Pre-departure dry run verifying successor independence.</p>
                  </div>
                  <button
                    onClick={runSimulation}
                    disabled={simRunning}
                    className="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-1.5 transition-all disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${simRunning ? "animate-spin" : ""}`} />
                    <span>{simRunning ? "Simulating..." : "Run Incident Drill"}</span>
                  </button>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-3">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-slate-600">SCENARIO: Payment Gateway Invalidation Loop (Severity 1)</span>
                    <span className="text-violet-700 font-bold">Phase {simStep} of 4</span>
                  </div>

                  <div className="space-y-2">
                    <div className={`p-2.5 rounded-lg border text-xs transition-all ${
                      simStep >= 1 ? "bg-amber-50 border-amber-200 text-amber-900" : "bg-white border-slate-200 text-slate-400"
                    }`}>
                      1. Inbound webhook latency spikes to 4,200ms across payment workers.
                    </div>
                    <div className={`p-2.5 rounded-lg border text-xs transition-all ${
                      simStep >= 2 ? "bg-violet-50 border-violet-200 text-violet-900" : "bg-white border-slate-200 text-slate-400"
                    }`}>
                      2. Team Obsidian scans 16-section dossier: Surfaces ADR-042 and previous mitigation playbook written by departing architect.
                    </div>
                    <div className={`p-2.5 rounded-lg border text-xs transition-all ${
                      simStep >= 3 ? "bg-indigo-50 border-indigo-200 text-indigo-900" : "bg-white border-slate-200 text-slate-400"
                    }`}>
                      3. Successor applies connection pool recycle threshold change with exact command line flags retrieved from dossier.
                    </div>
                    <div className={`p-2.5 rounded-lg border text-xs transition-all ${
                      simStep >= 4 ? "bg-emerald-50 border-emerald-200 text-emerald-900 font-bold" : "bg-white border-slate-200 text-slate-400"
                    }`}>
                      4. Latency recovers to 42ms. Zero escalation to offboarded engineer. 100% Autonomous Resolution.
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Comparison: Manual vs Obsidian */}
      <section id="comparison" className="max-w-5xl mx-auto px-6 py-14 space-y-8">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-violet-50 text-violet-700 text-xs font-semibold border border-violet-200">
            <Scale className="w-3.5 h-3.5" />
            <span>The Transition Gap</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
            Why Traditional Technical Handover Fails
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 max-w-xl mx-auto">
            Compare manual offboarding spreadsheets and meetings against autonomous dossier synthesis.
          </p>
        </div>

        <div className="apple-card overflow-hidden">
          <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-100">
            {/* Manual Handover */}
            <div className="p-7 space-y-4 bg-slate-50/40">
              <h3 className="text-sm font-bold text-slate-700">Manual Handover (The Status Quo)</h3>
              <ul className="space-y-3 text-xs text-slate-500">
                <li className="flex items-start gap-2">
                  <span className="font-semibold text-slate-400">-</span>
                  <span>Rushed 30-minute Zoom recordings that successors rarely have time to watch.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="font-semibold text-slate-400">-</span>
                  <span>Outdated Notion pages and unwritten architectural rationales lost in Slack DMs.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="font-semibold text-slate-400">-</span>
                  <span>Untracked background cron jobs, API keys, and single-person dependencies.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="font-semibold text-slate-400">-</span>
                  <span>Successor panicked on Day 1 on-call, forcing emergency calls to departed staff.</span>
                </li>
              </ul>
            </div>

            {/* Team Obsidian */}
            <div className="p-7 space-y-4 bg-white">
              <h3 className="text-sm font-bold text-slate-900">Team Obsidian Autonomous Handover</h3>
              <ul className="space-y-3 text-xs text-slate-700">
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                  <span>Synthesizes an audit-ready 16-section dossier automatically from GitHub and Slack.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                  <span>Every architectural decision is backed by immutable SHA-256 cryptographic proof.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                  <span>Departure risk heatmap detects knowledge bottlenecks before the engineer leaves.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                  <span>Successor simulator tests operational readiness with live simulated scenarios.</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ROI Calculator */}
      <section id="calculator" className="max-w-4xl mx-auto px-6 py-12 space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-violet-50 text-violet-700 text-xs font-semibold border border-violet-200">
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Succession Impact Calculator</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
            Calculate Your Organization&apos;s Knowledge Retention ROI
          </h2>
          <p className="text-xs sm:text-sm text-slate-500">
            Estimate engineering hours saved and onboarding ramp acceleration across your team.
          </p>
        </div>

        <div className="apple-card p-6 sm:p-8 space-y-6">
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => setCalculatorTier("small")}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                calculatorTier === "small" ? "bg-violet-600 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:text-slate-900"
              }`}
            >
              Startup (10-25 Devs)
            </button>
            <button
              onClick={() => setCalculatorTier("mid")}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                calculatorTier === "mid" ? "bg-violet-600 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:text-slate-900"
              }`}
            >
              Scale-up (50-150 Devs)
            </button>
            <button
              onClick={() => setCalculatorTier("enterprise")}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                calculatorTier === "enterprise" ? "bg-violet-600 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:text-slate-900"
              }`}
            >
              Enterprise (250+ Devs)
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
              <div className="text-[11px] text-slate-400 font-bold uppercase">Team Scale</div>
              <div className="text-base font-bold text-slate-900 mt-1">{calculatorValues[calculatorTier].devs}</div>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
              <div className="text-[11px] text-slate-400 font-bold uppercase">Departures / Year</div>
              <div className="text-base font-bold text-slate-900 mt-1">{calculatorValues[calculatorTier].turnover}</div>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
              <div className="text-[11px] text-slate-400 font-bold uppercase">Successor Ramp Up</div>
              <div className="text-base font-bold text-emerald-700 mt-1">{calculatorValues[calculatorTier].ramp}</div>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
              <div className="text-[11px] text-slate-400 font-bold uppercase">Est. Annual Value</div>
              <div className="text-base font-bold text-violet-700 mt-1">{calculatorValues[calculatorTier].savings}</div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="max-w-3xl mx-auto px-6 py-12 space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-violet-50 text-violet-700 text-xs font-semibold border border-violet-200">
            <HelpCircle className="w-3.5 h-3.5" />
            <span>Questions & Answers</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
            Frequently Asked Questions
          </h2>
        </div>

        <div className="space-y-2.5">
          {faqs.map((faq, idx) => {
            const isOpen = openFaq === idx
            return (
              <div key={idx} className="apple-card overflow-hidden">
                <button
                  onClick={() => setOpenFaq(isOpen ? null : idx)}
                  className="w-full text-left p-4 sm:p-5 flex items-center justify-between text-xs sm:text-sm font-bold text-slate-900 hover:text-violet-700 transition-colors"
                >
                  <span>{faq.q}</span>
                  <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                </button>
                {isOpen && (
                  <div className="px-5 pb-5 text-xs text-slate-600 leading-relaxed border-t border-slate-100 pt-3">
                    {faq.a}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Bottom CTA Banner */}
      <section className="max-w-5xl mx-auto px-6 py-12">
        <div className="p-8 sm:p-12 rounded-3xl bg-gradient-to-tr from-[#1E1238] to-[#3B1A7A] text-center space-y-5 text-white shadow-xl shadow-purple-950/20">
          <h2 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold tracking-tight">
            Never Lose Institutional Knowledge Again.
          </h2>
          <p className="text-xs sm:text-sm text-slate-300 max-w-xl mx-auto leading-relaxed">
            Eliminate transition panic and offboarding friction. Reconstruct your engineering organization&apos;s memory today with Team Obsidian.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
            <button
              onClick={() => goProtected("/dashboard")}
              className="w-full sm:w-auto px-6 py-3 rounded-xl text-xs font-bold bg-white text-slate-900 hover:bg-slate-100 flex items-center justify-center gap-2 shadow-md transition-all hover:scale-[1.02]"
            >
              <span>Launch Enterprise Workspace</span>
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => router.push("/login")}
              className="w-full sm:w-auto px-6 py-3 rounded-xl text-xs font-bold bg-white/10 hover:bg-white/15 text-white border border-white/20 flex items-center justify-center gap-2 transition-all"
            >
              <span>Sign In to Existing Account</span>
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white text-slate-500 text-xs py-8">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-lg bg-violet-600 p-1 flex items-center justify-center">
              <Layers className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-slate-900 text-xs">TEAM OBSIDIAN</span>
            <span className="text-[11px] text-slate-400">Autonomous Knowledge Handover</span>
          </div>

          <div className="flex items-center gap-6 text-[11px] text-slate-500">
            <a href="#studio" className="hover:text-slate-900 transition-colors">Dossier Engine</a>
            <a href="#comparison" className="hover:text-slate-900 transition-colors">Why Obsidian</a>
            <a href="#calculator" className="hover:text-slate-900 transition-colors">Succession ROI</a>
            <Link href="/login" className="hover:text-slate-900 transition-colors">Sign In</Link>
            <Link href="/register" className="hover:text-slate-900 transition-colors">Register</Link>
          </div>

          <div className="text-[11px] text-slate-400">
            2026 Team Obsidian. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  )
}
