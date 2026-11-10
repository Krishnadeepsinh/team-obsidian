"use client"

import React, { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import {
  Layers,
  Link2,
  Compass,
  Scale,
  CheckSquare,
  AlertTriangle,
  ArrowUpRight,
  TrendingUp,
  Calendar,
  Check,
  ChevronRight,
  Clock,
  ExternalLink,
  Github,
  MessageSquare,
  FileText,
  FileSignature,
  Sparkles,
  RefreshCw,
  Activity,
  Plus,
  Send,
  ShieldCheck,
  Database
} from "lucide-react"
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell
} from "recharts"
import { api } from "@/lib/api"

export default function OverviewPage() {
  const router = useRouter()
  const [data, setData] = useState<any>(null)
  const [activities, setActivities] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [checkedActions, setCheckedActions] = useState<Record<string, boolean>>({})
  const [quickQuery, setQuickQuery] = useState("")
  const [quickAnswer, setQuickAnswer] = useState<any>(null)
  const [quickAsking, setQuickAsking] = useState(false)
  const [seedingDemo, setSeedingDemo] = useState(false)

  const getActiveProjectId = () =>
    typeof window !== "undefined"
      ? localStorage.getItem("obsidian_active_project_id") ||
        localStorage.getItem("obsidian_active_project") ||
        undefined
      : undefined

  const loadData = async () => {
    try {
      setRefreshing(true)
      const activeProjId = getActiveProjectId()
      const [res, acts] = await Promise.all([
        api.getStats(activeProjId).catch(() => null),
        api.getActivity(activeProjId).catch(() => [])
      ])
      setData(res)
      setActivities(Array.isArray(acts) ? acts : [])
    } catch (err) {
      console.error("Dashboard stats error:", err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadData()
    const handleProjectChange = () => {
      loadData()
    }
    window.addEventListener("obsidian_project_changed", handleProjectChange)
    return () => {
      window.removeEventListener("obsidian_project_changed", handleProjectChange)
    }
  }, [])

  // Live metrics strictly based on real database records
  const metrics = data?.metrics || {
    projects: 0,
    connected_sources: 0,
    total_sources: 0,
    knowledge_items: 0,
    decisions: 0,
    open_tasks: 0,
    completed_tasks: 0,
    unresolved_risks: 0,
    critical_risks: 0
  }
  const activeHandover = data?.active_handover || null

  // Monthly Cumulative Ingestion Chart Data
  const chartData = data?.activity_trend && data.activity_trend.length > 0 
    ? data.activity_trend 
    : [
        { month: "Jun", ingested: 0, verified: 0 },
        { month: "Jul", ingested: 0, verified: 0 },
        { month: "Aug", ingested: 0, verified: 0 },
        { month: "Sep", ingested: 0, verified: 0 },
        { month: "Oct", ingested: 0, verified: 0 },
        { month: "Nov", ingested: 0, verified: 0 }
      ]

  // Knowledge Categories Donut Data
  const totalEntities = metrics.knowledge_items || 0
  const categoryData = (data?.distribution && data.distribution.length > 0 && totalEntities > 0)
    ? data.distribution.map((d: any) => ({
        name: d.category,
        value: totalEntities > 0 ? Math.round((d.count / totalEntities) * 100) : 0,
        color: d.fill || "#7C3AED"
      }))
    : [
        { name: "Decisions", value: 0, color: "#7C3AED" },
        { name: "Tasks", value: 0, color: "#38BDF8" },
        { name: "Technical", value: 0, color: "#6366F1" },
        { name: "Dependencies", value: 0, color: "#C084FC" },
        { name: "Risks", value: 0, color: "#F472B6" },
        { name: "Others", value: 0, color: "#F59E0B" }
      ]

  // Next Actions Data (from real open tasks)
  const nextActions = (data?.upcoming_tasks || []).map((t: any) => ({
    id: t.id,
    title: t.title,
    priority: (t.priority || "Medium").toUpperCase(),
    priorityColor: t.priority === "critical" || t.priority === "high"
      ? "bg-rose-50 text-rose-600 border-rose-200"
      : "bg-amber-50 text-amber-700 border-amber-200"
  }))

  // Recent Activity Items (from audit activity log)
  const recentActivities = activities.slice(0, 4).map((act: any) => ({
    icon: act.entity_type === "decision" ? Scale : act.entity_type === "integration" ? Link2 : FileText,
    title: act.details?.message || (typeof act.details === "string" ? act.details : act.action?.replace(".", " → ").toUpperCase() || "Activity Event"),
    time: act.timestamp ? new Date(act.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "Recently",
    color: "text-violet-600"
  }))

  // Recent Decisions (from real decisions)
  const recentDecisions = data?.recent_decisions || []

  // Integrations Status (from real connected integrations)
  const integrationsList = (data?.integrations || []).map((i: any) => ({
    name: i.name || i.provider?.toUpperCase(),
    sync: i.last_sync ? new Date(i.last_sync).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "Never",
    status: i.status === "connected" ? "Connected" : "Disconnected"
  }))

  const toggleAction = async (id: string) => {
    const nextDone = !checkedActions[id]
    setCheckedActions(prev => ({ ...prev, [id]: nextDone }))
    try {
      await api.updateTaskStatus(id, nextDone ? "completed" : "open")
      await loadData()
    } catch (err) {
      setCheckedActions(prev => ({ ...prev, [id]: !nextDone }))
      console.error("Task toggle failed:", err)
    }
  }

  const handleLoadDemo = async () => {
    try {
      setSeedingDemo(true)
      const res = await api.seedDemo()
      if (res?.project_id && typeof window !== "undefined") {
        localStorage.setItem("obsidian_active_project", res.project_id)
        window.dispatchEvent(new Event("obsidian_project_changed"))
      }
      await loadData()
    } catch (err: any) {
      alert(err.message || "Failed to initialize demo sandbox")
    } finally {
      setSeedingDemo(false)
    }
  }

  const handleQuickAsk = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!quickQuery.trim()) return
    try {
      setQuickAsking(true)
      const res = await api.queryAssistant(getActiveProjectId() || "default", quickQuery.trim())
      setQuickAnswer(res)
    } catch (err: any) {
      setQuickAnswer({
        answer: err.message || "Unable to query AI assistant right now.",
        is_grounded: false,
        citations: [],
      })
    } finally {
      setQuickAsking(false)
    }
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      {/* 1. Main Hero Section */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#170B2C] via-[#2A1052] to-[#120726] p-6 text-white shadow-xl shadow-purple-950/20 border border-purple-900/30">
        {/* Glow Effects */}
        <div className="absolute right-1/4 -top-24 w-96 h-96 bg-violet-600/20 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute right-10 top-1/2 -translate-y-1/2 w-64 h-64 bg-fuchsia-500/15 rounded-full blur-2xl pointer-events-none" />

        <div className="relative z-10 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6">
          <div className="space-y-2 max-w-2xl">
            {/* Status Pill */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/10 backdrop-blur-md border border-white/15 text-[11px] font-medium text-purple-200">
              <span className={`w-1.5 h-1.5 rounded-full ${activeHandover ? "bg-fuchsia-400 animate-pulse" : "bg-emerald-400"}`} />
              <span>{activeHandover ? (activeHandover.status || "Handover Active") : "Personal Workspace"}</span>
            </div>

            {/* Handover Title */}
            <h1 className="text-2xl lg:text-3xl font-bold tracking-tight text-white">
              {activeHandover?.departing_employee && activeHandover?.incoming_employee
                ? `${activeHandover.departing_employee} → ${activeHandover.incoming_employee}`
                : (activeHandover?.title || activeHandover?.project_name || "Workspace Knowledge Intelligence")}
            </h1>

            {/* Subtitle */}
            <p className="text-xs text-purple-200/80 font-medium">
              {activeHandover?.departing_employee && activeHandover?.incoming_employee
                ? `${activeHandover.project_name || "Workspace"} • ${activeHandover.title || "Knowledge Handover"}`
                : "Continuous knowledge synthesis, decision records, and multi-tenant handover tracking"}
            </p>

            {/* Meta & Progress */}
            {activeHandover && (
              <div className="flex flex-wrap items-center gap-5 pt-1 text-xs text-purple-200/80">
                {activeHandover.target_date && (
                  <div className="flex items-center gap-1.5">
                    <Calendar className="w-3.5 h-3.5 text-purple-300" />
                    <span>Target Completion: {activeHandover.target_date}</span>
                  </div>
                )}
                {typeof activeHandover.confidence === "number" && (
                  <div className="flex items-center gap-2">
                    <div className="w-28 h-2 rounded-full bg-white/20 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-violet-400 to-fuchsia-400 rounded-full shadow-sm"
                        style={{ width: `${Math.round(activeHandover.confidence * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-white">{Math.round(activeHandover.confidence * 100)}%</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={() => router.push("/handover")}
              className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-white hover:bg-slate-50 text-slate-900 flex items-center gap-1.5 shadow-md shadow-black/10 transition-all hover:scale-[1.02]"
            >
              <span>{activeHandover ? "Review Handover" : "Start Handover"}</span>
              <ArrowUpRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => router.push("/projects")}
              className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-white/10 hover:bg-white/20 text-white border border-white/20 backdrop-blur-md transition-all hover:scale-[1.02]"
            >
              Manage Projects
            </button>
          </div>
        </div>
      </div>

      {/* Onboarding Empty-State Checklist (Zero Hardcoded Demo Data) */}
      {!loading &&
        metrics.connected_sources === 0 &&
        metrics.knowledge_items === 0 &&
        metrics.decisions === 0 &&
        metrics.open_tasks === 0 &&
        !activeHandover && (
        <div className="apple-card p-5 border border-violet-200 bg-gradient-to-r from-violet-50/70 via-white to-indigo-50/70">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-violet-700">
                <Sparkles className="w-3.5 h-3.5" /> Clean Workspace Initialized
              </div>
              <h2 className="text-base font-bold text-slate-900">Get started in 3 steps — or explore the E-Commerce Sandbox</h2>
              <p className="text-xs text-slate-600 max-w-2xl">
                Real workspaces never start with synthetic employee names. Create a project, connect GitHub/Slack/Notion or upload docs, or explicitly load the synthetic E-Commerce demo dataset.
              </p>
              <div className="flex flex-wrap gap-2 pt-2">
                <Link href="/projects" className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:border-violet-300 text-slate-800 shadow-sm">
                  1. Create Project
                </Link>
                <Link href="/integrations" className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:border-violet-300 text-slate-800 shadow-sm">
                  2. Connect GitHub / Slack / Notion
                </Link>
                <Link href="/documents" className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:border-violet-300 text-slate-800 shadow-sm">
                  3. Upload Runbooks &amp; Docs
                </Link>
              </div>
            </div>
            <button
              onClick={handleLoadDemo}
              disabled={seedingDemo}
              className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 flex items-center gap-2 flex-shrink-0"
            >
              <Database className="w-4 h-4" />
              <span>{seedingDemo ? "Loading Demo Sandbox..." : "Load Synthetic Demo Sandbox"}</span>
            </button>
          </div>
        </div>
      )}

      {/* 2. KPI Metric Cards (6 in a row) */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
        {/* Active Projects */}
        <div
          onClick={() => router.push("/projects")}
          className="apple-card p-4 cursor-pointer flex flex-col justify-between"
        >
          <div className="w-8 h-8 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center mb-2">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-900 leading-tight">
              {metrics.projects ?? 0}
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-0.5">
              <span>Active Projects</span>
              <span className={`text-[11px] font-semibold ${metrics.projects > 0 ? "text-emerald-600" : "text-slate-400"}`}>
                {metrics.projects > 0 ? `${metrics.projects} Live` : "0 in workspace"}
              </span>
            </div>
          </div>
        </div>

        {/* Connected Sources */}
        <div
          onClick={() => router.push("/integrations")}
          className="apple-card p-4 cursor-pointer flex flex-col justify-between"
        >
          <div className="w-8 h-8 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center mb-2">
            <Link2 className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-900 leading-tight">
              {metrics.connected_sources ?? 0}
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-0.5">
              <span>Connected Sources</span>
              <span className={`text-[11px] font-semibold ${metrics.connected_sources > 0 ? "text-emerald-600" : "text-slate-400"}`}>
                {metrics.connected_sources > 0 ? `${metrics.connected_sources} Active` : "None"}
              </span>
            </div>
          </div>
        </div>

        {/* Knowledge Entities */}
        <div
          onClick={() => router.push("/knowledge/explorer")}
          className="apple-card p-4 cursor-pointer flex flex-col justify-between"
        >
          <div className="w-8 h-8 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center mb-2">
            <Compass className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-900 leading-tight">
              {metrics.knowledge_items ?? 0}
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-0.5">
              <span>Knowledge Entities</span>
              <span className={`text-[11px] font-semibold ${metrics.knowledge_items > 0 ? "text-emerald-600" : "text-slate-400"}`}>
                {metrics.knowledge_items > 0 ? "Indexed" : "0 Indexed"}
              </span>
            </div>
          </div>
        </div>

        {/* Decisions (ADRs) */}
        <div
          onClick={() => router.push("/decisions")}
          className="apple-card p-4 cursor-pointer flex flex-col justify-between"
        >
          <div className="w-8 h-8 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center mb-2">
            <Scale className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-900 leading-tight">
              {metrics.decisions ?? 0}
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-0.5">
              <span>Decisions (ADRs)</span>
              <span className={`text-[10px] font-semibold ${metrics.decisions > 0 ? "text-emerald-600" : "text-slate-400"}`}>
                {metrics.decisions > 0 ? "Traceable" : "0 Recorded"}
              </span>
            </div>
          </div>
        </div>

        {/* Open Tasks */}
        <div
          onClick={() => router.push("/tasks")}
          className="apple-card p-4 cursor-pointer flex flex-col justify-between"
        >
          <div className="w-8 h-8 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center mb-2">
            <CheckSquare className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-900 leading-tight">
              {metrics.open_tasks ?? 0}
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-0.5">
              <span>Open Tasks</span>
              <span className={`text-[11px] font-semibold ${metrics.open_tasks > 0 ? "text-amber-600" : "text-emerald-600"}`}>
                {metrics.open_tasks > 0 ? `${metrics.open_tasks} Pending` : "All cleared"}
              </span>
            </div>
          </div>
        </div>

        {/* Unresolved Risks */}
        <div
          onClick={() => router.push("/risks")}
          className="apple-card p-4 cursor-pointer flex flex-col justify-between"
        >
          <div className="w-8 h-8 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center mb-2">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-900 leading-tight">
              {metrics.unresolved_risks ?? 0}
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-0.5">
              <span>Unresolved Risks</span>
              <span className={`text-[10px] font-semibold ${metrics.unresolved_risks > 0 ? "text-rose-600" : "text-emerald-600"}`}>
                {metrics.unresolved_risks > 0 ? `${metrics.critical_risks || 0} Critical` : "All Safe"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Middle Content Row: Area Chart + Donut Categories + Next Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Knowledge Ingestion & Verification Area Chart */}
        <div className="lg:col-span-6 apple-card p-5">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Knowledge Ingestion & Verification</h2>
              <p className="text-[11px] text-slate-500 mt-0.5">
                Monthly cumulative volume of verified records vs incoming sources
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs font-medium">
              <span className="flex items-center gap-1.5 text-slate-600">
                <span className="w-2 h-2 rounded-full bg-[#C084FC]" />
                Ingested
              </span>
              <span className="flex items-center gap-1.5 text-slate-900 font-semibold">
                <span className="w-2 h-2 rounded-full bg-[#6D28D9]" />
                Verified
              </span>
            </div>
          </div>

          <div className="h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <defs>
                  <linearGradient id="verifiedWave" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#7C3AED" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#7C3AED" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="ingestedWave" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#C084FC" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#C084FC" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="month" stroke="#94A3B8" fontSize={10} tickLine={false} axisLine={false} />
                <YAxis stroke="#94A3B8" fontSize={10} tickLine={false} axisLine={false} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="bg-white/95 backdrop-blur-md border border-slate-200 p-2.5 rounded-xl shadow-lg text-xs space-y-1">
                          <p className="font-bold text-slate-900">Monthly Volume</p>
                          <p className="text-[#7C3AED] flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#7C3AED]" />
                            Ingested: {payload[0]?.value ?? 0}
                          </p>
                          <p className="text-[#6D28D9] font-semibold flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#6D28D9]" />
                            Verified: {payload[1]?.value ?? 0}
                          </p>
                        </div>
                      )
                    }
                    return null
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="ingested"
                  stroke="#C084FC"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#ingestedWave)"
                />
                <Area
                  type="monotone"
                  dataKey="verified"
                  stroke="#6D28D9"
                  strokeWidth={2.5}
                  fillOpacity={1}
                  fill="url(#verifiedWave)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Knowledge Categories Donut Chart */}
        <div className="lg:col-span-3 apple-card p-5 flex flex-col justify-between">
          <div>
            <h2 className="text-sm font-bold text-slate-900">Knowledge Categories</h2>
          </div>

          <div className="flex items-center justify-between my-2">
            {/* Center Donut */}
            <div className="relative w-32 h-32 flex-shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={categoryData}
                    cx="50%"
                    cy="50%"
                    innerRadius={38}
                    outerRadius={56}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {categoryData.map((entry: any, index: number) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-base font-bold text-slate-900 leading-none">{totalEntities}</span>
                <span className="text-[10px] text-slate-400 font-medium leading-none mt-0.5">Entities</span>
              </div>
            </div>

            {/* Legend Column */}
            <div className="space-y-1.5 text-xs flex-1 pl-2">
              {categoryData.map((cat: any, idx: number) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 truncate">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: cat.color }} />
                    <span className="text-slate-600 text-[11px] truncate">{cat.name}</span>
                  </div>
                  <span className="text-slate-800 font-bold text-[11px] ml-1">{cat.value}%</span>
                </div>
              ))}
            </div>
          </div>

          <div className="text-[11px] text-slate-400 pt-2 border-t border-slate-100 flex items-center justify-between">
            <span>Graph Health</span>
            <span className={`font-semibold ${totalEntities > 0 ? "text-emerald-600" : "text-slate-400"}`}>
              {totalEntities > 0 ? "Optimal (100%)" : "0 Entities Indexed"}
            </span>
          </div>
        </div>

        {/* Next Actions Checklist */}
        <div className="lg:col-span-3 apple-card p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-bold text-slate-900">Next Actions</h2>
          </div>

          {nextActions.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400 my-auto">
              <CheckSquare className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="font-medium text-slate-600">No pending actions</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Tasks will appear here as they are detected or assigned.</p>
            </div>
          ) : (
            <div className="space-y-2.5 my-auto">
              {nextActions.map((act: any) => {
                const isDone = checkedActions[act.id]
                return (
                  <div
                    key={act.id}
                    onClick={() => toggleAction(act.id)}
                    className="flex items-center justify-between gap-2 p-2 rounded-xl hover:bg-slate-50 transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors flex-shrink-0 ${
                        isDone ? "bg-violet-600 border-violet-600 text-white" : "border-slate-300 group-hover:border-slate-400"
                      }`}>
                        {isDone && <Check className="w-3 h-3 stroke-[3]" />}
                      </div>
                      <span className={`text-xs truncate ${isDone ? "line-through text-slate-400" : "text-slate-700 font-medium"}`}>
                        {act.title}
                      </span>
                    </div>
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0 ${act.priorityColor}`}>
                      {act.priority}
                    </span>
                  </div>
                )
              })}
            </div>
          )}

          <button
            onClick={() => router.push("/tasks")}
            className="w-full mt-3 py-1.5 text-center text-xs text-violet-600 hover:text-violet-700 font-semibold border-t border-slate-100 pt-2 block"
          >
            View All Tasks →
          </button>
        </div>
      </div>

      {/* 4. Bottom Content Row: Recent Activity + Recent Decisions + Connected Integrations */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Recent Project Activity (Width: ~33%) */}
        <div className="lg:col-span-4 apple-card p-5">
          <div className="flex items-center justify-between mb-3.5">
            <h2 className="text-sm font-bold text-slate-900">Recent Project Activity</h2>
            <Link href="/activity" className="text-xs font-semibold text-violet-600 hover:text-violet-700 flex items-center gap-1">
              <span>View All</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {recentActivities.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">
              <Clock className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="font-medium text-slate-600">No activity recorded</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Integration syncs and handover events will appear here.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {recentActivities.map((act, idx) => {
                const Icon = act.icon
                return (
                  <div key={idx} className="flex items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="w-7 h-7 rounded-lg bg-slate-50 border border-slate-100 flex items-center justify-center flex-shrink-0">
                        <Icon className={`w-3.5 h-3.5 ${act.color}`} />
                      </div>
                      <span className="text-slate-700 font-medium truncate">{act.title}</span>
                    </div>
                    <span className="text-[11px] text-slate-400 font-mono flex-shrink-0">{act.time}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Recent Decisions (Width: ~42%) */}
        <div className="lg:col-span-5 apple-card p-5">
          <div className="flex items-center justify-between mb-3.5">
            <h2 className="text-sm font-bold text-slate-900">Recent Decisions</h2>
            <Link href="/decisions" className="text-xs font-semibold text-violet-600 hover:text-violet-700 flex items-center gap-1">
              <span>View All</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {recentDecisions.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">
              <Scale className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="font-medium text-slate-600">No decisions recorded</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Architectural decisions (ADRs) will be automatically captured or manually logged.</p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {recentDecisions.map((dec: any) => (
                <div
                  key={dec.id}
                  onClick={() => router.push("/decisions")}
                  className="flex items-start justify-between gap-3 p-2.5 rounded-xl hover:bg-slate-50 border border-transparent hover:border-slate-100 transition-all cursor-pointer group"
                >
                  <div className="flex items-start gap-2.5 min-w-0">
                    <div className="w-6 h-6 rounded-md bg-purple-50 text-violet-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-900 truncate group-hover:text-violet-700 transition-colors">
                        {dec.title}
                      </p>
                      <p className="text-[11px] text-slate-500 truncate mt-0.5">
                        {dec.summary || dec.reasoning || "Accepted architectural choice with full evidence."}
                      </p>
                    </div>
                  </div>
                  <ArrowUpRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-violet-600 flex-shrink-0 transition-colors" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Integrations (Width: ~25%) */}
        <div className="lg:col-span-3 apple-card p-5">
          <div className="flex items-center justify-between mb-3.5">
            <h2 className="text-sm font-bold text-slate-900">Integrations</h2>
            <Link href="/integrations" className="text-xs font-semibold text-violet-600 hover:text-violet-700 flex items-center gap-1">
              <span>Manage</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {integrationsList.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">
              <Link2 className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="font-medium text-slate-600">No integrations connected</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Connect GitHub, Slack, Notion or Google Drive.</p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {integrationsList.map((item: any, idx: number) => (
                <div key={idx} className="flex items-center justify-between gap-2 text-xs">
                  <div>
                    <p className="font-bold text-slate-800 text-xs">{item.name}</p>
                    <p className="text-[10px] text-slate-400">Last sync: {item.sync}</p>
                  </div>
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                    item.status === "Connected"
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-slate-50 text-slate-600 border-slate-200"
                  }`}>
                    {item.status === "Connected" && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 5. Inline AI Project Assistant Quick-Ask */}
      <div className="apple-card p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-violet-600" />
              <span>AI Project Intelligence Quick-Ask</span>
            </h2>
            <p className="text-[11px] text-slate-500">
              Ask any question grounded in your active project&apos;s verified sources and documents.
            </p>
          </div>
          <Link href="/assistant" className="text-xs font-semibold text-violet-600 hover:text-violet-700 flex items-center gap-1">
            <span>Open Full Assistant</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <form onSubmit={handleQuickAsk} className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={quickQuery}
            onChange={(e) => setQuickQuery(e.target.value)}
            placeholder="e.g. What architectural decisions or open production risks exist in this project?"
            className="flex-1 px-3.5 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
          />
          <button
            type="submit"
            disabled={quickAsking || !quickQuery.trim()}
            className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white shadow-sm flex items-center justify-center gap-1.5"
          >
            <Send className="w-3.5 h-3.5" />
            <span>{quickAsking ? "Querying..." : "Ask Grounded AI"}</span>
          </button>
        </form>

        {quickAnswer && (
          <div className={`p-3.5 rounded-xl border text-xs space-y-2 ${
            quickAnswer.is_grounded ? "bg-violet-50/40 border-violet-200" : "bg-amber-50/60 border-amber-200"
          }`}>
            <div className="flex items-center justify-between gap-2">
              <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase ${
                quickAnswer.is_grounded ? "text-emerald-700" : "text-amber-700"
              }`}>
                <ShieldCheck className="w-3.5 h-3.5" />
                {quickAnswer.is_grounded ? "Grounded in Project Evidence" : "Unsupported / Missing Evidence"}
              </span>
              {typeof quickAnswer.confidence === "number" && (
                <span className="text-[11px] font-semibold text-slate-600">
                  Confidence: {Math.round(quickAnswer.confidence * 100)}%
                </span>
              )}
            </div>
            <p className="text-slate-800 whitespace-pre-line leading-relaxed">{quickAnswer.answer}</p>
            {Array.isArray(quickAnswer.citations) && quickAnswer.citations.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {quickAnswer.citations.slice(0, 3).map((c: any, i: number) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded-md bg-white border border-slate-200 text-slate-600 font-medium">
                    {c.source_title || c.source_type}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
