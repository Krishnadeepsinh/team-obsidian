"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"
import { Stamp, XCircle, AlertTriangle, ArrowLeft, Archive, Send } from "lucide-react"

export default function ApprovalsPage() {
  const [handovers, setHandovers] = useState<any[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [handover, setHandover] = useState<any>(null)
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const loadData = useCallback(async (targetHid?: string) => {
    try {
      setError("")
      const storedPid =
        typeof window !== "undefined" ? localStorage.getItem("obsidian_active_project") || undefined : undefined
      const hs = await api.getHandovers(storedPid).catch(() => [])
      const list = Array.isArray(hs) ? hs : []
      setHandovers(list)
      const hid = targetHid || list[0]?.id
      if (hid) {
        setSelectedId(hid)
        const full = await api.getHandover(hid).catch(() => null)
        setHandover(full)
      } else {
        setHandover(null)
      }
    } catch (err: any) {
      setError(err.message || "Failed to load handover approvals.")
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleDecision = async (role: string, approverName: string, decisionStatus: string) => {
    if (!handover) return
    try {
      setSubmitting(true)
      setError("")
      setMsg("")
      await api.approveHandover(handover.id, {
        role,
        approver_name: approverName,
        status: decisionStatus,
        notes: notes.trim() || undefined,
      })
      setNotes("")
      setMsg(`Recorded "${decisionStatus}" sign-off for ${role.replace("_", " ")}.`)
      await loadData(handover.id)
    } catch (err: any) {
      setError(err.message || "Could not record approval.")
    } finally {
      setSubmitting(false)
    }
  }

  const handleLifecycleStatus = async (status: string) => {
    if (!handover) return
    try {
      setSubmitting(true)
      setError("")
      setMsg("")
      await api.updateHandoverStatus(handover.id, status, `Lifecycle transitioned to ${status}`)
      setMsg(`Handover transitioned to "${status}".`)
      await loadData(handover.id)
    } catch (err: any) {
      setError(err.message || `Cannot transition handover to "${status}".`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/handover" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-violet-700 mb-1">
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Handover Dossier
          </Link>
          <h1 className="text-2xl font-bold text-slate-900">Handover Sign-Off &amp; Governance</h1>
          <p className="text-xs text-slate-500 mt-1">
            Manage configurable stakeholder approvals before publishing or archiving the handover dossier.
          </p>
        </div>

        {handovers.length > 0 && (
          <select
            value={selectedId}
            onChange={(e) => loadData(e.target.value)}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
          >
            {handovers.map((h) => (
              <option key={h.id} value={h.id}>{h.title} ({h.status})</option>
            ))}
          </select>
        )}
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">{error}</div>
      )}
      {msg && (
        <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium">{msg}</div>
      )}

      {!handover ? (
        <div className="apple-card p-12 text-center text-xs text-slate-500">
          No handover dossier found. Generate a handover dossier first to collect sign-offs.
        </div>
      ) : (
        <div className="apple-card p-6 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
            <div>
              <span className="text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase bg-violet-50 text-violet-700 border border-violet-200">
                Status: {handover.status?.replace("_", " ")}
              </span>
              <h2 className="text-base font-bold text-slate-900 mt-1">{handover.title}</h2>
              <p className="text-xs text-slate-500">
                {handover.departing_employee_name} → {handover.incoming_employee_name}
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                disabled={submitting}
                onClick={() => handleLifecycleStatus("published")}
                className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm flex items-center gap-1.5"
              >
                <Send className="w-3.5 h-3.5" /> Publish Handover
              </button>
              <button
                disabled={submitting}
                onClick={() => handleLifecycleStatus("archived")}
                className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 flex items-center gap-1.5"
              >
                <Archive className="w-3.5 h-3.5" /> Archive
              </button>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">Optional Review Notes for Next Sign-Off Action</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add verification notes or conditions before signing off..."
              className="w-full px-3.5 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
            />
          </div>

          <div className="space-y-3">
            {(handover.approvals || []).map((app: any) => {
              const isApproved = app.status === "approved" || app.status === "acknowledged"
              const isRejected = app.status === "rejected"
              return (
                <div key={app.id} className="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold text-slate-900">{app.approver_name}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-white border border-slate-200 font-semibold uppercase text-slate-600">
                        {app.role?.replace("_", " ")}
                      </span>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase border ${
                          isApproved
                            ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                            : isRejected
                            ? "bg-rose-50 text-rose-700 border-rose-200"
                            : "bg-amber-50 text-amber-700 border-amber-200"
                        }`}
                      >
                        {app.status}
                      </span>
                    </div>
                    {app.notes && <p className="text-[11px] text-slate-600">Notes: {app.notes}</p>}
                    {app.signed_at && (
                      <p className="text-[10px] text-slate-400">Signed: {new Date(app.signed_at).toLocaleString()}</p>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      disabled={submitting}
                      onClick={() => handleDecision(app.role, app.approver_name, "changes_requested")}
                      className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 flex items-center gap-1"
                    >
                      <AlertTriangle className="w-3 h-3" /> Request Changes
                    </button>
                    <button
                      disabled={submitting}
                      onClick={() => handleDecision(app.role, app.approver_name, "rejected")}
                      className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100 flex items-center gap-1"
                    >
                      <XCircle className="w-3 h-3" /> Reject
                    </button>
                    <button
                      disabled={submitting}
                      onClick={() =>
                        handleDecision(
                          app.role,
                          app.approver_name,
                          app.role === "incoming_employee" ? "acknowledged" : "approved"
                        )
                      }
                      className="px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white flex items-center gap-1 shadow-sm"
                    >
                      <Stamp className="w-3.5 h-3.5" />
                      <span>{app.role === "incoming_employee" ? "Acknowledge" : "Approve & Sign"}</span>
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
