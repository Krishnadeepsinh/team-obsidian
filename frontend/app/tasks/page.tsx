"use client"

import React, { useCallback, useEffect, useState } from "react"
import { CheckSquare, Plus, Search, UserCheck, AlertCircle, Check } from "lucide-react"
import { api, getStoredProjectId, resolveActiveProjectId } from "@/lib/api"

export default function TasksPage() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [filterDeparting, setFilterDeparting] = useState(false)
  const [search, setSearch] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState("")

  // Form state
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [owner, setOwner] = useState("")
  const [priority, setPriority] = useState("medium")
  const [deadline, setDeadline] = useState("")
  const [isDeparting, setIsDeparting] = useState(false)
  const [reassignmentTarget, setReassignmentTarget] = useState("")

  const loadTasks = useCallback(async () => {
    try {
      setLoading(true)
      const projs = await api.getProjects().catch(() => [])
      const resolvedPid = resolveActiveProjectId(projs, getStoredProjectId())
      setSelectedProjectId(resolvedPid)
      const data = await api.getTasks(resolvedPid || undefined)
      setTasks(data)
    } catch (err) {
      console.error("Tasks load error:", err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTasks()
    const onProjChange = () => loadTasks()
    window.addEventListener("obsidian_project_changed", onProjChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjChange)
  }, [loadTasks])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !owner.trim()) return
    try {
      await api.createTask({
        project_id: selectedProjectId || getStoredProjectId() || undefined,
        title,
        description,
        owner,
        priority,
        deadline: deadline || new Date().toISOString().split("T")[0],
        is_departing_owner: isDeparting,
        suggested_reassignment: isDeparting ? (reassignmentTarget.trim() || null) : null
      })
      await loadTasks()
      setShowModal(false)
      setTitle("")
      setDescription("")
      setOwner("")
      setReassignmentTarget("")
    } catch (err) {
      console.error("Create task error:", err)
    }
  }

  const handleReassign = async (taskId: string, newOwner: string) => {
    try {
      await api.reassignTask(taskId, newOwner)
      loadTasks()
    } catch (err) {
      console.error("Reassign error:", err)
    }
  }

  const handleToggleStatus = async (taskId: string, currentStatus: string) => {
    try {
      await api.updateTaskStatus(taskId, currentStatus === "completed" ? "open" : "completed")
      await loadTasks()
    } catch (err) {
      console.error("Task status error:", err)
    }
  }

  const filtered = tasks.filter(t => {
    if (filterDeparting && !t.is_departing_owner) return false
    if (search && !t.title?.toLowerCase().includes(search.toLowerCase()) && !t.owner?.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Tasks & Responsibilities</h1>
          <p className="text-xs text-slate-500 mt-0.5">Track task ownership, detect departing employee assignments, and manage successor reassignment</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setFilterDeparting(!filterDeparting)}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-all ${filterDeparting
                ? "bg-amber-100 text-amber-900 border-amber-300"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
          >
            {filterDeparting ? "Showing Departing Lead Tasks Only" : "Filter Departing Lead Tasks"}
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-1.5 shadow-md shadow-violet-600/20 transition-all hover:scale-[1.02]"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Create Task</span>
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 apple-card p-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search tasks by title or owner..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-1.5 rounded-full text-xs bg-slate-50 border border-slate-200 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
          />
        </div>
        <div className="text-xs text-slate-500 font-mono">
          {filtered.length} Tasks
        </div>
      </div>

      <div className="space-y-3">
        {filtered.map((t) => (
          <div
            key={t.id}
            className={`apple-card p-5 transition-all flex flex-col md:flex-row items-start md:items-center justify-between gap-4 ${t.is_departing_owner
                ? "border-amber-200 bg-amber-50/20"
                : "hover:border-violet-200"
              }`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 mb-1.5">
                <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase ${t.priority === "critical"
                    ? "bg-rose-50 text-rose-600 border border-rose-200"
                    : t.priority === "high"
                      ? "bg-amber-50 text-amber-700 border border-amber-200"
                      : "bg-blue-50 text-blue-600 border border-blue-200"
                  }`}>
                  {t.priority}
                </span>

                <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium uppercase">
                  {t.status}
                </span>

                {t.is_departing_owner && (
                  <span className="text-[10px] px-2.5 py-0.5 rounded-full font-semibold bg-amber-100 text-amber-800 border border-amber-300 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3 text-amber-700" />
                    Departing Lead Assignment
                  </span>
                )}
              </div>

              <h2 className="text-sm font-bold text-slate-900 mb-1">{t.title}</h2>
              <p className="text-xs text-slate-500 mb-2.5 leading-relaxed">{t.description || "No description provided."}</p>

              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
                <span>Current Owner: <strong className="text-slate-800">{t.owner}</strong></span>
                {t.deadline && <span>• Deadline: <strong className="text-slate-600 font-mono">{t.deadline}</strong></span>}
                {t.suggested_reassignment && (
                  <span>
                    • Suggested Successor: <strong className="text-violet-700">{t.suggested_reassignment}</strong>
                  </span>
                )}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-wrap items-center gap-2 flex-shrink-0">
              <button
                onClick={() => handleToggleStatus(t.id, t.status)}
                className={`px-3 py-2 rounded-xl text-xs font-semibold border flex items-center gap-1.5 transition-all ${
                  t.status === "completed"
                    ? "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                    : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"
                }`}
              >
                <Check className="w-3.5 h-3.5" />
                <span>{t.status === "completed" ? "Reopen" : "Complete"}</span>
              </button>
              {t.is_departing_owner && (
                <button
                  onClick={() => handleReassign(t.id, t.suggested_reassignment || "Successor")}
                  className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-1.5 shadow-sm transition-all hover:scale-[1.02]"
                >
                  <UserCheck className="w-3.5 h-3.5" />
                  <span>Reassign to {t.suggested_reassignment || "Successor"}</span>
                </button>
              )}
            </div>
          </div>
        ))}

        {filtered.length === 0 && !loading && (
          <div className="apple-card p-12 text-center">
            <CheckSquare className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <h3 className="text-sm font-bold text-slate-800">No Tasks Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              Create an operational task to assign ownership and track transition readiness.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white"
            >
              Create First Task
            </button>
          </div>
        )}
      </div>

      {/* Create Task Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Create New Task</h3>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600 text-xs">✕ Close</button>
            </div>
            <form onSubmit={handleCreate} className="space-y-3.5">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Task Title *</label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Implement webhook retry queue"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Description</label>
                <textarea
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Details, acceptance criteria, or context..."
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Owner *</label>
                  <input
                    type="text"
                    required
                    value={owner}
                    onChange={(e) => setOwner(e.target.value)}
                    placeholder="e.g. Jane Doe"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Priority</label>
                  <select
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Deadline</label>
                  <input
                    type="date"
                    value={deadline}
                    onChange={(e) => setDeadline(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  />
                </div>
                <div className="flex items-center gap-2 pt-6">
                  <input
                    type="checkbox"
                    id="departingCheck"
                    checked={isDeparting}
                    onChange={(e) => setIsDeparting(e.target.checked)}
                    className="rounded border-slate-300 text-violet-600 focus:ring-violet-500"
                  />
                  <label htmlFor="departingCheck" className="text-xs font-medium text-slate-700 cursor-pointer">
                    Departing lead task
                  </label>
                </div>
              </div>
              {isDeparting && (
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Suggested Successor</label>
                  <input
                    type="text"
                    value={reassignmentTarget}
                    onChange={(e) => setReassignmentTarget(e.target.value)}
                    placeholder="e.g. Alex Successor"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  />
                </div>
              )}
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20"
                >
                  Save Task
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
