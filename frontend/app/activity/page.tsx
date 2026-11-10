"use client"

import React, { useEffect, useState } from "react"
import { Activity, Clock, ShieldCheck, User, GitCommit, MessageSquare, FileText, CheckCircle2, ArrowUpRight } from "lucide-react"
import { api } from "@/lib/api"

export default function ActivityPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => {
      const pid =
        typeof window !== "undefined"
          ? localStorage.getItem("obsidian_active_project_id") ||
            localStorage.getItem("obsidian_active_project") ||
            undefined
          : undefined
      api.getActivity(pid)
        .then(data => {
          setLogs(Array.isArray(data) ? data : [])
        })
        .catch(() => setLogs([]))
        .finally(() => setLoading(false))
    }
    load()
    window.addEventListener("obsidian_project_changed", load)
    return () => window.removeEventListener("obsidian_project_changed", load)
  }, [])

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 tracking-tight">Project Activity Stream</h1>
        <p className="text-xs text-slate-500 mt-0.5">Live immutable audit log of knowledge ingestion, verification reviews, and handover milestones</p>
      </div>

      <div className="apple-card p-5 space-y-3">
        {logs.map((log, idx) => (
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

        {logs.length === 0 && !loading && (
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
