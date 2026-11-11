"use client"

import { useEffect, useState, Suspense } from "react"
import Link from "next/link"
import { useSearchParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { KeyRound, ArrowLeft, CheckCircle2, Mail, Lock, AlertTriangle } from "lucide-react"

function ForgotPasswordForm() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const tokenFromUrl = searchParams.get("token") || ""
  const emailFromUrl = searchParams.get("email") || ""

  const [mode, setMode] = useState<"request" | "reset">(tokenFromUrl ? "reset" : "request")
  const [email, setEmail] = useState(emailFromUrl)
  const [resetToken, setResetToken] = useState(tokenFromUrl)
  const [newPassword, setNewPassword] = useState("")
  const [submittedMsg, setSubmittedMsg] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [emailDeliveryConfigured, setEmailDeliveryConfigured] = useState<boolean | null>(null)
  const [appEnv, setAppEnv] = useState<string>("")

  useEffect(() => {
    api
      .getAuthCapabilities()
      .then((caps) => {
        if (caps) {
          setEmailDeliveryConfigured(Boolean(caps.email_delivery_configured))
          setAppEnv(caps.app_env || "")
        }
      })
      .catch(() => {})
  }, [])

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError("")
    setSubmittedMsg("")
    try {
      const res = await api.forgotPassword(email)
      setSubmittedMsg(
        res.message ||
          "If an account exists for that email, a single-use password recovery link has been dispatched."
      )
    } catch (err: any) {
      setError(err.message || "Failed to send recovery request.")
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmReset = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError("")
    setSubmittedMsg("")
    try {
      const res = await api.resetPassword({
        email,
        reset_token: resetToken,
        new_password: newPassword,
      })
      setSubmittedMsg(res.message || "Password updated successfully. Redirecting to login...")
      setTimeout(() => router.push("/login"), 1200)
    } catch (err: any) {
      setError(err.message || "Invalid or expired reset token.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F8F9FD] flex items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-2.5">
          <div className="w-12 h-12 rounded-2xl bg-violet-100 border border-violet-200 flex items-center justify-center mx-auto">
            <KeyRound className="w-6 h-6 text-violet-600" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            {mode === "request" ? "Reset your password" : "Choose a new password"}
          </h1>
          <p className="text-xs text-slate-500">
            {mode === "request"
              ? "Enter your work email and we will send a single-use expiring recovery link."
              : "Enter the single-use token from your recovery email and set a new password."}
          </p>
        </div>

        <div className="apple-card p-6 sm:p-7 space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
              {error}
            </div>
          )}

          {submittedMsg && (
            <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-semibold">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                <span>Recovery Notice</span>
              </div>
              <p>{submittedMsg}</p>
            </div>
          )}

          {mode === "request" ? (
            emailDeliveryConfigured === false && appEnv === "production" ? (
              <div className="space-y-4">
                <div className="p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-xs space-y-1.5">
                  <div className="flex items-center gap-1.5 font-semibold">
                    <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
                    <span>Password Recovery Emails Not Enabled Yet</span>
                  </div>
                  <p className="leading-relaxed">
                    This deployment does not have an outbound email provider configured (<code>RESEND_API_KEY</code> or <code>SMTP_*</code>), so reset links cannot be emailed yet.
                  </p>
                  <p className="text-[11px] text-amber-800">
                    If you are already signed in, update your password under <Link href="/profile" className="underline font-semibold">Profile &amp; Security</Link>.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setSubmittedMsg("")
                    setError("")
                    setMode("reset")
                  }}
                  className="w-full py-2.5 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 transition-all"
                >
                  Already have a recovery token? Enter it here
                </button>
              </div>
            ) : (
            <form onSubmit={handleRequestReset} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">Work Email</label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@company.com"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 transition-all"
              >
                {loading ? "Sending recovery instructions..." : "Send Recovery Email"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setSubmittedMsg("")
                  setError("")
                  setMode("reset")
                }}
                className="w-full text-[11px] font-medium text-violet-600 hover:text-violet-700"
              >
                Already have a recovery token? Enter it here
              </button>
            </form>
            )
          ) : (
            <form onSubmit={handleConfirmReset} className="space-y-3.5">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">Work Email</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  className="w-full px-3 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">Recovery Token</label>
                <input
                  type="text"
                  required
                  value={resetToken}
                  onChange={(e) => setResetToken(e.target.value)}
                  placeholder="Paste single-use recovery token"
                  className="w-full px-3 py-2.5 rounded-xl text-xs font-mono bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">New Password (min 8 chars)</label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 transition-all"
              >
                {loading ? "Updating password..." : "Update Password"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setSubmittedMsg("")
                  setError("")
                  setMode("request")
                }}
                className="w-full text-[11px] font-medium text-slate-500 hover:text-slate-700"
              >
                Need a new recovery email?
              </button>
            </form>
          )}

          <div className="pt-4 border-t border-slate-100 text-center">
            <Link href="/login" className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-violet-700">
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to sign in</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#F8F9FD]" />}>
      <ForgotPasswordForm />
    </Suspense>
  )
}
