"use client"

import React, { useCallback, useEffect, useState } from "react"
import { Activity, Clock, Search } from "lucide-react"
import { api, getStoredProjectId, isAllProjectsSelected, resolveActiveProjectId, setStoredProjectId } from "@/lib/api"

export default function ActivityPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const allSelected = isAllProjectsSelected()
      const storedPid = allSelected ? "" : getStoredProjectId()
      const [projs, actsRaw] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getActivity(storedPid || undefined).catch(() => []),
      ])
      const projList = Array.isArray(projs) ? projs : []
      setProjects(projList)
      const resolvedPid = allSelected ? "" : resolveActiveProjectId(projList, storedPid || undefined)
      setActiveProject(resolvedPid)

      let finalActs = Array.isArray(actsRaw) ? actsRaw : []
      if (!allSelected && resolvedPid && resolvedPid !== storedPid) {
        finalActs = await api.getActivity(resolvedPid).catch(() => [])
      }
      setLogs(Array.isArray(finalActs) ? finalActs : [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    window.addEventListener("obsidian_project_changed", load)
    return () => window.removeEventListener("obsidian_project_changed", load)
  }, [load])

  const filteredLogs = logs.filter((log) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    const detailMsg = log.details?.message || (typeof log.details === "string" ? log.details : JSON.stringify(log.details || ""))
    return log.action?.toLowerCase().includes(q) || detailMsg.toLowerCase().includes(q)
  })

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Project Activity Stream</h1>
          <p className="text-xs text-slate-500 mt-0.5">Live immutable audit log of knowledge ingestion, verification reviews, and handover milestones</p>
        </div>

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
      </div>

      <div className="relative max-w-md">
        <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter activity by action or message..."
          className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 shadow-sm focus:outline-none focus:border-violet-500"
        />
      </div>

      <div className="apple-card p-5 space-y-3">
        {filteredLogs.map((log, idx) => (
          <div key={log.id || idx} className="flex items-start gap-4 p-3.5 rounded-xl bg-slate-50 border border-slate-100 hover:border-violet-200 transition-all">
            <div className="w-8 h-8 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center flex-shrink-0 mt-0.5 font-bold text-xs">
              <Activity className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-xs font-bold text-slate-800 uppercase tracking-wide">
                  {log.action?.replace(".", " → ").toUpperCase() || "AUDIT EVENT"}
                </span>
                <span className="text-[10px] text-slate-400 font-mono">
                  {log.created_at ? new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "Just now"}
                </span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                {log.details?.message || (typeof log.details === "string" ? log.details : JSON.stringify(log.details))}
              </p>
            </div>
          </div>
        ))}

        {filteredLogs.length === 0 && !loading && (
          <div className="py-12 text-center">
            <Clock className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <h3 className="text-sm font-bold text-slate-800">No Activity Logged</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1">
              Events such as integration syncs, ADR creation, task updates, and handover sign-offs will appear here.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
