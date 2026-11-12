"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { api, getStoredProjectId, isAllProjectsSelected, resolveActiveProjectId, setStoredProjectId } from "@/lib/api"
import { ShieldCheck, Search, ExternalLink, Clock, User, FolderGit2, Layers, RotateCcw, AlertTriangle, RefreshCw, CheckCircle2, X } from "lucide-react"

const STATUS_FILTERS = [
  "All",
  "Draft / AI Suggested",
  "Supported by Evidence",
  "Needs Human Verification",
  "Verified by Reviewer",
  "Contradicted",
  "Outdated",
  "Unknown / Missing Evidence",
]

const SOURCE_TYPE_LABELS: Record<string, string> = {
  github_commit: "Commits",
  github_pr: "Pull Requests",
  github_issue: "Issues",
  github_repository: "Repositories",
  github_ast: "Code AST",
  document: "Documents",
  slack_message: "Slack",
  notion_page: "Notion Pages",
  notion_database: "Notion DBs",
}

const PAGE_SIZE = 24

function formatSourceType(st?: string): string {
  if (!st) return "Other"
  const norm = st.toLowerCase()
  return SOURCE_TYPE_LABELS[norm] || st.replace(/_/g, " ")
}

function getEvidenceOrigin(ev: any): string {
  const meta = ev?.metadata_json && typeof ev.metadata_json === "object" ? ev.metadata_json : {}
  for (const key of ["repository", "repo", "channel_name", "channel_id", "filename", "database_id"]) {
    if (meta[key]) return String(meta[key]).trim()
  }
  const url = String(ev?.source_url || "")
  const ghMatch = url.match(/github\.com\/([^/]+\/[^/]+)/i)
  if (ghMatch) return ghMatch[1]
  return ""
}

function statusMatches(actual?: string, selected?: string): boolean {
  if (!selected || selected === "All") return true
  const a = (actual || "").trim().toLowerCase()
  const s = selected.trim().toLowerCase()
  if (s === "verified by reviewer" || s === "verified") {
    return a === "verified by reviewer" || a === "verified"
  }
  return a === s
}

const STATUS_BADGE_CLASS = (status: string) => {
  if (status === "Verified by Reviewer" || status === "Verified") {
    return "bg-emerald-50 text-emerald-700 border-emerald-200"
  }
  if (status === "Supported by Evidence") {
    return "bg-sky-50 text-sky-700 border-sky-200"
  }
  if (status === "Contradicted" || status === "Rejected") {
    return "bg-rose-50 text-rose-700 border-rose-200"
  }
  if (status === "Outdated" || status === "Unknown / Missing Evidence") {
    return "bg-slate-100 text-slate-600 border-slate-200"
  }
  return "bg-amber-50 text-amber-700 border-amber-200"
}

