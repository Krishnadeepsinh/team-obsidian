"use client"

import { Suspense, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import {
  Github,
  MessageSquare,
  FileText,
  RefreshCw,
  CheckCircle2,
  XCircle,
  KeyRound,
  Settings2,
  Trash2,
  Link2,
  History,
  ExternalLink,
  ShieldCheck,
  X,
} from "lucide-react"

const PROVIDER_CARDS = [
  {
    key: "github",
    title: "GitHub Repositories",
    desc: "Ingest pull requests, commits, review threads, issues, and ADRs with verified SHA-256 links.",
    icon: Github,
    configLabel: "Repository (owner/repo)",
    configPlaceholder: "my-org/backend-service",
    tokenPlaceholder: "ghp_... or fine-grained PAT",
  },
  {
    key: "slack",
    title: "Slack Channels",
    desc: "Ingest architectural discussions, incident threads, workarounds, and escalation history.",
    icon: MessageSquare,
    configLabel: "Channel ID(s)",
    configPlaceholder: "C0123456789",
    tokenPlaceholder: "xoxb-...",
  },
  {
    key: "notion",
    title: "Notion Workspaces",
    desc: "Ingest technical specs, runbooks, onboarding docs, and decision databases.",
    icon: FileText,
    configLabel: "Page ID / Database ID (optional)",
    configPlaceholder: "Notion UUID or leave empty for shared pages",
    tokenPlaceholder: "ntn_... or secret_...",
  },
]

function IntegrationsContent() {
  const searchParams = useSearchParams()
  const [integrations, setIntegrations] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState(() =>
    searchParams.get("oauth") === "connected"
      ? "OAuth source connected and verified successfully!"
      : ""
  )
  const [error, setError] = useState(() => {
    const err = searchParams.get("oauth_error")
    return err ? `OAuth authorization error: ${err}` : ""
  })

  // Token / Connect Modal
  const [connectProvider, setConnectProvider] = useState<string | null>(null)
  const [connectName, setConnectName] = useState("")
  const [connectToken, setConnectToken] = useState("")
  const [connectConfigVal, setConnectConfigVal] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // Config Modal
  const [configModal, setConfigModal] = useState<any>(null)
  const [editName, setEditName] = useState("")
  const [editConfigVal, setEditConfigVal] = useState("")

  // Sync Events Drawer
  const [eventsModal, setEventsModal] = useState<any>(null)
  const [eventsList, setEventsList] = useState<any[]>([])
  const [loadingEvents, setLoadingEvents] = useState(false)

  // Action busy tracker
  const [busyId, setBusyId] = useState<string | null>(null)

  const loadAll = async (pid?: string) => {
    try {
      setLoading(true)
      const storedPid =
        pid !== undefined
          ? pid
          : typeof window !== "undefined"
          ? localStorage.getItem("obsidian_active_project") || ""
          : ""
      const [projs, integs] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getIntegrations(storedPid || undefined).catch(() => []),
      ])
      setProjects(Array.isArray(projs) ? projs : [])
      const resolvedPid = storedPid || (Array.isArray(projs) && projs[0]?.id) || ""
      setActiveProject(resolvedPid)
      setIntegrations(Array.isArray(integs) ? integs : [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const targetProjectId = activeProject || projects[0]?.id || "default"

  const handleOAuthConnect = async (provider: string) => {
    try {
      setError("")
      setMessage("")
      const res = await api.getOAuthUrl(provider, targetProjectId)
      if (res?.authorize_url) {
        window.location.assign(res.authorize_url)
      }
    } catch (err: any) {
      setError(
        `${err.message || "OAuth app not configured yet."} You can still connect immediately using a verified API/Bot token below.`
      )
    }
  }

  const openTokenConnect = (provider: string) => {
    const meta = PROVIDER_CARDS.find((p) => p.key === provider)
    setConnectProvider(provider)
    setConnectName(meta?.title || `${provider.toUpperCase()} Connector`)
    setConnectToken("")
    setConnectConfigVal("")
  }

  const handleTokenConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!connectProvider) return
    const config: Record<string, any> = {}
    if (connectProvider === "github" && connectConfigVal.trim()) config.repo = connectConfigVal.trim()
    if (connectProvider === "slack" && connectConfigVal.trim()) config.channel_id = connectConfigVal.trim()
    if (connectProvider === "notion" && connectConfigVal.trim()) config.database_id = connectConfigVal.trim()

    try {
      setSubmitting(true)
      setError("")
      setMessage("")
      await api.createIntegration({
        project_id: targetProjectId,
        provider: connectProvider,
        name: connectName.trim() || `${connectProvider.toUpperCase()} Integration`,
        auth_type: "token",
        credentials: connectToken.trim() ? { access_token: connectToken.trim() } : {},
        config,
      })
      setConnectProvider(null)
      setMessage(`${connectProvider.toUpperCase()} integration saved. Click "Verify Auth" or "Sync Now" to ingest live records.`)
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Failed to connect integration.")
    } finally {
      setSubmitting(false)
    }
  }

  const handleVerify = async (integ: any) => {
    try {
      setBusyId(integ.id)
      setError("")
      const res = await api.verifyIntegration(integ.id)
      setMessage(`Verified ${integ.name}: status=${res.auth_status}${res.connected_account ? ` (${res.connected_account})` : ""}`)
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Verification failed — check token & scopes.")
    } finally {
      setBusyId(null)
    }
  }

  const handleSync = async (integ: any) => {
    try {
      setBusyId(integ.id)
      setError("")
      const res = await api.triggerSync(integ.id)
      setMessage(res.message || `Synced ${res.records_synced ?? 0} records from ${integ.name}.`)
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Synchronization failed.")
    } finally {
      setBusyId(null)
    }
  }

  const handleViewEvents = async (integ: any) => {
    setEventsModal(integ)
    setEventsList([])
    setLoadingEvents(true)
    try {
      const evs = await api.getIntegrationEvents(integ.id)
      setEventsList(Array.isArray(evs) ? evs : [])
    } catch (err: any) {
      setError(err.message || "Could not load sync history.")
    } finally {
      setLoadingEvents(false)
    }
  }

  const openConfigModal = (integ: any) => {
    setConfigModal(integ)
    setEditName(integ.name || "")
    const cfg = integ.config || {}
    setEditConfigVal(cfg.repo || cfg.channel_id || cfg.database_id || cfg.page_id || "")
  }

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!configModal) return
    const nextCfg = { ...(configModal.config || {}) }
    if (configModal.provider === "github") nextCfg.repo = editConfigVal.trim()
    else if (configModal.provider === "slack") nextCfg.channel_id = editConfigVal.trim()
    else nextCfg.database_id = editConfigVal.trim()
    try {
      await api.updateIntegrationConfig(configModal.id, { name: editName.trim(), config: nextCfg })
      setConfigModal(null)
      setMessage("Configuration updated.")
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Failed to update configuration.")
    }
  }

  const handleDisconnect = async (integ: any) => {
    try {
      setBusyId(integ.id)
      await api.disconnectIntegration(integ.id)
      setMessage(`Disconnected ${integ.name}.`)
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Disconnect failed.")
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (integ: any) => {
    if (!confirm(`Delete integration "${integ.name}"?`)) return
    try {
      await api.deleteIntegration(integ.id)
      setMessage(`Deleted ${integ.name}.`)
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Delete failed.")
    }
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Connected Knowledge Sources</h1>
          <p className="text-xs text-slate-500 mt-1">
            Authenticate GitHub, Slack, and Notion via OAuth or verified tokens for incremental, deduplicated ingestion.
          </p>
        </div>

        <select
          value={activeProject}
          onChange={(e) => {
            const pid = e.target.value
            setActiveProject(pid)
            if (typeof window !== "undefined") {
              if (pid) localStorage.setItem("obsidian_active_project", pid)
              else localStorage.removeItem("obsidian_active_project")
              window.dispatchEvent(new Event("obsidian_project_changed"))
            }
            loadAll(pid)
          }}
          className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm focus:outline-none focus:border-violet-500"
        >
          <option value="">All Accessible Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">{error}</div>
      )}
      {message && (
        <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" /> {message}
        </div>
      )}

      {/* Provider Catalog */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {PROVIDER_CARDS.map((card) => {
          const Icon = card.icon
          return (
            <div key={card.key} className="apple-card p-5 flex flex-col justify-between gap-4">
              <div className="space-y-2">
                <div className="w-10 h-10 rounded-xl bg-violet-50 border border-violet-100 text-violet-600 flex items-center justify-center">
                  <Icon className="w-5 h-5" />
                </div>
                <h2 className="text-sm font-bold text-slate-900">{card.title}</h2>
                <p className="text-xs text-slate-500 leading-relaxed">{card.desc}</p>
              </div>
              <div className="flex flex-wrap gap-2 pt-2">
                <button
                  onClick={() => handleOAuthConnect(card.key)}
                  className="flex-1 px-3 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm"
                >
                  OAuth Connect
                </button>
                <button
                  onClick={() => openTokenConnect(card.key)}
                  className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                >
                  <KeyRound className="w-3.5 h-3.5" /> Connect Integration
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Configured Integrations List */}
      <div className="space-y-3">
        <h2 className="text-sm font-bold text-slate-900">Configured Connections ({integrations.length})</h2>

        {!loading && integrations.length === 0 ? (
          <div className="apple-card p-10 text-center space-y-2">
            <Link2 className="w-9 h-9 text-slate-300 mx-auto" />
            <p className="text-sm font-bold text-slate-800">No Sources Connected Yet</p>
            <p className="text-xs text-slate-500 max-w-md mx-auto">
              Use OAuth Connect or API Token above to authenticate GitHub, Slack, or Notion for your selected project.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {integrations.map((integ) => {
              const isConn = integ.status === "connected"
              const isBusy = busyId === integ.id
              return (
                <div key={integ.id} className="apple-card p-5 space-y-3.5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-1.5 mb-1">
                        <span className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-bold uppercase">
                          {integ.provider}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-semibold border ${
                            isConn
                              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                              : "bg-rose-50 text-rose-700 border-rose-200"
                          }`}
                        >
                          {isConn ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                          {integ.status}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 font-semibold">
                          Auth: {integ.auth_status || "unverified"}
                        </span>
                      </div>
                      <h3 className="text-sm font-bold text-slate-900">{integ.name}</h3>
                    </div>

                    <div className="text-right text-[11px] text-slate-500">
                      <p className="font-bold text-slate-900">{integ.items_synced ?? 0} records</p>
                      <p>{integ.last_sync ? new Date(integ.last_sync).toLocaleString() : "Never synced"}</p>
                    </div>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 text-[11px] space-y-1 text-slate-600">
                    <div>
                      <strong className="text-slate-700">Account:</strong>{" "}
                      {integ.connected_account || "Not yet verified"}
                    </div>
                    {integ.config && Object.keys(integ.config).length > 0 && (
                      <div>
                        <strong className="text-slate-700">Target Scope:</strong>{" "}
                        {integ.config.repo || integ.config.channel_id || integ.config.database_id || JSON.stringify(integ.config)}
                      </div>
                    )}
                    {Array.isArray(integ.scopes) && integ.scopes.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-0.5">
                        {integ.scopes.map((sc: string) => (
                          <span key={sc} className="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-[10px] font-mono">
                            {sc}
                          </span>
                        ))}
                      </div>
                    )}
                    {integ.error_message && (
                      <div className="text-rose-600 font-medium pt-1">Error: {integ.error_message}</div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-100">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        disabled={isBusy}
                        onClick={() => handleVerify(integ)}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200 flex items-center gap-1"
                      >
                        <ShieldCheck className="w-3 h-3" /> Verify Auth
                      </button>
                      <button
                        disabled={isBusy}
                        onClick={() => handleSync(integ)}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-violet-600 hover:bg-violet-700 text-white flex items-center gap-1"
                      >
                        <RefreshCw className={`w-3 h-3 ${isBusy ? "animate-spin" : ""}`} /> Sync Now
                      </button>
                      <button
                        onClick={() => handleViewEvents(integ)}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                      >
                        <History className="w-3 h-3" /> Events
                      </button>
                      <button
                        onClick={() => openConfigModal(integ)}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                      >
                        <Settings2 className="w-3 h-3" /> Config
                      </button>
                    </div>

                    <div className="flex items-center gap-1.5">
                      {isConn ? (
                        <button
                          onClick={() => handleDisconnect(integ)}
                          className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200"
                        >
                          Disconnect
                        </button>
                      ) : (
                        <button
                          onClick={() => openTokenConnect(integ.provider)}
                          className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold text-violet-700 bg-violet-50 hover:bg-violet-100 border border-violet-200"
                        >
                          Reconnect
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(integ)}
                        className="p-1.5 rounded-xl text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                        title="Delete Connection"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Token Connect Modal */}
      {connectProvider && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 uppercase">Connect {connectProvider}</h3>
              <button onClick={() => setConnectProvider(null)} className="text-slate-400 hover:text-slate-600 text-xs">
                ✕ Close
              </button>
            </div>
            <form onSubmit={handleTokenConnect} className="space-y-3.5">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Connection Label</label>
                <input
                  type="text"
                  required
                  value={connectName}
                  onChange={(e) => setConnectName(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  {PROVIDER_CARDS.find((p) => p.key === connectProvider)?.configLabel}
                </label>
                <input
                  type="text"
                  value={connectConfigVal}
                  onChange={(e) => setConnectConfigVal(e.target.value)}
                  placeholder={PROVIDER_CARDS.find((p) => p.key === connectProvider)?.configPlaceholder}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">API / Bot Access Token</label>
                <input
                  type="password"
                  value={connectToken}
                  onChange={(e) => setConnectToken(e.target.value)}
                  placeholder={PROVIDER_CARDS.find((p) => p.key === connectProvider)?.tokenPlaceholder}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setConnectProvider(null)} className="px-3 py-1.5 rounded-xl text-xs text-slate-600 hover:bg-slate-100">
                  Cancel
                </button>
                <button type="submit" disabled={submitting} className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white">
                  {submitting ? "Connecting..." : "Save & Connect"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Config Modal */}
      {configModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">Configure {configModal.name}</h3>
              <button onClick={() => setConfigModal(null)} className="text-xs text-slate-400">✕ Close</button>
            </div>
            <form onSubmit={handleSaveConfig} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Display Name</label>
                <input
                  type="text"
                  required
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">Target Scope (Repo / Channel / Database ID)</label>
                <input
                  type="text"
                  value={editConfigVal}
                  onChange={(e) => setEditConfigVal(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setConfigModal(null)} className="px-3 py-1.5 rounded-xl text-xs text-slate-600">Cancel</button>
                <button type="submit" className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 text-white">Save Config</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Sync Events Modal */}
      {eventsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-2xl w-full max-h-[80vh] flex flex-col p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-slate-900">{eventsModal.name} — Sync History &amp; Records</h3>
                <p className="text-[11px] text-slate-500">Deduplicated normalized source items</p>
              </div>
              <button onClick={() => setEventsModal(null)} className="p-1 text-slate-400 hover:text-slate-700">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2.5 pr-1">
              {loadingEvents ? (
                <div className="py-10 text-center text-xs text-slate-400">Loading ingested records...</div>
              ) : eventsList.length === 0 ? (
                <div className="py-10 text-center text-xs text-slate-400">No source events imported yet. Click &ldquo;Sync Now&rdquo;.</div>
              ) : (
                eventsList.map((ev) => (
                  <div key={ev.id} className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900 truncate">{ev.title}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-white border border-slate-200 uppercase font-semibold text-slate-600">
                        {ev.event_type}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-600 line-clamp-2">{ev.content}</p>
                    <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                      <span>{ev.author || "Contributor"} • {ev.created_at ? new Date(ev.created_at).toLocaleString() : ""}</span>
                      {ev.url && (
                        <a href={ev.url} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                          Open Source <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      )}
                    </div>
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

export default function IntegrationsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-xs text-slate-400">Loading integrations...</div>}>
      <IntegrationsContent />
    </Suspense>
  )
}
