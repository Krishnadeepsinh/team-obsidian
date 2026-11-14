"use client"

import React, { useState } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

let clientQueryClientSingleton: QueryClient | null = null

function makeQueryClient(): QueryClient {
  return new QueryClient({
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
}

export function getQueryClient(): QueryClient {
  if (typeof window === "undefined") {
    return makeQueryClient()
  }
  if (!clientQueryClientSingleton) {
    clientQueryClientSingleton = makeQueryClient()
  }
  return clientQueryClientSingleton
}

export function clearClientCache(): void {
  if (clientQueryClientSingleton) {
    clientQueryClientSingleton.clear()
  }
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => getQueryClient())

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
