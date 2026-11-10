"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export default function DashboardRedirectPage() {
  const router = useRouter()
  useEffect(() => {
    router.replace("/")
  }, [router])

  return (
    <div className="min-h-screen bg-[#F8F9FD] flex items-center justify-center text-xs text-slate-500">
      Loading TEAM OBSIDIAN Workspace...
    </div>
  )
}
