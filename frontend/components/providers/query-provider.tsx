"use client"

import React, { useState } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

export let globalQueryClient: QueryClient | null = null

export function clearClientCache(): void {
  if (globalQueryClient) {
    globalQueryClient.clear()
  }
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute fresh data window prevents refetches on navigation
            gcTime: 10 * 60 * 1000, // 10 minutes cache retention
            retry: 1,
            refetchOnWindowFocus: false, // Prevents sudden background re-fetches
            refetchOnMount: false, // Reuses valid cache during route transitions
          },
        },
      })
  )

  globalQueryClient = queryClient

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

