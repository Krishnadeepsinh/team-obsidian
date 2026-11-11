"use client"

import React, { useCallback, useEffect, useState } from "react"
import { Scale, Plus, Search, ShieldCheck } from "lucide-react"
import { api, getStoredProjectId, resolveActiveProjectId } from "@/lib/api"

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState<string>("")

  // Form state
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")
  const [reasoning, setReasoning] = useState("")
  const [decisionMaker, setDecisionMaker] = useState("")
  const [component, setComponent] = useState("")

  const loadDecisions = useCallback(async () => {
    try {
      setLoading(true)
      const projs = await api.getProjects().catch(() => [])
      const resolvedPid = resolveActiveProjectId(projs, getStoredProjectId())
      const data = await api.getDecisions(resolvedPid || undefined)
      setDecisions(data)
      setSelectedProjectId(resolvedPid)
    } catch (err) {
      console.error("Decisions load error:", err)
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
      await api.createDecision({
        project_id: selectedProjectId || undefined,
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
    } catch (err) {
      console.error("Create decision error:", err)
    }
  }

  const filtered = decisions.filter(d =>
    (d.title && d.title.toLowerCase().includes(search.toLowerCase())) ||
    (d.summary && d.summary.toLowerCase().includes(search.toLowerCase())) ||
    (d.component && d.component.toLowerCase().includes(search.toLowerCase()))
  )

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Decisions & Architectural Records (ADRs)</h1>
          <p className="text-xs text-slate-500 mt-0.5">Every architectural choice, discarded alternative, and technical tradeoff with cryptographic evidence</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-2 shadow-md shadow-violet-600/20 transition-all hover:scale-[1.02]"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New Decision (ADR)</span>
        </button>
      </div>

      <div className="flex items-center justify-between gap-3 apple-card p-3">
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
        <div className="text-xs text-slate-500 font-mono">
          {filtered.length} Architectural Decisions
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
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold uppercase">
                    {d.status || "accepted"}
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                    {d.component}
                  </span>
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
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600 text-xs">✕ Close</button>
            </div>
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
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20"
                >
                  Save Decision
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
