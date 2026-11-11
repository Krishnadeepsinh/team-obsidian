"use client"

import React, { useState, useEffect } from "react"
import {
  Save,
  ShieldCheck,
  Cpu,
  Database,
  CheckCircle2,
  Check,
  Users,
  Building2,
  UserPlus
} from "lucide-react"
import { api } from "@/lib/api"

export default function SettingsPage() {
  const [saved, setSaved] = useState(false)
  const [currentUser, setCurrentUser] = useState<any>(null)
  const [userContext, setUserContext] = useState<any>(null)
  
  // Org Creation State
  const [newOrgName, setNewOrgName] = useState("")
  const [orgCreating, setOrgCreating] = useState(false)
  const [orgMessage, setOrgMessage] = useState("")

  // Invite Member State
  const [inviteEmail, setInviteEmail] = useState("")
  const [inviteRole, setInviteRole] = useState("developer")
  const [selectedOrgId, setSelectedOrgId] = useState("")
  const [inviting, setInviting] = useState(false)
  const [inviteMessage, setInviteMessage] = useState("")

  // Governance & Org Settings State
  const [orgSettings, setOrgSettings] = useState<any>(null)
  const [threshold, setThreshold] = useState<number>(0.75)
  const [requireSecApproval, setRequireSecApproval] = useState<boolean>(false)
  const [savingGovernance, setSavingGovernance] = useState(false)
  const [govError, setGovError] = useState("")

  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("obsidian_user")
      if (stored) {
        try {
          setCurrentUser(JSON.parse(stored))
        } catch {}
      }
      api.getUserContext().then((ctx) => {
        if (ctx) {
          setUserContext(ctx)
          if (ctx.user) setCurrentUser(ctx.user)
          if (ctx.organizations && ctx.organizations.length > 0) {
            setSelectedOrgId(ctx.organizations[0].id)
          }
        }
      }).catch(() => {})
      api.getOrgSettings().then((s) => {
        if (s) {
          setOrgSettings(s)
          if (typeof s.evidence_verification_threshold === "number") {
            setThreshold(s.evidence_verification_threshold)
          }
          setRequireSecApproval(Boolean(s.require_security_approval))
        }
      }).catch(() => {})
    }
  }, [])

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newOrgName.trim()) return
    try {
      setOrgCreating(true)
      const res = await api.createOrganization({ name: newOrgName })
      setOrgMessage(`Organization "${res.name}" created successfully!`)
      setNewOrgName("")
      const ctx = await api.getUserContext()
      if (ctx) setUserContext(ctx)
      setTimeout(() => setOrgMessage(""), 4000)
    } catch (err: any) {
      setOrgMessage(err?.message || "Failed to create organization")
    } finally {
      setOrgCreating(false)
    }
  }

  const handleInviteMember = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteEmail.trim() || !selectedOrgId) return
    try {
      setInviting(true)
      await api.inviteOrgMember(selectedOrgId, inviteEmail, inviteRole)
      setInviteMessage(`Invited ${inviteEmail} as ${inviteRole}!`)
      setInviteEmail("")
      setTimeout(() => setInviteMessage(""), 4000)
    } catch (err: any) {
      setInviteMessage(err?.message || "Failed to invite member")
    } finally {
      setInviting(false)
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      setSavingGovernance(true)
      setGovError("")
      const res = await api.updateOrgSettings({
        evidence_verification_threshold: Number(threshold),
        require_security_approval: Boolean(requireSecApproval),
      })
      if (res?.settings) setOrgSettings(res.settings)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err: any) {
      setGovError(err?.message || "Failed to update organization governance settings.")
    } finally {
      setSavingGovernance(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between pb-3 border-b border-slate-200">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Workspace & System Settings</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Manage multi-tenant organizations, team collaboration, personal workspace, and AI configuration
          </p>
        </div>
        {saved && (
          <span className="text-xs text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200 flex items-center gap-1 font-semibold">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            Settings Saved
          </span>
        )}
      </div>

        {govError && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
            {govError}
          </div>
        )}

      {/* 1. User Profile & Personal Workspace */}
      <div className="apple-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 text-sm font-bold text-slate-900">
            <Users className="w-4 h-4 text-violet-600" />
            <span>My Account & Personal Workspace</span>
          </div>
          <span className="text-[10px] uppercase font-bold text-violet-700 bg-violet-50 px-2 py-0.5 rounded-full border border-violet-200">
            Isolated Tenant
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          <div className="p-3 rounded-xl bg-slate-50 border border-slate-100">
            <span className="text-slate-400 uppercase text-[10px] font-bold block mb-0.5">User Name</span>
            <p className="font-bold text-slate-900">{currentUser?.name || "Workspace User"}</p>
          </div>
          <div className="p-3 rounded-xl bg-slate-50 border border-slate-100">
            <span className="text-slate-400 uppercase text-[10px] font-bold block mb-0.5">Email Identity</span>
            <p className="font-bold text-slate-900">{currentUser?.email || "Not available"}</p>
          </div>
          <div className="p-3 rounded-xl bg-slate-50 border border-slate-100">
            <span className="text-slate-400 uppercase text-[10px] font-bold block mb-0.5">Assigned Role</span>
            <p className="font-bold text-slate-900 capitalize">{currentUser?.role || "Developer"}</p>
          </div>
        </div>
      </div>

      {/* 2. Organization & Team Collaboration (Multi-User SaaS) */}
      <div className="apple-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 text-sm font-bold text-slate-900">
            <Building2 className="w-4 h-4 text-violet-600" />
            <span>Organizations & Workspaces</span>
          </div>
        </div>

        {/* List of Organizations */}
        <div className="space-y-2">
          <span className="text-[11px] font-bold text-slate-500 uppercase block">Active Organizations</span>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            {userContext?.organizations && userContext.organizations.length > 0 ? (
              userContext.organizations.map((org: any) => (
                <div key={org.id} className="p-3.5 rounded-xl border border-slate-200 bg-white shadow-sm flex items-center justify-between">
                  <div>
                    <h4 className="font-bold text-slate-900">{org.name}</h4>
                    <span className="text-[11px] text-slate-400">
                      {org.is_personal ? "Personal Workspace" : "Shared Organization"}
                    </span>
                  </div>
                  <span className="text-[10px] font-semibold text-violet-700 bg-violet-50 px-2 py-0.5 rounded-full border border-violet-200">
                    {org.tier || "Enterprise"}
                  </span>
                </div>
              ))
            ) : (
              <div className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 text-slate-500 text-xs">
                No shared organizations yet. Create one below to collaborate.
              </div>
            )}
          </div>
        </div>

        {/* Create Organization Form */}
        <form onSubmit={handleCreateOrg} className="pt-2 border-t border-slate-100 flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            placeholder="New Organization Name (e.g. Acme Corp)"
            value={newOrgName}
            onChange={(e) => setNewOrgName(e.target.value)}
            className="flex-1 px-3 py-2 text-xs rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
          <button
            type="submit"
            disabled={orgCreating || !newOrgName.trim()}
            className="px-4 py-2 text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white rounded-xl shadow-sm transition-all"
          >
            {orgCreating ? "Creating..." : "Create Organization"}
          </button>
        </form>
        {orgMessage && (
          <p className="text-xs text-emerald-600 font-medium">{orgMessage}</p>
        )}

        {/* Invite Member to Organization Form */}
        <div className="pt-3 border-t border-slate-100 space-y-2">
          <span className="text-[11px] font-bold text-slate-500 uppercase block">Invite Colleague to Organization</span>
          <form onSubmit={handleInviteMember} className="grid grid-cols-1 sm:grid-cols-4 gap-2 text-xs">
            <select
              value={selectedOrgId}
              onChange={(e) => setSelectedOrgId(e.target.value)}
              className="px-3 py-2 rounded-xl border border-slate-200 bg-white font-medium focus:outline-none focus:ring-2 focus:ring-violet-500"
            >
              {userContext?.organizations?.map((org: any) => (
                <option key={org.id} value={org.id}>{org.name}</option>
              ))}
            </select>
            <input
              type="email"
              placeholder="colleague@company.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="px-3 py-2 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500 sm:col-span-2"
            />
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              className="px-3 py-2 rounded-xl border border-slate-200 bg-white font-medium focus:outline-none focus:ring-2 focus:ring-violet-500"
            >
              <option value="developer">Developer</option>
              <option value="project_manager">Project Manager</option>
              <option value="admin">Admin</option>
              <option value="viewer">Viewer</option>
            </select>
            <div className="sm:col-span-4 flex justify-end">
              <button
                type="submit"
                disabled={inviting || !inviteEmail.trim()}
                className="px-4 py-2 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white rounded-xl shadow-sm transition-all flex items-center gap-1.5"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>{inviting ? "Inviting..." : "Send Invitation"}</span>
              </button>
            </div>
          </form>
          {inviteMessage && (
            <p className="text-xs text-emerald-600 font-medium">{inviteMessage}</p>
          )}
        </div>
      </div>

      {/* 3. Handover Governance Policy */}
      <form onSubmit={handleSave} className="apple-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <ShieldCheck className="w-4 h-4 text-violet-600" />
            <span>Evidence &amp; Approval Governance</span>
          </div>
          <span className="text-[11px] font-semibold text-slate-500">
            {orgSettings?.org_name || "Active Organization"}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 space-y-1.5">
            <label className="font-bold text-slate-800 block">
              Minimum Evidence Confidence Threshold ({Math.round(threshold * 100)}%)
            </label>
            <input
              type="range"
              min="0.5"
              max="0.95"
              step="0.05"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              className="w-full accent-violet-600"
            />
            <p className="text-[11px] text-slate-500">Claims below this score require explicit human review.</p>
          </div>

          <label className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-between gap-3 cursor-pointer">
            <div>
              <span className="font-bold text-slate-800 block">Require Security Lead Sign-off</span>
              <span className="text-[11px] text-slate-500">Enforce security gate before publishing handovers</span>
            </div>
            <input
              type="checkbox"
              checked={requireSecApproval}
              onChange={(e) => setRequireSecApproval(e.target.checked)}
              className="w-4 h-4 accent-violet-600"
            />
          </label>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={savingGovernance}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm flex items-center gap-1.5"
          >
            <Save className="w-3.5 h-3.5" /> {savingGovernance ? "Saving..." : "Save Governance Policy"}
          </button>
        </div>
      </form>

      {/* 4. AI Engine Architecture Card */}
      <div className="apple-card p-5 space-y-4">
        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Cpu className="w-4 h-4 text-violet-600" />
          <span>AI Model &amp; Embedding Architecture</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 space-y-1">
            <span className="text-slate-400 uppercase text-[10px] font-bold block">Primary LLM</span>
            <p className="text-sm font-bold text-slate-900">{orgSettings?.primary_llm || "gemini-3.5-flash"}</p>
            <p className="text-[11px] text-slate-500">Structured knowledge extraction &amp; 16-section dossier synthesis</p>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 space-y-1">
            <span className="text-slate-400 uppercase text-[10px] font-bold block">Secondary LLM</span>
            <p className="text-sm font-bold text-slate-900">{orgSettings?.secondary_llm || "gemini-3.5-flash-lite"}</p>
            <p className="text-[11px] text-slate-500">Entity deduplication, contradiction triage &amp; query routing</p>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 space-y-1">
            <span className="text-slate-400 uppercase text-[10px] font-bold block">Embedding Model</span>
            <p className="text-sm font-bold text-slate-900">{orgSettings?.embedding_model || "BAAI/bge-small-en-v1.5 (384 dim)"}</p>
            <p className="text-[11px] text-slate-500">Dense semantic vector representations for hybrid RAG</p>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 space-y-1">
            <span className="text-slate-400 uppercase text-[10px] font-bold block">Knowledge Graph</span>
            <p className="text-sm font-bold text-slate-900">NetworkX &amp; React Flow</p>
            <p className="text-[11px] text-slate-500">Blast-radius calculation &amp; topological dependency traversal</p>
          </div>
        </div>
      </div>

      {/* 5. Database & Infrastructure */}
      <div className="apple-card p-5 space-y-4">
        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Database className="w-4 h-4 text-violet-600" />
          <span>Cloud Database &amp; Security</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
            <span className="text-slate-400 uppercase text-[10px] font-bold block mb-1">Database Engine</span>
            <p className="font-bold text-slate-900">{orgSettings?.database || "PostgreSQL + pgvector"}</p>
            <p className="text-[11px] text-slate-500 mt-0.5">Transactional workspace &amp; vector indexing</p>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
            <span className="text-slate-400 uppercase text-[10px] font-bold block mb-1">Row Level Security (RLS)</span>
            <p className="font-bold text-emerald-700 flex items-center gap-1.5">
              <Check className="w-3.5 h-3.5 stroke-[3]" />
              Enforced Across Relational Tables
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5">Strict multi-tenant project isolation</p>
          </div>
        </div>
      </div>
    </div>
  )
}
