"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { api, safeHref } from "@/lib/api"
import { Bell, CheckCircle2, Clock } from "lucide-react"

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const loadNotifications = async () => {
    try {
      setLoading(true)
      const list = await api.getNotifications().catch(() => [])
      setNotifications(Array.isArray(list) ? list : [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadNotifications()
  }, [])

  const handleMarkRead = async (id: string) => {
    try {
      await api.markNotificationRead(id)
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)))
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("obsidian_project_changed"))
      }
    } catch {}
  }

  const handleMarkAllRead = async () => {
    const unread = notifications.filter((n) => !n.is_read)
    await Promise.all(unread.map((n) => api.markNotificationRead(n.id).catch(() => {})))
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Notifications &amp; Review Alerts</h1>
          <p className="text-xs text-slate-500 mt-1">
            Role assignments, handover review requests, approval sign-offs, and risk escalations.
          </p>
        </div>

        {unreadCount > 0 && (
          <button
            onClick={handleMarkAllRead}
            className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200 flex items-center gap-1.5"
          >
            <CheckCircle2 className="w-3.5 h-3.5" /> Mark all {unreadCount} read
          </button>
        )}
      </div>

      {loading ? (
        <div className="apple-card p-10 text-center text-xs text-slate-400">Loading notifications...</div>
      ) : notifications.length === 0 ? (
        <div className="apple-card p-12 text-center space-y-2">
          <Bell className="w-9 h-9 text-slate-300 mx-auto" />
          <h3 className="text-sm font-bold text-slate-800">All Caught Up</h3>
          <p className="text-xs text-slate-500">You have no notifications yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {notifications.map((n) => (
            <div
              key={n.id}
              className={`apple-card p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                !n.is_read ? "border-violet-300 bg-violet-50/30" : ""
              }`}
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  {!n.is_read && <span className="w-2 h-2 rounded-full bg-violet-600" />}
                  <h3 className="text-sm font-bold text-slate-900">{n.title}</h3>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 uppercase font-semibold">
                    {n.type || "info"}
                  </span>
                </div>
                <p className="text-xs text-slate-600">{n.message}</p>
                <div className="flex items-center gap-3 text-[10px] text-slate-400">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="w-3 h-3" /> {n.created_at ? new Date(n.created_at).toLocaleString() : ""}
                  </span>
                  {(() => {
                    const safeNotifLink = safeHref(n.link, { allowRelative: true })
                    return safeNotifLink ? (
                      <Link href={safeNotifLink} className="text-violet-600 hover:underline font-semibold">
                        View Details →
                      </Link>
                    ) : null
                  })()}
                </div>
              </div>

              {!n.is_read && (
                <button
                  onClick={() => handleMarkRead(n.id)}
                  className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex-shrink-0"
                >
                  Mark Read
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
