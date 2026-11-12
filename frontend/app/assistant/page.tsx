"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { api, getStoredProjectId, resolveActiveProjectId, safeHref, setStoredProjectId } from "@/lib/api"
import {
  Sparkles,
  Send,
  ShieldCheck,
  AlertTriangle,
  ExternalLink,
  User,
  Clock,
  Info,
} from "lucide-react"

const SUGGESTED_PROMPTS = [
  "What critical architectural decisions exist in this project?",
  "What production risks and single points of failure were identified?",
  "Which services depend on external payment or infrastructure providers?",
  "What tasks remain unfinished or need reassignment?",
]

export default function AssistantPage() {
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [departingFocus, setDepartingFocus] = useState("")
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<any[]>([])

  useEffect(() => {
    const loadProjects = async () => {
      const projs = await api.getProjects().catch(() => [])
      const list = Array.isArray(projs) ? projs : []
      setProjects(list)
      setActiveProject(resolveActiveProjectId(list, getStoredProjectId()) || list[0]?.id || "")
    }
    loadProjects()
    const onProjectChange = () => {
      loadProjects()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [])

  const handleSend = async (questionText: string) => {
    const q = questionText.trim()
    if (!q || loading) return
    setInput("")
    const userMsg = { role: "user", content: q }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await api.queryAssistant(activeProject || "default", q, departingFocus.trim() || undefined)
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.answer,
          citations: res.citations || [],
          confidence: res.confidence ?? 0,
          confidence_breakdown: res.confidence_breakdown || null,
          is_grounded: Boolean(res.is_grounded),
          model_used: res.model_used || "",
          suggested_followups: res.suggested_followups || [],
        },
      ])
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: err.message || "Error querying AI project assistant.",
          citations: [],
          confidence: 0,
          is_grounded: false,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto h-[calc(100vh-4.5rem)] flex flex-col gap-4">
      {/* Header & Project Context Controls */}
      <div className="apple-card p-4 flex flex-col md:flex-row md:items-center justify-between gap-3 flex-shrink-0">
        <div>
          <h1 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-violet-600" />
            <span>Evidence-Grounded AI Project Assistant</span>
          </h1>
          <p className="text-[11px] text-slate-500">
            Hybrid pgvector + keyword RAG over your project&apos;s authorized sources. Refuses unsupported claims.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              if (pid !== "default") {
                setStoredProjectId(pid || undefined)
              }
            }}
            className="px-3 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-800"
          >
            {projects.length === 0 && <option value="">No project available</option>}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          <input
            type="text"
            value={departingFocus}
            onChange={(e) => setDepartingFocus(e.target.value)}
            placeholder="Optional focus (e.g. contributor name)"
            className="px-3 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-800 w-48 focus:outline-none focus:border-violet-500"
          />
        </div>
      </div>

      {/* Chat Conversation */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.length === 0 ? (
          <div className="apple-card p-10 text-center space-y-3 my-8">
            <div className="w-11 h-11 rounded-2xl bg-violet-50 border border-violet-200 text-violet-600 flex items-center justify-center mx-auto">
              <Sparkles className="w-5 h-5" />
            </div>
            <h2 className="text-base font-bold text-slate-900">Ask about architecture, decisions, risks, or ownership</h2>
            <p className="text-xs text-slate-500 max-w-md mx-auto leading-relaxed">
              Every response cites verifiable records with source author, verification state, and confidence breakdown — or declines cleanly when project evidence is missing.
            </p>
          </div>
        ) : (
          messages.map((m, idx) => (
            <div key={idx} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-3xl rounded-2xl p-4 space-y-3 ${
                  m.role === "user"
                    ? "bg-violet-600 text-white shadow-md shadow-violet-600/15"
                    : "apple-card text-slate-800 w-full"
                }`}
              >
                {m.role === "assistant" && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-100">
                    <span
                      className={`inline-flex items-center gap-1.5 text-[11px] font-bold uppercase ${
                        m.is_grounded ? "text-emerald-700" : "text-amber-700"
                      }`}
                    >
                      {m.is_grounded ? <ShieldCheck className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                      {m.is_grounded ? "Grounded in Evidence" : "Unsupported / Missing Evidence"}
                    </span>
                    <div className="flex items-center gap-2 text-[11px] text-slate-500">
                      <span>Confidence: <strong className="text-slate-900">{Math.round((m.confidence || 0) * 100)}%</strong></span>
                      {m.model_used && <span className="px-2 py-0.5 rounded bg-slate-100 text-[10px] font-mono">{m.model_used}</span>}
                    </div>
                  </div>
                )}

                <p className="text-xs leading-relaxed whitespace-pre-line">{m.content}</p>

                {/* Explainable Confidence Breakdown */}
                {m.role === "assistant" && m.confidence_breakdown?.explanation && (
                  <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-100 text-[11px] text-slate-600 flex items-start gap-2">
                    <Info className="w-3.5 h-3.5 text-violet-600 flex-shrink-0 mt-0.5" />
                    <span>{m.confidence_breakdown.explanation}</span>
                  </div>
                )}

                {/* Grounded Citations */}
                {m.role === "assistant" && Array.isArray(m.citations) && m.citations.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-slate-100">
                    <span className="text-[10px] font-bold uppercase text-slate-400 block">
                      Verifiable Citations ({m.citations.length})
                    </span>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {m.citations.map((c: any, ci: number) => {
                        const safeCitationUrl = safeHref(c.source_url, { allowRelative: true })
                        const isExt = Boolean(safeCitationUrl && /^https?:\/\//i.test(safeCitationUrl))
                        return (
                          <div key={ci} className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1.5 text-[11px]">
                            <div className="flex items-start justify-between gap-2">
                              <span className="font-bold text-slate-900 line-clamp-1">{c.source_title || "Project Record"}</span>
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-white border border-slate-200 font-semibold text-violet-700 flex-shrink-0">
                                {c.source_type}
                              </span>
                            </div>
                            <p className="text-slate-600 line-clamp-2 italic">&ldquo;{c.excerpt}&rdquo;</p>
                            <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400 pt-1">
                              <div className="flex items-center gap-2">
                                {c.source_author && (
                                  <span className="inline-flex items-center gap-0.5">
                                    <User className="w-2.5 h-2.5" /> {c.source_author}
                                  </span>
                                )}
                                {c.verification_status && (
                                  <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 font-semibold">
                                    {c.verification_status}
                                  </span>
                                )}
                              </div>
                              {safeCitationUrl && (
                                isExt ? (
                                  <a href={safeCitationUrl} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                                    Source <ExternalLink className="w-2.5 h-2.5" />
                                  </a>
                                ) : (
                                  <Link href={safeCitationUrl} className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
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

                {/* Suggested Follow-ups */}
                {m.role === "assistant" && Array.isArray(m.suggested_followups) && m.suggested_followups.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {m.suggested_followups.map((sf: string, sfi: number) => (
                      <button
                        key={sfi}
                        onClick={() => handleSend(sf)}
                        className="text-[11px] px-2.5 py-1 rounded-full bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200 transition-colors"
                      >
                        {sf}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {loading && (
          <div className="apple-card p-4 max-w-md text-xs text-slate-500 flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 animate-spin text-violet-600" />
            <span>Retrieving semantic vectors and verifying evidence...</span>
          </div>
        )}
      </div>

      {/* Suggested Prompts */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 flex-shrink-0">
        {SUGGESTED_PROMPTS.map((prompt, i) => (
          <button
            key={i}
            onClick={() => handleSend(prompt)}
            className="text-[11px] font-medium text-slate-600 hover:text-violet-700 bg-white hover:bg-violet-50 border border-slate-200 hover:border-violet-200 px-3 py-1.5 rounded-full whitespace-nowrap transition-colors shadow-sm"
          >
            {prompt}
          </button>
        ))}
      </div>

      {/* Input Box */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          handleSend(input)
        }}
        className="flex-shrink-0 relative"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about the project, decisions, architecture, or open issues..."
          className="w-full pl-4 pr-24 py-3 rounded-2xl text-xs bg-white border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 shadow-md shadow-slate-900/5"
        />
        <button
          type="submit"
          disabled={!input.trim() || loading}
          className="absolute right-2 top-1/2 -translate-y-1/2 px-4 py-1.5 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white text-xs font-semibold flex items-center gap-1.5 shadow-sm"
        >
          <span>Ask</span>
          <Send className="w-3.5 h-3.5" />
        </button>
      </form>
    </div>
  )
}
