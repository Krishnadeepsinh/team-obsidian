"use client"

import React, { useCallback, useEffect, useState } from "react"
import { Scale, Plus, Search, ShieldCheck } from "lucide-react"
import { api, getStoredProjectId, isAllProjectsSelected, resolveActiveProjectId, setStoredProjectId } from "@/lib/api"

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("All")
  const [showModal, setShowModal] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState<string>("")
  const [errorMsg, setErrorMsg] = useState("")
  const [modalError, setModalError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // Form state
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")
  const [reasoning, setReasoning] = useState("")
  const [decisionMaker, setDecisionMaker] = useState("")
  const [component, setComponent] = useState("")

  const loadDecisions = useCallback(async () => {
    try {
      setLoading(true)
      const allSelected = isAllProjectsSelected()
      const projs = await api.getProjects().catch(() => [])
      const projList = Array.isArray(projs) ? projs : []
      setProjects(projList)
      const resolvedPid = allSelected ? "" : resolveActiveProjectId(projList, getStoredProjectId())
      const data = await api.getDecisions(resolvedPid || undefined)
      setDecisions(Array.isArray(data) ? data : [])
      setSelectedProjectId(resolvedPid)
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to load decisions.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDecisions()
    const onProjChange = () => loadDecisions()
    window.addEventListener("obsidian_project_changed", onProjChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjChange)
  }, [loadDecisions])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    try {
      setSubmitting(true)
      setModalError("")
      setErrorMsg("")
      await api.createDecision({
        project_id: selectedProjectId || projects[0]?.id || undefined,
        title,
        summary,
        reasoning,
        decision_maker: decisionMaker,
        date: new Date().toISOString().split("T")[0],
        component,
        decision_type: "technical",
        status: "accepted"
      })
      await loadDecisions()
      setShowModal(false)
      setTitle("")
      setSummary("")
      setReasoning("")
    } catch (err: any) {
      setModalError(err?.message || "Failed to save decision.")
    } finally {
      setSubmitting(false)
    }
  }

  const projectNames: Record<string, string> = {}
  for (const p of projects) {
    if (p?.id) projectNames[p.id] = p.name
  }

  const statusOptions = [
    "All",
    ...Array.from(new Set(decisions.map((d) => String(d.status || "accepted").toLowerCase()))),
  ]

  const filtered = decisions.filter((d) => {
    if (statusFilter !== "All" && String(d.status || "accepted").toLowerCase() !== statusFilter) return false
    const q = search.trim().toLowerCase()
    if (!q) return true
    return (
      d.title?.toLowerCase().includes(q) ||
      d.summary?.toLowerCase().includes(q) ||
      d.component?.toLowerCase().includes(q) ||
      d.decision_maker?.toLowerCase().includes(q)
    )
  })

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Decisions & Architectural Records (ADRs)</h1>
          <p className="text-xs text-slate-500 mt-0.5">Every architectural choice, discarded alternative, and technical tradeoff with cryptographic evidence</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedProjectId}
            onChange={(e) => {
              const pid = e.target.value
              setSelectedProjectId(pid)
              setStoredProjectId(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-2 shadow-md shadow-violet-600/20 transition-all hover:scale-[1.02]"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Decision (ADR)</span>
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
          {errorMsg}
        </div>
      )}

      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 apple-card p-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search decisions, components, makers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-1.5 rounded-full text-xs bg-slate-50 border border-slate-200 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {statusOptions.map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold capitalize border transition-all ${
                statusFilter === st
                  ? "bg-violet-600 text-white border-violet-600"
                  : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
              }`}
            >
              {st}
            </button>
          ))}
          <span className="text-xs text-slate-500 font-mono ml-2">
            {filtered.length} ADRs
          </span>
        </div>
      </div>

      <div className="space-y-4">
        {filtered.map((d) => (
          <div
            key={d.id}
            className="apple-card p-5 space-y-3 hover:border-violet-300 transition-all"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold uppercase">
                    {d.status || "accepted"}
                  </span>
                  {d.component && (
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                      {d.component}
                    </span>
                  )}
                  {!selectedProjectId && d.project_id && projectNames[d.project_id] && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100 font-semibold">
                      {projectNames[d.project_id]}
                    </span>
                  )}
                  <span className="text-[10px] text-slate-400 font-mono">
                    {d.date}
                  </span>
                </div>
                <h2 className="text-base font-bold text-slate-900 tracking-tight">{d.title}</h2>
              </div>

              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200">
                  <ShieldCheck className="w-3 h-3 text-emerald-600" />
                  100% Traceable
                </span>
              </div>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              {d.summary}
            </p>

            {d.reasoning && (
              <div className="p-3 rounded-xl bg-violet-50/60 border border-violet-100 space-y-1">
                <span className="text-[10px] font-bold text-violet-700 uppercase tracking-wider block">
                  Decision Reasoning & Tradeoffs
                </span>
                <p className="text-xs text-slate-700 leading-relaxed">
                  {d.reasoning}
                </p>
              </div>
            )}

            <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
              <span>Decision Maker: <strong className="text-slate-800">{d.decision_maker}</strong></span>
              <span className="text-slate-400 text-[11px] font-mono">ID: {d.id?.slice(0, 8)}</span>
            </div>
          </div>
        ))}

        {filtered.length === 0 && !loading && (
          <div className="apple-card p-12 text-center">
            <Scale className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <h3 className="text-sm font-bold text-slate-800">No Decisions Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              Log architectural decisions so that technical context is preserved for successors.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white"
            >
              Log Architectural Decision
            </button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Record Architectural Decision (ADR)</h3>
              <button onClick={() => { setShowModal(false); setModalError("") }} className="text-slate-400 hover:text-slate-600 text-xs">✕ Close</button>
            </div>
            {modalError && (
              <div className="p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
                {modalError}
              </div>
            )}
            <form onSubmit={handleCreate} className="space-y-3.5">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Decision Title *</label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Migration from REST to gRPC for Internal Services"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Summary / Context *</label>
                <textarea
                  rows={2}
                  required
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="What was decided and what problem does it address..."
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Reasoning & Tradeoffs</label>
                <textarea
                  rows={2}
                  value={reasoning}
                  onChange={(e) => setReasoning(e.target.value)}
                  placeholder="Why this was chosen over alternatives, performance gains, known tradeoffs..."
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Decision Maker</label>
                  <input
                    type="text"
                    value={decisionMaker}
                    onChange={(e) => setDecisionMaker(e.target.value)}
                    placeholder="e.g. Lead Architect"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Component / Domain</label>
                  <input
                    type="text"
                    value={component}
                    onChange={(e) => setComponent(e.target.value)}
                    placeholder="e.g. Auth Service"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  />
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white shadow-md shadow-violet-600/20"
                >
                  {submitting ? "Saving..." : "Save Decision"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