export default function EvidencePage() {
  const [evidences, setEvidences] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState("All")
  const [sourceTypeFilter, setSourceTypeFilter] = useState("All")
  const [originFilter, setOriginFilter] = useState("All")
  const [authorFilter, setAuthorFilter] = useState("All")
  const [search, setSearch] = useState("")
  const [visibleLimit, setVisibleLimit] = useState(PAGE_SIZE)
  const [selectedAudit, setSelectedAudit] = useState<any>(null)
  const [auditNotes, setAuditNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [auditError, setAuditError] = useState("")
  const [driftAlerts, setDriftAlerts] = useState<any[]>([])
  const [scanningDrift, setScanningDrift] = useState(false)
  const [driftMessage, setDriftMessage] = useState("")

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      const allSelected = isAllProjectsSelected()
      const storedPid = allSelected ? "" : getStoredProjectId()
      const [projs, resRaw, driftRaw] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getEvidence(storedPid || undefined).catch(() => []),
        api.getKnowledgeDrift(storedPid || undefined, "open").catch(() => []),
      ])
      const projList = Array.isArray(projs) ? projs : []
      setProjects(projList)
      const resolvedPid = allSelected ? "" : resolveActiveProjectId(projList, storedPid || undefined)
      setActiveProject(resolvedPid)

      let finalRes = Array.isArray(resRaw) ? resRaw : []
      if (!allSelected && resolvedPid && resolvedPid !== storedPid) {
        finalRes = await api.getEvidence(resolvedPid).catch(() => [])
      }
      setEvidences(Array.isArray(finalRes) ? finalRes : [])
      setDriftAlerts(Array.isArray(driftRaw) ? driftRaw : [])
      setVisibleLimit(PAGE_SIZE)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleScanDrift = async () => {
    try {
      setScanningDrift(true)
      setDriftMessage("")
      const res = await api.scanKnowledgeDrift(activeProject || undefined)
      setDriftMessage(
        res?.detected > 0
          ? `Detected ${res.detected} new knowledge drift alert(s) against ADRs, risks, and claims.`
          : "Drift scan complete — no new contradictions detected."
      )
      await loadData()
    } catch (err: any) {
      setDriftMessage(err?.message || "Drift scan failed.")
    } finally {
      setScanningDrift(false)
    }
  }

  const handleResolveDrift = async (id: string, nextStatus: "resolved" | "dismissed") => {
    try {
      await api.updateDriftStatus(id, nextStatus)
      setDriftAlerts((prev) => prev.filter((d) => d.id !== id))
    } catch {}
  }

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    const onProjectChange = () => {
      setOriginFilter("All")
      setAuthorFilter("All")
      setSourceTypeFilter("All")
      loadData()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [loadData])

  const projectNames = useMemo(() => {
    const map: Record<string, string> = {}
    for (const p of projects) {
      if (p?.id) map[p.id] = p.name
    }
    return map
  }, [projects])

  const sourceTypeOptions = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const ev of evidences) {
      const st = (ev.source_type || "other").toLowerCase()
      counts[st] = (counts[st] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [evidences])

  const originOptions = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const ev of evidences) {
      const orig = getEvidenceOrigin(ev)
      if (orig) counts[orig] = (counts[orig] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [evidences])

  const authorOptions = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const ev of evidences) {
      const auth = (ev.source_author || "").trim()
      if (auth) counts[auth] = (counts[auth] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [evidences])

  const statusCounts = useMemo(() => {
    const baseFiltered = evidences.filter((ev) => {
      if (sourceTypeFilter !== "All" && (ev.source_type || "").toLowerCase() !== sourceTypeFilter.toLowerCase()) return false
      if (originFilter !== "All" && getEvidenceOrigin(ev) !== originFilter) return false
      if (authorFilter !== "All" && (ev.source_author || "").trim() !== authorFilter) return false
      return true
    })
    const map: Record<string, number> = { All: baseFiltered.length }
    for (const st of STATUS_FILTERS) {
      if (st === "All") continue
      map[st] = baseFiltered.filter((ev) => statusMatches(ev.verification_status, st)).length
    }
    return map
  }, [evidences, sourceTypeFilter, originFilter, authorFilter])

  const handleAuditAction = async (newStatus: string) => {
    if (!selectedAudit) return
    try {
      setSubmitting(true)
      setAuditError("")
      await api.auditEvidence(selectedAudit.id, newStatus, auditNotes)
      setSelectedAudit(null)
      setAuditNotes("")
      await loadData()
    } catch (err: any) {
      setAuditError(err.message || "Audit submission failed")
    } finally {
      setSubmitting(false)
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return evidences.filter((ev) => {
      if (!statusMatches(ev.verification_status, statusFilter)) return false
      if (sourceTypeFilter !== "All" && (ev.source_type || "").toLowerCase() !== sourceTypeFilter.toLowerCase()) return false
      if (originFilter !== "All" && getEvidenceOrigin(ev) !== originFilter) return false
      if (authorFilter !== "All" && (ev.source_author || "").trim() !== authorFilter) return false
      if (q) {
        const origin = getEvidenceOrigin(ev).toLowerCase()
        const matchesQ =
          ev.source_title?.toLowerCase().includes(q) ||
          ev.excerpt?.toLowerCase().includes(q) ||
          ev.ai_interpretation?.toLowerCase().includes(q) ||
          ev.source_author?.toLowerCase().includes(q) ||
          origin.includes(q)
        if (!matchesQ) return false
      }
      return true
    })
  }, [evidences, statusFilter, sourceTypeFilter, originFilter, authorFilter, search])

  const visibleItems = filtered.slice(0, visibleLimit)
  const hasActiveFilters =
    statusFilter !== "All" || sourceTypeFilter !== "All" || originFilter !== "All" || authorFilter !== "All" || search.trim() !== ""

  const resetFilters = () => {
    setStatusFilter("All")
    setSourceTypeFilter("All")
    setOriginFilter("All")
    setAuthorFilter("All")
    setSearch("")
    setVisibleLimit(PAGE_SIZE)
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Evidence Verification &amp; Provenance</h1>
          <p className="text-xs text-slate-500 mt-1">
            Inspect original source excerpts, cryptographic hashes, authors, and human verification states.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleScanDrift}
            disabled={scanningDrift}
            className="px-3 py-2 rounded-xl text-xs font-semibold bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1.5 shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${scanningDrift ? "animate-spin" : ""}`} />
            <span>{scanningDrift ? "Scanning Drift..." : "Scan for Drift"}</span>
          </button>
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              setStoredProjectId(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      </div>

      {driftMessage && (
        <div className="p-3 rounded-xl bg-sky-50 border border-sky-200 text-sky-800 text-xs font-medium">{driftMessage}</div>
      )}

      {driftAlerts.length > 0 && (
        <div className="apple-card p-4 border border-amber-200 bg-amber-50/40 space-y-2.5">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold text-amber-900 flex items-center gap-1.5 uppercase tracking-wide">
              <AlertTriangle className="w-4 h-4 text-amber-600" />
              <span>Knowledge Drift Alerts ({driftAlerts.length} Open)</span>
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {driftAlerts.slice(0, 6).map((da) => (
              <div key={da.id} className="p-3 rounded-xl bg-white border border-amber-200/80 space-y-1.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-900 truncate">{da.target_title}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 font-bold uppercase flex-shrink-0">
                    {da.severity} • {da.drift_type?.replace("_", " ")}
                  </span>
                </div>
                <p className="text-[11px] text-slate-600 line-clamp-2">{da.summary}</p>
                <div className="flex items-center justify-end gap-1.5 pt-1">
                  <button
                    onClick={() => handleResolveDrift(da.id, "resolved")}
                    className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 inline-flex items-center gap-1"
                  >
                    <CheckCircle2 className="w-3 h-3" /> Resolve
                  </button>
                  <button
                    onClick={() => handleResolveDrift(da.id, "dismissed")}
                    className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-slate-100 text-slate-600 hover:bg-slate-200 inline-flex items-center gap-1"
                  >
                    <X className="w-3 h-3" /> Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters Card */}
      <div className="apple-card p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2.5">
          <div className="relative md:col-span-5">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setVisibleLimit(PAGE_SIZE)
              }}
              placeholder="Search title, repo, author, excerpt..."
              className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
            />
          </div>

          <select
            value={originFilter}
            onChange={(e) => {
              setOriginFilter(e.target.value)
              setVisibleLimit(PAGE_SIZE)
            }}
            aria-label="Filter by repository or source"
            className="md:col-span-4 px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-800 focus:outline-none focus:border-violet-500"
          >
            <option value="All">All Repositories &amp; Sources ({originOptions.length})</option>
            {originOptions.map(([orig, cnt]) => (
              <option key={orig} value={orig}>
                {orig} ({cnt})
              </option>
            ))}
          </select>

          <select
            value={authorFilter}
            onChange={(e) => {
              setAuthorFilter(e.target.value)
              setVisibleLimit(PAGE_SIZE)
            }}
            aria-label="Filter by author"
            className="md:col-span-3 px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-800 focus:outline-none focus:border-violet-500"
          >
            <option value="All">All Authors ({authorOptions.length})</option>
            {authorOptions.map(([auth, cnt]) => (
              <option key={auth} value={auth}>
                {auth} ({cnt})
              </option>
            ))}
          </select>
        </div>

        {/* Source Type Tabs */}
        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-slate-100">
          <span className="text-[10px] font-bold uppercase text-slate-400 mr-1">Type:</span>
          <button
            onClick={() => {
              setSourceTypeFilter("All")
              setVisibleLimit(PAGE_SIZE)
            }}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-all ${
              sourceTypeFilter === "All"
                ? "bg-violet-600 text-white border-violet-600 shadow-xs"
                : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
            }`}
          >
            All Sources ({evidences.length})
          </button>
          {sourceTypeOptions.map(([st, cnt]) => (
            <button
              key={st}
              onClick={() => {
                setSourceTypeFilter(st)
                setVisibleLimit(PAGE_SIZE)
              }}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-all capitalize ${
                sourceTypeFilter === st
                  ? "bg-violet-600 text-white border-violet-600 shadow-xs"
                  : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
              }`}
            >
              {formatSourceType(st)} ({cnt})
            </button>
          ))}
        </div>

        {/* Verification Status Filters */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-100">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase text-slate-400 mr-1">Status:</span>
            {STATUS_FILTERS.map((st) => {
              const cnt = statusCounts[st] ?? 0
              return (
                <button
                  key={st}
                  onClick={() => {
                    setStatusFilter(st)
                    setVisibleLimit(PAGE_SIZE)
                  }}
                  className={`px-2.5 py-1 rounded-xl text-[11px] font-semibold border transition-all ${
                    statusFilter === st
                      ? "bg-violet-600 text-white border-violet-600 shadow-xs"
                      : cnt === 0
                      ? "bg-white text-slate-400 border-slate-200 hover:bg-slate-50"
                      : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  {st} ({cnt})
                </button>
              )
            })}
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="font-mono text-[11px]">
              Showing {visibleItems.length} of {filtered.length}
            </span>
            {hasActiveFilters && (
              <button
                onClick={resetFilters}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-violet-700 bg-violet-50 hover:bg-violet-100 border border-violet-200"
              >
                <RotateCcw className="w-3 h-3" /> Reset
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Evidence Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {visibleItems.map((ev) => {
          const isExternalUrl = ev.source_url && /^https?:\/\//i.test(ev.source_url)
          const origin = getEvidenceOrigin(ev)
          const projName = !activeProject && ev.project_id ? projectNames[ev.project_id] : ""
          return (
            <div key={ev.id} className="apple-card p-5 flex flex-col justify-between gap-4">
              <div className="space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-bold uppercase">
                        {formatSourceType(ev.source_type)}
                      </span>
                      {origin && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-violet-50 text-violet-700 border border-violet-100 font-semibold max-w-[200px] truncate">
                          <FolderGit2 className="w-2.5 h-2.5 flex-shrink-0" />
                          {origin}
                        </span>
                      )}
                      {projName && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-700 border border-indigo-100 font-semibold max-w-[160px] truncate">
                          <Layers className="w-2.5 h-2.5 flex-shrink-0" />
                          {projName}
                        </span>
                      )}
                      <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${STATUS_BADGE_CLASS(ev.verification_status)}`}>
                        {ev.verification_status}
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        Conf: {Math.round((ev.confidence || 0) * 100)}%
                      </span>
                    </div>
                    <h3 className="text-sm font-bold text-slate-900">{ev.source_title}</h3>
                  </div>

                  {ev.source_url && (
                    isExternalUrl ? (
                      <a
                        href={ev.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] font-semibold text-violet-600 hover:underline inline-flex items-center gap-1 flex-shrink-0"
                      >
                        Origin <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : (
                      <Link
                        href={ev.source_url}
                        className="text-[11px] font-semibold text-violet-600 hover:underline inline-flex items-center gap-1 flex-shrink-0"
                      >
                        Source <ExternalLink className="w-3 h-3" />
                      </Link>
                    )
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                  {ev.source_author && (
                    <span className="inline-flex items-center gap-1">
                      <User className="w-3 h-3" /> {ev.source_author}
                    </span>
                  )}
                  {(ev.source_timestamp || ev.created_at) && (
                    <span className="inline-flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {new Date(ev.source_timestamp || ev.created_at).toLocaleDateString()}
                    </span>
                  )}
                  {ev.metadata_json?.page_number && <span>Page {ev.metadata_json.page_number}</span>}
                  {ev.metadata_json?.sheet_name && <span>Sheet {ev.metadata_json.sheet_name}</span>}
                </div>

                <blockquote className="p-3 rounded-xl bg-slate-50 border border-slate-100 text-xs text-slate-700 italic leading-relaxed">
                  &ldquo;{ev.excerpt}&rdquo;
                </blockquote>

                <div className="text-xs text-slate-600 leading-relaxed">
                  <strong className="text-violet-700 font-semibold block text-[10px] uppercase mb-0.5">
                    AI Interpretation:
                  </strong>
                  {ev.ai_interpretation}
                </div>

                {ev.review_notes && (
                  <p className="text-[11px] text-slate-500 bg-emerald-50/50 border border-emerald-100 px-3 py-1.5 rounded-lg">
                    Reviewer note: {ev.review_notes}
                  </p>
                )}
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
                <span className="font-mono text-[10px] text-slate-400 truncate max-w-[200px]">
                  SHA: {ev.content_hash?.slice(0, 16)}...
                </span>
                <button
                  onClick={() => {
                    setSelectedAudit(ev)
                    setAuditNotes(ev.review_notes || "")
                  }}
                  className="px-3 py-1 rounded-xl text-xs font-semibold bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200 transition-all"
                >
                  Review &amp; Sign Off
                </button>
              </div>
            </div>
          )
        })}

        {filtered.length === 0 && !loading && (
          <div className="col-span-full apple-card p-12 text-center space-y-3">
            <ShieldCheck className="w-10 h-10 text-slate-300 mx-auto" />
            <h3 className="text-sm font-bold text-slate-800">No Evidence Records Match Current Filters</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              {hasActiveFilters
                ? "Try resetting your source type, repository, status, or search filter."
                : "Verified and candidate evidence items will appear here as repositories, channels, and documents are ingested."}
            </p>
            {hasActiveFilters && (
              <button
                onClick={resetFilters}
                className="px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white"
              >
                Reset All Filters
              </button>
            )}
          </div>
        )}
      </div>

      {filtered.length > visibleItems.length && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            onClick={() => setVisibleLimit((prev) => prev + PAGE_SIZE)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-800 shadow-xs"
          >
            Load {Math.min(PAGE_SIZE, filtered.length - visibleItems.length)} More ({filtered.length - visibleItems.length} remaining)
          </button>
          <button
            onClick={() => setVisibleLimit(filtered.length)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200"
          >
            Show All ({filtered.length})
          </button>
        </div>
      )}

      {/* Review & Audit Modal */}
      {selectedAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Verify Evidence Provenance</h3>
              <button
                onClick={() => {
                  setSelectedAudit(null)
                  setAuditError("")
                }}
                className="text-slate-400 hover:text-slate-600 text-xs"
              >
                ✕ Close
              </button>
            </div>

            {auditError && (
              <div className="p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
                {auditError}
              </div>
            )}

            <div className="text-xs space-y-2.5">
              <p className="font-bold text-slate-900">{selectedAudit.source_title}</p>
              <p className="p-3 bg-slate-50 rounded-xl border border-slate-100 text-slate-600 italic">
                &ldquo;{selectedAudit.excerpt}&rdquo;
              </p>
              <textarea
                rows={2}
                value={auditNotes}
                onChange={(e) => setAuditNotes(e.target.value)}
                placeholder="Reviewer verification notes, discrepancies, or source context..."
                className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
              />
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
              <button
                disabled={submitting}
                onClick={() => handleAuditAction("Outdated")}
                className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200"
              >
                Mark Outdated
              </button>
              <button
                disabled={submitting}
                onClick={() => handleAuditAction("Contradicted")}
                className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100"
              >
                Mark Contradicted
              </button>
              <button
                disabled={submitting}
                onClick={() => handleAuditAction("Needs Human Verification")}
                className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100"
              >
                Needs Review
              </button>
              <button
                disabled={submitting}
                onClick={() => handleAuditAction("Verified by Reviewer")}
                className="px-4 py-1.5 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm"
              >
                Verify &amp; Approve
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
