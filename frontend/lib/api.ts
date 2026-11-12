// TEAM OBSIDIAN: Enterprise Frontend API Client

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"

/**
 * Sanitize dynamic URLs before rendering them inside <a> or Next.js <Link> href attributes.
 * Blocks javascript:, data:, vbscript:, and protocol-relative (//) external redirects.
 */
export function safeHref(
  rawUrl?: string | null,
  options: { allowRelative?: boolean } = {}
): string | null {
  if (!rawUrl || typeof rawUrl !== "string") return null
  const trimmed = rawUrl.trim()
  if (!trimmed) return null
  if (options.allowRelative && trimmed.startsWith("/") && !trimmed.startsWith("//")) {
    return trimmed
  }
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.toString()
    }
  } catch {
    return null
  }
  return null
}

function getAuthHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("obsidian_token") : null
  const headers: Record<string, string> = { ...extra }
  if (token && !headers["Authorization"]) {
    headers["Authorization"] = `Bearer ${token}`
  }
  return headers
}

async function performFetchWithRetry(url: string, options: RequestInit): Promise<Response> {
  const retryableStatuses = new Set([502, 503, 504])
  const retryDelaysMs = [2000, 4000, 6000]
  const emitWaking = (waking: boolean, attempt: number) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("obsidian_api_waking", { detail: { waking, attempt } }))
    }
  }
  for (let attempt = 0; attempt <= retryDelaysMs.length; attempt++) {
    try {
      const res = await fetch(url, options)
      if (attempt < retryDelaysMs.length && retryableStatuses.has(res.status)) {
        emitWaking(true, attempt + 1)
        await new Promise((r) => setTimeout(r, retryDelaysMs[attempt]))
        continue
      }
      if (attempt > 0) emitWaking(false, attempt)
      return res
    } catch (err: any) {
      const isNetworkError =
        err instanceof TypeError ||
        (typeof err?.message === "string" && err.message.toLowerCase().includes("failed to fetch"))
      if (attempt < retryDelaysMs.length && isNetworkError) {
        emitWaking(true, attempt + 1)
        await new Promise((r) => setTimeout(r, retryDelaysMs[attempt]))
        continue
      }
      emitWaking(false, attempt)
      if (isNetworkError) {
        throw new Error(
          `Cannot reach TEAM OBSIDIAN API (${API_BASE}). If the backend just woke from cold start, please retry in a few seconds.`
        )
      }
      throw err
    }
  }
  emitWaking(false, 0)
  throw new Error(`Cannot reach TEAM OBSIDIAN API (${API_BASE}).`)
}

export function warmUpBackendHealth(): void {
  if (typeof window === "undefined") return
  const rootUrl = API_BASE.replace(/\/api\/v1\/?$/, "")
  fetch(`${rootUrl}/health`, { method: "GET", cache: "no-store" }).catch(() => {})
}

async function fetchJson<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData
  const baseHeaders: Record<string, string> = isFormData ? {} : { "Content-Type": "application/json" }
  const headers = getAuthHeaders({
    ...baseHeaders,
    ...((options.headers as Record<string, string>) || {}),
  })

  const res = await performFetchWithRetry(url, {
    ...options,
    headers,
    cache: "no-store",
  })

  if (!res.ok) {
    if (
      res.status === 401 &&
      typeof window !== "undefined" &&
      !endpoint.startsWith("/auth/login") &&
      !endpoint.startsWith("/auth/register") &&
      !endpoint.startsWith("/auth/forgot-password") &&
      !endpoint.startsWith("/auth/reset-password")
    ) {
      localStorage.removeItem("obsidian_token")
      localStorage.removeItem("obsidian_user")
      window.dispatchEvent(new Event("obsidian_session_expired"))
    }
    let detail = res.statusText
    try {
      const parsed = await res.json()
      if (Array.isArray(parsed?.detail)) {
        detail = parsed.detail
          .map((d: any) => d?.msg || (typeof d === "string" ? d : JSON.stringify(d)))
          .join("; ")
      } else if (parsed?.detail && typeof parsed.detail === "object") {
        detail = JSON.stringify(parsed.detail)
      } else {
        detail = parsed?.detail || parsed?.message || JSON.stringify(parsed)
      }
    } catch {
      const errText = await res.text().catch(() => "")
      if (errText) detail = errText
    }
    throw new Error(detail || `API error ${res.status}`)
  }
  return (await res.json()) as T
}

