"use client"

import { Suspense, useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { api, getStoredProjectId, isAllProjectsSelected, resolveActiveProjectId, safeHref, setStoredProjectId } from "@/lib/api"
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
  Search,
  Loader2,
  Webhook,
  Copy,
  X,
} from "lucide-react"

function parseTargetsFromConfig(provider: string, cfg: Record<string, any> = {}): string[] {
  const p = (provider || "").toLowerCase()
  if (p === "github") {
    if (Array.isArray(cfg.repos) && cfg.repos.length > 0) {
      return cfg.repos.map((s: any) => String(s).trim()).filter(Boolean)
    }
    return String(cfg.repo || cfg.target || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (p === "slack") {
    if (Array.isArray(cfg.channels) && cfg.channels.length > 0) {
      return cfg.channels.map((s: any) => String(s).trim()).filter(Boolean)
    }
    return String(cfg.channel_id || cfg.channel || cfg.target || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (Array.isArray(cfg.targets) && cfg.targets.length > 0) {
    return cfg.targets.map((s: any) => String(s).trim()).filter(Boolean)
  }
  return String(cfg.database_id || cfg.page_id || cfg.target || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
}

function buildProviderConfig(provider: string, baseCfg: Record<string, any>, rawText: string): Record<string, any> {
  const nextCfg = { ...(baseCfg || {}) }
  const targets = rawText
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
  const p = (provider || "").toLowerCase()

  if (p === "github") {
    delete nextCfg.repo
    delete nextCfg.repos
    delete nextCfg.target
    if (targets.length > 0) {
      nextCfg.repos = targets
      nextCfg.repo = targets.join(", ")
    }
    return nextCfg
  }
  if (p === "slack") {
    delete nextCfg.channel_id
    delete nextCfg.channels
    delete nextCfg.target
    if (targets.length > 0) {
      nextCfg.channels = targets
      nextCfg.channel_id = targets.join(", ")
    }
    return nextCfg
  }
  delete nextCfg.database_id
  delete nextCfg.page_id
  delete nextCfg.targets
  delete nextCfg.target
  if (targets.length > 0) {
    nextCfg.targets = targets
    nextCfg.database_id = targets.join(", ")
  }
  return nextCfg
}

function resourceNoun(provider?: string | null): string {
  const p = (provider || "").toLowerCase()
  if (p === "github") return "Repositories"
  if (p === "slack") return "Channels"
  if (p === "notion") return "Pages & Databases"
  return "Targets"
}

function ResourcePickerList({
  provider,
  resources,
  loading,
  error,
  hint,
  search,
  onSearchChange,
  valueText,
  onToggleValue,
  onRefresh,
  refreshLabel,
  refreshDisabled = false,
  emptyNotice,
}: {
  provider: string
  resources: any[]
  loading: boolean
  error: string
  hint: string | null
  search: string
  onSearchChange: (v: string) => void
  valueText: string
  onToggleValue: (val: string) => void
  onRefresh: () => void
  refreshLabel: string
  refreshDisabled?: boolean
  emptyNotice?: string
}) {
  const selected = new Set(
    valueText
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  )
  const filtered = resources.filter((r) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return (
      String(r.label || "").toLowerCase().includes(q) ||
      String(r.sublabel || "").toLowerCase().includes(q) ||
      String(r.value || "").toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-bold text-slate-700">
          Available {resourceNoun(provider)}{" "}
          {selected.size > 0 && (
            <span className="ml-1 px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 text-[10px]">
              {selected.size} selected
            </span>
          )}
        </span>
        <button
          type="button"
          disabled={loading || refreshDisabled}
          onClick={onRefresh}
          className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-100 text-violet-700 inline-flex items-center gap-1 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          {loading ? "Loading..." : refreshLabel}
        </button>
      </div>

      {emptyNotice && !error && resources.length === 0 && (
        <div className="p-2 rounded-lg bg-slate-100 border border-slate-200 text-[11px] text-slate-600">
          {emptyNotice}
        </div>
      )}

      {error && (
        <div className="p-2 rounded-lg bg-rose-50 border border-rose-200 text-[11px] text-rose-700 font-medium">
          {error}
        </div>
      )}

      {hint && !error && (
        <div className="p-2 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800">
          {hint}
        </div>
      )}

      {resources.length > 0 && (
        <>
          <div className="relative">
            <Search className="w-3 h-3 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={`Filter ${resourceNoun(provider).toLowerCase()}...`}
              className="w-full pl-7 pr-2.5 py-1.5 rounded-lg text-xs bg-white border border-slate-200 focus:outline-none focus:border-violet-500"
            />
          </div>

          <div className="max-h-44 overflow-y-auto space-y-1 pr-0.5">
            {filtered.length === 0 ? (
              <p className="text-[11px] text-slate-400 text-center py-3">No matches for &ldquo;{search}&rdquo;.</p>
            ) : (
              filtered.map((res) => {
                const val = String(res.value || res.id || "")
                const checked = selected.has(val)
                return (
                  <label
                    key={val}
                    className={`flex items-start gap-2.5 p-2 rounded-lg border cursor-pointer transition-colors ${
                      checked
                        ? "bg-violet-50 border-violet-300 text-slate-900"
                        : "bg-white border-slate-200 hover:bg-slate-50 text-slate-700"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleValue(val)}
                      className="mt-0.5 rounded border-slate-300 text-violet-600 focus:ring-violet-500"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold truncate">{res.label || val}</div>
                      {res.sublabel && <div className="text-[10px] text-slate-500 truncate">{res.sublabel}</div>}
                    </div>
                  </label>
                )
              })
            )}
          </div>
        </>
      )}
    </div>
  )
}

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
  const [message, setMessage] = useState(() => {
    const connected = searchParams.get("connected")
    if (connected) {
      return `${connected.toUpperCase()} connected via OAuth and verified successfully!`
    }
    return searchParams.get("oauth") === "connected"
      ? "OAuth source connected and verified successfully!"
      : ""
  })
  const [oauthProviders, setOauthProviders] = useState<Record<string, boolean>>({})
  const [error, setError] = useState(() => {
    const err = searchParams.get("oauth_error")
    return err ? `OAuth authorization error: ${err}` : ""
  })

  // Token / Connect Modal
  const [connectProvider, setConnectProvider] = useState<string | null>(null)
  const [connectAuthTab, setConnectAuthTab] = useState<"oauth" | "token">("oauth")
  const [reconnectTargetId, setReconnectTargetId] = useState<string | null>(null)
  const [connectName, setConnectName] = useState("")
  const [connectToken, setConnectToken] = useState("")
  const [connectConfigVal, setConnectConfigVal] = useState("")
  const [connectResources, setConnectResources] = useState<any[]>([])
  const [loadingConnectResources, setLoadingConnectResources] = useState(false)
  const [connectResourceError, setConnectResourceError] = useState("")
  const [connectResourceHint, setConnectResourceHint] = useState<string | null>(null)
  const [connectResourceSearch, setConnectResourceSearch] = useState("")
  const [connectModalError, setConnectModalError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // Config Modal
  const [configModal, setConfigModal] = useState<any>(null)
  const [editName, setEditName] = useState("")
  const [editConfigVal, setEditConfigVal] = useState("")
  const [editSyncInterval, setEditSyncInterval] = useState<number>(0)
  const [configResources, setConfigResources] = useState<any[]>([])
  const [loadingConfigResources, setLoadingConfigResources] = useState(false)
  const [configResourceError, setConfigResourceError] = useState("")
  const [configResourceHint, setConfigResourceHint] = useState<string | null>(null)
  const [configResourceSearch, setConfigResourceSearch] = useState("")
  const [savingConfig, setSavingConfig] = useState(false)

  // Sync Events Drawer
  const [eventsModal, setEventsModal] = useState<any>(null)
  const [eventsList, setEventsList] = useState<any[]>([])
  const [loadingEvents, setLoadingEvents] = useState(false)

  // Webhook Modal
  const [webhookModal, setWebhookModal] = useState<any>(null)
  const [webhookInfo, setWebhookInfo] = useState<any>(null)
  const [loadingWebhook, setLoadingWebhook] = useState(false)
  const [rotatingWebhook, setRotatingWebhook] = useState(false)
  const [autoWebhookLoading, setAutoWebhookLoading] = useState(false)
  const [autoWebhookResults, setAutoWebhookResults] = useState<any[] | null>(null)
  const [copiedWebhook, setCopiedWebhook] = useState("")

  const openWebhookModal = async (integ: any) => {
    setWebhookModal(integ)
    setWebhookInfo(null)
    setAutoWebhookResults(null)
    setCopiedWebhook("")
    try {
      setLoadingWebhook(true)
      const info = await api.getWebhookConfig(integ.id)
      setWebhookInfo(info)
    } catch (err: any) {
      setError(err?.message || "Could not load webhook configuration.")
    } finally {
      setLoadingWebhook(false)
    }
  }

  const handleRotateWebhookSecret = async () => {
    if (!webhookModal) return
    try {
      setRotatingWebhook(true)
      const res = await api.generateWebhookSecret(webhookModal.id)
      setWebhookInfo(res)
    } catch (err: any) {
      setError(err?.message || "Failed to generate webhook secret.")
    } finally {
      setRotatingWebhook(false)
    }
  }

  const handleRegisterAutoWebhook = async () => {
    if (!webhookModal || autoWebhookLoading) return
    try {
      setAutoWebhookLoading(true)
      setError("")
      const res = await api.registerAutoWebhook(webhookModal.id)
      if (res?.webhook_url || res?.webhook_secret) {
        setWebhookInfo((prev: any) => ({
          ...(prev || {}),
          ...res,
          webhook_secret: res.webhook_secret || prev?.webhook_secret,
        }))
      }
      setAutoWebhookResults(Array.isArray(res?.results) ? res.results : [])
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err?.message || "Auto-webhook registration failed.")
    } finally {
      setAutoWebhookLoading(false)
    }
  }

  // Action busy & inline delete confirmation trackers
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const callbackIntegIdRef = useRef<string | null>(searchParams.get("integration_id"))

  const fetchConfigResources = useCallback(async (integrationId: string) => {
    try {
      setLoadingConfigResources(true)
      setConfigResourceError("")
      setConfigResourceHint(null)
      const res = await api.getIntegrationResources(integrationId)
      setConfigResources(Array.isArray(res?.resources) ? res.resources : [])
      setConfigResourceHint(res?.hint || null)
    } catch (err: any) {
      setConfigResources([])
      setConfigResourceError(err.message || "Could not load accessible resources.")
    } finally {
      setLoadingConfigResources(false)
    }
  }, [])

  const openConfigModal = useCallback(
    (integ: any) => {
      setConfigModal(integ)
      setEditName(integ.name || "")
      const targets = parseTargetsFromConfig(integ.provider, integ.config || {})
      setEditConfigVal(targets.join(", "))
      setEditSyncInterval(Number(integ.config?.sync_interval_minutes ?? 0))
      setConfigResources([])
      setConfigResourceSearch("")
      setConfigResourceError("")
      setConfigResourceHint(null)
      fetchConfigResources(integ.id)
    },
    [fetchConfigResources]
  )

  const loadAll = useCallback(
    async (pid?: string) => {
      try {
        setLoading(true)
        const allSelected = pid === undefined && isAllProjectsSelected()
        const storedPid = allSelected || pid === "" ? "" : pid !== undefined ? pid : getStoredProjectId()
        const [projs, integsRaw, caps] = await Promise.all([
          api.getProjects().catch(() => []),
          api.getIntegrations(storedPid || undefined).catch(() => []),
          api.getAuthCapabilities().catch(() => null),
        ])
        if (caps?.oauth_providers) setOauthProviders(caps.oauth_providers)
        const projList = Array.isArray(projs) ? projs : []
        setProjects(projList)
        const resolvedPid = allSelected || pid === "" ? "" : resolveActiveProjectId(projList, pid)
        setActiveProject(resolvedPid)

        let finalIntegs = Array.isArray(integsRaw) ? integsRaw : []
        if (resolvedPid && resolvedPid !== storedPid) {
          finalIntegs = await api.getIntegrations(resolvedPid).catch(() => [])
        }
        setIntegrations(finalIntegs)

        if (callbackIntegIdRef.current) {
          const targetId = callbackIntegIdRef.current
          let matched = finalIntegs.find((i: any) => i.id === targetId)
          if (!matched) {
            const allIntegs = await api.getIntegrations().catch(() => [])
            matched = Array.isArray(allIntegs) ? allIntegs.find((i: any) => i.id === targetId) : undefined
            if (matched?.project_id) {
              setActiveProject(matched.project_id)
              setStoredProjectId(matched.project_id)
              setIntegrations(allIntegs.filter((i: any) => i.project_id === matched.project_id))
            }
          }
          if (matched) {
            callbackIntegIdRef.current = null
            openConfigModal(matched)
          }
        }
      } finally {
        setLoading(false)
      }
    },
    [openConfigModal]
  )

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    const onProjectChange = () => {
      loadAll()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [loadAll])

  const targetProjectId = activeProject || projects[0]?.id || ""

  const handleOAuthConnect = async (provider: string) => {
    if (!targetProjectId) {
      setError("Create a project in Projects first before connecting a source.")
      return
    }
    try {
      setError("")
      setMessage("")
      const res = await api.getOAuthUrl(provider, targetProjectId)
      const safeUrl = safeHref(res?.authorize_url)
      if (safeUrl) {
        window.location.assign(safeUrl)
      }
    } catch (err: any) {
      setError(
        `${err.message || "OAuth app not configured yet."} You can still connect immediately using a verified API/Bot token below.`
      )
    }
  }

  const openTokenConnect = (provider: string, existingInteg?: any) => {
    if (!targetProjectId) {
      setError("Create a project in Projects first before connecting a source.")
      return
    }
    const meta = PROVIDER_CARDS.find((p) => p.key === provider)
    setConnectProvider(provider)
    setReconnectTargetId(existingInteg?.id || null)
    setConnectAuthTab(
      existingInteg || oauthProviders[provider] === false ? "token" : "oauth"
    )
    setConnectName(existingInteg?.name || meta?.title || `${provider.toUpperCase()} Connector`)
    setConnectToken("")
    setConnectConfigVal(
      existingInteg ? parseTargetsFromConfig(provider, existingInteg.config || {}).join(", ") : ""
    )
    setConnectResources([])
    setConnectResourceError("")
    setConnectResourceHint(null)
    setConnectResourceSearch("")
    setConnectModalError("")
  }

  const handleDiscoverForConnect = async () => {
    if (!connectProvider) return
    if (!connectToken.trim()) {
      setConnectResourceError("Enter your API / Bot Access Token first to fetch available targets.")
      return
    }
    try {
      setLoadingConnectResources(true)
      setConnectResourceError("")
      setConnectResourceHint(null)
      const res = await api.discoverIntegrationResources(connectProvider, connectToken.trim())
      setConnectResources(Array.isArray(res?.resources) ? res.resources : [])
      setConnectResourceHint(res?.hint || null)
    } catch (err: any) {
      setConnectResources([])
      setConnectResourceError(err.message || "Could not load available targets from provider.")
    } finally {
      setLoadingConnectResources(false)
    }
  }

  const toggleTargetValue = (currentText: string, setter: (v: string) => void, targetVal: string) => {
    const items = currentText
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
    if (items.includes(targetVal)) {
      setter(items.filter((i) => i !== targetVal).join(", "))
    } else {
      setter([...items, targetVal].join(", "))
    }
  }

  const handleTokenConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!connectProvider) return
    const config = buildProviderConfig(connectProvider, {}, connectConfigVal)

    try {
      setSubmitting(true)
      setError("")
      setMessage("")
      setConnectModalError("")
      if (reconnectTargetId) {
        await api.reconnectIntegration(reconnectTargetId, {
          credentials: connectToken.trim() ? { access_token: connectToken.trim() } : undefined,
          config,
        })
        setMessage(`${connectProvider.toUpperCase()} integration reconnected and verified.`)
      } else {
        await api.createIntegration({
          project_id: targetProjectId,
          provider: connectProvider,
          name: connectName.trim() || `${connectProvider.toUpperCase()} Integration`,
          auth_type: "token",
          credentials: connectToken.trim() ? { access_token: connectToken.trim() } : {},
          config,
        })
        setMessage(`${connectProvider.toUpperCase()} integration saved. Click "Sync Now" to ingest live records.`)
      }
      setConnectProvider(null)
      setReconnectTargetId(null)
      await loadAll(activeProject)
    } catch (err: any) {
      const msg = err.message || "Failed to connect integration."
      setConnectModalError(msg)
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleVerify = async (integ: any) => {
    try {
      setBusyId(integ.id)
      setError("")
      setMessage("")
      const res = await api.verifyIntegration(integ.id)
      if (res?.status === "error") {
        setError(res.message || `Verification failed for ${integ.name}.`)
      } else {
        const statusLabel = res?.auth_status || res?.status || "connected"
        setMessage(
          `Verified ${integ.name}: status=${statusLabel}${res?.connected_account ? ` (${res.connected_account})` : ""}`
        )
      }
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
      const count =
        res?.items_processed ??
        (res?.records_added ?? 0) + (res?.records_updated ?? 0) + (res?.records_skipped ?? 0)
      setMessage(res?.details?.message || res?.message || `Synced ${count} records from ${integ.name}.`)
      window.dispatchEvent(new Event("obsidian_pipeline_updated"))
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

  const saveConfigAndOptionallySync = async (andSync: boolean) => {
    if (!configModal) return
    const nextCfg = {
      ...buildProviderConfig(configModal.provider, configModal.config || {}, editConfigVal),
      sync_interval_minutes: editSyncInterval,
    }
    try {
      setSavingConfig(true)
      setError("")
      setMessage("")
      await api.updateIntegrationConfig(configModal.id, { name: editName.trim(), config: nextCfg })
      const targetInteg = configModal
      setConfigModal(null)
      if (andSync) {
        setBusyId(targetInteg.id)
        try {
          const syncRes = await api.triggerSync(targetInteg.id)
          const count =
            syncRes?.items_processed ??
            (syncRes?.records_added ?? 0) + (syncRes?.records_updated ?? 0) + (syncRes?.records_skipped ?? 0)
          setMessage(syncRes?.details?.message || `Configuration saved and synced ${count} records.`)
          window.dispatchEvent(new Event("obsidian_pipeline_updated"))
        } finally {
          setBusyId(null)
        }
      } else {
        setMessage("Configuration updated.")
      }
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Failed to update configuration.")
    } finally {
      setSavingConfig(false)
    }
  }

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    await saveConfigAndOptionallySync(false)
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

  const handleDelete = async (id: string, name: string) => {
    try {
      setConfirmDeleteId(null)
      setBusyId(id)
      await api.deleteIntegration(id)
      setMessage(`Deleted ${name}.`)
      await loadAll(activeProject)
    } catch (err: any) {
      setError(err.message || "Delete failed.")
    } finally {
      setBusyId(null)
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
            setStoredProjectId(pid)
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
          const matchingInteg = integrations.find(
            (i) =>
              i.provider === card.key &&
              i.status === "connected" &&
              (!activeProject || i.project_id === activeProject)
          )
          return (
            <div key={card.key} className="apple-card p-5 flex flex-col justify-between gap-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="w-10 h-10 rounded-xl bg-violet-50 border border-violet-100 text-violet-600 flex items-center justify-center">
                    <Icon className="w-5 h-5" />
                  </div>
                  {matchingInteg && (
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-[10px] font-semibold">
                      <CheckCircle2 className="w-3 h-3" />
                      Connected{matchingInteg.connected_account ? ` (@${matchingInteg.connected_account})` : ""}
                    </span>
                  )}
                </div>
                <h2 className="text-sm font-bold text-slate-900">{card.title}</h2>
                <p className="text-xs text-slate-500 leading-relaxed">{card.desc}</p>
              </div>
              <div className="flex flex-wrap gap-2 pt-2">
                {matchingInteg ? (
                  <>
                    <button
                      onClick={() => openConfigModal(matchingInteg)}
                      className="flex-1 px-3 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm"
                    >
                      Select {resourceNoun(card.key)}
                    </button>
                    <button
                      onClick={() => openTokenConnect(card.key)}
                      className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                    >
                      <KeyRound className="w-3.5 h-3.5" /> Add Token
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => handleOAuthConnect(card.key)}
                      className="flex-1 px-3 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm"
                    >
                      {oauthProviders[card.key] === false ? "OAuth Setup Required" : "OAuth Connect"}
                    </button>
                    <button
                      onClick={() => openTokenConnect(card.key)}
                      className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                    >
                      <KeyRound className="w-3.5 h-3.5" /> Connect Integration
                    </button>
                  </>
                )}
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
                    {(() => {
                      const targetList = parseTargetsFromConfig(integ.provider, integ.config || {})
                      return (
                        <div>
                          <strong className="text-slate-700">Target Scope:</strong>{" "}
                          {targetList.length > 0 ? (
                            targetList.join(", ")
                          ) : (
                            <span className="text-slate-500 italic">
                              Auto-discover accessible {resourceNoun(integ.provider).toLowerCase()} (click Config to pin)
                            </span>
                          )}
                        </div>
                      )
                    })()}
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
                        <Settings2 className="w-3 h-3" /> Select {resourceNoun(integ.provider).split(" ")[0]} / Config
                      </button>
                      <button
                        onClick={() => openWebhookModal(integ)}
                        className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1"
                      >
                        <Webhook className="w-3 h-3 text-violet-600" /> Webhook
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
                          onClick={() => openTokenConnect(integ.provider, integ)}
                          className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold text-violet-700 bg-violet-50 hover:bg-violet-100 border border-violet-200"
                        >
                          Reconnect
                        </button>
                      )}
                      {confirmDeleteId === integ.id ? (
                        <div className="inline-flex items-center gap-1">
                          <button
                            onClick={() => handleDelete(integ.id, integ.name)}
                            disabled={isBusy}
                            className="px-2 py-1 rounded-lg text-[10px] font-bold bg-rose-600 text-white hover:bg-rose-700"
                          >
                            Confirm?
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="px-1.5 py-1 rounded-lg text-[10px] font-semibold bg-slate-100 text-slate-600 hover:bg-slate-200"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(integ.id)}
                          className="p-1.5 rounded-xl text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                          title="Delete Connection"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
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
          <div className="apple-card max-w-lg w-full max-h-[90vh] overflow-y-auto p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 uppercase">
                {reconnectTargetId ? `Reconnect ${connectProvider}` : `Connect ${connectProvider}`}
              </h3>
              <button
                onClick={() => {
                  setConnectProvider(null)
                  setReconnectTargetId(null)
                }}
                className="text-slate-400 hover:text-slate-600 text-xs"
              >
                ✕ Close
              </button>
            </div>
            {connectModalError && (
              <div className="p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
                {connectModalError}
              </div>
            )}
            {(() => {
              const existingConnected = !reconnectTargetId
                ? integrations.find(
                    (i) =>
                      i.provider === connectProvider &&
                      i.status === "connected" &&
                      (!activeProject || i.project_id === activeProject)
                  )
                : null
              const supportsOauth = !reconnectTargetId && oauthProviders[connectProvider] !== false

              return (
                <>
                  {existingConnected && (
                    <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="text-emerald-900">
                        <strong>Already connected</strong>
                        {existingConnected.connected_account ? ` (@${existingConnected.connected_account})` : ""}. No API key needed to pick {resourceNoun(connectProvider).toLowerCase()}.
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setConnectProvider(null)
                          setReconnectTargetId(null)
                          openConfigModal(existingConnected)
                        }}
                        className="px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-emerald-600 hover:bg-emerald-700 text-white whitespace-nowrap"
                      >
                        Pick {resourceNoun(connectProvider)}
                      </button>
                    </div>
                  )}

                  {supportsOauth && (
                    <div className="grid grid-cols-2 gap-1 p-1 rounded-xl bg-slate-100 border border-slate-200">
                      <button
                        type="button"
                        onClick={() => setConnectAuthTab("oauth")}
                        className={`py-1.5 rounded-lg text-xs font-semibold transition-all ${
                          connectAuthTab === "oauth"
                            ? "bg-white text-violet-700 shadow-sm"
                            : "text-slate-600 hover:text-slate-900"
                        }`}
                      >
                        1-Click OAuth (Recommended)
                      </button>
                      <button
                        type="button"
                        onClick={() => setConnectAuthTab("token")}
                        className={`py-1.5 rounded-lg text-xs font-semibold transition-all ${
                          connectAuthTab === "token"
                            ? "bg-white text-slate-900 shadow-sm"
                            : "text-slate-600 hover:text-slate-900"
                        }`}
                      >
                        API / PAT Token
                      </button>
                    </div>
                  )}

                  {supportsOauth && connectAuthTab === "oauth" ? (
                    <div className="p-4 rounded-xl bg-violet-50/70 border border-violet-200 space-y-3">
                      <div className="text-xs text-slate-700 leading-relaxed">
                        Authorize <strong>TEAM OBSIDIAN</strong> securely with your{" "}
                        <span className="capitalize font-semibold">{connectProvider}</span> account via OAuth 2.0.
                        Right after authorization, your {resourceNoun(connectProvider).toLowerCase()} picker opens automatically — no manual API key required.
                      </div>
                      <div className="flex items-center justify-between gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => setConnectAuthTab("token")}
                          className="text-[11px] font-semibold text-slate-600 hover:text-slate-900 underline"
                        >
                          Use manual token instead
                        </button>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setConnectProvider(null)
                              setReconnectTargetId(null)
                            }}
                            className="px-3 py-1.5 rounded-xl text-xs text-slate-600 hover:bg-slate-100"
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const prov = connectProvider
                              setConnectProvider(null)
                              handleOAuthConnect(prov)
                            }}
                            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm"
                          >
                            Continue with {connectProvider.toUpperCase()} OAuth
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
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
                        <label className="text-xs font-semibold text-slate-700 block mb-1">API / Bot Access Token</label>
                        <div className="flex gap-2">
                          <input
                            type="password"
                            required={!reconnectTargetId}
                            value={connectToken}
                            onChange={(e) => setConnectToken(e.target.value)}
                            placeholder={PROVIDER_CARDS.find((p) => p.key === connectProvider)?.tokenPlaceholder}
                            className="flex-1 px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                          />
                          <button
                            type="button"
                            onClick={handleDiscoverForConnect}
                            disabled={loadingConnectResources || !connectToken.trim()}
                            className="px-3 py-2 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-800 whitespace-nowrap disabled:opacity-50"
                          >
                            {loadingConnectResources ? "Loading..." : `Fetch ${resourceNoun(connectProvider)}`}
                          </button>
                        </div>
                      </div>

                      <ResourcePickerList
                        provider={connectProvider}
                        resources={connectResources}
                        loading={loadingConnectResources}
                        error={connectResourceError}
                        hint={connectResourceHint}
                        search={connectResourceSearch}
                        onSearchChange={setConnectResourceSearch}
                        valueText={connectConfigVal}
                        onToggleValue={(val) => toggleTargetValue(connectConfigVal, setConnectConfigVal, val)}
                        onRefresh={handleDiscoverForConnect}
                        refreshLabel={connectResources.length > 0 ? "Refresh List" : `Load ${resourceNoun(connectProvider)}`}
                        refreshDisabled={!connectToken.trim()}
                        emptyNotice={
                          !connectToken.trim()
                            ? `Paste a Personal Access Token above and click Fetch ${resourceNoun(connectProvider)}, or switch to 1-Click OAuth.`
                            : undefined
                        }
                      />

                      <div>
                        <label className="text-xs font-semibold text-slate-700 block mb-1">
                          {PROVIDER_CARDS.find((p) => p.key === connectProvider)?.configLabel} (optional, comma-separated)
                        </label>
                        <input
                          type="text"
                          value={connectConfigVal}
                          onChange={(e) => setConnectConfigVal(e.target.value)}
                          placeholder={PROVIDER_CARDS.find((p) => p.key === connectProvider)?.configPlaceholder}
                          className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                        />
                      </div>
                      <div className="flex justify-end gap-2 pt-2">
                        <button
                          type="button"
                          onClick={() => {
                            setConnectProvider(null)
                            setReconnectTargetId(null)
                          }}
                          className="px-3 py-1.5 rounded-xl text-xs text-slate-600 hover:bg-slate-100"
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          disabled={submitting}
                          className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50"
                        >
                          {submitting ? "Connecting..." : reconnectTargetId ? "Reconnect & Verify" : "Save & Connect"}
                        </button>
                      </div>
                    </form>
                  )}
                </>
              )
            })()}
          </div>
        </div>
      )}

      {/* Config Modal */}
      {configModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full max-h-[90vh] overflow-y-auto p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-slate-900">Configure {configModal.name}</h3>
                <p className="text-[11px] text-slate-500">
                  Select which {resourceNoun(configModal.provider).toLowerCase()} to ingest for this project
                </p>
              </div>
              <button onClick={() => setConfigModal(null)} className="text-xs text-slate-400 hover:text-slate-600">
                ✕ Close
              </button>
            </div>
            <form onSubmit={handleSaveConfig} className="space-y-3.5">
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

              <ResourcePickerList
                provider={configModal.provider}
                resources={configResources}
                loading={loadingConfigResources}
                error={configResourceError}
                hint={configResourceHint}
                search={configResourceSearch}
                onSearchChange={setConfigResourceSearch}
                valueText={editConfigVal}
                onToggleValue={(val) => toggleTargetValue(editConfigVal, setEditConfigVal, val)}
                onRefresh={() => fetchConfigResources(configModal.id)}
                refreshLabel={configResources.length > 0 ? "Refresh List" : `Load ${resourceNoun(configModal.provider)}`}
              />

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  Target Scope (comma-separated, leave blank to auto-discover)
                </label>
                <input
                  type="text"
                  value={editConfigVal}
                  onChange={(e) => setEditConfigVal(e.target.value)}
                  placeholder={PROVIDER_CARDS.find((p) => p.key === configModal.provider)?.configPlaceholder}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  Automated Sync Cadence
                </label>
                <select
                  value={editSyncInterval}
                  onChange={(e) => setEditSyncInterval(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-800"
                >
                  <option value={0}>Manual / Webhook-only</option>
                  <option value={15}>Every 15 minutes</option>
                  <option value={60}>Hourly</option>
                  <option value={360}>Every 6 hours</option>
                  <option value={1440}>Daily</option>
                </select>
              </div>
              <div className="flex flex-wrap justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setConfigModal(null)}
                  className="px-3 py-1.5 rounded-xl text-xs text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingConfig}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-800 disabled:opacity-50"
                >
                  {savingConfig ? "Saving..." : "Save Config"}
                </button>
                <button
                  type="button"
                  disabled={savingConfig}
                  onClick={() => saveConfigAndOptionallySync(true)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50"
                >
                  {savingConfig ? "Syncing..." : "Save & Sync Now"}
                </button>
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
                eventsList.map((ev) => {
                  const eventTitle =
                    ev.details?.message || ev.title || String(ev.event_type || "sync_event").replace(/_/g, " ")
                  const eventTime = ev.timestamp || ev.created_at
                  const summaryText =
                    ev.error_message ||
                    ev.content ||
                    `Processed records: +${ev.records_added ?? 0} added, ${ev.records_updated ?? 0} updated, ${ev.records_skipped ?? 0} deduplicated`
                  return (
                    <div key={ev.id} className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold text-slate-900 truncate">{eventTitle}</span>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          <span
                            className={`text-[10px] px-2 py-0.5 rounded uppercase font-semibold border ${
                              ev.status === "error"
                                ? "bg-rose-50 text-rose-700 border-rose-200"
                                : "bg-emerald-50 text-emerald-700 border-emerald-200"
                            }`}
                          >
                            {ev.status || "ok"}
                          </span>
                          <span className="text-[10px] px-2 py-0.5 rounded bg-white border border-slate-200 uppercase font-semibold text-slate-600">
                            {ev.event_type}
                          </span>
                        </div>
                      </div>
                      <p className={`text-[11px] line-clamp-2 ${ev.error_message ? "text-rose-600 font-medium" : "text-slate-600"}`}>
                        {summaryText}
                      </p>
                      <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                        <span>
                          {ev.details?.provider ? `${String(ev.details.provider).toUpperCase()} • ` : ""}
                          {eventTime ? new Date(eventTime).toLocaleString() : ""}
                        </span>
                        {(() => {
                          const safeEventUrl = safeHref(ev.url)
                          return safeEventUrl ? (
                            <a href={safeEventUrl} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
                              Open Source <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          ) : null
                        })()}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* Realtime Webhook Modal */}
      {webhookModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="apple-card max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Webhook className="w-4 h-4 text-violet-600" />
                  <span>Realtime Signed Webhook — {webhookModal.name}</span>
                </h3>
                <p className="text-[11px] text-slate-500">
                  Receive live {webhookModal.provider} events &amp; trigger automatic Knowledge Drift detection
                </p>
              </div>
              <button onClick={() => setWebhookModal(null)} className="p-1 text-slate-400 hover:text-slate-700">
                <X className="w-4 h-4" />
              </button>
            </div>

            {loadingWebhook ? (
              <div className="py-8 text-center text-xs text-slate-400">Loading webhook endpoint...</div>
            ) : (
              <div className="space-y-3 text-xs">
                <div className="space-y-1">
                  <label className="font-semibold text-slate-700 block">Payload URL</label>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={webhookInfo?.webhook_url || ""}
                      className="flex-1 px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 font-mono text-[11px] text-slate-800"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (webhookInfo?.webhook_url) {
                          navigator.clipboard?.writeText(webhookInfo.webhook_url)
                          setCopiedWebhook("url")
                        }
                      }}
                      className="px-2.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold inline-flex items-center gap-1"
                    >
                      <Copy className="w-3 h-3" /> {copiedWebhook === "url" ? "Copied" : "Copy"}
                    </button>
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-700">HMAC Verification Header</span>
                    <code className="text-[11px] bg-white px-2 py-0.5 rounded border border-slate-200">
                      {webhookInfo?.signature_header || "X-Hub-Signature-256"}
                    </code>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-700">Signing Secret Status</span>
                    <span className={`font-semibold ${webhookInfo?.has_secret ? "text-emerald-700" : "text-amber-700"}`}>
                      {webhookInfo?.has_secret ? "Configured (Encrypted)" : "Not generated yet"}
                    </span>
                  </div>
                </div>

                {webhookInfo?.webhook_secret && (
                  <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 space-y-1.5">
                    <p className="font-bold text-emerald-800 text-[11px]">
                      New Signing Secret (copy now — stored encrypted, shown once):
                    </p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 px-2.5 py-1.5 rounded bg-white border border-emerald-200 font-mono text-[11px] break-all text-slate-900">
                        {webhookInfo.webhook_secret}
                      </code>
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard?.writeText(webhookInfo.webhook_secret)
                          setCopiedWebhook("secret")
                        }}
                        className="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold text-[11px]"
                      >
                        {copiedWebhook === "secret" ? "Copied" : "Copy"}
                      </button>
                    </div>
                  </div>
                )}

                {autoWebhookResults && autoWebhookResults.length > 0 && (
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1.5">
                    <div className="text-[11px] font-bold text-slate-700">Repository Webhook Registration Results:</div>
                    {autoWebhookResults.map((r: any, idx: number) => (
                      <div key={r.repo || idx} className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="font-mono text-slate-800 truncate">{r.repo}</span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                            r.status === "registered" || r.status === "already_exists"
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-rose-100 text-rose-700"
                          }`}
                        >
                          {r.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      disabled={rotatingWebhook}
                      onClick={handleRotateWebhookSecret}
                      className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50"
                    >
                      {rotatingWebhook
                        ? "Generating..."
                        : webhookInfo?.has_secret
                        ? "Rotate Secret"
                        : "Generate Secret"}
                    </button>
                    {webhookModal.provider === "github" && (
                      <button
                        type="button"
                        disabled={autoWebhookLoading}
                        onClick={handleRegisterAutoWebhook}
                        className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white disabled:opacity-50"
                      >
                        {autoWebhookLoading ? "Registering..." : "1-Click Register on GitHub"}
                      </button>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setWebhookModal(null)}
                    className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
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
