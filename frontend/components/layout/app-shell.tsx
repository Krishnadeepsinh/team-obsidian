"use client"

import React, { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  ChevronDown,
  Compass,
  FileSignature,
  FileText,
  FolderGit2,
  GitFork,
  HelpCircle,
  History,
  Layers,
  LayoutDashboard,
  LogOut,
  Menu,
  MoreHorizontal,
  Network,
  Scale,
  ScrollText,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Stamp,
  Unplug,
  Users,
  X,
} from "lucide-react"
import { ALL_PROJECTS_VALUE, api, setStoredProjectId } from "@/lib/api"

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const [activeTab, setActiveTab] = useState("Workspace")
  const [searchQuery, setSearchQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [showProjectMenu, setShowProjectMenu] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)
  const [activeProject, setActiveProject] = useState("My Workspace")
  const [projectsList, setProjectsList] = useState<any[]>([])
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [isDesktopViewport, setIsDesktopViewport] = useState(true)
  const [currentUser, setCurrentUser] = useState<any>(null)
  const [unreadCount, setUnreadCount] = useState(0)

  useEffect(() => {
    if (typeof window === "undefined") return
    const mql = window.matchMedia("(min-width: 768px)")
    const syncViewport = () => setIsDesktopViewport(mql.matches)
    syncViewport()
    mql.addEventListener("change", syncViewport)
    return () => mql.removeEventListener("change", syncViewport)
  }, [])

  const isPublic =
    pathname === "/landing" ||
    pathname === "/login" ||
    pathname === "/register" ||
    pathname === "/forgot-password"

  useEffect(() => {
    if (!isPublic && typeof window !== "undefined") {
      const token = localStorage.getItem("obsidian_token")
      if (!token) {
        router.push("/login")
        return
      }
      try {
        const parts = token.split(".")
        if (parts.length === 3) {
          const payload = JSON.parse(atob(parts[1]))
          if (payload.exp && payload.exp < Date.now() / 1000) {
            localStorage.removeItem("obsidian_token")
            localStorage.removeItem("obsidian_user")
            router.push("/login")
            return
          }
        }
      } catch {}
    }
  }, [pathname, isPublic, router])

  useEffect(() => {
    setMobileNavOpen(false)
  }, [pathname])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        searchInputRef.current?.focus()
        searchInputRef.current?.select()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  useEffect(() => {
    if (pathname === "/activity" || pathname === "/logs" || pathname === "/timeline") {
      setActiveTab("Activity")
    } else if (pathname?.startsWith("/handover") || pathname === "/evidence") {
      setActiveTab("Reports")
    } else {
      setActiveTab("Workspace")
    }
  }, [pathname])

  useEffect(() => {
    if (isPublic || typeof window === "undefined") return
    const token = localStorage.getItem("obsidian_token")
    if (!token) return

    const stored = localStorage.getItem("obsidian_user")
    if (stored) {
      try {
        setCurrentUser(JSON.parse(stored))
      } catch {}
    }

    api
      .getUserContext()
      .then((ctx) => {
        if (ctx) {
          if (ctx.user) {
            setCurrentUser(ctx.user)
            localStorage.setItem("obsidian_user", JSON.stringify(ctx.user))
          }
          if (ctx.projects && ctx.projects.length > 0) {
            setProjectsList(ctx.projects)
            const savedProjId =
              localStorage.getItem("obsidian_active_project_id") ||
              localStorage.getItem("obsidian_active_project")
            if (savedProjId === ALL_PROJECTS_VALUE) {
              setActiveProject("All Projects")
            } else {
              const found = ctx.projects.find((p: any) => p.id === savedProjId)
              if (found) {
                setActiveProject(found.name)
              } else {
                setActiveProject(ctx.projects[0].name)
                localStorage.setItem("obsidian_active_project_id", ctx.projects[0].id)
                localStorage.setItem("obsidian_active_project", ctx.projects[0].id)
              }
            }
          }
        }
      })
      .catch(() => {})

    api
      .getNotifications()
      .then((list) => {
        if (Array.isArray(list)) {
          setUnreadCount(list.filter((n: any) => !n.is_read).length)
        }
      })
      .catch(() => {})
  }, [pathname, isPublic])

  useEffect(() => {
    if (isPublic || typeof window === "undefined") return
    const syncFromStorage = () => {
      const savedProjId =
        localStorage.getItem("obsidian_active_project_id") ||
        localStorage.getItem("obsidian_active_project")
      if (savedProjId === ALL_PROJECTS_VALUE) {
        setActiveProject("All Projects")
      } else if (savedProjId) {
        const matched = projectsList.find((p: any) => p.id === savedProjId)
        if (matched) setActiveProject(matched.name)
      }
    }
    window.addEventListener("obsidian_project_changed", syncFromStorage)
    return () => window.removeEventListener("obsidian_project_changed", syncFromStorage)
  }, [isPublic, projectsList])

  const handleSignOut = async () => {
    setShowUserMenu(false)
    setMobileNavOpen(false)
    await api.logout()
    if (typeof window !== "undefined") {
      localStorage.removeItem("obsidian_token")
      localStorage.removeItem("obsidian_user")
      localStorage.removeItem("obsidian_active_project_id")
      localStorage.removeItem("obsidian_active_project")
    }
    router.push("/login")
  }

  if (isPublic) {
    return <div className="min-h-screen bg-[#F8F9FD] text-slate-900">{children}</div>
  }

  const navItems = [
    { name: "Overview", href: "/", icon: LayoutDashboard },
    { name: "Projects", href: "/projects", icon: FolderGit2 },
    { name: "Knowledge", href: "/knowledge/explorer", icon: Compass },
    { name: "Handover", href: "/handover", icon: FileSignature },
    { name: "Integrations", href: "/integrations", icon: Unplug },
    { name: "Team", href: "/team", icon: Users },
  ]

  const secondaryItems = [
    { name: "Knowledge Graph", href: "/knowledge/graph", icon: Network },
    { name: "Dependencies", href: "/knowledge/dependencies", icon: GitFork },
    { name: "Decisions (ADRs)", href: "/decisions", icon: Scale },
    { name: "Tasks & Owners", href: "/tasks", icon: CheckCircle2 },
    { name: "Risks & SPOFs", href: "/risks", icon: AlertTriangle },
    { name: "Knowledge Gaps", href: "/gaps", icon: HelpCircle },
    { name: "Documents", href: "/documents", icon: FileText },
    { name: "Evidence Center", href: "/evidence", icon: ShieldCheck },
    { name: "Approvals", href: "/handover/approvals", icon: Stamp },
    { name: "History", href: "/handover/history", icon: History },
    { name: "Timeline", href: "/timeline", icon: Activity },
    { name: "Audit Logs", href: "/logs", icon: ScrollText },
  ]

  const userInitials = (currentUser?.name || currentUser?.email || "U")
    .split(" ")
    .filter(Boolean)
    .map((n: string) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#F8F9FD] text-slate-900 font-sans antialiased">
      {/* Desktop Sidebar */}
      {isDesktopViewport && (
        <aside className="hidden md:flex w-60 flex-shrink-0 flex-col bg-white border-r border-[#E8EBF2] select-none z-30">
        <div className="p-4 pt-5 pb-3">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-[#1E1238] to-[#3B1A7A] p-1.5 flex items-center justify-center shadow-md shadow-purple-900/10">
              <Layers className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-bold text-sm tracking-tight text-slate-900 block leading-tight">
                TEAM OBSIDIAN
              </span>
              <span className="text-[10px] text-slate-400 block font-medium leading-none mt-0.5">
                Knowledge Handover Platform
              </span>
            </div>
          </Link>
        </div>

        {/* Active Project Switcher */}
        <div className="px-3 pb-3 relative">
          <button
            onClick={() => setShowProjectMenu(!showProjectMenu)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-[#F8F9FD] hover:bg-[#F1F3FA] border border-[#E8EBF2] text-xs font-semibold text-slate-800 transition-all shadow-sm"
          >
            <div className="flex items-center gap-2 truncate">
              <Layers className="w-3.5 h-3.5 text-violet-600 flex-shrink-0" />
              <span className="truncate">{activeProject}</span>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
          </button>

          {showProjectMenu && (
            <div className="absolute top-full left-3 right-3 mt-1 bg-white border border-[#E8EBF2] rounded-xl shadow-xl p-1 z-50 max-h-64 overflow-y-auto">
              <div className="text-[10px] uppercase font-bold text-slate-400 px-2.5 py-1">Projects</div>
              <button
                onClick={() => {
                  setActiveProject("All Projects")
                  setStoredProjectId("")
                  setShowProjectMenu(false)
                }}
                className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center justify-between ${
                  activeProject === "All Projects" ? "bg-violet-50 text-violet-700" : "text-slate-700 hover:bg-slate-50"
                }`}
              >
                <span className="truncate">All Accessible Projects</span>
                {activeProject === "All Projects" && <CheckCircle2 className="w-3 h-3 text-violet-600 flex-shrink-0" />}
              </button>
              {projectsList.length > 0 ? (
                projectsList.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => {
                      setActiveProject(p.name)
                      setStoredProjectId(p.id)
                      setShowProjectMenu(false)
                    }}
                    className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center justify-between ${
                      activeProject === p.name ? "bg-violet-50 text-violet-700" : "text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <span className="truncate">{p.name}</span>
                    {activeProject === p.name && <CheckCircle2 className="w-3 h-3 text-violet-600 flex-shrink-0" />}
                  </button>
                ))
              ) : (
                <div className="px-2.5 py-2 text-[11px] text-slate-500 text-center">No projects in workspace</div>
              )}
              <div className="border-t border-slate-100 mt-1 pt-1">
                <Link
                  href="/projects"
                  onClick={() => setShowProjectMenu(false)}
                  className="block text-center text-[11px] text-violet-600 font-semibold py-1 hover:underline"
                >
                  Manage Projects →
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 space-y-1 overflow-y-auto pb-2">
          {navItems.map((item) => {
            const isActive = pathname === item.href || (item.href !== "/" && pathname?.startsWith(item.href))
            const Icon = item.icon
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                  isActive
                    ? "bg-[#EDE9FE] text-[#6D28D9] font-semibold shadow-sm"
                    : "text-slate-600 hover:text-slate-900 hover:bg-[#F8F9FD]"
                }`}
              >
                <Icon className={`w-4 h-4 flex-shrink-0 ${isActive ? "text-[#7C3AED]" : "text-slate-500"}`} />
                <span>{item.name}</span>
              </Link>
            )
          })}

          <div className="pt-3 pb-1 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Intelligence & Review
          </div>
          {secondaryItems.map((item) => {
            const isActive = pathname === item.href
            const Icon = item.icon
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-3 py-1.5 rounded-xl text-[11.5px] font-medium transition-all ${
                  isActive
                    ? "bg-[#EDE9FE] text-[#6D28D9] font-semibold"
                    : "text-slate-500 hover:text-slate-900 hover:bg-[#F8F9FD]"
                }`}
              >
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? "text-[#7C3AED]" : "text-slate-400"}`} />
                <span>{item.name}</span>
              </Link>
            )
          })}
        </nav>

        {/* Bottom AI Assistant Card */}
        <div className="p-3">
          <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#F5F2FF] via-[#EDE9FE] to-[#E0E7FF] border border-violet-200/80 p-3.5 shadow-sm">
            <div className="relative z-10">
              <h4 className="text-xs font-bold text-slate-900 leading-tight">AI Project Assistant</h4>
              <p className="text-[11px] text-slate-500 mt-0.5 mb-2.5 leading-snug">
                Ask anything about your project
              </p>
              <button
                onClick={() => router.push("/assistant")}
                className="w-full py-2 px-3 rounded-xl text-xs font-semibold bg-gradient-to-r from-[#6D28D9] to-[#7C3AED] hover:from-[#5B21B6] hover:to-[#6D28D9] text-white flex items-center justify-center gap-1.5 shadow-md shadow-violet-500/20 transition-all"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Chat with AI</span>
              </button>
            </div>
          </div>
        </div>

        {/* User Footer */}
        <div className="p-3 border-t border-[#E8EBF2] bg-white">
          <div className="flex items-center justify-between">
            <div
              onClick={() => router.push("/profile")}
              className="flex items-center gap-2.5 cursor-pointer min-w-0 flex-1 group"
            >
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-[#1E1238] to-[#3B1A7A] flex items-center justify-center text-white text-[11px] font-bold flex-shrink-0 shadow-sm">
                {userInitials}
              </div>
              <div className="min-w-0">
                <p className="text-xs font-bold text-slate-900 truncate group-hover:text-violet-700 transition-colors">
                  {currentUser?.name || "Workspace User"}
                </p>
                <p className="text-[10px] text-slate-500 truncate capitalize">
                  {currentUser?.role?.replace("_", " ") || currentUser?.email || "Member"}
                </p>
              </div>
            </div>
            <div className="relative">
              <button
                onClick={() => setShowUserMenu(!showUserMenu)}
                aria-label="User menu"
                data-testid="user-menu-trigger"
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>
              {showUserMenu && (
                <div className="absolute bottom-full right-0 mb-1 w-40 bg-white border border-[#E8EBF2] rounded-xl shadow-xl p-1 z-50">
                  <Link
                    href="/settings"
                    onClick={() => setShowUserMenu(false)}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs text-slate-700 hover:bg-slate-50"
                  >
                    <Settings className="w-3.5 h-3.5 text-slate-400" />
                    <span>Settings</span>
                  </Link>
                  <button
                    onClick={handleSignOut}
                    className="w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs text-rose-600 hover:bg-rose-50"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
        </aside>
      )}

      {/* Mobile Drawer Backdrop */}
      {mobileNavOpen && (
        <div
          className="fixed inset-x-0 top-14 bottom-0 bg-slate-900/40 backdrop-blur-sm z-40 md:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      {/* Mobile Navigation Drawer */}
      {mobileNavOpen && (
        <aside
          role="dialog"
          aria-modal="true"
          className="fixed top-14 bottom-0 left-0 w-64 bg-white border-r border-[#E8EBF2] z-50 flex flex-col md:hidden shadow-2xl select-none"
        >
        <div className="p-4 pt-5 pb-3 flex items-center justify-between border-b border-[#E8EBF2]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-[#1E1238] to-[#3B1A7A] p-1 flex items-center justify-center">
              <Layers className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-sm text-slate-900">TEAM OBSIDIAN</span>
          </div>
          <button
            onClick={() => setMobileNavOpen(false)}
            className="p-1 rounded-lg hover:bg-slate-100 text-slate-500"
            aria-label="Close menu"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
          {[...navItems, ...secondaryItems, { name: "AI Assistant", href: "/assistant", icon: Sparkles }, { name: "Settings", href: "/settings", icon: Settings }].map(
            (item) => {
              const Icon = item.icon
              const isActive = pathname === item.href
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileNavOpen(false)}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                    isActive ? "bg-[#EDE9FE] text-[#6D28D9] font-semibold" : "text-slate-600 hover:bg-[#F8F9FD]"
                  }`}
                >
                  <Icon className={`w-4 h-4 flex-shrink-0 ${isActive ? "text-[#7C3AED]" : "text-slate-500"}`} />
                  <span>{item.name}</span>
                </Link>
              )
            }
          )}
        </nav>

        <div className="p-3 border-t border-[#E8EBF2]">
          <button
            onClick={handleSignOut}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium text-rose-600 hover:bg-rose-50"
          >
            <LogOut className="w-4 h-4" />
            <span>Sign Out</span>
          </button>
        </div>
        </aside>
      )}

      {/* Main App Viewport */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-[#F8F9FD]">
        <header className="h-14 flex-shrink-0 bg-white/80 backdrop-blur-md border-b border-[#E8EBF2] px-3 sm:px-6 flex items-center justify-between z-50 md:z-20">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setMobileNavOpen((prev) => !prev)}
              className="p-1.5 rounded-lg text-slate-600 hover:bg-slate-100 md:hidden"
              aria-label="Toggle mobile navigation menu"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center bg-[#F1F3FA] p-1 rounded-full border border-slate-200/50">
              <button
                onClick={() => {
                  setActiveTab("Workspace")
                  router.push("/")
                }}
                className={`px-2.5 sm:px-4 py-1 rounded-full text-xs font-semibold transition-all ${
                  activeTab === "Workspace" ? "bg-white text-violet-700 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Workspace
              </button>
              <button
                onClick={() => {
                  setActiveTab("Reports")
                  router.push("/handover")
                }}
                className={`px-2.5 sm:px-4 py-1 rounded-full text-xs font-semibold transition-all ${
                  activeTab === "Reports" ? "bg-white text-violet-700 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Reports
              </button>
              <button
                onClick={() => {
                  setActiveTab("Activity")
                  router.push("/activity")
                }}
                className={`px-2.5 sm:px-4 py-1 rounded-full text-xs font-semibold transition-all ${
                  activeTab === "Activity" ? "bg-white text-violet-700 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Activity
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="relative hidden sm:block">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                ref={searchInputRef}
                type="text"
                placeholder="Search projects, decisions, tasks..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && searchQuery.trim()) {
                    router.push(`/knowledge/explorer?search=${encodeURIComponent(searchQuery)}`)
                  }
                }}
                className="w-72 pl-9 pr-8 py-1.5 rounded-full text-xs bg-[#F8F9FD] border border-[#E8EBF2] text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-violet-400 focus:bg-white transition-all shadow-inner"
              />
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] font-mono text-slate-400 px-1 py-0.2 rounded bg-slate-200/60">
                ⌘K
              </span>
            </div>

            <button
              onClick={() => router.push("/notifications")}
              className="relative p-2 rounded-full hover:bg-slate-100 text-slate-600 transition-colors"
              title="Notifications"
            >
              <Bell className="w-4 h-4" />
              {unreadCount > 0 && (
                <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-rose-500 ring-2 ring-white" />
              )}
            </button>

            <button
              onClick={() => router.push("/profile")}
              className="w-7 h-7 rounded-full bg-[#1E1238] flex items-center justify-center text-white text-[10px] font-bold cursor-pointer hover:ring-2 hover:ring-violet-400 transition-all shadow-sm"
              title={currentUser?.name || "Profile"}
            >
              {userInitials}
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
