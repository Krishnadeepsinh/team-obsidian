"use client"

import { useCallback, useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { api, getStoredProjectId, setStoredProjectId } from "@/lib/api"
import {
  ArrowLeft,
  Layers,
  Users,
  Clock,
  GitBranch,
  FileText,
  Scale,
  CheckSquare,
  AlertTriangle,
  UserPlus,
  Trash2,
  Sparkles,
  ExternalLink,
  CheckCircle2,
  Edit3,
} from "lucide-react"

const CANONICAL_ROLES = [
  { value: "project_owner", label: "Project Owner" },
  { value: "project_manager", label: "Project Manager" },
  { value: "tech_lead", label: "Tech Lead" },
  { value: "developer", label: "Developer" },
  { value: "departing_employee", label: "Departing Employee" },
  { value: "incoming_employee", label: "Incoming Employee" },
  { value: "reviewer", label: "Reviewer / QA" },
  { value: "viewer", label: "Viewer (Read-Only)" },
  { value: "workspace_owner", label: "Workspace Owner" },
  { value: "org_admin", label: "Org Admin" },
]

export default function ProjectDetailPage() {
  const params = useParams()
  const router = useRouter()
  const projectId = String(params?.id || "")

  const [project, setProject] = useState<any>(null)
  const [members, setMembers] = useState<any[]>([])
  const [timeline, setTimeline] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [statusMsg, setStatusMsg] = useState("")

  // Add/Invite member state
  const [inviteEmail, setInviteEmail] = useState("")
  const [inviteRole, setInviteRole] = useState("developer")
  const [inviting, setInviting] = useState(false)

  // Edit modal state
  const [showEdit, setShowEdit] = useState(false)
  const [editName, setEditName] = useState("")
  const [editDesc, setEditDesc] = useState("")
  const [editPriority, setEditPriority] = useState("medium")
  const [editStatus, setEditStatus] = useState("active")

  const loadAll = useCallback(async () => {
    if (!projectId) return
    try {
      setLoading(true)
      setError("")
      const [p, m, t] = await Promise.all([
        api.getProject(projectId),
        api.getProjectMembers(projectId).catch(() => []),
        api.getProjectTimeline(projectId).catch(() => []),
      ])
      setProject(p)
      setEditName(p.name || "")
      setEditDesc(p.description || "")
      setEditPriority(p.priority || "medium")
      setEditStatus(p.status || "active")
      setMembers(Array.isArray(m) ? m : [])
      setTimeline(Array.isArray(t) ? t : [])
      setStoredProjectId(p.id)
    } catch (err: any) {
      setError(err.message || "Failed to load project details.")
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteEmail.trim()) return
    try {
      setInviting(true)
      setStatusMsg("")
      setError("")
      await api.addProjectMember(projectId, {
        email: inviteEmail.trim(),
        project_role: inviteRole,
      })
      setInviteEmail("")
      setStatusMsg("Project member assigned successfully.")
      await loadAll()
    } catch (err: any) {
      setError(err.message || "Could not add project member.")
    } finally {
      setInviting(false)
    }
  }

  const handleRoleChange = async (userEmail: string, userId: string, nextRole: string) => {
    try {
      await api.addProjectMember(projectId, {
        user_id: userId,
        email: userEmail || undefined,
        project_role: nextRole,
      })
      setStatusMsg("Member role updated.")
      await loadAll()
    } catch (err: any) {
      setError(err.message || "Failed to update role.")
    }
  }

  const handleRemoveMember = async (userId: string) => {
    if (!confirm("Remove this member from the project?")) return
    try {
      await api.removeProjectMember(projectId, userId)
      setStatusMsg("Member removed from project.")
      await loadAll()
    } catch (err: any) {
      setError(err.message || "Failed to remove member.")
    }
  }

  const handleUpdateProject = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.updateProject(projectId, {
        name: editName,
        description: editDesc,
        priority: editPriority,
        status: editStatus,
      })
      setShowEdit(false)
      setStatusMsg("Project settings updated.")
      await loadAll()
    } catch (err: any) {
      setError(err.message || "Failed to update project.")
    }
  }

  const handleDeleteProject = async () => {
    if (!confirm(`Delete project "${project?.name}" permanently? All project records will be removed.`)) return
    try {
      await api.deleteProject(projectId)
      if (getStoredProjectId() === projectId) {
        setStoredProjectId(undefined)
      }
      router.push("/projects")
    } catch (err: any) {
      setError(err.message || "Failed to delete project.")
    }
  }

  if (loading) {
    return (
      <div className="p-6 max-w-6xl mx-auto">
        <div className="apple-card p-10 text-center text-xs text-slate-400">Loading project workspace...</div>
      </div>
    )
  }

  if (error && !project) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <Link href="/projects" className="inline-flex items-center gap-1.5 text-xs font-semibold text-violet-600">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Projects
        </Link>
        <div className="apple-card p-8 text-center text-rose-600 text-xs font-medium">{error}</div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/projects" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-violet-700">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Projects
        </Link>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setShowEdit(true)}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1.5"
          >
            <Edit3 className="w-3.5 h-3.5" /> Edit Project
          </button>
          <Link
            href="/integrations"
            className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1.5"
          >
            <GitBranch className="w-3.5 h-3.5 text-violet-600" /> Sources
          </Link>
          <Link
            href="/handover"
            className="px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm flex items-center gap-1.5"
          >
            <FileText className="w-3.5 h-3.5" /> Handover Dossier
          </Link>
          <button
            onClick={handleDeleteProject}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100 flex items-center gap-1"
          >
            <Trash2 className="w-3.5 h-3.5" /> Delete
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

      {/* Header Card */}
      <div className="apple-card p-6 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1.5 max-w-2xl">
            <div className="flex items-center gap-2">
              <span className="text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase bg-violet-50 text-violet-700 border border-violet-200">
                {project?.priority || "medium"} priority
              </span>
              <span className="text-[10px] px-2.5 py-0.5 rounded-full font-semibold bg-slate-100 text-slate-600 uppercase">
                {project?.status || "active"}
              </span>
              {project?.is_demo && (
                <span className="text-[10px] px-2.5 py-0.5 rounded-full font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                  Demo Sandbox
                </span>
              )}
            </div>
            <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              <Layers className="w-5 h-5 text-violet-600" />
              <span>{project?.name}</span>
            </h1>
            <p className="text-xs text-slate-600 leading-relaxed">
              {project?.description || "No project description specified."}
            </p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div className="px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-100">
              <p className="text-lg font-bold text-slate-900">{project?.member_count ?? members.length}</p>
              <p className="text-[10px] text-slate-500 uppercase font-semibold">Members</p>
            </div>
            <div className="px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-100">
              <p className="text-lg font-bold text-slate-900">{project?.decision_count ?? 0}</p>
              <p className="text-[10px] text-slate-500 uppercase font-semibold">Decisions</p>
            </div>
            <div className="px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-100">
              <p className="text-lg font-bold text-slate-900">{project?.task_count ?? 0}</p>
              <p className="text-[10px] text-slate-500 uppercase font-semibold">Tasks</p>
            </div>
            <div className="px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-100">
              <p className="text-lg font-bold text-slate-900">{project?.evidence_count ?? 0}</p>
              <p className="text-[10px] text-slate-500 uppercase font-semibold">Evidence</p>
            </div>
          </div>
        </div>
      </div>

      {/* Main Grid: Members RBAC + Chronological Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Members & RBAC */}
        <div className="lg:col-span-5 apple-card p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Users className="w-4 h-4 text-violet-600" />
              <span>Project Access &amp; RBAC Roles</span>
            </h2>
            <span className="text-[11px] font-semibold text-slate-400">{members.length} assigned</span>
          </div>

          <form onSubmit={handleAddMember} className="space-y-2 p-3.5 rounded-xl bg-slate-50 border border-slate-100">
            <label className="text-[11px] font-bold text-slate-600 uppercase block">Add / Assign Existing User</label>
            <input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="teammate@company.com"
              className="w-full px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
            />
            <div className="flex gap-2">
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="flex-1 px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 focus:outline-none focus:border-violet-500"
              >
                {CANONICAL_ROLES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
              <button
                type="submit"
                disabled={inviting}
                className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-1.5"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>{inviting ? "Saving..." : "Assign"}</span>
              </button>
            </div>
          </form>

          <div className="space-y-2">
            {members.map((m) => (
              <div key={m.id || m.user_id} className="p-3 rounded-xl border border-slate-100 bg-white flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs font-bold text-slate-900 truncate">{m.user_name || "Project Member"}</p>
                  <p className="text-[11px] text-slate-500 truncate">{m.user_email}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <select
                    value={m.project_role}
                    onChange={(e) => handleRoleChange(m.user_email, m.user_id, e.target.value)}
                    className="px-2 py-1 rounded-lg text-[11px] font-medium bg-slate-50 border border-slate-200 text-slate-700"
                  >
                    {CANONICAL_ROLES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                  <button
                    onClick={() => handleRemoveMember(m.user_id)}
                    title="Remove Member"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Project Chronological Timeline */}
        <div className="lg:col-span-7 apple-card p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Clock className="w-4 h-4 text-violet-600" />
              <span>Project Knowledge Timeline</span>
            </h2>
            <Link href="/knowledge/graph" className="text-xs font-semibold text-violet-600 hover:text-violet-700 flex items-center gap-1">
              <Sparkles className="w-3.5 h-3.5" /> Inspect Knowledge Graph
            </Link>
          </div>

          {timeline.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-400">
              <Clock className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="font-semibold text-slate-600">No project timeline events yet</p>
              <p className="mt-1">Sync GitHub/Slack/Notion or upload project documentation to populate history.</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[540px] overflow-y-auto pr-1">
              {timeline.map((ev: any) => (
                <div key={ev.id} className="p-3.5 rounded-xl bg-slate-50 border border-slate-100 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      {ev.type === "decision" ? (
                        <Scale className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                      ) : ev.type === "task" ? (
                        <CheckSquare className="w-3.5 h-3.5 text-amber-600 flex-shrink-0" />
                      ) : (
                        <AlertTriangle className="w-3.5 h-3.5 text-violet-600 flex-shrink-0" />
                      )}
                      <span className="text-xs font-bold text-slate-900 truncate">{ev.title}</span>
                    </div>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-white border border-slate-200 font-semibold text-slate-600 flex-shrink-0">
                      {ev.badge}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-600 leading-relaxed">{ev.description}</p>
                  <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                    <span>Author: {ev.author || "System"}</span>
                    <div className="flex items-center gap-2">
                      <span>{ev.timestamp ? new Date(ev.timestamp).toLocaleString() : ""}</span>
                      {ev.url && (
                        <a href={ev.url} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                          Source <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Edit Modal */}
      {showEdit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Edit Project</h3>
              <button onClick={() => setShowEdit(false)} className="text-xs text-slate-400 hover:text-slate-600">✕ Close</button>
            </div>
            <form onSubmit={handleUpdateProject} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Project Name</label>
                <input
                  type="text"
                  required
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Description</label>
                <textarea
                  rows={3}
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Priority</label>
                  <select
                    value={editPriority}
                    onChange={(e) => setEditPriority(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Status</label>
                  <select
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                  >
                    <option value="active">Active</option>
                    <option value="handover_in_progress">Handover In Progress</option>
                    <option value="archived">Archived</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setShowEdit(false)} className="px-3 py-1.5 rounded-xl text-xs text-slate-600 hover:bg-slate-100">
                  Cancel
                </button>
                <button type="submit" className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

