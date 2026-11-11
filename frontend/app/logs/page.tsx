"use client"

import { useCallback, useEffect, useState } from "react"
import { api, getStoredProjectId, isAllProjectsSelected, resolveActiveProjectId, setStoredProjectId } from "@/lib/api"
import { Terminal, Search, RefreshCw } from "lucide-react"

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [entityFilter, setEntityFilter] = useState("All")
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")

  const loadLogs = useCallback(async () => {
    try {
      setLoading(true)
      const allSelected = isAllProjectsSelected()
      const storedPid = allSelected ? "" : getStoredProjectId()
      const [projs, res] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getOrgActivity(storedPid || undefined).catch(() => []),
      ])
      const projList = Array.isArray(projs) ? projs : []
      setProjects(projList)
      const resolvedPid = allSelected ? "" : resolveActiveProjectId(projList, storedPid || undefined)
      setActiveProject(resolvedPid)

      let finalLogs = Array.isArray(res) ? res : []
      if (!allSelected && resolvedPid && resolvedPid !== storedPid) {
        finalLogs = await api.getOrgActivity(resolvedPid).catch(() => [])
      }
      setLogs(Array.isArray(finalLogs) ? finalLogs : [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  useEffect(() => {
    const onProjectChange = () => {
      loadLogs()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [loadLogs])

  const entityTypes = [
    "All",
    ...Array.from(new Set(logs.map((l) => String(l.entity_type || "system").toLowerCase()))),
  ]

  const filtered = logs.filter((l) => {
    if (entityFilter !== "All" && String(l.entity_type || "system").toLowerCase() !== entityFilter) return false
    if (!search.trim()) return true
    const s = search.toLowerCase()
    const detailStr = typeof l.details === "string" ? l.details : JSON.stringify(l.details || {})
    return (
      l.action?.toLowerCase().includes(s) ||
      l.actor_email?.toLowerCase().includes(s) ||
      l.entity_type?.toLowerCase().includes(s) ||
      detailStr.toLowerCase().includes(s)
    )
  })

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Security &amp; Workspace Audit Logs</h1>
          <p className="text-xs text-slate-500 mt-1">
            Immutable trail of authentication, member role assignments, source syncs, and handover approvals.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              setStoredProjectId(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button
            onClick={loadLogs}
            className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1.5 shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh Logs
          </button>
        </div>
      </div>

      <div className="apple-card p-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by action, actor email, entity..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {entityTypes.map((et) => (
            <button
              key={et}
              onClick={() => setEntityFilter(et)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold capitalize border transition-all ${
                entityFilter === et
                  ? "bg-violet-600 text-white border-violet-600"
                  : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
              }`}
            >
              {et.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      <div className="apple-card overflow-hidden">
        {loading ? (
          <div className="p-10 text-center text-xs text-slate-400">Loading audit events...</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <Terminal className="w-9 h-9 text-slate-300 mx-auto" />
            <p className="text-sm font-bold text-slate-800">No Audit Events Recorded</p>
            <p className="text-xs text-slate-500">Workspace actions will appear here automatically as your team collaborates.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-100 text-[10px] font-bold uppercase text-slate-500">
                <tr>
                  <th className="px-5 py-3">Timestamp</th>
                  <th className="px-5 py-3">Action</th>
                  <th className="px-5 py-3">Entity</th>
                  <th className="px-5 py-3">Actor</th>
                  <th className="px-5 py-3">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((log) => {
                  const detailMsg =
                    log.details?.message ||
                    (typeof log.details === "string" ? log.details : JSON.stringify(log.details || {}))
                  return (
                    <tr key={log.id} className="hover:bg-slate-50/70">
                      <td className="px-5 py-3 font-mono text-[11px] text-slate-500 whitespace-nowrap">
                        {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-5 py-3">
                        <span className="px-2 py-0.5 rounded-md bg-violet-50 text-violet-700 border border-violet-200 font-mono text-[11px] font-semibold">
                          {log.action}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-slate-600 uppercase text-[10px] font-bold">{log.entity_type}</td>
                      <td className="px-5 py-3 text-slate-700 font-medium">{log.actor_email || "System"}</td>
                      <td className="px-5 py-3 text-slate-600 max-w-md truncate">{detailMsg}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
