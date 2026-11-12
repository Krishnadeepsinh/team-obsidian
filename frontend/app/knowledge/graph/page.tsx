"use client"

import { useEffect, useState, useCallback, useMemo } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  Handle,
  Position,
  MarkerType,
  useNodesState,
  useEdgesState,
  useReactFlow,
  useNodesInitialized,
  type ReactFlowInstance,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { api, getStoredProjectId, isAllProjectsSelected, resolveActiveProjectId, setStoredProjectId } from "@/lib/api"
import {
  Network,
  Sparkles,
  AlertTriangle,
  Search,
  Zap,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  Maximize2,
  X,
  UserMinus,
  UserPlus,
  Copy,
  Download,
  EyeOff,
  ArrowLeftRight,
} from "lucide-react"

const DEFAULT_ENTITY_TYPES = [
  "All",
  "person",
  "component",
  "service",
  "infrastructure",
  "database",
  "external_service",
  "organization",
  "decision",
  "risk",
]

function CustomKnowledgeNode({ data, selected }: { data: any; selected?: boolean }) {
  const accentColor = data?.color || "#0EA5E9"
  const badgeBg = data?.bg || "#F0F9FF"
  const badgeText = data?.textColor || "#0C4A6E"
  const isSpof = Boolean(data?.isSpof)
  const confidencePct = Math.round((data?.confidence ?? 0.75) * 100)
  const isHorizontal = data?.layout === "horizontal"
  const departureRole = data?.departureRole as "departing" | "orphaned_spof" | "impacted" | "dimmed" | undefined

  const ringClass = selected
    ? "ring-2 ring-violet-500 shadow-lg"
    : departureRole === "departing" || departureRole === "orphaned_spof"
    ? "ring-2 ring-rose-500 shadow-lg"
    : departureRole === "impacted"
    ? "ring-2 ring-amber-500 shadow-md"
    : isSpof
    ? "ring-2 ring-amber-400/80 shadow-md"
    : "shadow-sm hover:shadow-md"

  const borderColor = selected
    ? "#7C3AED"
    : departureRole === "departing" || departureRole === "orphaned_spof"
    ? "#EF4444"
    : departureRole === "impacted"
    ? "#F59E0B"
    : isSpof
    ? "#F59E0B"
    : accentColor

  return (
    <div
      className={`w-[224px] rounded-2xl bg-white px-3.5 py-2.5 transition-all select-none ${ringClass} ${
        departureRole === "dimmed" ? "opacity-30" : ""
      }`}
      style={{
        border: `1.5px solid ${borderColor}`,
      }}
    >
      <Handle
        type="target"
        position={isHorizontal ? Position.Left : Position.Top}
        className="!w-2 !h-2 !bg-slate-400 !border-white"
      />

      <div className="flex items-center justify-between gap-1.5">
        <span
          className="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wide truncate max-w-[115px]"
          style={{
            backgroundColor: badgeBg,
            color: badgeText,
            border: `1px solid ${accentColor}40`,
          }}
        >
          {String(data?.entityType || "entity").replace(/_/g, " ")}
        </span>
        {departureRole === "departing" ? (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-rose-50 border border-rose-300 text-rose-800 text-[9px] font-bold">
            DEPARTING
          </span>
        ) : departureRole === "orphaned_spof" ? (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-rose-50 border border-rose-300 text-rose-800 text-[9px] font-bold">
            ORPHANED
          </span>
        ) : departureRole === "impacted" ? (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-amber-50 border border-amber-300 text-amber-800 text-[9px] font-bold">
            AT RISK
          </span>
        ) : isSpof ? (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-amber-50 border border-amber-300 text-amber-800 text-[9px] font-bold">
            <AlertTriangle className="w-2.5 h-2.5 text-amber-600" />
            SPOF
          </span>
        ) : (
          <span className="text-[9px] font-semibold text-slate-400">{confidencePct}%</span>
        )}
      </div>

      <div className="mt-1.5 text-xs font-bold text-slate-900 leading-snug line-clamp-2" title={data?.label}>
        {data?.label || "Entity"}
      </div>

      {data?.description && (
        <p className="mt-1 text-[10px] text-slate-500 leading-snug line-clamp-2" title={data.description}>
          {data.description}
        </p>
      )}

      <div className="mt-2 pt-1.5 border-t border-slate-100 flex items-center justify-between gap-2 text-[9px] text-slate-400">
        <span>{data?.degree ?? 0} {(data?.degree ?? 0) === 1 ? "link" : "links"}</span>
        <span className="truncate max-w-[130px]">
          {data?.soleOwner ? `Owner: ${data.soleOwner}` : `${confidencePct}% conf`}
        </span>
      </div>

      <Handle
        type="source"
        position={isHorizontal ? Position.Right : Position.Bottom}
        className="!w-2 !h-2 !bg-slate-400 !border-white"
      />
    </div>
  )
}

