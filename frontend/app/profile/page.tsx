"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { User, Lock, CheckCircle2, Save } from "lucide-react"

export default function ProfilePage() {
  const [user, setUser] = useState<any>(null)
  const [name, setName] = useState("")
  const [title, setTitle] = useState("")
  const [department, setDepartment] = useState("")
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileMsg, setProfileMsg] = useState("")

  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [savingPwd, setSavingPwd] = useState(false)
  const [pwdMsg, setPwdMsg] = useState("")
  const [pwdErr, setPwdErr] = useState("")

  useEffect(() => {
    api.getUserContext().then((ctx) => {
      if (ctx?.user) {
        setUser(ctx.user)
        setName(ctx.user.name || "")
        setTitle(ctx.user.title || "")
        setDepartment(ctx.user.department || "")
      }
    }).catch(() => {})
  }, [])

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      setSavingProfile(true)
      setProfileMsg("")
      const updated = await api.updateProfile({ name, title, department })
      setUser(updated)
      if (typeof window !== "undefined") {
        localStorage.setItem("obsidian_user", JSON.stringify(updated))
      }
      setProfileMsg("Profile updated successfully.")
    } catch (err: any) {
      alert(err.message || "Could not update profile.")
    } finally {
      setSavingProfile(false)
    }
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      setSavingPwd(true)
      setPwdMsg("")
      setPwdErr("")
      const res = await api.changePassword(currentPassword, newPassword)
      setCurrentPassword("")
      setNewPassword("")
      setPwdMsg(res.message || "Password updated securely.")
    } catch (err: any) {
      setPwdErr(err.message || "Password update failed.")
    } finally {
      setSavingPwd(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Your Profile &amp; Security</h1>
        <p className="text-xs text-slate-500 mt-1">
          Manage your identity details and Argon2id account password.
        </p>
      </div>

      {/* Profile Form */}
      <form onSubmit={handleSaveProfile} className="apple-card p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
            <User className="w-4 h-4 text-violet-600" />
            <span>Account Identity</span>
          </h2>
          {user?.role && (
            <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 font-bold uppercase">
              {user.role.replace("_", " ")}
            </span>
          )}
        </div>

        {profileMsg && (
          <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" /> {profileMsg}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">Full Name</label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">Email</label>
            <input
              type="email"
              disabled
              value={user?.email || ""}
              className="w-full px-3 py-2 rounded-xl text-xs bg-slate-100 border border-slate-200 text-slate-500"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">Job Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Senior Backend Engineer"
              className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">Department</label>
            <input
              type="text"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="e.g. Platform Engineering"
              className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
            />
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={savingProfile}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white shadow-sm flex items-center gap-1.5"
          >
            <Save className="w-3.5 h-3.5" /> {savingProfile ? "Saving..." : "Save Profile"}
          </button>
        </div>
      </form>

      {/* Password Form */}
      <form onSubmit={handleChangePassword} className="apple-card p-6 space-y-4">
        <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2 border-b border-slate-100 pb-3">
          <Lock className="w-4 h-4 text-violet-600" />
          <span>Change Password</span>
        </h2>

        {pwdErr && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">{pwdErr}</div>
        )}
        {pwdMsg && (
          <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" /> {pwdMsg}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">Current Password</label>
            <input
              type="password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-700 block mb-1">New Password (min 8 chars)</label>
            <input
              type="password"
              required
              minLength={8}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200"
            />
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={savingPwd}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white"
          >
            {savingPwd ? "Updating..." : "Update Password"}
          </button>
        </div>
      </form>
    </div>
  )
}
