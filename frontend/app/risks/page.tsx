"use client"

import React, { useCallback, useEffect, useState } from "react"
import { AlertTriangle, Plus, Search, CheckCircle2 } from "lucide-react"
import { api, getStoredProjectId, resolveActiveProjectId } from "@/lib/api"

export default function RisksPage() {
  const [risks, setRisks] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState("")

  // Form state
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [severity, setSeverity] = useState("high")
  const [likelihood, setLikelihood] = useState("medium")
  const [mitigation, setMitigation] = useState("")
  const [components, setComponents] = useState("")

  const loadRisks = useCallback(async () => {
    try {
      setLoading(true)
      const projs = await api.getProjects().catch(() => [])
      const resolvedPid = resolveActiveProjectId(projs, getStoredProjectId())
      setSelectedProjectId(resolvedPid)
      const data = await api.getRisks(resolvedPid || undefined)
      setRisks(data)
    } catch (err) {
      console.error("Risks error:", err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRisks()
    const onProjChange = () => loadRisks()
    window.addEventListener("obsidian_project_changed", onProjChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjChange)
  }, [loadRisks])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !description.trim()) return
    try {
      const compList = components.split(",").map(c => c.trim()).filter(Boolean)
      await api.createRisk({
        project_id: selectedProjectId || getStoredProjectId() || undefined,
        title,
        description,
        severity,
        likelihood,
        mitigation_strategy: mitigation,
        related_components: compList
      })
      await loadRisks()
      setShowModal(false)
      setTitle("")
      setDescription("")
      setMitigation("")
      setComponents("")
    } catch (err) {
      console.error("Create risk error:", err)
    }
  }

  const handleToggleRiskStatus = async (riskId: string, currentStatus: string) => {
    try {
      await api.updateRiskStatus(riskId, currentStatus === "mitigated" ? "open" : "mitigated")
      await loadRisks()
    } catch (err) {
      console.error("Risk status update error:", err)
    }
  }

  const filtered = risks.filter(r =>
    (r.title && r.title.toLowerCase().includes(search.toLowerCase())) ||
    (r.description && r.description.toLowerCase().includes(search.toLowerCase()))
  )

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Technical Risks & Bottlenecks</h1>
          <p className="text-xs text-slate-500 mt-0.5">Identified single points of failure, code vulnerabilities, and dependency bottlenecks</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-rose-600 hover:bg-rose-700 text-white flex items-center gap-1.5 shadow-md shadow-rose-600/20 transition-all hover:scale-[1.02]"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Log Risk</span>
        </button>
      </div>

      <div className="flex items-center justify-between gap-3 apple-card p-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search risks by keyword, component..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-1.5 rounded-full text-xs bg-slate-50 border border-slate-200 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-rose-500 focus:bg-white"
          />
        </div>
        <div className="text-xs text-slate-500 font-mono">
          {filtered.length} Risks Logged
        </div>
      </div>

      <div className="space-y-4">
        {filtered.map((r) => (
          <div
            key={r.id}
            className="apple-card p-5 space-y-3 hover:border-rose-200 transition-all"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className={`text-[10px] font-mono px-2.5 py-0.5 rounded-full font-bold uppercase ${
                    r.severity === "critical"
                      ? "bg-rose-50 text-rose-600 border border-rose-200"
                      : "bg-amber-50 text-amber-700 border border-amber-200"
                  }`}>
                    {r.severity} Severity
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 uppercase">
                    Likelihood: {r.likelihood}
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                    {r.category?.replace("_", " ").toUpperCase()}
                  </span>
                </div>
                <h2 className="text-base font-bold text-slate-900 tracking-tight">{r.title}</h2>
              </div>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              {r.description}
            </p>

            {r.mitigation_strategy && (
              <div className="p-3 rounded-xl bg-emerald-50/70 border border-emerald-100 space-y-1">
                <span className="text-[10px] font-bold text-emerald-800 uppercase tracking-wider block">
                  Mitigation Strategy
                </span>
                <p className="text-xs text-emerald-950 leading-relaxed">
                  {r.mitigation_strategy}
                </p>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${
                  r.status === "mitigated"
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-rose-50 text-rose-700 border-rose-200"
                }`}>
                  {r.status || "open"}
                </span>
                {r.related_components && r.related_components.length > 0 && r.related_components.map((comp: string, i: number) => (
                  <span key={i} className="px-2 py-0.5 rounded-md text-[11px] bg-slate-100 text-slate-700">
                    {comp}
                  </span>
                ))}
              </div>
              <button
                onClick={() => handleToggleRiskStatus(r.id, r.status)}
                className="px-3 py-1 rounded-xl text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
              >
                <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                <span>{r.status === "mitigated" ? "Reopen Risk" : "Mark Mitigated"}</span>
              </button>
            </div>
          </div>
        ))}

        {filtered.length === 0 && !loading && (
          <div className="apple-card p-12 text-center">
            <AlertTriangle className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <h3 className="text-sm font-bold text-slate-800">No Risks Logged</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              Log architectural risks, single points of failure, or unmitigated technical debt.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-rose-600 hover:bg-rose-700 text-white"
            >
              Log First Risk
            </button>
          </div>
        )}
      </div>

      {/* Log Risk Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Log Technical Risk</h3>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600 text-xs">✕ Close</button>
            </div>
            <form onSubmit={handleCreate} className="space-y-3.5">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Risk Title *</label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Single Point of Failure in Redis Cluster"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-rose-500 focus:bg-white"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Description *</label>
                <textarea
                  rows={2}
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Detail the technical risk, impact, and failure modes..."
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-rose-500 focus:bg-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Severity</label>
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-rose-500"
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Likelihood</label>
                  <select
                    value={likelihood}
                    onChange={(e) => setLikelihood(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-rose-500"
                  >
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Mitigation Strategy</label>
                <textarea
                  rows={2}
                  value={mitigation}
                  onChange={(e) => setMitigation(e.target.value)}
                  placeholder="Planned mitigation, circuit breaker, failover..."
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-rose-500 focus:bg-white"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Affected Components (comma-separated)</label>
                <input
                  type="text"
                  value={components}
                  onChange={(e) => setComponents(e.target.value)}
                  placeholder="e.g. Redis, Payment Adapter"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-rose-500"
                />
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
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-rose-600 hover:bg-rose-700 text-white shadow-md shadow-rose-600/20"
                >
                  Save Risk
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
