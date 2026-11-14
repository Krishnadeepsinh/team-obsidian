"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"

// 1. User & Multi-Tenant Workspace Context
export function useUserContext() {
  return useQuery({
    queryKey: queryKeys.auth.context(),
    queryFn: async () => {
      const ctx = await api.getUserContext()
      if (ctx?.user) {
        localStorage.setItem("obsidian_authenticated", "true")
        localStorage.setItem("obsidian_user", JSON.stringify(ctx.user))
      }
      return ctx
    },
    staleTime: 60 * 1000,
  })
}

// 2. Notifications
export function useNotifications() {
  return useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: () => api.getNotifications(),
    staleTime: 30 * 1000,
  })
}

// 3. Projects List
export function useProjects(workspaceId?: string) {
  return useQuery({
    queryKey: queryKeys.projects.list(undefined, workspaceId),
    queryFn: () => api.getProjects(workspaceId),
    staleTime: 60 * 1000,
  })
}

// 4. Project Details
export function useProject(projectId: string) {
  return useQuery({
    queryKey: queryKeys.projects.detail(undefined, projectId),
    queryFn: () => api.getProject(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  })
}

// 5. Project Members
export function useProjectMembers(projectId: string) {
  return useQuery({
    queryKey: queryKeys.projects.members(undefined, projectId),
    queryFn: () => api.getProjectMembers(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  })
}

// 6. Project Timeline
export function useProjectTimeline(projectId: string) {
  return useQuery({
    queryKey: queryKeys.projects.timeline(undefined, projectId),
    queryFn: () => api.getProjectTimeline(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  })
}

// 7. Workspaces
export function useWorkspaces() {
  return useQuery({
    queryKey: queryKeys.workspaces.list(),
    queryFn: () => api.getWorkspaces(),
    staleTime: 60 * 1000,
  })
}

// 8. Dashboard Statistics
export function useDashboardStats(projectId?: string) {
  return useQuery({
    queryKey: queryKeys.dashboard.stats(undefined, projectId),
    queryFn: () => api.getStats(projectId),
    staleTime: 30 * 1000,
  })
}

// 9. Dashboard Activity
export function useDashboardActivity(projectId?: string) {
  return useQuery({
    queryKey: queryKeys.dashboard.activity(undefined, projectId),
    queryFn: () => api.getActivity(projectId),
    staleTime: 30 * 1000,
  })
}

// Cache Invalidation Utilities
export function useInvalidateQueries() {
  const queryClient = useQueryClient()

  return {
    invalidateProjects: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
    invalidateDashboard: () => queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    invalidateUserContext: () => queryClient.invalidateQueries({ queryKey: ["auth"] }),
    invalidateNotifications: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    invalidateProjectDetail: (projectId: string) =>
      queryClient.invalidateQueries({ queryKey: ["projects", "detail", undefined, projectId] }),
    clearAll: () => queryClient.clear(),
  }
}