async function downloadAuthFile(endpoint: string, fallbackFilename: string): Promise<void> {
  const res = await performFetchWithRetry(`${API_BASE}${endpoint}`, {
    headers: getAuthHeaders(),
    cache: "no-store",
  })
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`)
  }
  const blob = await res.blob()
  const disposition = res.headers.get("content-disposition") || ""
  const match = disposition.match(/filename="?([^"]+)"?/i)
  const filename = match?.[1] || fallbackFilename

  const url = window.URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export const ALL_PROJECTS_VALUE = "__all__"

export function isAllProjectsSelected(): boolean {
  if (typeof window === "undefined") return false
  return (
    localStorage.getItem("obsidian_active_project_id") === ALL_PROJECTS_VALUE ||
    localStorage.getItem("obsidian_active_project") === ALL_PROJECTS_VALUE
  )
}

export function getStoredProjectId(): string {
  if (typeof window === "undefined") return ""
  const raw =
    localStorage.getItem("obsidian_active_project_id") ||
    localStorage.getItem("obsidian_active_project") ||
    ""
  return raw === ALL_PROJECTS_VALUE ? "" : raw
}

export function setStoredProjectId(pid?: string, dispatch = true): void {
  if (typeof window === "undefined") return
  if (pid === "") {
    localStorage.setItem("obsidian_active_project_id", ALL_PROJECTS_VALUE)
    localStorage.setItem("obsidian_active_project", ALL_PROJECTS_VALUE)
  } else if (pid) {
    localStorage.setItem("obsidian_active_project_id", pid)
    localStorage.setItem("obsidian_active_project", pid)
  } else {
    localStorage.removeItem("obsidian_active_project_id")
    localStorage.removeItem("obsidian_active_project")
  }
  if (dispatch) {
    window.dispatchEvent(new Event("obsidian_project_changed"))
  }
}

export function resolveActiveProjectId(projects: any[], preferredId?: string): string {
  const list = Array.isArray(projects) ? projects : []
  if (preferredId === "" || preferredId === ALL_PROJECTS_VALUE) {
    return ""
  }
  if (preferredId === undefined && isAllProjectsSelected()) {
    return ""
  }
  const candidate = (preferredId !== undefined ? preferredId : getStoredProjectId()).trim()
  if (candidate && candidate !== "default" && candidate !== ALL_PROJECTS_VALUE && list.some((p) => p?.id === candidate)) {
    return candidate
  }
  const fallbackId = list[0]?.id || ""
  if (typeof window !== "undefined") {
    setStoredProjectId(fallbackId || undefined, false)
  }
  return fallbackId
}

function persistAuthSession(res: any): void {
  if (typeof window !== "undefined" && res?.access_token) {
    localStorage.setItem("obsidian_token", res.access_token)
    if (res.user) localStorage.setItem("obsidian_user", JSON.stringify(res.user))
    if (res.active_project_id) {
      setStoredProjectId(res.active_project_id, false)
    }
  }
}

export const api = {
  // Auth & Multi-Tenant Context
  getAuthCapabilities: async () => fetchJson<any>("/auth/capabilities"),
  login: async (credentials: { email: string; password: string }) => {
    const res = await fetchJson<any>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    })
    persistAuthSession(res)
    return res
  },
  register: async (userData: any) => {
    const res = await fetchJson<any>("/auth/register", {
      method: "POST",
      body: JSON.stringify(userData),
    })
    persistAuthSession(res)
    return res
  },
  logout: async () => {
    return fetchJson<any>("/auth/logout", { method: "POST" }).catch(() => ({}))
  },
  getUserContext: async () => {
    return fetchJson<any>("/auth/me/context")
  },
  updateProfile: async (data: { name?: string; title?: string; department?: string; avatar_url?: string }) => {
    return fetchJson<any>("/auth/me", {
      method: "PUT",
      body: JSON.stringify(data),
    })
  },
  changePassword: async (current_password: string, new_password: string) => {
    const res = await fetchJson<any>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    })
    persistAuthSession(res)
    return res
  },
  forgotPassword: async (email: string) => {
    return fetchJson<any>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    })
  },
  resetPassword: async (data: { email: string; reset_token: string; new_password: string }) => {
    return fetchJson<any>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify(data),
    })
  },

  // Workspaces & Organizations
  getWorkspaces: async () => fetchJson<any[]>("/workspaces"),
  createWorkspace: async (data: { name: string; org_id?: string; description?: string }) =>
    fetchJson<any>("/workspaces", { method: "POST", body: JSON.stringify(data) }),
  getOrganizations: async () => fetchJson<any[]>("/workspaces/organizations"),
  createOrganization: async (data: { name: string }) =>
    fetchJson<any>("/workspaces/organizations", { method: "POST", body: JSON.stringify(data) }),
  inviteOrgMember: async (orgId: string, email: string, role?: string) =>
    fetchJson<any>(`/workspaces/organizations/${orgId}/invite`, {
      method: "POST",
      body: JSON.stringify({ email, role: role || "developer" }),
    }),

  // Dashboard
  getStats: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any>(`/dashboard/stats${q}`)
  },
  getActivity: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/dashboard/activity${q}`)
  },

  // Projects
  getProjects: async () => fetchJson<any[]>("/projects"),
  getProject: async (id: string) => fetchJson<any>(`/projects/${id}`),
  createProject: async (data: any) =>
    fetchJson<any>("/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: async (id: string, data: any) =>
    fetchJson<any>(`/projects/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProject: async (id: string) =>
    fetchJson<any>(`/projects/${id}`, { method: "DELETE" }),
  getProjectTimeline: async (id: string) => fetchJson<any[]>(`/projects/${id}/timeline`),
  getProjectMembers: async (id: string) => fetchJson<any[]>(`/projects/${id}/members`),
  addProjectMember: async (projectId: string, data: { email?: string; user_id?: string; project_role?: string }) =>
    fetchJson<any>(`/projects/${projectId}/members`, { method: "POST", body: JSON.stringify(data) }),
  removeProjectMember: async (projectId: string, userId: string) =>
    fetchJson<any>(`/projects/${projectId}/members/${userId}`, { method: "DELETE" }),

  // Knowledge Explorer & Graph
  getKnowledgeExplorer: async (
    projectId?: string,
    category?: string,
    search?: string,
    verificationStatus?: string,
    employee?: string
  ) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (category) params.set("category", category)
    if (search) params.set("search", search)
    if (verificationStatus) params.set("verification_status", verificationStatus)
    if (employee) params.set("employee", employee)
    return fetchJson<any[]>(`/knowledge/explorer?${params.toString()}`)
  },
  getGraphReactFlow: async (
    projectId?: string,
    entityType?: string,
    search?: string,
    layout: "vertical" | "horizontal" = "vertical",
    hideIsolated: boolean = false
  ) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (entityType && entityType !== "All") params.set("entity_type", entityType)
    if (search) params.set("search", search)
    if (layout) params.set("layout", layout)
    if (hideIsolated) params.set("hide_isolated", "true")
    const qs = params.toString()
    return fetchJson<{ nodes: any[]; edges: any[]; spof_warnings?: any[]; people?: any[]; stats: any }>(
      `/graph/react-flow${qs ? `?${qs}` : ""}`
    )
  },
  getBlastRadius: async (nodeId: string) => fetchJson<any>(`/graph/blast-radius/${nodeId}`),
  getDepartureImpact: async (personNodeId: string) =>
    fetchJson<any>(`/graph/departure-impact/${personNodeId}`),
  assignBackupOwner: async (data: {
    component_id: string
    backup_person_name: string
    relation_type?: "owns" | "maintains"
  }) =>
    fetchJson<any>("/graph/assign-backup-owner", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  exportGraphMermaid: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<{ mermaid: string; node_count: number; edge_count: number }>(`/graph/export/mermaid${q}`)
  },
  extractKnowledgeGraph: async (projectId: string) =>
    fetchJson<any>(`/graph/extract/${projectId}`, { method: "POST" }),
  getDependencies: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/knowledge/dependencies${q}`)
  },

  getProjectPipelineStatus: async (projectId: string) =>
    fetchJson<any>(`/projects/${projectId}/pipeline-status`),

  // AI Project Assistant
  queryAssistant: async (projectId: string, question: string, departingFocus?: string, conversationId?: string) =>
    fetchJson<any>("/assistant/query", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        question,
        departing_focus: departingFocus || undefined,
        conversation_id: conversationId || undefined,
      }),
    }),
  queryAssistantStream: async (params: {
    projectId: string
    question: string
    departingFocus?: string
    conversationId?: string
    onMeta?: (meta: any) => void
    onToken?: (chunk: string) => void
  }) => {
    const res = await performFetchWithRetry(`${API_BASE}/assistant/query/stream`, {
      method: "POST",
      headers: getAuthHeaders({
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      }),
      body: JSON.stringify({
        project_id: params.projectId,
        question: params.question,
        departing_focus: params.departingFocus || undefined,
        conversation_id: params.conversationId || undefined,
      }),
    })
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}))
      throw new Error(errData?.detail || `Assistant stream failed (${res.status})`)
    }
    const reader = res.body?.getReader()
    if (!reader) {
      return api.queryAssistant(params.projectId, params.question, params.departingFocus, params.conversationId)
    }
    const decoder = new TextDecoder()
    let buffer = ""
    let finalPayload: any = null

    const processFrame = (frame: string) => {
      const lines = frame.split(/\r?\n/)
      let evName = "message"
      const dataLines: string[] = []
      for (const line of lines) {
        if (line.startsWith("event:")) {
          evName = line.slice(6).trim()
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim())
        }
      }
      if (dataLines.length === 0) return
      const rawJson = dataLines.join("\n")
      try {
        const parsed = JSON.parse(rawJson)
        if (evName === "meta" && params.onMeta) {
          params.onMeta(parsed)
        } else if (evName === "token" && params.onToken && parsed?.text) {
          params.onToken(parsed.text)
        } else if (evName === "done") {
          finalPayload = parsed
        }
      } catch {}
    }

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx = buffer.indexOf("\n\n")
      while (idx !== -1) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (frame.trim()) processFrame(frame)
        idx = buffer.indexOf("\n\n")
      }
    }
    if (buffer.trim()) processFrame(buffer)
    return finalPayload
  },
  getAssistantConversations: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/assistant/conversations${q}`)
  },
  getAssistantConversation: async (conversationId: string) =>
    fetchJson<any>(`/assistant/conversations/${conversationId}`),
  deleteAssistantConversation: async (conversationId: string) =>
    fetchJson<any>(`/assistant/conversations/${conversationId}`, { method: "DELETE" }),
  promoteAssistantInsight: async (data: {
    project_id: string
    target_type: "decision" | "gap"
    title: string
    content: string
    component?: string
    severity?: string
    evidence_ids?: string[]
  }) =>
    fetchJson<any>("/assistant/promote", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Decisions
  getDecisions: async (projectId?: string, status?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (status) params.set("status", status)
    const qs = params.toString()
    return fetchJson<any[]>(`/decisions${qs ? `?${qs}` : ""}`)
  },
  createDecision: async (data: any) =>
    fetchJson<any>("/decisions", { method: "POST", body: JSON.stringify(data) }),

  // Tasks
  getTasks: async (projectId?: string, departingOnly?: boolean, status?: string, priority?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (departingOnly) params.set("departing_only", "true")
    if (status) params.set("status", status)
    if (priority) params.set("priority", priority)
    return fetchJson<any[]>(`/tasks?${params.toString()}`)
  },
  createTask: async (data: any) =>
    fetchJson<any>("/tasks", { method: "POST", body: JSON.stringify(data) }),
  reassignTask: async (taskId: string, newOwner: string) =>
    fetchJson<any>(`/tasks/${taskId}/reassign`, {
      method: "POST",
      body: JSON.stringify({ new_owner: newOwner }),
    }),
  updateTaskStatus: async (taskId: string, status: string) =>
    fetchJson<any>(`/tasks/${taskId}/status`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),

  // Risks & Gaps
  getRisks: async (projectId?: string, severity?: string, status?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (severity) params.set("severity", severity)
    if (status) params.set("status", status)
    const qs = params.toString()
    return fetchJson<any[]>(`/risks${qs ? `?${qs}` : ""}`)
  },
  createRisk: async (data: any) =>
    fetchJson<any>("/risks", { method: "POST", body: JSON.stringify(data) }),
  updateRiskStatus: async (riskId: string, status: string) =>
    fetchJson<any>(`/risks/${riskId}/status`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),
  getGaps: async (projectId?: string, severity?: string, status?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (severity) params.set("severity", severity)
    if (status) params.set("status", status)
    const qs = params.toString()
    return fetchJson<any[]>(`/gaps${qs ? `?${qs}` : ""}`)
  },
  createGap: async (data: any) =>
    fetchJson<any>("/gaps", { method: "POST", body: JSON.stringify(data) }),
  resolveGap: async (gapId: string, status: string, resolution_notes?: string) =>
    fetchJson<any>(`/gaps/${gapId}/resolve`, {
      method: "PUT",
      body: JSON.stringify({ status, resolution_notes }),
    }),

  // Integrations & OAuth
  getIntegrations: async (projectId?: string) => {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/integrations${params}`)
  },
  getOAuthUrl: async (provider: string, projectId: string) =>
    fetchJson<{ authorize_url: string; redirect_uri: string }>(
      `/integrations/oauth/${provider}/authorize?project_id=${encodeURIComponent(projectId)}`
    ),
  createIntegration: async (data: any) =>
    fetchJson<any>("/integrations", { method: "POST", body: JSON.stringify(data) }),
  verifyIntegration: async (id: string) =>
    fetchJson<any>(`/integrations/${id}/verify`, { method: "POST" }),
  getIntegrationEvents: async (id: string) => fetchJson<any[]>(`/integrations/${id}/events`),
  getIntegrationResources: async (id: string) =>
    fetchJson<{ provider: string; resources: any[]; hint?: string | null }>(`/integrations/${id}/resources`),
  discoverIntegrationResources: async (provider: string, token: string) =>
    fetchJson<{ provider: string; resources: any[]; hint?: string | null }>("/integrations/discover-resources", {
      method: "POST",
      body: JSON.stringify({ provider, token }),
    }),
  updateIntegrationConfig: async (id: string, data: { config: any; name?: string }) =>
    fetchJson<any>(`/integrations/${id}/config`, { method: "PUT", body: JSON.stringify(data) }),
  triggerSync: async (id: string) =>
    fetchJson<any>(`/integrations/${id}/sync`, { method: "POST" }),
  disconnectIntegration: async (id: string) =>
    fetchJson<any>(`/integrations/${id}/disconnect`, { method: "POST" }),
  reconnectIntegration: async (id: string, data: any) =>
    fetchJson<any>(`/integrations/${id}/reconnect`, { method: "POST", body: JSON.stringify(data) }),
  deleteIntegration: async (id: string) =>
    fetchJson<any>(`/integrations/${id}`, { method: "DELETE" }),

  // Documents
  getDocuments: async (projectId?: string) => {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/documents${params}`)
  },
  uploadDocument: async (formData: FormData) =>
    fetchJson<any>("/documents/upload", { method: "POST", body: formData }),
  getDocumentChunks: async (docId: string) => fetchJson<any[]>(`/documents/${docId}/chunks`),
  downloadDocument: async (docId: string, filename: string) =>
    downloadAuthFile(`/documents/${docId}/download`, filename),
  deleteDocument: async (docId: string) =>
    fetchJson<any>(`/documents/${docId}`, { method: "DELETE" }),

  // Evidence Center
  getEvidence: async (
    projectId?: string,
    status?: string,
    search?: string,
    sourceType?: string,
    sourceOrigin?: string,
    author?: string
  ) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (status) params.set("status", status)
    if (search) params.set("search", search)
    if (sourceType) params.set("source_type", sourceType)
    if (sourceOrigin) params.set("source_origin", sourceOrigin)
    if (author) params.set("author", author)
    return fetchJson<any[]>(`/evidence?${params.toString()}`)
  },
  auditEvidence: async (id: string, newStatus: string, reviewNotes?: string) =>
    fetchJson<any>(`/evidence/${id}/audit`, {
      method: "POST",
      body: JSON.stringify({ new_status: newStatus, review_notes: reviewNotes }),
    }),

  // Handover Engine
  getHandovers: async (projectId?: string) => {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/handovers${params}`)
  },
  getHandover: async (id: string) => fetchJson<any>(`/handovers/${id}`),
  reconstructHandover: async (data: any) =>
    fetchJson<any>("/handovers/reconstruct", { method: "POST", body: JSON.stringify(data) }),
  editSection: async (handoverId: string, sectionId: string, content: string, isVerified?: boolean, reason?: string) =>
    fetchJson<any>(`/handovers/${handoverId}/sections/${sectionId}`, {
      method: "PUT",
      body: JSON.stringify({ content, is_verified: isVerified, reason }),
    }),
  reviewSection: async (
    handoverId: string,
    sectionId: string,
    action: "verify" | "approve" | "reject" | "request_changes",
    notes?: string
  ) =>
    fetchJson<any>(`/handovers/${handoverId}/sections/${sectionId}/review`, {
      method: "POST",
      body: JSON.stringify({ action, notes }),
    }),
  verifyClaim: async (handoverId: string, claimId: string, verification_status: string, review_notes?: string) =>
    fetchJson<any>(`/handovers/${handoverId}/claims/${claimId}/verify`, {
      method: "POST",
      body: JSON.stringify({ verification_status, review_notes }),
    }),
  addSectionComment: async (handoverId: string, sectionId: string, author: string, text: string) =>
    fetchJson<any>(`/handovers/${handoverId}/sections/${sectionId}/comments`, {
      method: "POST",
      body: JSON.stringify({ author, text }),
    }),
  approveHandover: async (
    handoverId: string,
    data: { approver_name?: string; role: string; status: string; notes?: string }
  ) =>
    fetchJson<any>(`/handovers/${handoverId}/approve`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateHandoverStatus: async (handoverId: string, status: string, reason?: string) =>
    fetchJson<any>(`/handovers/${handoverId}/status`, {
      method: "POST",
      body: JSON.stringify({ status, reason }),
    }),
  downloadHandoverPdf: async (handoverId: string) =>
    downloadAuthFile(`/handovers/${handoverId}/pdf`, `Handover_${handoverId.slice(0, 8)}.pdf`),
  downloadHandoverMarkdown: async (handoverId: string) =>
    downloadAuthFile(`/handovers/${handoverId}/export/markdown`, `HANDOVER_${handoverId.slice(0, 8)}.md`),
  getHandoverReadinessGate: async (handoverId: string) =>
    fetchJson<any>(`/handovers/${handoverId}/readiness-gate`),
  getReadinessSimulator: async (handoverId: string, regenerate: boolean = false) =>
    fetchJson<any>(`/handovers/${handoverId}/simulator?regenerate=${regenerate ? "true" : "false"}`),
  evaluateReadinessSimulator: async (
    handoverId: string,
    payload: { candidate_name?: string; scenarios: any[]; answers: Record<string, string> }
  ) =>
    fetchJson<any>(`/handovers/${handoverId}/simulator/evaluate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createOnboardingTasksFromSimulator: async (handoverId: string, simulationId?: string) =>
    fetchJson<any>(`/handovers/${handoverId}/simulator/create-onboarding-tasks`, {
      method: "POST",
      body: JSON.stringify(simulationId ? { simulation_id: simulationId } : {}),
    }),

  // Knowledge Drift & Realtime Webhooks
  getKnowledgeDrift: async (projectId?: string, status: string = "all") => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (status) params.set("status", status)
    return fetchJson<any[]>(`/knowledge/drift?${params.toString()}`)
  },
  scanKnowledgeDrift: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any>(`/knowledge/drift/scan${q}`, { method: "POST" })
  },
  updateDriftStatus: async (driftId: string, status: "acknowledged" | "resolved" | "dismissed") =>
    fetchJson<any>(`/knowledge/drift/${driftId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  getWebhookConfig: async (integrationId: string) =>
    fetchJson<any>(`/integrations/${integrationId}/webhook-config`),
  generateWebhookSecret: async (integrationId: string) =>
    fetchJson<any>(`/integrations/${integrationId}/webhook-config`, { method: "POST" }),
  registerAutoWebhook: async (integrationId: string) =>
    fetchJson<any>(`/integrations/${integrationId}/auto-webhook`, { method: "POST" }),

  // Organization, Team, Notifications, Logs & Settings
  getTeamMembers: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/team/members${q}`)
  },
  getNotifications: async () => fetchJson<any[]>("/team/notifications"),
  markNotificationRead: async (id: string) =>
    fetchJson<any>(`/team/notifications/${id}/read`, { method: "PUT" }),
  getOrgActivity: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/team/activity${q}`)
  },
  getOrgSettings: async () => fetchJson<any>("/team/settings"),
  updateOrgSettings: async (data: any) =>
    fetchJson<any>("/team/settings", { method: "PUT", body: JSON.stringify(data) }),

  // Explicit Demo Workspace Initializer
  seedDemo: async () => fetchJson<any>("/seed/demo", { method: "POST" }),
}
