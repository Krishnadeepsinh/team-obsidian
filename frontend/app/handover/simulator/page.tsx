"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api, getStoredProjectId } from "@/lib/api"
import {
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Trophy,
} from "lucide-react"

export default function ReadinessSimulatorPage() {
  const [handovers, setHandovers] = useState<any[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [simData, setSimData] = useState<any>(null)
  const [candidateName, setCandidateName] = useState("")
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [error, setError] = useState("")

  const loadSimulator = useCallback(async (targetHid?: string, regenerate: boolean = false) => {
    try {
      if (regenerate) setRegenerating(true)
      else setLoading(true)
      setError("")
      const pid = getStoredProjectId() || undefined
      const hs = await api.getHandovers(pid).catch(() => [])
      const list = Array.isArray(hs) ? hs : []
      setHandovers(list)

      const hid = targetHid || list[0]?.id || ""
      setSelectedId(hid)
      if (!hid) {
        setSimData(null)
        return
      }
      const data = await api.getReadinessSimulator(hid, regenerate)
      setSimData(data)
      if (data?.incoming_employee_name) {
        setCandidateName((prev) => prev || data.incoming_employee_name)
      }
      setAnswers({})
      if (!regenerate && data?.history?.length > 0) {
        setResult(data.history[0])
      } else {
        setResult(null)
      }
    } catch (err: any) {
      setError(err.message || "Failed to load readiness simulator scenarios.")
    } finally {
      setLoading(false)
      setRegenerating(false)
    }
  }, [])

  useEffect(() => {
    loadSimulator()
  }, [loadSimulator])

  useEffect(() => {
    const onProjectChange = () => {
      loadSimulator()
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [loadSimulator])

  const handleEvaluate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedId || !simData?.scenarios?.length) return
    const hasAny = simData.scenarios.some((s: any) => (answers[s.id] || "").trim().length > 0)
    if (!hasAny) {
      setError("Write at least one scenario response before submitting evaluation.")
      return
    }
    try {
      setEvaluating(true)
      setError("")
      const res = await api.evaluateReadinessSimulator(selectedId, {
        candidate_name: candidateName.trim() || simData.incoming_employee_name,
        scenarios: simData.scenarios,
        answers,
      })
      setResult(res)
      const refreshed = await api.getReadinessSimulator(selectedId, false).catch(() => null)
      if (refreshed) setSimData(refreshed)
    } catch (err: any) {
      setError(err.message || "Simulation evaluation failed.")
    } finally {
      setEvaluating(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href="/handover"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-violet-700 mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Handover Dossier
          </Link>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <BrainCircuit className="w-6 h-6 text-violet-600" />
            <span>Successor Readiness Simulator</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Verify incoming engineer incident triage, blast-radius awareness, and ADR decision readiness against live project evidence before sign-off.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {handovers.length > 0 && (
            <select
              value={selectedId}
              onChange={(e) => loadSimulator(e.target.value, false)}
              className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
            >
              {handovers.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.title}
                </option>
              ))}
            </select>
          )}
          {selectedId && (
            <button
              onClick={() => loadSimulator(selectedId, true)}
              disabled={regenerating}
              className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 flex items-center gap-1.5 shadow-sm"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${regenerating ? "animate-spin" : ""}`} />
              <span>Regenerate Scenarios</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">{error}</div>
      )}

      {loading ? (
        <div className="apple-card p-10 text-center text-xs text-slate-500">Generating project-grounded readiness scenarios...</div>
      ) : !simData ? (
        <div className="apple-card p-10 text-center space-y-2">
          <BrainCircuit className="w-9 h-9 text-slate-300 mx-auto" />
          <p className="text-sm font-bold text-slate-800">No Handover Dossier Available</p>
          <p className="text-xs text-slate-500">Generate a handover dossier first to launch successor readiness simulation.</p>
          <Link href="/handover" className="inline-block mt-2 px-4 py-2 rounded-xl bg-violet-600 text-white text-xs font-semibold">
            Open Handover Dossier
          </Link>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Quantitative Readiness Banner */}
          <div className="apple-card p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 font-bold uppercase">
                  Handover Readiness Gate
                </span>
                {simData.latest_score !== null && simData.latest_score !== undefined && (
                  <span
                    className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase border ${
                      simData.readiness_passed
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-amber-50 text-amber-700 border-amber-200"
                    }`}
                  >
                    Latest Score: {simData.latest_score}% ({simData.readiness_passed ? "PASSED >= 70%" : "NEEDS REVIEW"})
                  </span>
                )}
              </div>
              <h2 className="text-sm font-bold text-slate-900">{simData.handover_title}</h2>
              <p className="text-xs text-slate-500">
                Outgoing: <strong>{simData.departing_employee_name}</strong> → Successor: <strong>{simData.incoming_employee_name}</strong>
              </p>
            </div>

            <Link
              href="/handover/approvals"
              className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white flex items-center gap-1.5 self-start sm:self-center"
            >
              <ShieldCheck className="w-3.5 h-3.5" /> Review Sign-Off Gate
            </Link>
          </div>

          {/* Interactive Scenario Form */}
          <form onSubmit={handleEvaluate} className="space-y-4">
            <div className="apple-card p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <label className="text-xs font-semibold text-slate-700">Incoming Candidate / Responder Name</label>
              <input
                type="text"
                value={candidateName}
                onChange={(e) => setCandidateName(e.target.value)}
                placeholder="Successor engineer name"
                className="sm:w-72 px-3 py-2 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900"
              />
            </div>

            {(simData.scenarios || []).map((sc: any, idx: number) => (
              <div key={sc.id || idx} className="apple-card p-5 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 rounded-lg bg-violet-100 text-violet-700 text-xs font-bold flex items-center justify-center">
                      {idx + 1}
                    </span>
                    <h3 className="text-sm font-bold text-slate-900">{sc.title}</h3>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-semibold uppercase">
                      {String(sc.category || "scenario").replace(/_/g, " ")}
                    </span>
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                        sc.severity === "critical" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {sc.severity || "high"}
                    </span>
                  </div>
                </div>

                <p className="text-xs text-slate-700 leading-relaxed bg-slate-50 p-3.5 rounded-xl border border-slate-100">
                  {sc.prompt}
                </p>

                {Array.isArray(sc.expected_concepts) && sc.expected_concepts.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500">
                    <span className="font-semibold">Key concepts checked:</span>
                    {sc.expected_concepts.map((c: string) => (
                      <span key={c} className="px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-100">
                        {c}
                      </span>
                    ))}
                  </div>
                )}

                <textarea
                  rows={4}
                  value={answers[sc.id] || ""}
                  onChange={(e) => setAnswers((prev) => ({ ...prev, [sc.id]: e.target.value }))}
                  placeholder="Describe root cause triage, affected downstream services, ADR constraints, and rollback/recovery plan..."
                  className="w-full px-3.5 py-2.5 rounded-xl text-xs bg-white border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500"
                />
              </div>
            ))}

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={evaluating}
                className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white shadow-md shadow-violet-600/20 flex items-center gap-2"
              >
                <Send className="w-3.5 h-3.5" />
                <span>{evaluating ? "Grading Responses..." : "Submit & Compute Readiness Score"}</span>
              </button>
            </div>
          </form>

          {/* Latest Scorecard */}
          {result && (
            <div className="apple-card p-6 space-y-4 border-2 border-violet-100">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-100">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-11 h-11 rounded-2xl flex items-center justify-center ${
                      result.passed ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"
                    }`}
                  >
                    {result.passed ? <Trophy className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">
                      Readiness Evaluation: {result.overall_score}% ({result.passed ? "Ready for Sign-Off" : "Review Gaps Needed"})
                    </h3>
                    <p className="text-xs text-slate-600 mt-0.5">{result.summary_feedback}</p>
                  </div>
                </div>
                <span className="text-[11px] text-slate-400">
                  {result.created_at ? new Date(result.created_at).toLocaleString() : ""}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {(result.responses || []).map((r: any, idx: number) => (
                  <div key={r.scenario_id || idx} className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-slate-900 truncate">{r.title}</span>
                      <span
                        className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                          r.score >= 70 ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {r.score}%
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-600 leading-relaxed">{r.feedback}</p>
                    {Array.isArray(r.strengths) && r.strengths.length > 0 && (
                      <div className="text-[10px] text-emerald-700 flex items-start gap-1">
                        <CheckCircle2 className="w-3 h-3 mt-0.5 flex-shrink-0" />
                        <span>{r.strengths.join(", ")}</span>
                      </div>
                    )}
                    {Array.isArray(r.missed_concepts) && r.missed_concepts.length > 0 && (
                      <div className="text-[10px] text-amber-700 flex items-start gap-1">
                        <Sparkles className="w-3 h-3 mt-0.5 flex-shrink-0" />
                        <span>Missed: {r.missed_concepts.join(", ")}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

