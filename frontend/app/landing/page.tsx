"use client"

import React from "react"
import { useRouter } from "next/navigation"
import {
  Layers,
  Sparkles,
  ShieldCheck,
  Zap,
  ArrowRight,
  Lock
} from "lucide-react"

export default function LandingPage() {
  const router = useRouter()
  const goProtected = (path: string) => {
    const hasUser = typeof window !== "undefined" && Boolean(localStorage.getItem("obsidian_user"))
    router.push(hasUser ? path : "/login")
  }

  return (
    <div className="min-h-screen bg-[#F8F9FD] text-slate-900 selection:bg-violet-100 selection:text-violet-900 relative overflow-hidden font-sans">
      {/* Top Navbar */}
      <header className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between relative z-10 border-b border-slate-200/60 bg-white/70 backdrop-blur-md sticky top-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-[#1E1238] to-[#3B1A7A] p-1.5 flex items-center justify-center shadow-sm">
            <Layers className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-sm tracking-tight text-slate-900">TEAM OBSIDIAN</span>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/login")}
            className="text-xs font-semibold text-slate-600 hover:text-slate-900 px-3 py-1.5 transition-colors"
          >
            Sign In
          </button>
          <button
            onClick={() => goProtected("/")}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-2 shadow-md shadow-violet-600/20 transition-all hover:scale-[1.02]"
          >
            <span>Launch Platform</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      {/* Hero Section */}
      <section className="max-w-4xl mx-auto px-6 pt-16 pb-20 text-center relative z-10 space-y-6">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-violet-50 border border-violet-200 text-xs text-violet-700 font-semibold shadow-sm">
          <Sparkles className="w-3.5 h-3.5 text-violet-600" />
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

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-4">
          <button
            onClick={() => goProtected("/")}
            className="w-full sm:w-auto px-6 py-3 rounded-2xl text-xs font-bold bg-violet-600 hover:bg-violet-700 text-white flex items-center justify-center gap-2 shadow-lg shadow-violet-600/25 transition-all hover:scale-[1.02]"
          >
            <span>Enter Enterprise Workspace</span>
            <ArrowRight className="w-4 h-4" />
          </button>
          <button
            onClick={() => goProtected("/handover")}
            className="w-full sm:w-auto px-6 py-3 rounded-2xl text-xs font-bold bg-white hover:bg-slate-50 text-slate-800 border border-slate-200 flex items-center justify-center gap-2 shadow-sm transition-all"
          >
            <span>View Handover Dossier</span>
          </button>
        </div>

        {/* 3 Core Value Pillars */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-12 text-left">
          <div className="apple-card p-6 space-y-2">
            <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center font-bold">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900">Traceability</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Every extracted architectural statement is cryptographically hashed with SHA-256 back to commit diffs and discussions.
            </p>
          </div>

          <div className="apple-card p-6 space-y-2">
            <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
              <Zap className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900">Actionability</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Surfaces in-flight PRs, unfinished tasks, unassigned ownership, and concrete Day 1-30 successor roadmaps.
            </p>
          </div>

          <div className="apple-card p-6 space-y-2">
            <div className="w-9 h-9 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold">
              <Lock className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900">Permission Awareness</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              PostgreSQL Row Level Security (RLS) ensures sensitive credentials and workspace knowledge remain strictly compartmentalized.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
