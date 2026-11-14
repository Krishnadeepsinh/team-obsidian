// TEAM OBSIDIAN: Strict Multi-Tenant Query Cache Keys
// Enforces user-isolated and workspace-scoped cache partitioning

export const queryKeys = {
  auth: {
    me: (userId?: string) => ["auth", "me", userId || "anonymous"] as const,
    context: (userId?: string) => ["auth", "context", userId || "anonymous"] as const,
  },
  projects: {
    all: (userId?: string) => ["projects", "all", userId || "anonymous"] as const,
    list: (userId?: string, workspaceId?: string) =>
      ["projects", "list", userId || "anonymous", workspaceId || "all"] as const,
    detail: (userId?: string, projectId?: string) =>
      ["projects", "detail", userId || "anonymous", projectId || ""] as const,
    members: (userId?: string, projectId?: string) =>
      ["projects", "members", userId || "anonymous", projectId || ""] as const,
    timeline: (userId?: string, projectId?: string) =>
      ["projects", "timeline", userId || "anonymous", projectId || ""] as const,
  },
  workspaces: {
    list: (userId?: string) => ["workspaces", "list", userId || "anonymous"] as const,
  },
  dashboard: {
    stats: (userId?: string, projectId?: string) =>
      ["dashboard", "stats", userId || "anonymous", projectId || "all"] as const,
    activity: (userId?: string, projectId?: string) =>
      ["dashboard", "activity", userId || "anonymous", projectId || "all"] as const,
  },
  notifications: {
    list: (userId?: string) => ["notifications", "list", userId || "anonymous"] as const,
  },
  knowledge: {
    explorer: (
      userId?: string,
      projectId?: string,
      category?: string,
      search?: string,
      verificationStatus?: string,
      employee?: string
    ) =>
      [
        "knowledge",
        "explorer",
        userId || "anonymous",
        projectId || "all",
        category || "all",
        search || "",
        verificationStatus || "all",
        employee || "",
      ] as const,
  },
}

