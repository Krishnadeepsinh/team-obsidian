"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api, getStoredProjectId, setStoredProjectId } from "@/lib/api"
import { ShieldCheck, Search, ExternalLink, Clock, User } from "lucide-react"

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
  const [search, setSearch] = useState("")
  const [selectedAudit, setSelectedAudit] = useState<any>(null)
  const [auditNotes, setAuditNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const loadData = useCallback(async (pid?: string, status?: string, query?: string) => {
    try {
      setLoading(true)
      const storedPid = pid !== undefined ? pid : getStoredProjectId()
      const [projs, res] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getEvidence(storedPid || undefined, status === "All" ? undefined : status, query || undefined).catch(() => []),
      ])
      setProjects(Array.isArray(projs) ? projs : [])
      setActiveProject(storedPid)
      setEvidences(Array.isArray(res) ? res : [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData(undefined, "All", "")
  }, [loadData])

  const handleAuditAction = async (newStatus: string) => {
    if (!selectedAudit) return
    try {
      setSubmitting(true)
      await api.auditEvidence(selectedAudit.id, newStatus, auditNotes)
      setSelectedAudit(null)
      setAuditNotes("")
      await loadData(activeProject, statusFilter, search)
    } catch (err: any) {
      alert(err.message || "Audit submission failed")
    } finally {
      setSubmitting(false)
    }
  }

  const filtered = evidences.filter((ev) => {
    const matchStatus = statusFilter === "All" || ev.verification_status === statusFilter
    const matchSearch =
      !search.trim() ||
      ev.source_title?.toLowerCase().includes(search.toLowerCase()) ||
      ev.excerpt?.toLowerCase().includes(search.toLowerCase()) ||
      ev.ai_interpretation?.toLowerCase().includes(search.toLowerCase()) ||
      ev.source_author?.toLowerCase().includes(search.toLowerCase())
    return matchStatus && matchSearch
  })

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Evidence Verification &amp; Provenance</h1>
          <p className="text-xs text-slate-500 mt-1">
            Inspect original source excerpts, cryptographic hashes, authors, and human verification states.
          </p>
        </div>

        <select
          value={activeProject}
          onChange={(e) => {
            const pid = e.target.value
            setActiveProject(pid)
            setStoredProjectId(pid || undefined)
            loadData(pid, statusFilter, search)
          }}
          className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500"
        >
          <option value="">All Accessible Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Filters */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search evidence title, author, excerpt..."
            className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 shadow-sm focus:outline-none focus:border-violet-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_FILTERS.map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-2.5 py-1.5 rounded-xl text-[11px] font-semibold border transition-all ${
                statusFilter === st
                  ? "bg-violet-600 text-white border-violet-600 shadow-sm"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Evidence Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map((ev) => {
          const isExternalUrl = ev.source_url && /^https?:\/\//i.test(ev.source_url)
          return (
            <div key={ev.id} className="apple-card p-5 flex flex-col justify-between gap-4">
              <div className="space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-bold uppercase">
                        {ev.source_type?.replace("_", " ")}
                      </span>
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
            <h3 className="text-sm font-bold text-slate-800">No Evidence Records Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Verified and candidate evidence items will appear here as repositories, channels, and documents are ingested.
            </p>
          </div>
        )}
      </div>

      {/* Review & Audit Modal */}
      {selectedAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Verify Evidence Provenance</h3>
              <button onClick={() => setSelectedAudit(null)} className="text-slate-400 hover:text-slate-600 text-xs">
                ✕ Close
              </button>
            </div>

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
