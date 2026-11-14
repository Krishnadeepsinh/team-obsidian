"use client"

import React, { useState } from "react"
import { useRouter } from "next/navigation"
import {
  Plus,
  Search,
  Layers,
  ArrowUpRight
} from "lucide-react"
import { api } from "@/lib/api"
import { useProjects, useInvalidateQueries } from "@/hooks/use-queries"
import { useQueryClient } from "@tanstack/react-query"
import { queryKeys } from "@/lib/query-keys"

export default function ProjectsPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { data: projectsData, isLoading } = useProjects()
  const { invalidateProjects, invalidateDashboard, invalidateUserContext } = useInvalidateQueries()
  const projects = Array.isArray(projectsData) ? projectsData : []
  const loading = isLoading && projects.length === 0
  const [search, setSearch] = useState("")
  const [showModal, setShowModal] = useState(false)
  
  // New Project Form state
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [priority, setPriority] = useState("medium")
  const [tags, setTags] = useState("")
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState("")

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    try {
      setCreating(true)
      setCreateError("")
      const tagList = tags.split(",").map(t => t.trim()).filter(Boolean)
      await api.createProject({
        name,
        description,
        priority,
        tags: tagList
      })
      invalidateProjects()
      invalidateDashboard()
      invalidateUserContext()
      setShowModal(false)
      setName("")
      setDescription("")
      setTags("")
    } catch (err: any) {
      setCreateError(err.message || "Failed to create project.")
    } finally {
      setCreating(false)
    }
  }

  const filtered = projects.filter(p => 
    (p.name && p.name.toLowerCase().includes(search.toLowerCase())) || 
    (p.description && p.description.toLowerCase().includes(search.toLowerCase()))
  )

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Enterprise Projects</h1>
          <p className="text-xs text-slate-500 mt-0.5">Independent project workspaces with autonomous knowledge repositories</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-2 shadow-md shadow-violet-600/20 transition-all hover:scale-[1.02]"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New Project</span>
        </button>
      </div>

      {/* Filter / Search Bar */}
      <div className="flex items-center justify-between gap-4 apple-card p-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search projects by name, description, tags..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-1.5 rounded-full text-xs bg-slate-50 border border-slate-200 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white transition-colors"
          />
        </div>
        <div className="text-xs text-slate-500 font-mono">
          {filtered.length} Projects Total
        </div>
      </div>

      {/* Projects Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {loading && (
          <>
            {[1, 2, 3].map((i) => (
              <div key={i} className="apple-card p-5 animate-pulse space-y-3">
                <div className="flex justify-between items-center">
                  <div className="h-4 w-20 bg-slate-200 rounded-full" />
                  <div className="h-4 w-12 bg-slate-200 rounded-full" />
                </div>
                <div className="h-5 w-3/4 bg-slate-200 rounded" />
                <div className="h-3 w-full bg-slate-100 rounded" />
                <div className="h-3 w-2/3 bg-slate-100 rounded" />
                <div className="flex gap-2 pt-3 border-t border-slate-100">
                  <div className="h-6 w-16 bg-slate-100 rounded-md" />
                  <div className="h-6 w-16 bg-slate-100 rounded-md" />
                </div>
              </div>
            ))}
          </>
        )}

        {filtered.map((p) => (
          <div
            key={p.id}
            onClick={() => router.push(`/projects/${p.id}`)}
            onMouseEnter={() => {
              queryClient.prefetchQuery({
                queryKey: queryKeys.projects.detail(undefined, p.id),
                queryFn: () => api.getProject(p.id),
                staleTime: 60 * 1000,
              })
            }}
            className="apple-card p-5 flex flex-col justify-between hover:border-violet-300 transition-all cursor-pointer group"
          >
            <div>
              {/* Header Badges */}
              <div className="flex items-center justify-between gap-2 mb-3">
                <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase ${
                  p.priority === "critical"
                    ? "bg-rose-50 text-rose-600 border border-rose-200"
                    : p.priority === "high"
                    ? "bg-amber-50 text-amber-700 border border-amber-200"
                    : "bg-blue-50 text-blue-600 border border-blue-200"
                }`}>
                  {p.priority} Priority
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium">
                  {p.status || "active"}
                </span>
              </div>

              {/* Title & Description */}
              <h3 className="text-base font-bold text-slate-900 group-hover:text-violet-700 transition-colors mb-1.5 flex items-center justify-between">
                <span>{p.name}</span>
                <ArrowUpRight className="w-4 h-4 text-slate-400 group-hover:text-violet-600 transition-colors" />
              </h3>
              <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed mb-4">
                {p.description || "Production system under active management and continuous handover."}
              </p>

              {/* Tags */}
              {p.tags && p.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {p.tags.map((t: string, i: number) => (
                    <span key={i} className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 font-medium">
                      #{t}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Bottom Metrics Bar */}
            <div className="pt-3 border-t border-slate-100 grid grid-cols-4 gap-2 text-center text-xs">
              <div className="bg-slate-50 p-1.5 rounded-lg">
                <p className="text-xs font-bold text-slate-900">{p.member_count ?? 0}</p>
                <p className="text-[9px] text-slate-400 uppercase font-medium">Members</p>
              </div>
              <div className="bg-slate-50 p-1.5 rounded-lg">
                <p className="text-xs font-bold text-slate-900">{p.decision_count ?? 0}</p>
                <p className="text-[9px] text-slate-400 uppercase font-medium">ADRs</p>
              </div>
              <div className="bg-slate-50 p-1.5 rounded-lg">
                <p className="text-xs font-bold text-slate-900">{p.task_count ?? 0}</p>
                <p className="text-[9px] text-slate-400 uppercase font-medium">Tasks</p>
              </div>
              <div className="bg-slate-50 p-1.5 rounded-lg">
                <p className="text-xs font-bold text-slate-900">{p.evidence_count ?? 0}</p>
                <p className="text-[9px] text-slate-400 uppercase font-medium">Evidence</p>
              </div>
            </div>
          </div>
        ))}

        {filtered.length === 0 && !loading && (
          <div className="col-span-full apple-card p-12 text-center">
            <Layers className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <h3 className="text-sm font-bold text-slate-800">No Projects Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              Create an enterprise project workspace to start reconstructing knowledge and managing handovers.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20"
            >
              Create First Project
            </button>
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Create New Project</h3>
              <button onClick={() => { setShowModal(false); setCreateError("") }} className="text-slate-400 hover:text-slate-600 text-xs">✕ Close</button>
            </div>
            {createError && (
              <div className="p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
                {createError}
              </div>
            )}
            <form onSubmit={handleCreate} className="space-y-3.5">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Project Name *</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Core Payment Engine"
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Description</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Goals, architecture scope, tech stack..."
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
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
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">Tags (comma-separated)</label>
                  <input
                    type="text"
                    value={tags}
                    onChange={(e) => setTags(e.target.value)}
                    placeholder="FastAPI, React"
                    className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                  />
                </div>
              </div>
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
                  disabled={creating}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white shadow-md shadow-violet-600/20"
                >
                  {creating ? "Creating..." : "Create Project"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
