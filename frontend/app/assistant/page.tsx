"use client"

import { useCallback, useEffect, useRef, useState } from "react"
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
  MessageSquare,
  Plus,
  Trash2,
  Scale,
  HelpCircle,
  CheckCircle2,
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
  const [conversations, setConversations] = useState<any[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<any[]>([])
  const [promotingKey, setPromotingKey] = useState<string | null>(null)
  const [promotedNotice, setPromotedNotice] = useState<{ msgId: string; type: string; title: string } | null>(null)
  const [errorMsg, setErrorMsg] = useState("")
  const endRef = useRef<HTMLDivElement | null>(null)

  const refreshConversations = useCallback(async (pid: string) => {
    if (!pid) {
      setConversations([])
      return
    }
    try {
      const list = await api.getAssistantConversations(pid)
      setConversations(Array.isArray(list) ? list : [])
    } catch {
      setConversations([])
    }
  }, [])

  useEffect(() => {
    const loadProjects = async () => {
      const projs = await api.getProjects().catch(() => [])
      const list = Array.isArray(projs) ? projs : []
      setProjects(list)
      const resolved = resolveActiveProjectId(list, getStoredProjectId()) || list[0]?.id || ""
      setActiveProject(resolved)
      if (resolved) {
        refreshConversations(resolved)
      }
    }
    loadProjects()
    const onProjectChange = () => {
      loadProjects()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [refreshConversations])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages.length])

  const startNewThread = () => {
    setActiveConversationId(null)
    setMessages([])
    setPromotedNotice(null)
    setErrorMsg("")
  }

  const handleSelectConversation = async (convId: string) => {
    try {
      setErrorMsg("")
      const detail = await api.getAssistantConversation(convId)
      setActiveConversationId(detail.id)
      if (detail.departing_focus) {
        setDepartingFocus(detail.departing_focus)
      }
      setMessages(
        (detail.messages || []).map((m: any) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations || [],
          confidence: m.confidence,
          confidence_breakdown: m.confidence_breakdown,
          is_grounded: m.is_grounded,
          model_used: m.model_used,
          suggested_followups: m.suggested_followups || [],
        }))
      )
    } catch (err: any) {
      setErrorMsg(err?.message || "Could not load selected conversation thread.")
    }
  }

  const handleDeleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api.deleteAssistantConversation(convId)
      setConversations((prev) => prev.filter((c) => c.id !== convId))
      if (activeConversationId === convId) {
        startNewThread()
      }
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to delete conversation thread.")
    }
  }

  const sendQuestion = async (q?: string) => {
    const query = (q ?? input).trim()
    if (!query || loading) return
    if (!activeProject) {
      setErrorMsg("Select or create a project first before querying the assistant.")
      return
    }

    const tempAssistantId = `stream-${Date.now()}`
    setInput("")
    setErrorMsg("")
    setPromotedNotice(null)
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", content: query },
      {
        id: tempAssistantId,
        role: "assistant",
        content: "",
        streaming: true,
        citations: [],
        suggested_followups: [],
      },
    ])
    setLoading(true)

    try {
      let resolvedConvId = activeConversationId
      const res = await api.queryAssistantStream({
        projectId: activeProject,
        question: query,
        departingFocus: departingFocus.trim() || undefined,
        conversationId: activeConversationId || undefined,
        onMeta: (meta) => {
          if (meta?.conversation_id) {
            resolvedConvId = meta.conversation_id
            setActiveConversationId(meta.conversation_id)
          }
        },
        onToken: (chunk) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempAssistantId ? { ...m, content: (m.content || "") + chunk } : m
            )
          )
        },
      })

      const finalConvId = res?.conversation_id || resolvedConvId
      if (finalConvId) {
        setActiveConversationId(finalConvId)
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAssistantId
            ? {
                id: res?.message_id || tempAssistantId,
                role: "assistant",
                content: res?.answer || m.content,
                citations: res?.citations || [],
                confidence: res?.confidence ?? 0,
                confidence_breakdown: res?.confidence_breakdown,
                is_grounded: res?.is_grounded,
                model_used: res?.model_used,
                suggested_followups: res?.suggested_followups || [],
                streaming: false,
              }
            : m
        )
      )
      await refreshConversations(activeProject)
    } catch (err: any) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAssistantId
            ? {
                ...m,
                content: `Unable to verify answer: ${err?.message || "Backend request failed."}`,
                is_grounded: false,
                streaming: false,
              }
            : m
        )
      )
    } finally {
      setLoading(false)
    }
  }

  const handlePromote = async (msg: any, targetType: "decision" | "gap", idx: number) => {
    if (!activeProject || promotingKey) return
    const msgKey = `${msg.id || idx}-${targetType}`
    // Find nearest preceding user question for concise default title
    const priorUser = [...messages].slice(0, idx).reverse().find((m) => m.role === "user")
    const derivedTitle = (priorUser?.content || msg.content || "Assistant Finding")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 110)

    try {
      setPromotingKey(msgKey)
      setErrorMsg("")
      const res = await api.promoteAssistantInsight({
        project_id: activeProject,
        target_type: targetType,
        title: derivedTitle,
        content: msg.content,
        evidence_ids: (msg.citations || []).map((c: any) => c.evidence_id).filter(Boolean),
      })
      setPromotedNotice({
        msgId: msg.id || String(idx),
        type: targetType,
        title: res?.title || derivedTitle,
      })
    } catch (err: any) {
      setErrorMsg(err?.message || `Failed to promote finding to ${targetType}.`)
    } finally {
      setPromotingKey(null)
    }
  }

  return (
    <div className="p-6 max-w-[1440px] mx-auto flex flex-col gap-4 h-[calc(100vh-56px)]">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-violet-600" /> AI Knowledge Assistant
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Persistent multi-turn Hybrid RAG (pgvector + keyword) with streaming synthesis, citations &amp; 1-click ADR/Gap promotion.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              setStoredProjectId(pid)
              startNewThread()
              refreshConversations(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500"
          >
            {projects.length === 0 ? (
              <option value="">No projects found</option>
            ) : (
              projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))
            )}
          </select>

          <input
            type="text"
            value={departingFocus}
            onChange={(e) => setDepartingFocus(e.target.value)}
            placeholder="Focus employee (optional)"
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500 w-44"
          />

          <button
            type="button"
            onClick={startNewThread}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-violet-600 text-white hover:bg-violet-500 transition-colors shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> New Thread
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="px-3.5 py-2 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium flex-shrink-0">
          {errorMsg}
        </div>
      )}

      {/* Main Layout: Saved Threads Sidebar + Active Conversation */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Saved Threads */}
        <aside className="lg:col-span-3 bg-white border border-slate-200 rounded-2xl p-3 flex flex-col min-h-0 shadow-sm">
          <div className="flex items-center justify-between px-1.5 pb-2.5 border-b border-slate-100">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
              <MessageSquare className="w-3.5 h-3.5 text-violet-600" /> Saved Threads
            </span>
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600">
              {conversations.length}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto mt-2 space-y-1.5 pr-1">
            {conversations.length === 0 ? (
              <p className="text-[11px] text-slate-400 px-2 py-4 text-center">
                No saved conversations yet for this project. Ask a question to start a persisted thread.
              </p>
            ) : (
              conversations.map((conv) => {
                const isActive = activeConversationId === conv.id
                return (
                  <div
                    key={conv.id}
                    onClick={() => handleSelectConversation(conv.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") handleSelectConversation(conv.id)
                    }}
                    className={`group p-2.5 rounded-xl border text-left cursor-pointer transition-all flex items-start justify-between gap-2 ${
                      isActive
                        ? "bg-violet-50 border-violet-300 text-violet-900"
                        : "bg-slate-50/70 border-slate-100 hover:bg-white hover:border-slate-200 text-slate-700"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold truncate">{conv.title}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5 flex items-center gap-2">
                        <span>{conv.message_count} msgs</span>
                        {conv.departing_focus && <span className="truncate">• {conv.departing_focus}</span>}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => handleDeleteConversation(conv.id, e)}
                      className="opacity-70 group-hover:opacity-100 p-1 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                      title="Delete thread"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )
              })
            )}
          </div>
        </aside>

        {/* Chat Area */}
        <div className="lg:col-span-9 bg-white border border-slate-200 rounded-2xl flex flex-col min-h-0 shadow-sm overflow-hidden">
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center max-w-2xl mx-auto">
                <div className="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center text-violet-600 mb-4 border border-violet-200">
                  <Sparkles className="w-7 h-7" />
                </div>
                <h2 className="text-lg font-bold text-slate-900">Ask anything about project architecture &amp; handovers</h2>
                <p className="text-xs text-slate-500 mt-2 leading-relaxed">
                  Every answer streams live with multi-turn thread persistence and strict grounding in ingested GitHub PRs, Slack threads, Notion pages, and documents.
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-6 w-full">
                  {SUGGESTED_PROMPTS.map((p, idx) => (
                    <button
                      key={idx}
                      onClick={() => sendQuestion(p)}
                      className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 hover:bg-violet-50 hover:border-violet-200 text-left text-xs text-slate-700 font-medium transition-all"
                    >
                      &ldquo;{p}&rdquo;
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, idx) => {
                const msgId = m.id || String(idx)
                return (
                  <div key={msgId} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                    {m.role === "user" ? (
                      <div className="bg-violet-600 text-white px-4 py-2.5 rounded-2xl rounded-br-sm max-w-[75%] text-xs font-medium shadow-sm">
                        {m.content}
                      </div>
                    ) : (
                      <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-bl-sm p-5 max-w-[92%] space-y-4 shadow-sm w-full">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            {m.streaming ? (
                              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-violet-700 bg-violet-100 px-2 py-0.5 rounded-full animate-pulse">
                                <Sparkles className="w-3.5 h-3.5" /> Streaming grounded answer...
                              </span>
                            ) : m.is_grounded ? (
                              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full">
                                <ShieldCheck className="w-3.5 h-3.5" /> Evidence Grounded ({Math.round((m.confidence || 0) * 100)}%)
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-rose-700 bg-rose-100 px-2 py-0.5 rounded-full">
                                <AlertTriangle className="w-3.5 h-3.5" /> Insufficient Project Evidence
                              </span>
                            )}
                            {m.model_used && <span className="text-[10px] text-slate-400 font-mono">{m.model_used}</span>}
                          </div>

                          {!m.streaming && m.content && (
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                disabled={Boolean(promotingKey)}
                                onClick={() => handlePromote(m, "decision", idx)}
                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white border border-slate-200 hover:border-violet-300 hover:bg-violet-50 text-[10px] font-semibold text-slate-700 transition-colors"
                              >
                                <Scale className="w-3 h-3 text-violet-600" />
                                {promotingKey === `${msgId}-decision` ? "Saving..." : "Save as ADR"}
                              </button>
                              <button
                                type="button"
                                disabled={Boolean(promotingKey)}
                                onClick={() => handlePromote(m, "gap", idx)}
                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white border border-slate-200 hover:border-amber-300 hover:bg-amber-50 text-[10px] font-semibold text-slate-700 transition-colors"
                              >
                                <HelpCircle className="w-3 h-3 text-amber-600" />
                                {promotingKey === `${msgId}-gap` ? "Logging..." : "Log Gap"}
                              </button>
                            </div>
                          )}
                        </div>

                        <div className="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
                          {m.content || (m.streaming ? "Searching project evidence..." : "")}
                        </div>

                        {promotedNotice && promotedNotice.msgId === msgId && (
                          <div className="px-3 py-2 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-[11px] flex items-center justify-between gap-2">
                            <span className="flex items-center gap-1.5 font-medium">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              Saved as {promotedNotice.type === "decision" ? "Decision (ADR)" : "Knowledge Gap"}: &ldquo;{promotedNotice.title}&rdquo;
                            </span>
                            <Link
                              href={promotedNotice.type === "decision" ? "/decisions" : "/gaps"}
                              className="font-bold underline hover:text-emerald-950 flex-shrink-0"
                            >
                              View {promotedNotice.type === "decision" ? "Decisions" : "Gaps"}
                            </Link>
                          </div>
                        )}

                        {m.confidence_breakdown && !m.streaming && (
                          <div className="p-3 rounded-xl bg-white border border-slate-200 text-[11px] text-slate-600 flex flex-wrap items-center gap-4">
                            <span className="font-semibold text-slate-700 flex items-center gap-1">
                              <Info className="w-3.5 h-3.5 text-violet-500" /> Confidence Breakdown:
                            </span>
                            <span>Citations: <strong>{m.confidence_breakdown.total_citations || 0}</strong></span>
                            <span>Verified: <strong>{m.confidence_breakdown.verified_citations || 0}</strong></span>
                            <span>Sources: <strong>{m.confidence_breakdown.distinct_sources || 0}</strong></span>
                          </div>
                        )}

                        {m.citations && m.citations.length > 0 && !m.streaming && (
                          <div className="pt-3 border-t border-slate-200 space-y-2">
                            <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                              Supporting Evidence Citations ({m.citations.length})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                              {m.citations.map((c: any, cIdx: number) => {
                                const safeCitationUrl = safeHref(c.source_url)
                                return (
                                  <div key={cIdx} className="p-3 rounded-xl bg-white border border-slate-200 text-xs space-y-1.5">
                                    <div className="flex items-center justify-between gap-2">
                                      <span className="font-semibold text-slate-800 truncate">
                                        [Evidence {cIdx + 1}] {c.source_title}
                                      </span>
                                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 font-semibold uppercase flex-shrink-0">
                                        {c.source_type}
                                      </span>
                                    </div>
                                    <p className="text-[11px] text-slate-600 line-clamp-2">&ldquo;{c.excerpt}&rdquo;</p>
                                    <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                                      <span className="flex items-center gap-1">
                                        <User className="w-3 h-3" /> {c.source_author || "Unknown"}
                                      </span>
                                      <span className="flex items-center gap-1">
                                        <Clock className="w-3 h-3" /> {c.source_timestamp ? String(c.source_timestamp).slice(0, 10) : ""}
                                      </span>
                                      {safeCitationUrl ? (
                                        <a href={safeCitationUrl} target="_blank" rel="noreferrer" className="text-violet-600 hover:underline flex items-center gap-0.5">
                                          Source <ExternalLink className="w-2.5 h-2.5" />
                                        </a>
                                      ) : (
                                        <Link href={`/evidence?search=${encodeURIComponent(c.source_title)}`} className="text-violet-600 hover:underline">
                                          Inspect
                                        </Link>
                                      )}
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )}

                        {m.suggested_followups && m.suggested_followups.length > 0 && !m.streaming && (
                          <div className="flex flex-wrap gap-2 pt-2">
                            {m.suggested_followups.map((f: string, fIdx: number) => (
                              <button
                                key={fIdx}
                                onClick={() => sendQuestion(f)}
                                className="px-3 py-1 rounded-full bg-white border border-slate-200 hover:border-violet-300 text-[11px] text-slate-600 hover:text-violet-700 transition-all"
                              >
                                &rarr; {f}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })
            )}
            <div ref={endRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              sendQuestion()
            }}
            className="p-4 border-t border-slate-200 bg-slate-50 flex items-center gap-3"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a technical question about architecture, risks, ownership, or handovers..."
              className="flex-1 px-4 py-2.5 rounded-xl bg-white border border-slate-200 text-xs text-slate-900 focus:outline-none focus:border-violet-500"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-semibold shadow-sm transition-all"
            >
              <Send className="w-3.5 h-3.5" /> {loading ? "Streaming..." : "Ask"}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
