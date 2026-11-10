"use client"

import { useEffect, useState, useCallback } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { api } from "@/lib/api"
import {
  Network,
  Sparkles,
  AlertTriangle,
  Search,
  Zap,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  X,
} from "lucide-react"

const ENTITY_TYPES = [
  "All",
  "person",
  "service",
  "database",
  "infrastructure",
  "external_service",
  "decision",
  "risk",
]

export default function KnowledgeGraphPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([])
  const [projects, setProjects] = useState<any[]>([])
  const [activeProject, setActiveProject] = useState("")
  const [entityType, setEntityType] = useState("All")
  const [search, setSearch] = useState("")
  const [spofWarnings, setSpofWarnings] = useState<any[]>([])
  const [stats, setStats] = useState<any>({})
  const [loading, setLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)
  const [statusMsg, setStatusMsg] = useState("")

  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [blastRadius, setBlastRadius] = useState<any>(null)
  const [loadingBlast, setLoadingBlast] = useState(false)

  const loadGraph = async (pid?: string, etype?: string, q?: string) => {
    try {
      setLoading(true)
      const storedPid =
        pid !== undefined
          ? pid
          : typeof window !== "undefined"
          ? localStorage.getItem("obsidian_active_project") || ""
          : ""
      const [projs, graphRes] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getGraphReactFlow(storedPid || undefined, etype, q || undefined).catch(() => ({ nodes: [], edges: [], spof_warnings: [], stats: {} })),
      ])
      setProjects(Array.isArray(projs) ? projs : [])
      const resolvedPid = storedPid || (Array.isArray(projs) && projs[0]?.id) || ""
      if (pid === undefined) setActiveProject(resolvedPid)
      setNodes(graphRes.nodes || [])
      setEdges(graphRes.edges || [])
      setSpofWarnings(graphRes.spof_warnings || [])
      setStats(graphRes.stats || {})
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadGraph(undefined, entityType, search)
  }, [])

  const handleFilterChange = (nextType: string, nextSearch: string, nextPid: string) => {
    setEntityType(nextType)
    setSearch(nextSearch)
    loadGraph(nextPid, nextType, nextSearch)
  }

  const handleExtract = async () => {
    const pid = activeProject || projects[0]?.id
    if (!pid) {
      alert("Select or create a project first.")
      return
    }
    try {
      setExtracting(true)
      setStatusMsg("")
      const res = await api.extractKnowledgeGraph(pid)
      setStatusMsg(res.message || "Extracted entities, relationships, ADRs, risks, and dependencies from project evidence.")
      await loadGraph(pid, entityType, search)
    } catch (err: any) {
      alert(err.message || "AI Knowledge Extraction failed.")
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

  return (
    <div className="p-6 max-w-[1440px] mx-auto space-y-4">
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
              if (typeof window !== "undefined") {
                if (pid) localStorage.setItem("obsidian_active_project", pid)
                else localStorage.removeItem("obsidian_active_project")
                window.dispatchEvent(new Event("obsidian_project_changed"))
              }
              handleFilterChange(entityType, search, pid)
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

      {statusMsg && (
        <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium">
          {statusMsg}
        </div>
      )}

      {/* Search & Entity Filters + SPOF Summary */}
      <div className="apple-card p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 flex-1">
          <div className="relative flex-1 min-w-[220px] max-w-sm">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => handleFilterChange(entityType, e.target.value, activeProject)}
              placeholder="Search nodes by name or description..."
              className="w-full pl-9 pr-3 py-1.5 rounded-xl text-xs bg-slate-50 border border-slate-200 text-slate-900 focus:outline-none focus:border-violet-500 focus:bg-white"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {ENTITY_TYPES.map((et) => (
              <button
                key={et}
                onClick={() => handleFilterChange(et, search, activeProject)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold capitalize border transition-all ${
                  entityType === et
                    ? "bg-violet-600 text-white border-violet-600"
                    : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
                }`}
              >
                {et.replace("_", " ")}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="font-semibold text-slate-700">{nodes.length} Nodes</span>
          <span>•</span>
          <span className="font-semibold text-slate-700">{edges.length} Relationships</span>
          {stats?.density !== undefined && (
            <>
              <span>•</span>
              <span>Density: {stats.density}</span>
            </>
          )}
        </div>
      </div>

      {/* SPOF Warnings */}
      {spofWarnings.length > 0 && (
        <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 font-bold text-amber-800">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <span>Single Points of Failure Detected ({spofWarnings.length}):</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {spofWarnings.slice(0, 5).map((sp: any, idx: number) => (
              <span key={idx} className="px-2.5 py-0.5 rounded-full bg-white border border-amber-200 text-amber-800 font-semibold text-[11px]">
                {sp.name || sp.entity_name || sp.node_name} ({sp.dependent_count ?? sp.impact_score ?? "Critical"})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Interactive Graph Canvas */}
      <div
        data-testid="graph-canvas"
        className="apple-card relative h-[560px] w-full overflow-hidden border border-slate-200 bg-[#FAFBFF]"
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
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            fitView
          >
            <Background color="#CBD5E1" gap={18} />
            <Controls />
            <MiniMap zoomable pannable nodeColor="#7C3AED" />
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
