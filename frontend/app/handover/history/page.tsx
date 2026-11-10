"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"
import { History, ArrowLeft, GitCommit, User } from "lucide-react"

export default function HandoverHistoryPage() {
  const [handovers, setHandovers] = useState<any[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [handover, setHandover] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const loadData = async (hid?: string) => {
    try {
      setLoading(true)
      const storedPid =
        typeof window !== "undefined" ? localStorage.getItem("obsidian_active_project") || undefined : undefined
      const hs = await api.getHandovers(storedPid).catch(() => [])
      const list = Array.isArray(hs) ? hs : []
      setHandovers(list)
      const targetId = hid || selectedId || list[0]?.id
      if (targetId) {
        setSelectedId(targetId)
        const full = await api.getHandover(targetId).catch(() => null)
        setHandover(full)
      } else {
        setHandover(null)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const versions = handover?.versions || []

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/handover" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-violet-700 mb-1">
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Handover Dossier
          </Link>
          <h1 className="text-2xl font-bold text-slate-900">Handover Version History &amp; Diffs</h1>
          <p className="text-xs text-slate-500 mt-1">
            Immutable audit trail of section edits, reviewer verification updates, and lifecycle changes.
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

      {loading ? (
        <div className="apple-card p-10 text-center text-xs text-slate-400">Loading revision history...</div>
      ) : versions.length === 0 ? (
        <div className="apple-card p-12 text-center space-y-2">
          <History className="w-9 h-9 text-slate-300 mx-auto" />
          <p className="text-sm font-bold text-slate-800">No Revision History Found</p>
          <p className="text-xs text-slate-500">Section edits and sign-off updates will appear here automatically.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {versions.map((v: any) => (
            <div key={v.id} className="apple-card p-5 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <span className="px-2.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 text-[11px] font-bold flex items-center gap-1">
                    <GitCommit className="w-3 h-3" /> v{v.version_number}
                  </span>
                  <span className="text-sm font-bold text-slate-900">
                    {v.changed_section || v.changelog || "Dossier Revision"}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[11px] text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <User className="w-3 h-3" /> {v.created_by}
                  </span>
                  <span>{v.created_at ? new Date(v.created_at).toLocaleString() : ""}</span>
                </div>
              </div>

              {(v.reason || v.changelog) && (
                <p className="text-xs text-slate-600">
                  <strong className="text-slate-800">Change Note:</strong> {v.reason || v.changelog}
                </p>
              )}

              {(v.previous_content || v.new_content) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
                  <div className="p-3 rounded-xl bg-rose-50/50 border border-rose-200 space-y-1">
                    <span className="text-[10px] font-bold uppercase text-rose-700 block">Previous Content</span>
                    <p className="text-slate-700 whitespace-pre-wrap line-clamp-6">
                      {v.previous_content || "—"}
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-emerald-50/50 border border-emerald-200 space-y-1">
                    <span className="text-[10px] font-bold uppercase text-emerald-700 block">New Content</span>
                    <p className="text-slate-700 whitespace-pre-wrap line-clamp-6">
                      {v.new_content || "—"}
                    </p>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
