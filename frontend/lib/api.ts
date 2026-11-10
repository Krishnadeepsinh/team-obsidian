// TEAM OBSIDIAN: Enterprise Frontend API Client

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"

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
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(url, options)
      if (attempt === 0 && retryableStatuses.has(res.status)) {
        await new Promise((r) => setTimeout(r, 1500))
        continue
      }
      return res
    } catch (err: any) {
      const isNetworkError =
        err instanceof TypeError ||
        (typeof err?.message === "string" && err.message.toLowerCase().includes("failed to fetch"))
      if (attempt === 0 && isNetworkError) {
        await new Promise((r) => setTimeout(r, 1500))
        continue
      }
      if (isNetworkError) {
        throw new Error(
          `Cannot reach TEAM OBSIDIAN API (${API_BASE}). If the backend just woke from cold start, please retry in a few seconds.`
        )
      }
      throw err
    }
  }
  throw new Error(`Cannot reach TEAM OBSIDIAN API (${API_BASE}).`)
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
    let detail = res.statusText
    try {
      const parsed = await res.json()
      detail = parsed?.detail || parsed?.message || JSON.stringify(parsed)
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

function persistAuthSession(res: any): void {
  if (typeof window !== "undefined" && res?.access_token) {
    localStorage.setItem("obsidian_token", res.access_token)
    if (res.user) localStorage.setItem("obsidian_user", JSON.stringify(res.user))
    if (res.active_project_id) {
      localStorage.setItem("obsidian_active_project_id", res.active_project_id)
      localStorage.setItem("obsidian_active_project", res.active_project_id)
    }
  }
}

export const api = {
  // Auth & Multi-Tenant Context
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
    return fetchJson<any>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    })
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
  getGraphReactFlow: async (projectId?: string, entityType?: string, search?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (entityType && entityType !== "All") params.set("entity_type", entityType)
    if (search) params.set("search", search)
    const qs = params.toString()
    return fetchJson<{ nodes: any[]; edges: any[]; spof_warnings?: any[]; stats: any }>(
      `/graph/react-flow${qs ? `?${qs}` : ""}`
    )
  },
  getBlastRadius: async (nodeId: string) => fetchJson<any>(`/graph/blast-radius/${nodeId}`),
  extractKnowledgeGraph: async (projectId: string) =>
    fetchJson<any>(`/graph/extract/${projectId}`, { method: "POST" }),
  getDependencies: async (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/knowledge/dependencies${q}`)
  },

  // AI Project Assistant
  queryAssistant: async (projectId: string, question: string, departingFocus?: string) =>
    fetchJson<any>("/assistant/query", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        question,
        departing_focus: departingFocus || undefined,
      }),
    }),

  // Decisions
  getDecisions: async (projectId?: string) => {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/decisions${params}`)
  },
  createDecision: async (data: any) =>
    fetchJson<any>("/decisions", { method: "POST", body: JSON.stringify(data) }),

  // Tasks
  getTasks: async (projectId?: string, departingOnly?: boolean) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (departingOnly) params.set("departing_only", "true")
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
  getRisks: async (projectId?: string) => {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/risks${params}`)
  },
  createRisk: async (data: any) =>
    fetchJson<any>("/risks", { method: "POST", body: JSON.stringify(data) }),
  updateRiskStatus: async (riskId: string, status: string) =>
    fetchJson<any>(`/risks/${riskId}/status`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),
  getGaps: async (projectId?: string) => {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""
    return fetchJson<any[]>(`/gaps${params}`)
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
  getEvidence: async (projectId?: string, status?: string, search?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set("project_id", projectId)
    if (status) params.set("status", status)
    if (search) params.set("search", search)
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
