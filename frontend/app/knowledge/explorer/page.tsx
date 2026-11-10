"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Compass, Search, User, ShieldCheck } from "lucide-react"

const CATEGORIES = [
  "All",
  "Decisions",
  "Tasks",
  "Risks",
  "Knowledge Gaps",
  "Entities",
]

const VERIFICATION_STATUSES = [
  "All",
  "Draft / AI Suggested",
  "Supported by Evidence",
  "Needs Human Verification",
  "Verified by Reviewer",
  "Contradicted",
  "Outdated",
  "Unknown / Missing Evidence",
]

export default function KnowledgeExplorerPage() {
  const [items, setItems] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [category, setCategory] = useState("All")
  const [verificationStatus, setVerificationStatus] = useState("All")
  const [employee, setEmployee] = useState("")
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  const loadData = useCallback(async (pid?: string, cat?: string, q?: string, vstat?: string, emp?: string) => {
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
        api
          .getKnowledgeExplorer(
            storedPid || undefined,
            cat === "All" ? undefined : cat,
            q || undefined,
            vstat === "All" ? undefined : vstat,
            emp || undefined
          )
          .catch(() => []),
      ])
      setProjects(Array.isArray(projs) ? projs : [])
      if (pid === undefined) setActiveProject(storedPid)
      setItems(Array.isArray(rows) ? rows : [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData(undefined, "All", "", "All", "")
  }, [loadData])

  const applyFilters = (nextPid = activeProject, nextCat = category, nextQ = search, nextVs = verificationStatus, nextEmp = employee) => {
    loadData(nextPid, nextCat, nextQ, nextVs, nextEmp)
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge Explorer</h1>
          <p className="text-xs text-slate-500 mt-1">
            Unified searchable index of decisions, tasks, risks, knowledge gaps, and technical entities.
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
            applyFilters(pid, category, search, verificationStatus, employee)
          }}
          className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
        >
          <option value="">All Accessible Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Filters Bar */}
      <div className="apple-card p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                applyFilters(activeProject, category, e.target.value, verificationStatus, employee)
              }}
              placeholder="Search titles, summaries, rationale..."
              className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
            />
          </div>

          <div className="relative">
            <User className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={employee}
              onChange={(e) => {
                setEmployee(e.target.value)
                applyFilters(activeProject, category, search, verificationStatus, e.target.value)
              }}
              placeholder="Filter by owner / author..."
              className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
            />
          </div>

          <select
            value={verificationStatus}
            onChange={(e) => {
              setVerificationStatus(e.target.value)
              applyFilters(activeProject, category, search, e.target.value, employee)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-800 focus:outline-none focus:border-violet-500"
          >
            {VERIFICATION_STATUSES.map((vs) => (
              <option key={vs} value={vs}>{vs === "All" ? "All Verification States" : vs}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => {
                setCategory(cat)
                applyFilters(activeProject, cat, search, verificationStatus, employee)
              }}
              className={`px-3 py-1 rounded-xl text-[11px] font-semibold border transition-all ${
                category === cat
                  ? "bg-violet-600 text-white border-violet-600 shadow-sm"
                  : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((item) => (
          <div key={`${item.category}-${item.id}`} className="apple-card p-5 flex flex-col justify-between gap-3">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase bg-violet-50 text-violet-700 border border-violet-200">
                  {item.category}
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">
                  {item.verification_status || item.status}
                </span>
              </div>
              <h3 className="text-sm font-bold text-slate-900">{item.title}</h3>
              {item.subtitle && <p className="text-[11px] text-slate-400">{item.subtitle}</p>}
              <p className="text-xs text-slate-600 line-clamp-3 leading-relaxed">{item.summary || item.content}</p>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1 font-medium text-slate-700">
                <User className="w-3 h-3 text-slate-400" /> {item.owner || "Unassigned"}
              </span>
              <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold">
                <ShieldCheck className="w-3 h-3" /> {Math.round((item.confidence || 0.7) * 100)}%
              </span>
            </div>
          </div>
        ))}

        {!loading && items.length === 0 && (
          <div className="col-span-full apple-card p-12 text-center">
            <Compass className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <h3 className="text-sm font-bold text-slate-800">No Knowledge Records Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1">
              Connect integrations, upload documents, or create decisions and tasks to populate the knowledge explorer.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
