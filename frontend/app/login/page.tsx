"use client"

import { useEffect, useState, useRef } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { api, warmUpBackendHealth } from "@/lib/api"
import { Layers, ArrowRight, Lock, Mail, Sparkles, ShieldCheck, RefreshCw, ArrowLeft } from "lucide-react"

export default function LoginPage() {
  const router = useRouter()
  const [step, setStep] = useState<"credentials" | "otp">("credentials")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [otp, setOtp] = useState("")
  const [maskedEmail, setMaskedEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [wakingApi, setWakingApi] = useState(false)
  const [error, setError] = useState("")
  const [infoMessage, setInfoMessage] = useState("")

  // OTP Countdown Timers
  const [countdown, setCountdown] = useState(300) // 5 minutes
  const [resendCooldown, setResendCooldown] = useState(60) // 60 seconds
  const [canResend, setCanResend] = useState(false)
  const otpInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    warmUpBackendHealth()
    const onWaking = (ev: Event) => {
      setWakingApi(Boolean((ev as CustomEvent)?.detail?.waking))
    }
    window.addEventListener("obsidian_api_waking", onWaking)
    return () => window.removeEventListener("obsidian_api_waking", onWaking)
  }, [])

  // 5-minute expiry countdown timer
  useEffect(() => {
    if (step !== "otp") return
    if (countdown <= 0) return

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer)
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [step, countdown])

  // 60-second resend cooldown timer
  useEffect(() => {
    if (step !== "otp") return
    if (resendCooldown <= 0) {
      setCanResend(true)
      return
    }

    setCanResend(false)
    const timer = setInterval(() => {
      setResendCooldown((prev) => {
        if (prev <= 1) {
          clearInterval(timer)
          setCanResend(true)
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [step, resendCooldown])

  // Auto-focus OTP input when switching to OTP step
  useEffect(() => {
    if (step === "otp") {
      setTimeout(() => {
        otpInputRef.current?.focus()
      }, 100)
    }
  }, [step])

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
  }

  const handleCredentialsSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError("")
    setInfoMessage("")
    try {
      const res = await api.login({ email, password })
      if (res.otp_required) {
        setStep("otp")
        setMaskedEmail(res.masked_email || email)
        setCountdown(res.expires_in || 300)
        setResendCooldown(60)
        setInfoMessage("We sent a 6-digit verification code to your email.")
      } else if (res.access_token) {
        router.push("/dashboard")
      }
    } catch (err: any) {
      setError(err.message || "Invalid credentials. Please check your email and password.")
    } finally {
      setLoading(false)
    }
  }

  const handleOtpSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (otp.trim().length !== 6) {
      setError("Please enter the complete 6-digit verification code.")
      return
    }
    setLoading(true)
    setError("")
    setInfoMessage("")
    try {
      const res = await api.verifyLoginOtp(email, otp.trim())
      if (res.access_token) {
        router.push("/dashboard")
      }
    } catch (err: any) {
      setError(err.message || "Verification code is invalid or has expired.")
    } finally {
      setLoading(false)
    }
  }

  const handleResendOtp = async () => {
    if (!canResend || loading) return
    setLoading(true)
    setError("")
    setInfoMessage("")
    try {
      const res = await api.resendLoginOtp(email)
      setCountdown(res.expires_in || 300)
      setResendCooldown(60)
      setCanResend(false)
      setInfoMessage(res.message || "A new 6-digit verification code has been dispatched to your email.")
      setOtp("")
      otpInputRef.current?.focus()
    } catch (err: any) {
      setError(err.message || "Failed to resend verification code. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F8F9FD] flex items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-3">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-[#7C3AED] to-[#6366F1] flex items-center justify-center mx-auto shadow-lg shadow-violet-500/20">
            {step === "otp" ? <ShieldCheck className="w-6 h-6 text-white" /> : <Layers className="w-6 h-6 text-white" />}
          </div>
          <div>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-violet-50 text-violet-700 border border-violet-200 mb-2">
              <Sparkles className="w-3 h-3" /> TEAM OBSIDIAN
            </span>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
              {step === "otp" ? "Two-Step Verification" : "Sign in to your workspace"}
            </h1>
            <p className="text-xs text-slate-500 mt-1">
              {step === "otp"
                ? `Enter the 6-digit verification code sent to ${maskedEmail || email}`
                : "Knowledge Reconstruction, Evidence Verification & Handover Platform"}
            </p>
          </div>
        </div>

        <div className="apple-card p-6 sm:p-7 space-y-5">
          {wakingApi && (
            <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-xs font-medium">
              Waking cloud API instance from sleep — signing in automatically once ready...
            </div>
          )}
          {infoMessage && (
            <div className="p-3 rounded-xl bg-violet-50 border border-violet-200 text-violet-800 text-xs font-medium">
              {infoMessage}
            </div>
          )}
          {error && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
              {error}
            </div>
          )}

          {step === "credentials" ? (
            <form onSubmit={handleCredentialsSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700">Work Email</label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@company.com"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white transition-colors"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-700">Password</label>
                  <Link href="/forgot-password" className="text-[11px] font-medium text-violet-600 hover:text-violet-700">
                    Forgot password?
                  </Link>
                </div>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-violet-500 focus:bg-white transition-colors"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 flex items-center justify-center gap-2 transition-all cursor-pointer"
              >
                <span>{loading ? "Checking credentials..." : "Continue"}</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </form>
          ) : (
            <form onSubmit={handleOtpSubmit} className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-700">6-Digit Security Code</label>
                  <span
                    className={`text-[11px] font-medium ${
                      countdown < 60 ? "text-rose-600 font-semibold" : "text-slate-500"
                    }`}
                  >
                    Expires in: {formatTime(countdown)}
                  </span>
                </div>
                <div className="relative">
                  <input
                    ref={otpInputRef}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    required
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="123456"
                    className="w-full py-3 text-center text-xl font-bold tracking-[0.5em] rounded-xl bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-300 focus:outline-none focus:border-violet-500 focus:bg-white transition-colors"
                  />
                </div>
                <p className="text-[11px] text-slate-500 text-center">
                  Check your inbox for the code sent from TEAM OBSIDIAN Security.
                </p>
              </div>

              <button
                type="submit"
                disabled={loading || otp.length !== 6 || countdown <= 0}
                className="w-full py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 flex items-center justify-center gap-2 transition-all cursor-pointer"
              >
                <span>{loading ? "Verifying..." : "Verify & Sign In"}</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>

              <div className="flex items-center justify-between pt-2 text-xs">
                <button
                  type="button"
                  onClick={() => {
                    setStep("credentials")
                    setOtp("")
                    setError("")
                  }}
                  className="text-slate-500 hover:text-slate-700 flex items-center gap-1 cursor-pointer"
                >
                  <ArrowLeft className="w-3 h-3" />
                  <span>Change email</span>
                </button>

                <button
                  type="button"
                  onClick={handleResendOtp}
                  disabled={!canResend || loading}
                  className="font-medium text-violet-600 hover:text-violet-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1 cursor-pointer"
                >
                  <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
                  <span>{canResend ? "Resend Code" : `Resend in ${resendCooldown}s`}</span>
                </button>
              </div>
            </form>
          )}

          <div className="pt-4 border-t border-slate-100 text-center text-xs text-slate-500">
            New to Team Obsidian?{" "}
            <Link href="/register" className="font-semibold text-violet-600 hover:text-violet-700">
              Create your workspace
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
