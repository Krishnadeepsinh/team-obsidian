"use client"

import { useCallback, useEffect, useState } from "react"
import { api, getStoredProjectId, resolveActiveProjectId, safeHref, setStoredProjectId } from "@/lib/api"
import { Clock, Scale, CheckSquare, GitCommit, ExternalLink, Search } from "lucide-react"

export default function TimelinePage() {
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [events, setEvents] = useState<any[]>([])
  const [typeFilter, setTypeFilter] = useState("All")
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  const loadTimeline = useCallback(async (pid?: string) => {
    try {
      setLoading(true)
      const storedPid = pid !== undefined ? pid : getStoredProjectId()
      const projs = await api.getProjects().catch(() => [])
      const list = Array.isArray(projs) ? projs : []
      setProjects(list)

      const targetPid = resolveActiveProjectId(list, storedPid) || list[0]?.id || ""
      setActiveProject(targetPid)

      if (targetPid) {
        const res = await api.getProjectTimeline(targetPid).catch(() => [])
        setEvents(Array.isArray(res) ? res : [])
      } else {
        setEvents([])
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTimeline()
  }, [loadTimeline])

  useEffect(() => {
    const onProjectChange = () => {
      loadTimeline()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [loadTimeline])

  const eventTypes = [
    "All",
    ...Array.from(new Set(events.map((e) => String(e.type || "event").toLowerCase()))),
  ]

  const filteredEvents = events.filter((ev) => {
    if (typeFilter !== "All" && String(ev.type || "").toLowerCase() !== typeFilter) return false
    const q = search.trim().toLowerCase()
    if (!q) return true
    return (
      ev.title?.toLowerCase().includes(q) ||
      ev.description?.toLowerCase().includes(q) ||
      ev.author?.toLowerCase().includes(q) ||
      ev.badge?.toLowerCase().includes(q)
    )
  })

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Project Knowledge Timeline</h1>
          <p className="text-xs text-slate-500 mt-1">
            Chronological history of commits, PRs, discussions, decisions, and tasks across your project.
          </p>
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
          {projects.length === 0 && <option value="">No Projects</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      <div className="apple-card p-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search timeline events, authors..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {eventTypes.map((et) => (
            <button
              key={et}
              onClick={() => setTypeFilter(et)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold capitalize border transition-all ${
                typeFilter === et
                  ? "bg-violet-600 text-white border-violet-600"
                  : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
              }`}
            >
              {et.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="apple-card p-10 text-center text-xs text-slate-400">Loading project chronology...</div>
      ) : filteredEvents.length === 0 ? (
        <div className="apple-card p-12 text-center space-y-2">
          <Clock className="w-9 h-9 text-slate-300 mx-auto" />
          <h3 className="text-sm font-bold text-slate-800">No Matching Timeline Events</h3>
          <p className="text-xs text-slate-500 max-w-sm mx-auto">
            Create a project and sync integrations or upload documentation to track project milestones.
          </p>
        </div>
      ) : (
        <div className="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-violet-200">
          {filteredEvents.map((ev) => (
            <div key={ev.id} className="relative apple-card p-4 space-y-2">
              <div className="absolute -left-[22px] top-5 w-3.5 h-3.5 rounded-full bg-violet-600 border-2 border-white shadow" />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  {ev.type === "decision" ? (
                    <Scale className="w-3.5 h-3.5 text-emerald-600" />
                  ) : ev.type === "task" ? (
                    <CheckSquare className="w-3.5 h-3.5 text-amber-600" />
                  ) : (
                    <GitCommit className="w-3.5 h-3.5 text-violet-600" />
                  )}
                  <h3 className="text-sm font-bold text-slate-900">{ev.title}</h3>
                </div>
                <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 font-bold uppercase">
                  {ev.badge}
                </span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">{ev.description}</p>
              <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                <span>By {ev.author || "Team"}</span>
                <div className="flex items-center gap-3">
                  <span>{ev.timestamp ? new Date(ev.timestamp).toLocaleString() : ""}</span>
                  {(() => {
                    const safeTimelineUrl = safeHref(ev.url)
                    return safeTimelineUrl ? (
                      <a href={safeTimelineUrl} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                        Origin <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : null
                  })()}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
