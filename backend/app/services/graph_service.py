from typing import Any, Dict, List
import networkx as nx


class GraphService:
    """Enterprise Knowledge Graph service powered by NetworkX and React Flow visualization."""

    def build_graph(self, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]]) -> nx.DiGraph:
        G = nx.DiGraph()
        for e in entities:
            G.add_node(
                e["id"],
                label=e.get("name", e.get("title", "Unknown")),
                entity_type=e.get("entity_type", "Component"),
                confidence=e.get("confidence", 0.5),
                properties=e.get("properties", {}),
            )

        for r in relationships:
            src = r["source_entity_id"]
            dst = r["target_entity_id"]
            if G.has_node(src) and G.has_node(dst):
                G.add_edge(
                    src,
                    dst,
                    id=r.get("id"),
                    relation_type=r.get("relation_type", "depends_on"),
                    context=r.get("context", ""),
                    confidence=r.get("confidence", 0.5),
                )
        return G

    def calculate_centrality(self, G: nx.DiGraph) -> Dict[str, float]:
        if len(G.nodes) == 0:
            return {}
        try:
            return nx.pagerank(G, alpha=0.85)
        except Exception:
            return nx.degree_centrality(G)

    def calculate_blast_radius(self, G: nx.DiGraph, node_id: str) -> List[str]:
        if not G.has_node(node_id):
            return []
        try:
            return list(nx.descendants(G, node_id))
        except Exception:
            return []

    def calculate_upstream_dependencies(self, G: nx.DiGraph, node_id: str) -> List[str]:
        if not G.has_node(node_id):
            return []
        try:
            return list(nx.ancestors(G, node_id))
        except Exception:
            return []

    def detect_single_points_of_failure(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Identify components/services owned or maintained by a single person."""
        ent_by_id = {e["id"]: e for e in entities}
        owners_by_target: Dict[str, List[str]] = {}
        G = self.build_graph(entities, relationships)

        for r in relationships:
            rel = (r.get("relation_type") or "").lower()
            src_ent = ent_by_id.get(r["source_entity_id"])
            dst_ent = ent_by_id.get(r["target_entity_id"])
            if not src_ent or not dst_ent:
                continue
            if rel in ("owns", "maintains", "decided") and (src_ent.get("entity_type") or "").lower() == "person":
                owners_by_target.setdefault(dst_ent["id"], []).append(src_ent["name"])

        spofs: List[Dict[str, Any]] = []
        for target_id, owners in owners_by_target.items():
            unique_owners = sorted(set(owners))
            if len(unique_owners) == 1:
                comp = ent_by_id[target_id]
                downstream = self.calculate_blast_radius(G, target_id)
                spofs.append({
                    "component_id": target_id,
                    "component_name": comp.get("name"),
                    "component_type": comp.get("entity_type"),
                    "sole_owner": unique_owners[0],
                    "downstream_impact_count": len(downstream),
                })
        return spofs

    def _compute_layout(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        G: nx.DiGraph,
    ) -> Dict[str, Dict[str, float]]:
        """Compute non-overlapping layered hierarchical coordinates with compact row wrapping."""
        if not entities:
            return {}

        ent_ids = [e["id"] for e in entities]
        isolated = [nid for nid in ent_ids if G.in_degree(nid) == 0 and G.out_degree(nid) == 0]
        connected = [nid for nid in ent_ids if nid not in set(isolated)]

        layers: Dict[str, int] = {}
        if connected:
            seeds = [nid for nid in connected if G.in_degree(nid) == 0]
            if not seeds:
                # Cycle-only subgraph: seed from highest net out-degree
                seeds = [max(connected, key=lambda n: G.out_degree(n) - G.in_degree(n))]

            queue = list(seeds)
            for s in seeds:
                layers[s] = 0

            max_depth = len(connected)
            while queue:
                curr = queue.pop(0)
                curr_layer = layers[curr]
                if curr_layer >= max_depth:
                    continue
                for nxt in G.successors(curr):
                    if nxt not in layers or (layers[nxt] < curr_layer + 1 and nxt not in seeds):
                        # Guard against infinite cycles
                        if curr_layer + 1 <= max_depth:
                            layers[nxt] = curr_layer + 1
                            queue.append(nxt)

            # Assign any remaining disconnected cyclic components
            for nid in connected:
                if nid not in layers:
                    layers[nid] = 0
                    subq = [nid]
                    while subq:
                        curr = subq.pop(0)
                        for nxt in G.successors(curr):
                            if nxt not in layers and layers[curr] + 1 <= max_depth:
                                layers[nxt] = layers[curr] + 1
                                subq.append(nxt)

        by_layer: Dict[int, List[str]] = {}
        for nid in connected:
            by_layer.setdefault(layers.get(nid, 0), []).append(nid)

        if isolated:
            iso_layer = (max(by_layer.keys()) + 1) if by_layer else 0
            by_layer[iso_layer] = isolated

        # Order each layer by average parent x-slot so edges stay short and untangled
        col_index: Dict[str, float] = {}
        for l_idx in sorted(by_layer.keys()):
            row_ids = by_layer[l_idx]
            if l_idx > 0:
                def _parent_barycenter(nid: str) -> tuple:
                    preds = [col_index[p] for p in G.predecessors(nid) if p in col_index]
                    return (sum(preds) / len(preds) if preds else 9999.0, -G.degree(nid), nid)
                row_ids.sort(key=_parent_barycenter)
            else:
                row_ids.sort(key=lambda nid: (-G.out_degree(nid), nid))
            for idx, nid in enumerate(row_ids):
                col_index[nid] = float(idx)

        x_gap = 270.0
        y_gap = 190.0
        subrow_gap = 145.0
        max_cols = 5

        positions: Dict[str, Dict[str, float]] = {}
        current_y = 0.0
        for l_idx in sorted(by_layer.keys()):
            row_ids = by_layer[l_idx]
            chunks = [row_ids[i : i + max_cols] for i in range(0, len(row_ids), max_cols)]
            for c_idx, chunk in enumerate(chunks):
                row_width = (len(chunk) - 1) * x_gap
                start_x = -row_width / 2.0
                for idx, nid in enumerate(chunk):
                    positions[nid] = {
                        "x": round(start_x + idx * x_gap, 1),
                        "y": round(current_y + c_idx * subrow_gap, 1),
                    }
            current_y += max(1, len(chunks)) * subrow_gap + (y_gap - subrow_gap)

        return positions

    def to_react_flow(self, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        G = self.build_graph(entities, relationships)
        pageranks = self.calculate_centrality(G)
        spofs = self.detect_single_points_of_failure(entities, relationships)
        spof_by_id = {s["component_id"]: s for s in spofs}

        type_colors = {
            "person": {"bg": "#F5F3FF", "border": "#7C3AED", "text": "#5B21B6"},
            "project": {"bg": "#EFF6FF", "border": "#0284C7", "text": "#0C4A6E"},
            "decision": {"bg": "#ECFDF5", "border": "#10B981", "text": "#065F46"},
            "task": {"bg": "#FFFBEB", "border": "#F59E0B", "text": "#78350F"},
            "risk": {"bg": "#FEF2F2", "border": "#EF4444", "text": "#7F1D1D"},
            "system": {"bg": "#EEF2FF", "border": "#6366F1", "text": "#312E81"},
            "service": {"bg": "#EEF2FF", "border": "#6366F1", "text": "#312E81"},
            "component": {"bg": "#F0F9FF", "border": "#0EA5E9", "text": "#0C4A6E"},
            "database": {"bg": "#FAF5FF", "border": "#9333EA", "text": "#581C87"},
            "infrastructure": {"bg": "#F1F5F9", "border": "#475569", "text": "#0F172A"},
            "external_service": {"bg": "#FDF2F8", "border": "#DB2777", "text": "#831843"},
            "vendor": {"bg": "#FDF2F8", "border": "#DB2777", "text": "#831843"},
            "organization": {"bg": "#FFF7ED", "border": "#EA580C", "text": "#9A3412"},
            "document": {"bg": "#F8FAFC", "border": "#64748B", "text": "#1E293B"},
        }

        positions = self._compute_layout(entities, relationships, G)
        nodes = []

        for e in entities:
            node_id = e["id"]
            e_type = e.get("entity_type", "Component")
            theme = type_colors.get((e_type or "component").strip().lower(), type_colors["component"])
            pr = pageranks.get(node_id, 0.05)
            spof_info = spof_by_id.get(node_id)

            nodes.append({
                "id": node_id,
                "type": "customKnowledgeNode",
                "position": positions.get(node_id, {"x": 0.0, "y": 0.0}),
                "data": {
                    "id": node_id,
                    "label": e.get("name", e.get("title", "Entity")),
                    "entityType": e_type,
                    "description": e.get("description", ""),
                    "confidence": e.get("confidence", 0.5),
                    "verificationStatus": e.get("verification_status", "Needs Human Verification"),
                    "importance": round(pr * 100, 1),
                    "degree": G.degree(node_id) if G.has_node(node_id) else 0,
                    "evidenceId": e.get("evidence_id"),
                    "isSpof": spof_info is not None,
                    "soleOwner": spof_info["sole_owner"] if spof_info else None,
                    "downstreamImpactCount": spof_info["downstream_impact_count"] if spof_info else 0,
                    "color": theme["border"],
                    "bg": theme["bg"],
                    "textColor": theme["text"],
                },
            })

        edges = []
        for i, r in enumerate(relationships):
            rel_type = r.get("relation_type", "depends_on")
            is_blocker = "block" in rel_type.lower() or "depend" in rel_type.lower()
            edges.append({
                "id": r.get("id", f"edge-{i}"),
                "source": r["source_entity_id"],
                "target": r["target_entity_id"],
                "label": rel_type.replace("_", " "),
                "animated": is_blocker,
                "labelStyle": {"fontSize": 10, "fontWeight": 600, "fill": "#475569"},
                "labelBgStyle": {"fill": "#FFFFFF", "fillOpacity": 0.92},
                "labelBgPadding": [6, 3],
                "labelBgBorderRadius": 6,
                "style": {
                    "stroke": "#EF4444" if is_blocker else "#7C3AED",
                    "strokeWidth": 2 if is_blocker else 1.5,
                },
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "spof_warnings": spofs,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "spof_count": len(spofs),
                "density": round(nx.density(G), 3) if len(nodes) > 1 else 0,
            },
        }


graph_service = GraphService()
