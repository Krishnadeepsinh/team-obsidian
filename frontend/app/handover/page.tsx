"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"
import {
  FileText,
  Sparkles,
  Download,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Edit3,
  MessageSquare,
  History,
  Stamp,
  Plus,
  Send,
  ShieldCheck,
  ExternalLink,
  Trash2,
} from "lucide-react"

const SOURCE_CATEGORIES = ["Architecture", "Decisions", "Tasks", "Risks", "Gaps", "Dependencies"]

const VERIF_BADGE = (status: string) => {
  if (status === "Verified by Reviewer" || status === "Verified") {
    return "bg-emerald-50 text-emerald-700 border-emerald-200"
  }
  if (status === "Supported by Evidence") {
    return "bg-sky-50 text-sky-700 border-sky-200"
  }
  if (status === "Contradicted" || status === "Rejected") {
    return "bg-rose-50 text-rose-700 border-rose-200"
  }
  return "bg-amber-50 text-amber-700 border-amber-200"
}

export default function HandoverPage() {
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [handovers, setHandovers] = useState<any[]>([])
  const [currentHandover, setCurrentHandover] = useState<any>(null)
  const [selectedSectionId, setSelectedSectionId] = useState<string>("")
  const [evidenceMap, setEvidenceMap] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [statusMsg, setStatusMsg] = useState("")
  const [downloadingPdf, setDownloadingPdf] = useState(false)

  // Editing section
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState("")
  const [editReason, setEditReason] = useState("")

  // Comments
  const [commentText, setCommentText] = useState("")
  const [userName, setUserName] = useState("Reviewer")

  // Reconstruct Wizard
  const [showWizard, setShowWizard] = useState(false)
  const [wizardProjectId, setWizardProjectId] = useState("")
  const [wizardSources, setWizardSources] = useState<any[]>([])
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([])
  const [selectedCategories, setSelectedCategories] = useState<string[]>(SOURCE_CATEGORIES)
  const [departingName, setDepartingName] = useState("")
  const [departingRole, setDepartingRole] = useState("")
  const [incomingName, setIncomingName] = useState("")
  const [incomingRole, setIncomingRole] = useState("")
  const [targetDate, setTargetDate] = useState("")
  const [customApprovers, setCustomApprovers] = useState<{ role: string; approver_name: string }[]>([])
  const [newAppRole, setNewAppRole] = useState("tech_lead")
  const [newAppName, setNewAppName] = useState("")
  const [reconstructing, setReconstructing] = useState(false)

  const loadHandoverList = useCallback(async (pid?: string, selectId?: string) => {
    try {
      setLoading(true)
      const storedPid =
        pid !== undefined
          ? pid
          : typeof window !== "undefined"
          ? localStorage.getItem("obsidian_active_project_id") ||
            localStorage.getItem("obsidian_active_project") ||
            ""
          : ""
      const [projs, list, ctx] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getHandovers(storedPid || undefined).catch(() => []),
        api.getUserContext().catch(() => null),
      ])
      if (ctx?.user?.name) setUserName(ctx.user.name)
      setProjects(Array.isArray(projs) ? projs : [])
      const resolvedPid = storedPid || (Array.isArray(projs) && projs[0]?.id) || ""
      if (pid === undefined) setActiveProject(resolvedPid)
      setWizardProjectId(resolvedPid)

      const hs = Array.isArray(list) ? list : []
      setHandovers(hs)
      const targetId = selectId || hs[0]?.id
      if (targetId) {
        const full = await api.getHandover(targetId).catch(() => null)
        setCurrentHandover(full)
        if (full?.project_id) {
          const evList = await api.getEvidence(full.project_id).catch(() => [])
          const map: Record<string, any> = {}
          if (Array.isArray(evList)) {
            for (const ev of evList) map[ev.id] = ev
          }
          setEvidenceMap(map)
        }
        if (full?.sections?.length) {
          setSelectedSectionId((prev) =>
            prev && full.sections.some((s: any) => s.id === prev) ? prev : full.sections[0].id
          )
        }
      } else {
        setCurrentHandover(null)
        setEvidenceMap({})
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHandoverList()
  }, [loadHandoverList])

  useEffect(() => {
    if (showWizard && wizardProjectId) {
      api.getIntegrations(wizardProjectId).then((res) => {
        const list = Array.isArray(res) ? res : []
        setWizardSources(list)
        setSelectedSourceIds(list.map((i: any) => i.id))
      }).catch(() => setWizardSources([]))
    }
  }, [showWizard, wizardProjectId])

  const activeSection =
    currentHandover?.sections?.find((s: any) => s.id === selectedSectionId) ||
    currentHandover?.sections?.[0] ||
    null

  const refreshCurrent = async (hid?: string) => {
    const id = hid || currentHandover?.id
    if (!id) return
    const full = await api.getHandover(id)
    setCurrentHandover(full)
  }

  const handleReconstruct = async (e: React.FormEvent) => {
    e.preventDefault()
    const pid = wizardProjectId || activeProject || projects[0]?.id
    if (!pid) {
      setError("Please create or select a project before reconstructing a handover.")
      return
    }
    try {
      setReconstructing(true)
      setError("")
      const created = await api.reconstructHandover({
        project_id: pid,
        departing_employee_name: departingName,
        departing_employee_role: departingRole,
        incoming_employee_name: incomingName,
        incoming_employee_role: incomingRole,
        target_date: targetDate || undefined,
        selected_source_ids: selectedSourceIds,
        selected_sources: wizardSources
          .filter((s) => selectedSourceIds.includes(s.id))
          .map((s) => s.provider),
        selected_categories: selectedCategories,
        approvers:
          customApprovers.length > 0
            ? customApprovers.map((a) => ({ ...a, is_required: true }))
            : undefined,
      })
      setShowWizard(false)
      setCustomApprovers([])
      setDepartingName("")
      setDepartingRole("")
      setIncomingName("")
      setIncomingRole("")
      setStatusMsg("Handover dossier reconstructed from project evidence.")
      await loadHandoverList(activeProject, created.id)
    } catch (err: any) {
      setError(err.message || "Failed to reconstruct handover.")
    } finally {
      setReconstructing(false)
    }
  }

  const handleDownloadPdf = async () => {
    if (!currentHandover) return
    try {
      setDownloadingPdf(true)
      await api.downloadHandoverPdf(currentHandover.id)
    } catch (err: any) {
      setError(err.message || "PDF export failed.")
    } finally {
      setDownloadingPdf(false)
    }
  }

  const handleSaveSection = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!currentHandover || !activeSection) return
    try {
      await api.editSection(
        currentHandover.id,
        activeSection.id,
        editContent,
        undefined,
        editReason.trim() || "Manual section update"
      )
      setEditing(false)
      setEditReason("")
      setStatusMsg(`Saved section "${activeSection.title}" and logged version diff.`)
      await refreshCurrent()
    } catch (err: any) {
      setError(err.message || "Could not update section.")
    }
  }

  const handleReviewSection = async (action: "verify" | "reject" | "request_changes") => {
    if (!currentHandover || !activeSection) return
    try {
      await api.reviewSection(currentHandover.id, activeSection.id, action)
      setStatusMsg(`Updated verification state (${action}) on section #${activeSection.section_number}.`)
      await refreshCurrent()
    } catch (err: any) {
      setError(err.message || "Review action failed.")
    }
  }

  const handleVerifyClaim = async (claimId: string, verification_status: string) => {
    if (!currentHandover) return
    try {
      await api.verifyClaim(currentHandover.id, claimId, verification_status)
      await refreshCurrent()
    } catch (err: any) {
      setError(err.message || "Claim verification failed.")
    }
  }

  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!currentHandover || !activeSection || !commentText.trim()) return
    try {
      await api.addSectionComment(currentHandover.id, activeSection.id, userName, commentText.trim())
      setCommentText("")
      await refreshCurrent()
    } catch (err: any) {
      setError(err.message || "Failed to add comment.")
    }
  }

  return (
    <div className="p-6 max-w-[1440px] mx-auto space-y-5">
      {/* Top Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">16-Section Handover Dossier</h1>
          <p className="text-xs text-slate-500 mt-1">
            Source-grounded knowledge reconstruction with claim-level verification, audit trails, and ReportLab PDF export.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
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
              loadHandoverList(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          {handovers.length > 0 && (
            <select
              value={currentHandover?.id || ""}
              onChange={(e) => loadHandoverList(activeProject, e.target.value)}
              className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm max-w-[240px]"
            >
              {handovers.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.title} ({h.status})
                </option>
              ))}
            </select>
          )}

          <button
            onClick={() => setShowWizard(true)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20 flex items-center gap-1.5"
          >
            <Plus className="w-3.5 h-3.5" /> New Handover Dossier
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">{error}</div>
      )}
      {statusMsg && (
        <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> {statusMsg}
        </div>
      )}

      {loading ? (
        <div className="apple-card p-12 text-center text-xs text-slate-400">Loading handover dossiers...</div>
      ) : !currentHandover ? (
        <div className="apple-card p-12 text-center space-y-3">
          <FileText className="w-10 h-10 text-slate-300 mx-auto" />
          <h2 className="text-base font-bold text-slate-900">No Handover Dossier Created Yet</h2>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            Connect sources or upload project documents, then launch the Reconstruction Wizard to assemble an evidence-backed 16-section handover.
          </p>
          <button
            onClick={() => setShowWizard(true)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white"
          >
            Reconstruct Handover
          </button>
        </div>
      ) : (
        <>
          {/* Summary Banner */}
          <div className="apple-card p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase bg-violet-50 text-violet-700 border border-violet-200">
                  {currentHandover.status?.replace("_", " ")}
                </span>
                <span className="text-xs font-semibold text-slate-700">
                  {currentHandover.departing_employee_name} ({currentHandover.departing_employee_role}) →{" "}
                  {currentHandover.incoming_employee_name} ({currentHandover.incoming_employee_role})
                </span>
              </div>
              <h2 className="text-lg font-bold text-slate-900">{currentHandover.title}</h2>
              <p className="text-xs text-slate-500">
                Computed Confidence:{" "}
                <strong className="text-slate-900">
                  {Math.round((currentHandover.overall_confidence ?? 0) * 100)}%
                </strong>
                {currentHandover.confidence_breakdown?.explanation
                  ? ` — ${currentHandover.confidence_breakdown.explanation}`
                  : ""}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2 flex-shrink-0">
              <Link
                href="/handover/approvals"
                className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1.5"
              >
                <Stamp className="w-3.5 h-3.5 text-violet-600" /> Approvals
              </Link>
              <Link
                href="/handover/history"
                className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1.5"
              >
                <History className="w-3.5 h-3.5 text-violet-600" /> Version Diffs
              </Link>
              <button
                onClick={handleDownloadPdf}
                disabled={downloadingPdf}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white shadow-sm flex items-center gap-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                <span>{downloadingPdf ? "Exporting..." : "Download PDF"}</span>
              </button>
            </div>
          </div>

          {/* Main 16-Section Split Workspace */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* Section Navigation Rail */}
            <div className="lg:col-span-4 apple-card p-3 space-y-1 max-h-[680px] overflow-y-auto">
              {(currentHandover.sections || []).map((sec: any) => {
                const isActive = activeSection?.id === sec.id
                const vStatus = sec.verification_status || "Needs Human Verification"
                return (
                  <button
                    key={sec.id}
                    onClick={() => {
                      setSelectedSectionId(sec.id)
                      setEditing(false)
                    }}
                    className={`w-full text-left p-3 rounded-xl border transition-all flex items-start justify-between gap-2 ${
                      isActive
                        ? "bg-violet-50/90 border-violet-200 text-violet-900 shadow-sm"
                        : "bg-transparent border-transparent hover:bg-slate-50 text-slate-700"
                    }`}
                  >
                    <div className="min-w-0">
                      <span className="text-[10px] font-bold text-violet-600 block">SECTION {sec.section_number}</span>
                      <span className="text-xs font-semibold line-clamp-1">{sec.title}</span>
                    </div>
                    <span className={`text-[9px] px-2 py-0.5 rounded-full border font-semibold flex-shrink-0 ${VERIF_BADGE(vStatus)}`}>
                      {sec.is_verified ? "Verified" : "Review"}
                    </span>
                  </button>
                )
              })}
            </div>

            {/* Active Section Content, Claims & Comments */}
            <div className="lg:col-span-8 space-y-4">
              {activeSection && (
                <div className="apple-card p-6 space-y-5">
                  {/* Section Header & Verification Actions */}
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 pb-4 border-b border-slate-100">
                    <div>
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="text-[10px] font-bold uppercase text-violet-600">
                          Section {activeSection.section_number}
                        </span>
                        <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-semibold border ${VERIF_BADGE(activeSection.verification_status || "Needs Human Verification")}`}>
                          {activeSection.verification_status || "Needs Human Verification"}
                        </span>
                        <span className="text-[11px] font-mono text-slate-400">
                          Conf: {Math.round((activeSection.confidence ?? 0) * 100)}%
                        </span>
                      </div>
                      <h3 className="text-lg font-bold text-slate-900">{activeSection.title}</h3>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5">
                      <button
                        onClick={() => {
                          setEditing(!editing)
                          setEditContent(activeSection.content || "")
                        }}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                      >
                        <Edit3 className="w-3 h-3" /> {editing ? "Cancel" : "Edit"}
                      </button>
                      <button
                        onClick={() => handleReviewSection("request_changes")}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 flex items-center gap-1"
                      >
                        <AlertTriangle className="w-3 h-3" /> Needs Changes
                      </button>
                      <button
                        onClick={() => handleReviewSection("reject")}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 flex items-center gap-1"
                      >
                        <XCircle className="w-3 h-3" /> Reject
                      </button>
                      <button
                        onClick={() => handleReviewSection("verify")}
                        className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-emerald-600 hover:bg-emerald-700 text-white flex items-center gap-1 shadow-sm"
                      >
                        <CheckCircle2 className="w-3 h-3" /> Verify Section
                      </button>
                    </div>
                  </div>

                  {/* Body or Editor */}
                  {editing ? (
                    <form onSubmit={handleSaveSection} className="space-y-3">
                      <textarea
                        rows={10}
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        className="w-full p-3.5 rounded-xl text-xs font-mono bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                      />
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          type="text"
                          value={editReason}
                          onChange={(e) => setEditReason(e.target.value)}
                          placeholder="Reason for edit (recorded in Version Diff history)"
                          className="flex-1 px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                        />
                        <button type="submit" className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 text-white">
                          Save &amp; Record Version
                        </button>
                      </div>
                    </form>
                  ) : (
                    <div className="prose prose-sm max-w-none text-xs text-slate-700 whitespace-pre-line leading-relaxed bg-slate-50/70 p-4 rounded-xl border border-slate-100">
                      {activeSection.content}
                    </div>
                  )}

                  {/* Per-Claim Verification Table */}
                  {Array.isArray(activeSection.claims) && activeSection.claims.length > 0 && (
                    <div className="space-y-2.5 pt-2">
                      <h4 className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                        <ShieldCheck className="w-4 h-4 text-violet-600" />
                        <span>Claim-Level Evidence Verification ({activeSection.claims.length})</span>
                      </h4>
                      <div className="space-y-2">
                        {activeSection.claims.map((cl: any) => (
                          <div key={cl.id} className="p-3 rounded-xl bg-white border border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                            <div className="space-y-1 min-w-0">
                              <p className="text-slate-800 font-medium">{cl.claim_text}</p>
                              <div className="flex items-center gap-2 text-[10px] text-slate-400">
                                <span className={`px-2 py-0.5 rounded-full border font-semibold ${VERIF_BADGE(cl.verification_status)}`}>
                                  {cl.verification_status}
                                </span>
                                <span>Conf: {Math.round((cl.confidence ?? 0) * 100)}%</span>
                                <span>Evidence refs: {cl.evidence_ids?.length || 0}</span>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 flex-shrink-0">
                              <button
                                onClick={() => handleVerifyClaim(cl.id, "Verified by Reviewer")}
                                className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
                              >
                                Verify
                              </button>
                              <button
                                onClick={() => handleVerifyClaim(cl.id, "Contradicted")}
                                className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100"
                              >
                                Contradicted
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Section-Specific Evidence References (Navigable Provenance) */}
                  {Array.isArray(activeSection.evidence_ids) && activeSection.evidence_ids.length > 0 && (
                    <div className="space-y-2 pt-3 border-t border-slate-100">
                      <h4 className="text-xs font-bold text-slate-900">
                        Supporting Section Evidence ({activeSection.evidence_ids.length})
                      </h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {activeSection.evidence_ids.slice(0, 6).map((eid: string) => {
                          const ev = evidenceMap[eid]
                          if (!ev) {
                            return (
                              <div key={eid} className="p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-[11px] font-mono text-slate-500">
                                Evidence #{eid.slice(0, 8)}
                              </div>
                            )
                          }
                          const isExt = ev.source_url && /^https?:\/\//i.test(ev.source_url)
                          return (
                            <div key={eid} className="p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-[11px] space-y-1">
                              <div className="flex items-start justify-between gap-2">
                                <span className="font-bold text-slate-800 line-clamp-1">{ev.source_title}</span>
                                <span className="text-[9px] px-1.5 py-0.5 rounded bg-white border border-slate-200 uppercase font-semibold text-violet-700 flex-shrink-0">
                                  {ev.source_type}
                                </span>
                              </div>
                              <p className="text-slate-600 line-clamp-2 italic">&ldquo;{ev.excerpt}&rdquo;</p>
                              <div className="flex items-center justify-between text-[10px] text-slate-400">
                                <span>{ev.source_author || "Author"} • SHA {ev.content_hash?.slice(0, 10)}</span>
                                {ev.source_url && (
                                  isExt ? (
                                    <a href={ev.source_url} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                                      Origin <ExternalLink className="w-2.5 h-2.5" />
                                    </a>
                                  ) : (
                                    <Link href={ev.source_url} className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                                      Source <ExternalLink className="w-2.5 h-2.5" />
                                    </Link>
                                  )
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Comments */}
                  <div className="space-y-3 pt-4 border-t border-slate-100">
                    <h4 className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                      <MessageSquare className="w-4 h-4 text-violet-600" />
                      <span>Review Comments ({activeSection.comments?.length || 0})</span>
                    </h4>
                    <div className="space-y-2">
                      {(activeSection.comments || []).map((c: any, ci: number) => (
                        <div key={ci} className="p-2.5 rounded-xl bg-slate-50 border border-slate-100 text-xs">
                          <div className="flex items-center justify-between text-[10px] text-slate-400 mb-0.5">
                            <span className="font-bold text-slate-700">{c.author}</span>
                            <span>{c.timestamp ? new Date(c.timestamp).toLocaleString() : ""}</span>
                          </div>
                          <p className="text-slate-700">{c.text}</p>
                        </div>
                      ))}
                    </div>
                    <form onSubmit={handleAddComment} className="flex gap-2">
                      <input
                        type="text"
                        value={commentText}
                        onChange={(e) => setCommentText(e.target.value)}
                        placeholder="Add verification feedback or handover question..."
                        className="flex-1 px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 focus:outline-none focus:border-violet-500 focus:bg-white"
                      />
                      <button type="submit" className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-violet-600 text-white flex items-center gap-1">
                        <Send className="w-3 h-3" /> Post
                      </button>
                    </form>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Reconstruct Handover Wizard Modal */}
      {showWizard && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-600" /> Reconstruct 16-Section Handover Dossier
              </h3>
              <button onClick={() => setShowWizard(false)} className="text-xs text-slate-400">✕ Close</button>
            </div>
            <form onSubmit={handleReconstruct} className="space-y-3.5">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Target Project *</label>
                <select
                  required
                  value={wizardProjectId}
                  onChange={(e) => setWizardProjectId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Departing Member Name *</label>
                  <input
                    type="text"
                    required
                    value={departingName}
                    onChange={(e) => setDepartingName(e.target.value)}
                    placeholder="Full name"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Departing Role *</label>
                  <input
                    type="text"
                    required
                    value={departingRole}
                    onChange={(e) => setDepartingRole(e.target.value)}
                    placeholder="e.g. Senior Backend Engineer"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Incoming Successor Name *</label>
                  <input
                    type="text"
                    required
                    value={incomingName}
                    onChange={(e) => setIncomingName(e.target.value)}
                    placeholder="Successor full name"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Incoming Role *</label>
                  <input
                    type="text"
                    required
                    value={incomingRole}
                    onChange={(e) => setIncomingRole(e.target.value)}
                    placeholder="e.g. Staff Engineer"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Target Handover Date</label>
                <input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>

              {wizardSources.length > 0 && (
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1.5">Connected Sources to Include</label>
                  <div className="flex flex-wrap gap-2">
                    {wizardSources.map((src) => {
                      const checked = selectedSourceIds.includes(src.id)
                      return (
                        <label key={src.id} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-slate-50 border border-slate-200 text-xs cursor-pointer">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() =>
                              setSelectedSourceIds((prev) =>
                                checked ? prev.filter((i) => i !== src.id) : [...prev, src.id]
                              )
                            }
                          />
                          <span>{src.name} ({src.provider})</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )}

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1.5">Intelligence Scopes</label>
                <div className="flex flex-wrap gap-1.5">
                  {SOURCE_CATEGORIES.map((cat) => {
                    const checked = selectedCategories.includes(cat)
                    return (
                      <button
                        type="button"
                        key={cat}
                        onClick={() =>
                          setSelectedCategories((prev) =>
                            checked ? prev.filter((c) => c !== cat) : [...prev, cat]
                          )
                        }
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border ${
                          checked ? "bg-violet-600 text-white border-violet-600" : "bg-slate-50 text-slate-600 border-slate-200"
                        }`}
                      >
                        {cat}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                  Configurable Required Approvers (Optional — defaults from project members)
                </label>
                <div className="flex flex-wrap gap-2 mb-2">
                  <select
                    value={newAppRole}
                    onChange={(e) => setNewAppRole(e.target.value)}
                    className="px-2.5 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  >
                    <option value="tech_lead">Tech Lead</option>
                    <option value="project_manager">Project Manager</option>
                    <option value="departing_employee">Departing Employee</option>
                    <option value="incoming_employee">Incoming Successor</option>
                    <option value="security">Security Lead</option>
                  </select>
                  <input
                    type="text"
                    value={newAppName}
                    onChange={(e) => setNewAppName(e.target.value)}
                    placeholder="Approver name"
                    className="flex-1 min-w-[140px] px-3 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (!newAppName.trim()) return
                      setCustomApprovers((prev) => [...prev, { role: newAppRole, approver_name: newAppName.trim() }])
                      setNewAppName("")
                    }}
                    className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700"
                  >
                    + Add
                  </button>
                </div>
                {customApprovers.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {customApprovers.map((ap, i) => (
                      <span key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-violet-50 border border-violet-200 text-[11px] font-medium text-violet-800">
                        {ap.approver_name} ({ap.role.replace("_", " ")})
                        <button
                          type="button"
                          onClick={() => setCustomApprovers((prev) => prev.filter((_, idx) => idx !== i))}
                          className="text-violet-500 hover:text-rose-600"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setShowWizard(false)} className="px-3 py-2 rounded-xl text-xs text-slate-600">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={reconstructing}
                  className="px-5 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20"
                >
                  {reconstructing ? "Reconstructing 16 Sections..." : "Generate Handover Dossier"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
