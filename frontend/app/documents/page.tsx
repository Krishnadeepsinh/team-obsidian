"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { api, getStoredProjectId, resolveActiveProjectId, setStoredProjectId } from "@/lib/api"
import {
  FileUp,
  FileText,
  Download,
  Trash2,
  Eye,
  X,
  CheckCircle2,
  ShieldCheck,
  Search,
} from "lucide-react"

const MAX_UPLOAD_MB = 25

export default function DocumentsPage() {
  const [docs, setDocs] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const projectsRef = useRef<any[]>([])
  const [activeProject, setActiveProject] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [title, setTitle] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [search, setSearch] = useState("")
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")

  // Chunk Inspector Drawer
  const [selectedDoc, setSelectedDoc] = useState<any>(null)
  const [chunks, setChunks] = useState<any[]>([])
  const [loadingChunks, setLoadingChunks] = useState(false)

  const loadData = useCallback(async (pid?: string) => {
    try {
      setLoading(true)
      let projs = projectsRef.current
      try {
        const projsRaw = await api.getProjects()
        if (Array.isArray(projsRaw)) {
          projs = projsRaw
          projectsRef.current = projsRaw
          setProjects(projsRaw)
        }
      } catch (err: any) {
        if (projectsRef.current.length === 0) {
          setError(err?.message || "Unable to load projects right now. Retry in a moment.")
        }
      }

      let resolvedPid = ""
      if (pid === "") {
        resolvedPid = ""
      } else if (pid !== undefined) {
        resolvedPid = resolveActiveProjectId(projs, pid)
      } else {
        resolvedPid = resolveActiveProjectId(projs, getStoredProjectId())
      }

      setActiveProject(resolvedPid)
      try {
        const res = await api.getDocuments(resolvedPid || undefined)
        if (Array.isArray(res)) {
          setDocs(res)
        }
      } catch (err: any) {
        setError((prev) => prev || err?.message || "Could not refresh documents list.")
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleFileChange = (picked: File | null) => {
    setError("")
    setFile(picked)
    if (picked && !title.trim()) {
      const stem = picked.name.replace(/\.[^/.]+$/, "").replace(/[_-]+/g, " ").trim()
      if (stem) setTitle(stem)
    }
  }

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError("Select a document file to upload.")
      return
    }
    if (file.size === 0) {
      setError("Selected file is empty (0 bytes). Choose a non-empty file.")
      return
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`File exceeds the ${MAX_UPLOAD_MB} MB upload limit.`)
      return
    }
    const targetPid = activeProject || projects[0]?.id || ""
    if (!targetPid) {
      setError("Create a project in Projects before uploading documents.")
      return
    }

    const effectiveTitle = title.trim() || file.name.replace(/\.[^/.]+$/, "") || file.name
    const formData = new FormData()
    formData.append("project_id", targetPid)
    formData.append("title", effectiveTitle)
    formData.append("extract_knowledge", "true")
    formData.append("file", file)

    try {
      setUploading(true)
      setError("")
      setMessage("")
      const alreadyIds = new Set(docs.map((d) => d.id))
      const uploaded = await api.uploadDocument(formData)
      setTitle("")
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ""
      if (uploaded?.id && alreadyIds.has(uploaded.id)) {
        setMessage(`Identical file (same SHA-256) is already indexed as "${uploaded.title}".`)
      } else {
        setMessage(
          `Uploaded "${uploaded?.title || effectiveTitle}" (${uploaded?.chunk_count || 0} searchable chunks, SHA-256 verified).`
        )
      }
      await loadData(activeProject || targetPid)
    } catch (err: any) {
      setError(err.message || "Document upload failed.")
    } finally {
      setUploading(false)
    }
  }

  const handleInspectChunks = async (doc: any) => {
    setSelectedDoc(doc)
    setChunks([])
    setLoadingChunks(true)
    try {
      const list = await api.getDocumentChunks(doc.id)
      setChunks(Array.isArray(list) ? list : [])
    } catch (err: any) {
      setError(err.message || "Could not load document chunks.")
    } finally {
      setLoadingChunks(false)
    }
  }

  const handleDownload = async (doc: any) => {
    try {
      await api.downloadDocument(doc.id, doc.filename || `${doc.title}.${doc.file_type || "txt"}`)
    } catch (err: any) {
      setError(err.message || "Download failed.")
    }
  }

  const handleDelete = async (doc: any) => {
    if (!confirm(`Delete "${doc.title}"? Associated chunk references will be removed.`)) return
    try {
      await api.deleteDocument(doc.id)
      setMessage(`Deleted "${doc.title}".`)
      await loadData(activeProject || undefined)
    } catch (err: any) {
      setError(err.message || "Delete failed.")
    }
  }

  const filtered = docs.filter(
    (d) =>
      !search.trim() ||
      d.title?.toLowerCase().includes(search.toLowerCase()) ||
      d.filename?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Documents &amp; Artifacts</h1>
          <p className="text-xs text-slate-500 mt-1">
            Upload PDFs, DOCX, XLSX, CSV, Markdown, JSON, and runbooks with SHA-256 provenance and chunk-level citations.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              setStoredProjectId(pid || undefined)
              loadData(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">{error}</div>
      )}
      {message && (
        <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> {message}
        </div>
      )}

      {/* Upload Card */}
      <form onSubmit={handleUpload} className="apple-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
            <FileUp className="w-4 h-4 text-violet-600" />
            <span>Upload Project Knowledge Document</span>
          </h2>
          <span className="text-[11px] text-slate-400">
            Supported (max {MAX_UPLOAD_MB} MB): PDF, DOCX, XLSX, CSV, MD, TXT, HTML, JSON, YAML, SQL, LOG
          </span>
        </div>

        {!loading && projects.length === 0 && (
          <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-xs flex items-center justify-between gap-2">
            <span>You need at least one project before indexing documents.</span>
            <Link href="/projects" className="font-semibold underline whitespace-nowrap">
              Go to Projects →
            </Link>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
          <input
            type="text"
            placeholder="Document Title (auto-filled from filename if blank)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="md:col-span-5 px-3.5 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
          />
          <input
            ref={fileInputRef}
            type="file"
            required
            accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv,.html,.htm,.json,.yaml,.yml,.log,.rst,.sql,.xml"
            onChange={(e) => handleFileChange(e.target.files?.[0] || null)}
            className="md:col-span-5 text-xs text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-slate-200 file:bg-slate-50 file:text-xs file:font-semibold file:text-slate-700 hover:file:bg-slate-100"
          />
          <button
            type="submit"
            disabled={uploading || !file || projects.length === 0}
            className="md:col-span-2 px-4 py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white shadow-md shadow-violet-600/20"
          >
            {uploading ? "Parsing..." : "Upload & Index"}
          </button>
        </div>
      </form>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search documents by title or filename..."
          className="w-full pl-9 pr-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 shadow-sm focus:outline-none focus:border-violet-500"
        />
      </div>

      {/* Document Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((doc) => (
          <div key={doc.id} className="apple-card p-5 flex flex-col justify-between gap-4">
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-violet-50 border border-violet-100 text-violet-600 flex items-center justify-center flex-shrink-0">
                    <FileText className="w-4 h-4" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-xs font-bold text-slate-900 truncate">{doc.title}</h3>
                    <p className="text-[11px] text-slate-400 truncate">{doc.filename}</p>
                  </div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-bold uppercase flex-shrink-0">
                  {doc.file_type || "file"}
                </span>
              </div>

              <div className="flex flex-wrap gap-1.5 text-[10px] font-medium text-slate-500">
                <span className="px-2 py-0.5 rounded-md bg-slate-50 border border-slate-100">
                  {doc.chunk_count ?? 0} Chunks
                </span>
                {doc.page_count ? (
                  <span className="px-2 py-0.5 rounded-md bg-slate-50 border border-slate-100">
                    {doc.page_count} Pages
                  </span>
                ) : null}
                {Array.isArray(doc.sheet_names) && doc.sheet_names.length > 0 ? (
                  <span className="px-2 py-0.5 rounded-md bg-slate-50 border border-slate-100">
                    Sheets: {doc.sheet_names.join(", ")}
                  </span>
                ) : null}
                <span className="px-2 py-0.5 rounded-md bg-slate-50 border border-slate-100">
                  {((doc.file_size_bytes || 0) / 1024).toFixed(1)} KB
                </span>
              </div>

              {doc.extracted_text && (
                <p className="text-[11px] text-slate-600 line-clamp-3 leading-relaxed bg-slate-50 p-2.5 rounded-xl border border-slate-100">
                  {doc.extracted_text}
                </p>
              )}

              <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                <span className="font-mono flex items-center gap-1">
                  <ShieldCheck className="w-3 h-3 text-emerald-600" />
                  SHA {doc.sha256_hash?.slice(0, 12)}...
                </span>
                <span>{doc.uploaded_by || "Member"}</span>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
              <button
                onClick={() => handleInspectChunks(doc)}
                className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200 flex items-center gap-1"
              >
                <Eye className="w-3 h-3" /> Chunks
              </button>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => handleDownload(doc)}
                  className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-slate-50 hover:bg-slate-100 text-slate-700 border border-slate-200 flex items-center gap-1"
                >
                  <Download className="w-3 h-3" /> Download
                </button>
                <button
                  onClick={() => handleDelete(doc)}
                  className="p-1.5 rounded-xl text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                  title="Delete Document"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
        ))}

        {!loading && filtered.length === 0 && (
          <div className="col-span-full apple-card p-12 text-center space-y-2">
            <FileText className="w-10 h-10 text-slate-300 mx-auto" />
            <h3 className="text-sm font-bold text-slate-800">No Documents Uploaded Yet</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Upload ADRs, runbooks, architecture PDFs, or spreadsheets above to parse and verify chunk evidence.
            </p>
          </div>
        )}
      </div>

      {/* Chunk Provenance Modal */}
      {selectedDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-3xl w-full max-h-[85vh] flex flex-col p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-slate-900">{selectedDoc.title} — Extracted Chunks</h3>
                <p className="text-[11px] text-slate-500">
                  SHA-256: <span className="font-mono">{selectedDoc.sha256_hash}</span>
                </p>
              </div>
              <button onClick={() => setSelectedDoc(null)} className="p-1 rounded-lg text-slate-400 hover:text-slate-700">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {loadingChunks ? (
                <div className="py-10 text-center text-xs text-slate-400">Loading document chunks...</div>
              ) : chunks.length === 0 ? (
                <div className="py-10 text-center text-xs text-slate-400">No parsed chunks found for this file.</div>
              ) : (
                chunks.map((c) => (
                  <div key={c.id || c.chunk_index} className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] font-bold uppercase text-violet-700">
                      <span>
                        Chunk #{Number(c.chunk_index) + 1}
                        {c.page_number ? ` • Page ${c.page_number}` : ""}
                        {c.sheet_name ? ` • Sheet ${c.sheet_name}` : ""}
                        {c.heading ? ` • ${c.heading}` : ""}
                      </span>
                      <span className="font-mono text-slate-400">SHA {c.sha256_hash?.slice(0, 12)}</span>
                    </div>
                    <p className="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed">{c.content}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
