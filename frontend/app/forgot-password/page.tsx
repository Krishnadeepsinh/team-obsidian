"use client"

import { useEffect, useState, Suspense } from "react"
import Link from "next/link"
import { useSearchParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { KeyRound, ArrowLeft, CheckCircle2, Mail, Lock, ShieldCheck, RefreshCw } from "lucide-react"

function ForgotPasswordForm() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const tokenFromUrl = searchParams.get("token") || ""
  const emailFromUrl = searchParams.get("email") || ""

  const [step, setStep] = useState<"email" | "otp" | "reset">(tokenFromUrl ? "reset" : "email")
  const [email, setEmail] = useState(emailFromUrl)
  const [otp, setOtp] = useState("")
  const [resetSessionToken, setResetSessionToken] = useState(tokenFromUrl)
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [submittedMsg, setSubmittedMsg] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  // Countdown timer for 60s resend cooldown
  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => {
      setCooldown((prev) => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  // Step 1: Request 6-digit OTP
  const handleRequestOtp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!email.trim() || !email.includes("@")) {
      setError("Please enter a valid email address.")
      return
    }
    setLoading(true)
    setError("")
    setSubmittedMsg("")
    try {
      const res = await api.forgotPassword(email.trim())
      setSubmittedMsg(
        res.message || "A 6-digit verification code has been dispatched to your email."
      )
      setCooldown(60)
      setStep("otp")
    } catch (err: any) {
      setError(err.message || "Failed to send verification code. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  // Step 2: Verify 6-digit OTP
  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    const cleanOtp = otp.trim()
    if (cleanOtp.length !== 6 || !/^\d{6}$/.test(cleanOtp)) {
      setError("Please enter a valid 6-digit numeric verification code.")
      return
    }
    setLoading(true)
    setError("")
    setSubmittedMsg("")
    try {
      const res = await api.verifyOtp(email.trim(), cleanOtp)
      setResetSessionToken(res.reset_session_token)
      setSubmittedMsg("Verification code confirmed. You may now choose your new password.")
      setStep("reset")
    } catch (err: any) {
      setError(err.message || "Invalid or expired verification code.")
    } finally {
      setLoading(false)
    }
  }

  // Step 3: Set New Password
  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters long.")
      return
    }
    if (newPassword !== confirmPassword) {
      setError("New password and confirmation password do not match.")
      return
    }
    setLoading(true)
    setError("")
    setSubmittedMsg("")
    try {
      const res = await api.resetPassword({
        email: email.trim(),
        reset_token: resetSessionToken,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setSubmittedMsg(res.message || "Password updated successfully. Redirecting to sign in...")
      setTimeout(() => {
        window.location.href = "/login"
      }, 1500)
    } catch (err: any) {
      setError(err.message || "Failed to update password. Please request a new code.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F8F9FD] flex items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-2.5">
          <div className="w-12 h-12 rounded-2xl bg-violet-100 border border-violet-200 flex items-center justify-center mx-auto shadow-sm">
            <KeyRound className="w-6 h-6 text-violet-600" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            {step === "email" && "Reset your password"}
            {step === "otp" && "Enter verification code"}
            {step === "reset" && "Create a new password"}
          </h1>
          <p className="text-xs text-slate-500">
            {step === "email" && "Enter your work email to receive a secure 6-digit verification code."}
            {step === "otp" && `Enter the 6-digit code sent to ${email}.`}
            {step === "reset" && "Choose a strong password to secure your account."}
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
                <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                <span>Notice</span>
              </div>
              <p>{submittedMsg}</p>
            </div>
          )}

          {/* STEP 1: Email Form */}
          {step === "email" && (
            <form onSubmit={handleRequestOtp} className="space-y-4">
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
                className="w-full py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 transition-all flex items-center justify-center gap-1.5"
              >
                {loading ? "Sending code..." : "Send Verification Code"}
              </button>
            </form>
          )}

          {/* STEP 2: 6-Digit OTP Form */}
          {step === "otp" && (
            <form onSubmit={handleVerifyOtp} className="space-y-4">
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-700">6-Digit Code</label>
                  <span className="text-[11px] text-slate-400">Valid for 5 mins</span>
                </div>
                <div className="relative">
                  <ShieldCheck className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    required
                    maxLength={6}
                    pattern="[0-9]{6}"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoFocus
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="123456"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl text-base tracking-[0.5em] text-center font-mono font-bold bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || otp.length !== 6}
                className="w-full py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 transition-all"
              >
                {loading ? "Verifying..." : "Verify Code"}
              </button>

              <div className="flex items-center justify-between pt-2 text-xs">
                <button
                  type="button"
                  onClick={() => {
                    setError("")
                    setSubmittedMsg("")
                    setStep("email")
                  }}
                  className="text-slate-500 hover:text-slate-700 font-medium"
                >
                  Change email
                </button>

                <button
                  type="button"
                  disabled={cooldown > 0 || loading}
                  onClick={() => handleRequestOtp()}
                  className="inline-flex items-center gap-1 text-violet-600 hover:text-violet-700 font-semibold disabled:text-slate-400 disabled:cursor-not-allowed"
                >
                  <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
                  <span>{cooldown > 0 ? `Resend code (${cooldown}s)` : "Resend code"}</span>
                </button>
              </div>
            </form>
          )}

          {/* STEP 3: Reset Password Form */}
          {step === "reset" && (
            <form onSubmit={handleResetPassword} className="space-y-3.5">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">New Password (min 8 characters)</label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="password"
                    required
                    minLength={8}
                    autoFocus
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">Confirm New Password</label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
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
