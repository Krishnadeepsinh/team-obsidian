"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { Layers, GitBranch, MessageSquare, FileText, FileUp, ArrowRight, Sparkles } from "lucide-react"

export default function OnboardingPage() {
  const router = useRouter()

  const steps = [
    {
      title: "1. Create a Project Scope",
      desc: "Define the system, team ownership, and handover context inside your workspace.",
      href: "/projects",
      cta: "Open Projects",
      icon: Layers,
    },
    {
      title: "2. Connect Knowledge Sources",
      desc: "Authenticate GitHub, Slack, and Notion connectors or verify your existing scopes.",
      href: "/integrations",
      cta: "Connect Sources",
      icon: GitBranch,
    },
    {
      title: "3. Upload Runbooks & Architecture Docs",
      desc: "Ingest PDF, Markdown, DOCX, XLSX, CSV, JSON, YAML, or plain text artifacts with chunk citations.",
      href: "/documents",
      cta: "Upload Documents",
      icon: FileUp,
    },
    {
      title: "4. Reconstruct & Verify Handover",
      desc: "Run AI extraction, inspect the Knowledge Graph blast radius, and review the 16-section dossier.",
      href: "/handover",
      cta: "Open Handovers",
      icon: FileText,
    },
  ]

  return (
    <div className="min-h-screen bg-[#F8F9FD] flex items-center justify-center p-4 sm:p-8">
      <div className="w-full max-w-3xl space-y-6">
        <div className="rounded-3xl bg-gradient-to-br from-[#2E1065] via-[#3B0764] to-[#1E1B4B] p-6 sm:p-8 text-white shadow-xl shadow-violet-950/15 space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-[11px] font-semibold text-violet-200">
            <Sparkles className="w-3.5 h-3.5" /> Workspace Ready
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Welcome to Team Obsidian</h1>
          <p className="text-xs sm:text-sm text-violet-100/80 max-w-2xl leading-relaxed">
            Your multi-tenant workspace starts clean with zero hardcoded sample employees. Follow the 4 steps below to connect sources, extract knowledge, and generate an evidence-backed handover dossier.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {steps.map((step) => {
            const Icon = step.icon
            return (
              <div key={step.title} className="apple-card p-5 flex flex-col justify-between gap-4">
                <div className="space-y-2.5">
                  <div className="w-9 h-9 rounded-xl bg-violet-50 border border-violet-200 flex items-center justify-center text-violet-600">
                    <Icon className="w-4 h-4" />
                  </div>
                  <h2 className="text-sm font-bold text-slate-900">{step.title}</h2>
                  <p className="text-xs text-slate-500 leading-relaxed">{step.desc}</p>
                </div>
                <Link
                  href={step.href}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-violet-600 hover:text-violet-700"
                >
                  <span>{step.cta}</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            )
          })}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <Link href="/assistant" className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-violet-700">
            <MessageSquare className="w-3.5 h-3.5" /> Open Evidence-Grounded AI Assistant
          </Link>
          <button
            onClick={() => router.push("/")}
            className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20 flex items-center gap-2"
          >
            <span>Go to Overview Dashboard</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
