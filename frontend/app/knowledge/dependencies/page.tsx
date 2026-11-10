"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { GitMerge, Search, ShieldAlert } from "lucide-react"

export default function DependenciesPage() {
  const [deps, setDeps] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [criticalityFilter, setCriticalityFilter] = useState("All")
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  const loadData = async (pid?: string) => {
    try {
      setLoading(true)
      const storedPid =
        pid !== undefined
          ? pid
          : typeof window !== "undefined"
          ? localStorage.getItem("obsidian_active_project") || ""
          : ""
      const [projs, rows] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getDependencies(storedPid || undefined).catch(() => []),
      ])
      setProjects(Array.isArray(projs) ? projs : [])
      setActiveProject(storedPid)
      setDeps(Array.isArray(rows) ? rows : [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const filtered = deps.filter((d) => {
    const matchCrit =
      criticalityFilter === "All" || (d.criticality || "medium").toLowerCase() === criticalityFilter.toLowerCase()
    const matchSearch =
      !search.trim() ||
      d.source_component?.toLowerCase().includes(search.toLowerCase()) ||
      d.target_component?.toLowerCase().includes(search.toLowerCase()) ||
      d.description?.toLowerCase().includes(search.toLowerCase()) ||
      d.owner?.toLowerCase().includes(search.toLowerCase())
    return matchCrit && matchSearch
  })

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Service &amp; Infrastructure Dependencies</h1>
          <p className="text-xs text-slate-500 mt-1">
            Track cross-service coupling, third-party APIs, and component ownership extracted from evidence.
          </p>
        </div>

        <select
          value={activeProject}
          onChange={(e) => {
            const pid = e.target.value
            setActiveProject(pid)
            if (typeof window !== "undefined") {
              if (pid) localStorage.setItem("obsidian_active_project", pid)
              else localStorage.removeItem("obsidian_active_project")
              window.dispatchEvent(new Event("obsidian_project_changed"))
            }
            loadData(pid)
          }}
          className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
        >
          <option value="">All Accessible Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by service, dependency target, or owner..."
            className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 shadow-sm focus:outline-none focus:border-violet-500"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {["All", "critical", "high", "medium", "low"].map((c) => (
            <button
              key={c}
              onClick={() => setCriticalityFilter(c)}
              className={`px-3 py-1.5 rounded-xl text-[11px] font-semibold capitalize border transition-all ${
                criticalityFilter === c
                  ? "bg-violet-600 text-white border-violet-600 shadow-sm"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Dependencies Table Card */}
      <div className="apple-card overflow-hidden">
        {loading ? (
          <div className="p-10 text-center text-xs text-slate-400">Loading architecture dependencies...</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <GitMerge className="w-9 h-9 text-slate-300 mx-auto" />
            <h3 className="text-sm font-bold text-slate-800">No Dependencies Recorded Yet</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Run AI Knowledge Graph extraction from connected sources or documents to map service dependencies.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-100 text-[10px] font-bold uppercase text-slate-500">
                <tr>
                  <th className="px-5 py-3">Source Component</th>
                  <th className="px-5 py-3">Relationship</th>
                  <th className="px-5 py-3">Target Dependency</th>
                  <th className="px-5 py-3">Criticality</th>
                  <th className="px-5 py-3">Owner</th>
                  <th className="px-5 py-3">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50/70 transition-colors">
                    <td className="px-5 py-3.5 font-bold text-slate-900">{d.source_component}</td>
                    <td className="px-5 py-3.5">
                      <span className="px-2 py-0.5 rounded-md bg-violet-50 text-violet-700 border border-violet-200 text-[10px] font-mono font-semibold">
                        {d.dependency_type}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 font-bold text-slate-900">{d.target_component}</td>
                    <td className="px-5 py-3.5">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${
                          d.criticality === "critical"
                            ? "bg-rose-50 text-rose-700 border-rose-200"
                            : d.criticality === "high"
                            ? "bg-amber-50 text-amber-700 border-amber-200"
                            : "bg-slate-100 text-slate-600 border-slate-200"
                        }`}
                      >
                        {d.criticality === "critical" && <ShieldAlert className="w-2.5 h-2.5" />}
                        {d.criticality || "medium"}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-slate-600 font-medium">{d.owner || "Unassigned"}</td>
                    <td className="px-5 py-3.5 text-slate-500 max-w-xs truncate">{d.description || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
