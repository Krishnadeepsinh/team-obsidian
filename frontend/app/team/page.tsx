"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"
import { Users, Mail, Search, ShieldCheck } from "lucide-react"

export default function TeamPage() {
  const [members, setMembers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")

  useEffect(() => {
    const loadMembers = async () => {
      try {
        setLoading(true)
        const storedPid =
          typeof window !== "undefined" ? localStorage.getItem("obsidian_active_project") || undefined : undefined
        const list = await api.getTeamMembers(storedPid).catch(() => [])
        setMembers(Array.isArray(list) ? list : [])
      } finally {
        setLoading(false)
      }
    }
    loadMembers()
  }, [])

  const filtered = members.filter(
    (m) =>
      !search.trim() ||
      m.name?.toLowerCase().includes(search.toLowerCase()) ||
      m.email?.toLowerCase().includes(search.toLowerCase()) ||
      m.role?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Team &amp; Workspace Stakeholders</h1>
          <p className="text-xs text-slate-500 mt-1">
            Collaborators sharing an organization or authorized project scope with your account.
          </p>
        </div>

        <Link
          href="/settings"
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm self-start"
        >
          Manage Organization Invites
        </Link>
      </div>

      <div className="relative max-w-md">
        <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search colleagues by name, email, or role..."
          className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 shadow-sm focus:outline-none focus:border-violet-500"
        />
      </div>

      {loading ? (
        <div className="apple-card p-10 text-center text-xs text-slate-400">Loading workspace directory...</div>
      ) : filtered.length === 0 ? (
        <div className="apple-card p-12 text-center space-y-2">
          <Users className="w-9 h-9 text-slate-300 mx-auto" />
          <p className="text-sm font-bold text-slate-800">No Matching Team Members</p>
          <p className="text-xs text-slate-500">Invite colleagues in Settings or assign members to a project.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((m) => (
            <div key={m.id} className="apple-card p-5 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-[#7C3AED] to-[#6366F1] text-white font-bold text-xs flex items-center justify-center flex-shrink-0">
                    {(m.name || "U")
                      .split(" ")
                      .map((p: string) => p[0])
                      .join("")
                      .slice(0, 2)
                      .toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-sm font-bold text-slate-900 truncate">{m.name}</h3>
                    <p className="text-[11px] text-slate-500 truncate">{m.title || "Engineering Member"}</p>
                  </div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 font-bold uppercase flex-shrink-0">
                  {(m.role || "developer").replace("_", " ")}
                </span>
              </div>

              <div className="pt-2 border-t border-slate-100 space-y-1 text-xs text-slate-600">
                <div className="flex items-center gap-1.5 truncate">
                  <Mail className="w-3.5 h-3.5 text-slate-400" />
                  <span className="truncate">{m.email}</span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                  <span>{m.department || "Core Team"}</span>
                  <span className="inline-flex items-center gap-1 text-emerald-600 font-semibold">
                    <ShieldCheck className="w-3 h-3" /> Active
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
