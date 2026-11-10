"use client"

import { useEffect, useState } from "react"
import { api, getStoredProjectId } from "@/lib/api"
import { HelpCircle, Plus, CheckCircle2, AlertTriangle, RotateCcw } from "lucide-react"

export default function GapsPage() {
  const [gaps, setGaps] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)

  // Create form
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [gapType, setGapType] = useState("undocumented_process")
  const [severity, setSeverity] = useState("high")
  const [impact, setImpact] = useState("")
  const [recommendedAction, setRecommendedAction] = useState("")

  const loadAll = async (pid?: string) => {
    try {
      setLoading(true)
      const storedPid = pid !== undefined ? pid : getStoredProjectId()
      const [projs, list] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getGaps(storedPid || undefined).catch(() => []),
      ])
      setProjects(Array.isArray(projs) ? projs : [])
      const resolved = storedPid || (Array.isArray(projs) && projs[0]?.id) || ""
      if (pid === undefined) setActiveProject(resolved)
      setGaps(Array.isArray(list) ? list : [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    const targetPid = activeProject || projects[0]?.id || ""
    if (!targetPid) {
      alert("Create a project first before logging a knowledge gap.")
      return
    }
    try {
      await api.createGap({
        project_id: targetPid,
        title,
        description,
        gap_type: gapType,
        severity,
        impact: impact || "May delay successor onboarding or incident response.",
        recommended_action: recommendedAction || "Conduct a targeted KT walkthrough and document the procedure.",
      })
      setShowModal(false)
      setTitle("")
      setDescription("")
      setImpact("")
      setRecommendedAction("")
      await loadAll(activeProject)
    } catch (err: any) {
      alert(err.message || "Could not log knowledge gap")
    }
  }

  const handleToggleStatus = async (gap: any) => {
    const nextStatus = gap.status === "resolved" ? "open" : "resolved"
    try {
      await api.resolveGap(gap.id, nextStatus)
      await loadAll(activeProject)
    } catch (err: any) {
      alert(err.message || "Failed to update gap status")
    }
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge Gaps &amp; Missing Evidence</h1>
          <p className="text-xs text-slate-500 mt-1">
            Identify undocumented tribal knowledge, orphaned services, and unresolved handover questions.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              loadAll(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20 flex items-center gap-1.5"
          >
            <Plus className="w-3.5 h-3.5" /> Log Knowledge Gap
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {gaps.map((g) => {
          const isResolved = g.status === "resolved"
          return (
            <div key={g.id} className="apple-card p-5 flex flex-col justify-between gap-4">
              <div className="space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase border ${
                        g.severity === "critical"
                          ? "bg-rose-50 text-rose-700 border-rose-200"
                          : g.severity === "high"
                          ? "bg-amber-50 text-amber-700 border-amber-200"
                          : "bg-sky-50 text-sky-700 border-sky-200"
                      }`}
                    >
                      {g.severity} severity
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 font-semibold uppercase">
                      {g.gap_type?.replace("_", " ")}
                    </span>
                  </div>
                  <span
                    className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase border ${
                      isResolved
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-amber-50 text-amber-700 border-amber-200"
                    }`}
                  >
                    {g.status}
                  </span>
                </div>

                <h3 className="text-sm font-bold text-slate-900">{g.title}</h3>
                <p className="text-xs text-slate-600 leading-relaxed">{g.description}</p>

                <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 text-[11px] space-y-1">
                  <div>
                    <strong className="text-rose-700">Impact:</strong>{" "}
                    <span className="text-slate-600">{g.impact}</span>
                  </div>
                  <div>
                    <strong className="text-violet-700">Recommended Action:</strong>{" "}
                    <span className="text-slate-600">{g.recommended_action}</span>
                  </div>
                </div>
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-between">
                <span className="text-[10px] text-slate-400">
                  Logged {g.created_at ? new Date(g.created_at).toLocaleDateString() : ""}
                </span>
                <button
                  onClick={() => handleToggleStatus(g)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 border transition-all ${
                    isResolved
                      ? "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                      : "bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-600"
                  }`}
                >
                  {isResolved ? (
                    <>
                      <RotateCcw className="w-3 h-3" /> Reopen Gap
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-3 h-3" /> Mark Resolved
                    </>
                  )}
                </button>
              </div>
            </div>
          )
        })}

        {!loading && gaps.length === 0 && (
          <div className="col-span-full apple-card p-12 text-center space-y-2">
            <HelpCircle className="w-10 h-10 text-slate-300 mx-auto" />
            <h3 className="text-sm font-bold text-slate-800">No Knowledge Gaps Open</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Detected undocumented workflows or manually flagged handover blind spots will appear here.
            </p>
          </div>
        )}
      </div>

      {/* Create Gap Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-500" /> Log Knowledge Gap
              </h3>
              <button onClick={() => setShowModal(false)} className="text-xs text-slate-400">✕ Close</button>
            </div>
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Gap Title *</label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Undocumented webhook dead-letter replay steps"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Type</label>
                  <select
                    value={gapType}
                    onChange={(e) => setGapType(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  >
                    <option value="undocumented_process">Undocumented Process</option>
                    <option value="missing_evidence">Missing Evidence</option>
                    <option value="single_point_of_failure">Single Point of Failure</option>
                    <option value="access_credentials">Access / Credentials</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Severity</label>
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Description *</label>
                <textarea
                  rows={2}
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Impact</label>
                <input
                  type="text"
                  value={impact}
                  onChange={(e) => setImpact(e.target.value)}
                  placeholder="What fails if this remains unresolved?"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Recommended Action</label>
                <input
                  type="text"
                  value={recommendedAction}
                  onChange={(e) => setRecommendedAction(e.target.value)}
                  placeholder="e.g. Pair with owner to document runbook"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="px-3 py-1.5 rounded-xl text-xs text-slate-600">Cancel</button>
                <button type="submit" className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 text-white">Save Gap</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