const nodeTypes = {
  customKnowledgeNode: CustomKnowledgeNode,
}

function AutoFitView({ fitKey }: { fitKey: string }) {
  const { fitView } = useReactFlow()
  const nodesInitialized = useNodesInitialized()

  useEffect(() => {
    if (!nodesInitialized) return
    const raf = window.requestAnimationFrame(() => {
      fitView({ padding: 0.16, maxZoom: 0.95, duration: 220 })
    })
    return () => window.cancelAnimationFrame(raf)
  }, [nodesInitialized, fitKey, fitView])

  return null
}

export default function KnowledgeGraphPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([])
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null)
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [entityType, setEntityType] = useState("All")
  const [availableTypes, setAvailableTypes] = useState<string[]>(DEFAULT_ENTITY_TYPES)
  const [search, setSearch] = useState("")
  const [spofWarnings, setSpofWarnings] = useState<any[]>([])
  const [peopleList, setPeopleList] = useState<any[]>([])
  const [stats, setStats] = useState<any>({})
  const [layoutMode, setLayoutMode] = useState<"vertical" | "horizontal">("vertical")
  const [hideIsolated, setHideIsolated] = useState(false)
  const [simulatePersonId, setSimulatePersonId] = useState("")
  const [departureImpact, setDepartureImpact] = useState<any>(null)
  const [simulatingDeparture, setSimulatingDeparture] = useState(false)
  const [loading, setLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)
  const [statusMsg, setStatusMsg] = useState("")
  const [errorMsg, setErrorMsg] = useState("")

  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [blastRadius, setBlastRadius] = useState<any>(null)
  const [loadingBlast, setLoadingBlast] = useState(false)
  const [backupOwnerName, setBackupOwnerName] = useState("")
  const [backupRelationType, setBackupRelationType] = useState<"maintains" | "owns">("maintains")
  const [assigningBackup, setAssigningBackup] = useState(false)
  const [copiedMermaid, setCopiedMermaid] = useState(false)

  const loadGraph = useCallback(async (
    pid?: string,
    etype?: string,
    q?: string,
    nextLayout?: "vertical" | "horizontal",
    nextHideIsolated?: boolean
  ) => {
    try {
      setLoading(true)
      const useLayout = nextLayout ?? layoutMode
      const useHideIso = nextHideIsolated ?? hideIsolated
      const allSelected = pid === undefined && isAllProjectsSelected()
      const storedPid = allSelected || pid === "" ? "" : pid !== undefined ? pid : getStoredProjectId()
      const [projs, graphResRaw] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getGraphReactFlow(storedPid || undefined, etype, q || undefined, useLayout, useHideIso).catch(() => ({
          nodes: [],
          edges: [],
          spof_warnings: [],
          people: [],
          stats: {},
        })),
      ])
      const projList = Array.isArray(projs) ? projs : []
      setProjects(projList)
      const resolvedPid = allSelected || pid === "" ? "" : resolveActiveProjectId(projList, pid)
      setActiveProject(resolvedPid)

      let graphRes = graphResRaw
      if (resolvedPid && resolvedPid !== storedPid) {
        graphRes = await api
          .getGraphReactFlow(resolvedPid, etype, q || undefined, useLayout, useHideIso)
          .catch(() => ({ nodes: [], edges: [], spof_warnings: [], people: [], stats: {} }))
      }
      const nextNodes = Array.isArray(graphRes.nodes) ? graphRes.nodes : []
      const nextEdges = (Array.isArray(graphRes.edges) ? graphRes.edges : []).map((edge: any) => ({
        ...edge,
        markerEnd: edge.markerEnd || {
          type: MarkerType.ArrowClosed,
          width: 15,
          height: 15,
          color: edge.style?.stroke || "#7C3AED",
        },
      }))
      setNodes(nextNodes)
      setEdges(nextEdges)
      setSpofWarnings(graphRes.spof_warnings || [])
      setPeopleList(Array.isArray(graphRes.people) ? graphRes.people : [])
      setStats(graphRes.stats || {})

      if (!etype || etype === "All") {
        const discovered = Array.from(
          new Set(
            nextNodes
              .map((n: any) => String(n?.data?.entityType || "").trim().toLowerCase())
              .filter(Boolean)
          )
        )
        const merged = Array.from(new Set([...DEFAULT_ENTITY_TYPES, ...discovered]))
        setAvailableTypes(merged)
      }
    } finally {
      setLoading(false)
    }
  }, [setEdges, setNodes, layoutMode, hideIsolated])

  useEffect(() => {
    loadGraph(undefined, "All", "")
  }, [loadGraph])

  useEffect(() => {
    const onProjectChange = () => {
      loadGraph(undefined, entityType, search)
    }
    window.addEventListener("obsidian_project_changed", onProjectChange)
    return () => window.removeEventListener("obsidian_project_changed", onProjectChange)
  }, [loadGraph, entityType, search])

  const handleFilterChange = (nextType: string, nextSearch: string, nextPid: string) => {
    setEntityType(nextType)
    setSearch(nextSearch)
    setSelectedNode(null)
    loadGraph(nextPid, nextType, nextSearch)
  }

  const handleExtract = async () => {
    const pid = activeProject || projects[0]?.id
    if (!pid) {
      setErrorMsg("Select or create a project first.")
      return
    }
    try {
      setExtracting(true)
      setStatusMsg("")
      setErrorMsg("")
      const res = await api.extractKnowledgeGraph(pid)
      setStatusMsg(res.message || "Extracted entities, relationships, ADRs, risks, and dependencies from project evidence.")
      await loadGraph(pid, entityType, search)
    } catch (err: any) {
      setErrorMsg(err.message || "AI Knowledge Extraction failed.")
    } finally {
      setExtracting(false)
    }
  }

  const onNodeClick = useCallback(async (_: any, node: any) => {
    setSelectedNode(node)
    setBlastRadius(null)
    setLoadingBlast(true)
    try {
      const br = await api.getBlastRadius(node.id)
      setBlastRadius(br)
    } catch {
      setBlastRadius(null)
    } finally {
      setLoadingBlast(false)
    }
  }, [])

  const focusNodeById = (nodeId?: string) => {
    if (!nodeId) return
    const target = nodes.find((n: any) => n.id === nodeId)
    if (!target) return
    onNodeClick(null, target)
    if (rfInstance) {
      rfInstance.fitView({ nodes: [{ id: nodeId }], padding: 0.8, maxZoom: 1.05, duration: 300 })
    }
  }

  const handleSimulateDeparture = async (personId: string) => {
    setSimulatePersonId(personId)
    if (!personId) {
      setDepartureImpact(null)
      return
    }
    try {
      setSimulatingDeparture(true)
      setErrorMsg("")
      const impact = await api.getDepartureImpact(personId)
      setDepartureImpact(impact)
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to simulate departure impact.")
      setDepartureImpact(null)
    } finally {
      setSimulatingDeparture(false)
    }
  }

  const handleAssignBackup = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedNode || !backupOwnerName.trim()) return
    try {
      setAssigningBackup(true)
      setErrorMsg("")
      setStatusMsg("")
      const res = await api.assignBackupOwner({
        component_id: selectedNode.id,
        backup_person_name: backupOwnerName.trim(),
        relation_type: backupRelationType,
      })
      setBackupOwnerName("")
      setStatusMsg(
        res.is_still_spof
          ? `Added relationship for ${res.backup_person_name} on ${res.component_name}.`
          : `SPOF mitigated! ${res.backup_person_name} assigned as backup owner for ${res.component_name}.`
      )
      await loadGraph(activeProject, entityType, search, layoutMode, hideIsolated)
      if (simulatePersonId) {
        const refreshedImpact = await api.getDepartureImpact(simulatePersonId).catch(() => null)
        setDepartureImpact(refreshedImpact)
      }
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to assign backup owner.")
    } finally {
      setAssigningBackup(false)
    }
  }

  const handleCopyOrDownloadMermaid = async (download: boolean) => {
    try {
      setErrorMsg("")
      const res = await api.exportGraphMermaid(activeProject || undefined)
      const diagram = res.mermaid || "flowchart TD\n"
      if (download) {
        const blob = new Blob([diagram], { type: "text/plain;charset=utf-8" })
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `team_obsidian_graph_${(activeProject || "workspace").slice(0, 12)}.mmd`
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(url)
        setStatusMsg("Downloaded Mermaid architecture diagram (.mmd).")
      } else if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(diagram)
        setCopiedMermaid(true)
        setTimeout(() => setCopiedMermaid(false), 2000)
        setStatusMsg("Copied Mermaid diagram to clipboard — paste directly into README or GitHub PRs.")
      }
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to export Mermaid diagram.")
    }
  }

  const renderedNodes = useMemo(() => {
    if (!departureImpact) return nodes
    const departingId = departureImpact.person_id
    const orphanedIds = new Set<string>((departureImpact.orphaned_spofs || []).map((x: any) => x.id))
    const affectedIds = new Set<string>(departureImpact.affected_node_ids || [])
    return nodes.map((n: any) => {
      const role =
        n.id === departingId
          ? "departing"
          : orphanedIds.has(n.id)
          ? "orphaned_spof"
          : affectedIds.has(n.id)
          ? "impacted"
          : "dimmed"
      return {
        ...n,
        data: {
          ...n.data,
          departureRole: role,
        },
      }
    })
  }, [nodes, departureImpact])

  const renderedEdges = useMemo(() => {
    if (!departureImpact) return edges
    const departingId = departureImpact.person_id
    const affectedIds = new Set<string>(departureImpact.affected_node_ids || [])
    return edges.map((edge: any) => {
      const touchesBlast =
        edge.source === departingId ||
        (affectedIds.has(edge.source) && affectedIds.has(edge.target))
      return {
        ...edge,
        animated: touchesBlast,
        style: touchesBlast
          ? { stroke: "#DC2626", strokeWidth: 2.5 }
          : { ...(edge.style || {}), opacity: 0.16 },
      }
    })
  }, [edges, departureImpact])

  return (
    <div className="p-4 sm:p-5 max-w-[1440px] mx-auto space-y-3.5">
      {/* Header & Actions */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge Graph &amp; Blast Radius</h1>
          <p className="text-xs text-slate-500 mt-1">
            Inspect component ownership, upstream/downstream dependencies, and single points of failure.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={activeProject}
            onChange={(e) => {
              const pid = e.target.value
              setActiveProject(pid)
              setStoredProjectId(pid)
            }}
            className="px-3 py-2 rounded-xl text-xs bg-white border border-slate-200 text-slate-800 shadow-sm"
          >
            <option value="">All Accessible Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          <button
            onClick={handleExtract}
            disabled={extracting}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white shadow-md shadow-violet-600/20 flex items-center gap-1.5"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{extracting ? "Extracting Graph..." : "AI Extract Knowledge Graph"}</span>
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
          {errorMsg}
        </div>
      )}
      {statusMsg && (
        <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium">
          {statusMsg}
        </div>
      )}

      {/* Search & Entity Filters + SPOF Summary */}
      <div className="apple-card p-3 flex flex-col lg:flex-row lg:items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5 flex-1">
          <div className="relative flex-1 min-w-[160px] max-w-[200px]">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => handleFilterChange(entityType, e.target.value, activeProject)}
              placeholder="Search nodes..."
              className="w-full pl-8 pr-3 py-1 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
            />
          </div>

          <div className="flex flex-wrap gap-1">
            {availableTypes.map((et) => (
              <button
                key={et}
                onClick={() => handleFilterChange(et, search, activeProject)}
                className={`px-2 py-0.5 rounded-lg text-[11px] font-semibold capitalize border transition-all ${
                  entityType === et
                    ? "bg-violet-600 text-white border-violet-600"
                    : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
                }`}
              >
                {et.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 flex-shrink-0">
          <div className="flex items-center gap-1.5 bg-rose-50/70 border border-rose-200 rounded-xl px-2 py-1">
            <UserMinus className="w-3.5 h-3.5 text-rose-600 flex-shrink-0" />
            <select
              value={simulatePersonId}
              onChange={(e) => handleSimulateDeparture(e.target.value)}
              disabled={simulatingDeparture || peopleList.length === 0}
              className="bg-transparent text-[11px] font-semibold text-rose-900 focus:outline-none max-w-[175px]"
              aria-label="Simulate employee departure"
            >
              <option value="">
                {peopleList.length > 0 ? "What-If Person Leaves..." : "No Person Nodes Yet"}
              </option>
              {peopleList.map((p: any) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.spof_count ?? 0} SPOFs)
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            onClick={() => {
              const nextLayout = layoutMode === "vertical" ? "horizontal" : "vertical"
              setLayoutMode(nextLayout)
              loadGraph(activeProject, entityType, search, nextLayout, hideIsolated)
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-[11px] font-semibold bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700"
            title="Switch layout direction"
          >
            <ArrowLeftRight className="w-3 h-3" />
            <span>{layoutMode === "vertical" ? "Top-Down" : "Left-Right"}</span>
          </button>

          <button
            type="button"
            onClick={() => {
              const nextHide = !hideIsolated
              setHideIsolated(nextHide)
              loadGraph(activeProject, entityType, search, layoutMode, nextHide)
            }}
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-[11px] font-semibold border transition-all ${
              hideIsolated
                ? "bg-violet-600 text-white border-violet-600"
                : "bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-700"
            }`}
            title="Hide isolated nodes with zero links"
          >
            <EyeOff className="w-3 h-3" />
            <span>Hide Isolated</span>
          </button>

          <button
            type="button"
            onClick={() => handleCopyOrDownloadMermaid(false)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-[11px] font-semibold bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700"
            title="Copy Mermaid flowchart code"
          >
            <Copy className="w-3 h-3" />
            <span>{copiedMermaid ? "Copied!" : "Mermaid"}</span>
          </button>

          <button
            type="button"
            onClick={() => handleCopyOrDownloadMermaid(true)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-[11px] font-semibold bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700"
            title="Download .mmd Mermaid file"
          >
            <Download className="w-3 h-3" />
            <span>.mmd</span>
          </button>

          <span className="font-semibold text-slate-700 pl-1">
            {nodes.length} Nodes • {edges.length} Links
            {stats?.density !== undefined ? ` • Density ${stats.density}` : ""}
          </span>
        </div>
      </div>

      {/* Departure Simulation Impact Banner */}
      {departureImpact && (
        <div className="p-3 rounded-2xl bg-rose-50 border border-rose-200 flex flex-col lg:flex-row lg:items-center justify-between gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 font-bold text-rose-900">
              <UserMinus className="w-4 h-4 text-rose-600" />
              Departure Impact: {departureImpact.person_name}
            </span>
            <span className="px-2 py-0.5 rounded-full bg-rose-600 text-white font-bold text-[10px]">
              Bus-Factor Risk: {departureImpact.bus_factor_risk_score}%
            </span>
            <span className="text-rose-800">
              <strong>{departureImpact.orphaned_spofs?.length ?? 0}</strong> orphaned SPOFs •{" "}
              <strong>{departureImpact.affected_entities?.length ?? 0}</strong> downstream impacted nodes
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {(departureImpact.orphaned_spofs || []).slice(0, 4).map((item: any) => (
              <button
                key={item.id}
                type="button"
                onClick={() => focusNodeById(item.id)}
                className="px-2 py-0.5 rounded-full bg-white border border-rose-300 text-rose-800 font-semibold text-[11px] hover:bg-rose-100"
              >
                {item.name} ({item.downstream_count} impact)
              </button>
            ))}
            <button
              type="button"
              onClick={() => handleSimulateDeparture("")}
              className="px-2.5 py-0.5 rounded-lg bg-white border border-slate-200 text-slate-700 font-semibold text-[11px] hover:bg-slate-100"
            >
              Clear Simulation
            </button>
          </div>
        </div>
      )}

      {/* SPOF Warnings */}
      {spofWarnings.length > 0 && (
        <div className="p-2.5 px-3.5 rounded-2xl bg-amber-50 border border-amber-200 flex flex-wrap items-center gap-2 text-xs">
          <div className="flex items-center gap-1.5 font-bold text-amber-800">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <span>Single Points of Failure Detected ({spofWarnings.length}):</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {spofWarnings.slice(0, 6).map((sp: any, idx: number) => {
              const spofName = sp.component_name || sp.name || sp.entity_name || sp.node_name || "Unnamed Component"
              const owner = sp.sole_owner ? ` — Owner: ${sp.sole_owner}` : ""
              const impact = sp.downstream_impact_count ?? sp.dependent_count ?? sp.impact_score
              const impactLabel = impact !== undefined ? `${impact} downstream` : "Critical"
              return (
                <button
                  key={sp.component_id || idx}
                  type="button"
                  onClick={() => focusNodeById(sp.component_id)}
                  className="px-2.5 py-0.5 rounded-full bg-white hover:bg-amber-100 border border-amber-300 text-amber-900 font-semibold text-[11px] transition-colors cursor-pointer"
                  title="Click to focus node and inspect blast radius"
                >
                  {spofName}
                  <span className="font-normal text-amber-700">{owner} ({impactLabel})</span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Interactive Graph Canvas */}
      <div
        data-testid="graph-canvas"
        className="apple-card relative h-[calc(100vh-300px)] min-h-[380px] max-h-[580px] w-full overflow-hidden border border-slate-200 bg-[#FAFBFF]"
      >
        {loading ? (
          <div className="h-full flex items-center justify-center text-xs text-slate-400">
            Loading topological knowledge graph...
          </div>
        ) : nodes.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-3">
            <Network className="w-10 h-10 text-slate-300" />
            <h3 className="text-sm font-bold text-slate-800">No Knowledge Graph Entities Yet</h3>
            <p className="text-xs text-slate-500 max-w-md">
              Sync an integration or upload documents first, then click &ldquo;AI Extract Knowledge Graph&rdquo; to map services, owners, decisions, and risks.
            </p>
          </div>
        ) : (
          <ReactFlow
            nodes={renderedNodes}
            edges={renderedEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onInit={setRfInstance}
            minZoom={0.2}
            maxZoom={1.75}
            fitView
            fitViewOptions={{ padding: 0.16, maxZoom: 0.95 }}
            zoomOnScroll={false}
            panOnScroll={false}
            zoomOnPinch
            zoomOnDoubleClick={false}
          >
            <AutoFitView fitKey={`${activeProject}:${entityType}:${layoutMode}:${hideIsolated}:${nodes.length}`} />
            <Background color="#CBD5E1" gap={18} />
            <Controls showInteractive={false} />
            <MiniMap zoomable pannable nodeColor="#7C3AED" />
            <Panel position="top-right" className="flex items-center gap-2">
              <span className="hidden sm:inline-block px-2.5 py-1 rounded-lg bg-white/90 border border-slate-200 text-[10px] text-slate-500 shadow-xs">
                Click any node for blast radius • Drag canvas to pan
              </span>
              <button
                type="button"
                onClick={() => rfInstance?.fitView({ padding: 0.16, maxZoom: 0.95, duration: 250 })}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white hover:bg-slate-50 border border-slate-200 text-[11px] font-semibold text-slate-700 shadow-xs"
              >
                <Maximize2 className="w-3 h-3" />
                <span>Fit View</span>
              </button>
            </Panel>
          </ReactFlow>
        )}

        {/* Light Lavender Blast Radius Drawer */}
        {selectedNode && (
          <div className="absolute right-4 top-4 bottom-4 w-80 sm:w-96 rounded-2xl border border-slate-200 bg-white/95 backdrop-blur-xl p-5 shadow-2xl z-20 flex flex-col justify-between overflow-y-auto">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span
                  className="text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase border border-violet-200 bg-violet-50 text-violet-700"
                >
                  {selectedNode.data?.entityType || "entity"}
                </span>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="text-slate-400 hover:text-slate-700 p-1 rounded-lg hover:bg-slate-100"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div>
                <h2 className="text-base font-bold text-slate-900">{selectedNode.data?.label}</h2>
                <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                  {selectedNode.data?.description || "No entity description recorded yet."}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-slate-100">
                <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-100">
                  <span className="text-[10px] text-slate-400 uppercase font-bold block">Confidence</span>
                  <span className="font-bold text-emerald-700">
                    {Math.round((selectedNode.data?.confidence || 0.75) * 100)}%
                  </span>
                </div>
                <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-100">
                  <span className="text-[10px] text-slate-400 uppercase font-bold block">Verification</span>
                  <span className="font-semibold text-slate-800 text-[11px]">
                    {selectedNode.data?.verificationStatus || "Needs Review"}
                  </span>
                </div>
              </div>

              {loadingBlast ? (
                <div className="p-3 text-xs text-slate-400 text-center">Calculating blast radius...</div>
              ) : blastRadius ? (
                <div className="space-y-3">
                  {/* Downstream */}
                  <div className="p-3.5 rounded-xl bg-rose-50/70 border border-rose-200 space-y-2">
                    <div className="flex items-center justify-between text-xs font-bold text-rose-800">
                      <span className="flex items-center gap-1.5">
                        <Zap className="w-3.5 h-3.5 text-rose-600" /> Downstream Impact
                      </span>
                      <span>{blastRadius.affected_count ?? 0} nodes</span>
                    </div>
                    {blastRadius.affected_entities?.length > 0 ? (
                      <ul className="space-y-1 text-[11px] text-rose-900">
                        {blastRadius.affected_entities.map((item: any) => (
                          <li key={item.id} className="flex items-center gap-1">
                            <ArrowDownRight className="w-3 h-3 text-rose-500 flex-shrink-0" />
                            <span className="truncate font-medium">{item.name}</span>
                            <span className="text-rose-500 text-[10px]">({item.entity_type})</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-[11px] text-rose-700/80">No downstream transitive dependents detected.</p>
                    )}
                  </div>

                  {/* Upstream */}
                  <div className="p-3.5 rounded-xl bg-sky-50/70 border border-sky-200 space-y-2">
                    <div className="flex items-center justify-between text-xs font-bold text-sky-800">
                      <span className="flex items-center gap-1.5">
                        <ArrowUpRight className="w-3.5 h-3.5 text-sky-600" /> Upstream Dependencies
                      </span>
                      <span>{blastRadius.upstream_count ?? 0} nodes</span>
                    </div>
                    {blastRadius.upstream_entities?.length > 0 ? (
                      <ul className="space-y-1 text-[11px] text-sky-900">
                        {blastRadius.upstream_entities.map((item: any) => (
                          <li key={item.id} className="truncate font-medium">
                            • {item.name} <span className="text-sky-600 text-[10px]">({item.entity_type})</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-[11px] text-sky-700/80">No upstream dependencies recorded.</p>
                    )}
                  </div>
                </div>
              ) : null}

              {/* SPOF Mitigation: Assign Backup Owner */}
              {(selectedNode.data?.entityType || "").toLowerCase() !== "person" && (
                <form
                  onSubmit={handleAssignBackup}
                  className="p-3.5 rounded-xl bg-violet-50/70 border border-violet-200 space-y-2.5"
                >
                  <div className="flex items-center justify-between text-xs font-bold text-violet-900">
                    <span className="flex items-center gap-1.5">
                      <UserPlus className="w-3.5 h-3.5 text-violet-600" />
                      {selectedNode.data?.isSpof ? "Mitigate SPOF — Assign Backup" : "Assign Secondary Owner"}
                    </span>
                  </div>
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      list="graph-people-suggestions"
                      value={backupOwnerName}
                      onChange={(e) => setBackupOwnerName(e.target.value)}
                      placeholder="Backup engineer name..."
                      className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg text-xs bg-white border border-violet-200 focus:outline-none focus:border-violet-500"
                    />
                    <datalist id="graph-people-suggestions">
                      {peopleList.map((p: any) => (
                        <option key={p.id} value={p.name} />
                      ))}
                    </datalist>
                    <select
                      value={backupRelationType}
                      onChange={(e) => setBackupRelationType(e.target.value as "maintains" | "owns")}
                      className="px-2 py-1.5 rounded-lg text-[11px] font-semibold bg-white border border-violet-200 text-slate-700"
                    >
                      <option value="maintains">maintains</option>
                      <option value="owns">owns</option>
                    </select>
                  </div>
                  <button
                    type="submit"
                    disabled={assigningBackup || !backupOwnerName.trim()}
                    className="w-full py-1.5 rounded-lg text-xs font-semibold bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white transition-colors"
                  >
                    {assigningBackup ? "Assigning..." : "Assign Backup Owner"}
                  </button>
                </form>
              )}
            </div>

            <div className="pt-4 border-t border-slate-100 mt-4">
              <span className="text-[10px] text-slate-500 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                Computed dynamically via NetworkX dependency traversal
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
