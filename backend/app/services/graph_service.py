import re
from typing import Any, Dict, List, Optional
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

    RELATION_WEIGHTS: Dict[str, float] = {
        "owns": 1.0,
        "maintains": 0.85,
        "decided": 0.65,
        "reviews": 0.45,
        "backup_for": 0.5,
        "contributes": 0.35,
    }

    def _compute_weighted_ownership(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Compute per-target weighted contributor scores, shares, and primary flags."""
        ent_by_id = {e["id"]: e for e in entities}
        raw_by_target: Dict[str, Dict[str, Dict[str, Any]]] = {}

        for r in relationships:
            rel = (r.get("relation_type") or "").lower()
            base_w = self.RELATION_WEIGHTS.get(rel)
            if base_w is None:
                continue
            src_id = r.get("source_entity_id")
            dst_id = r.get("target_entity_id")
            src_ent = ent_by_id.get(src_id)
            dst_ent = ent_by_id.get(dst_id)
            if not src_ent or not dst_ent:
                continue
            if (src_ent.get("entity_type") or "").lower() != "person":
                continue

            conf = float(r.get("confidence") if r.get("confidence") is not None else 1.0)
            conf = max(0.35, min(1.0, conf))
            explicit_w = 1.0
            if isinstance(r.get("properties"), dict) and r["properties"].get("weight") is not None:
                try:
                    explicit_w = max(0.1, float(r["properties"]["weight"]))
                except (TypeError, ValueError):
                    explicit_w = 1.0
            edge_w = base_w * conf * explicit_w

            target_map = raw_by_target.setdefault(dst_id, {})
            entry = target_map.setdefault(
                src_id,
                {
                    "person_id": src_id,
                    "name": src_ent.get("name", "Owner"),
                    "weights": [],
                    "is_primary": False,
                },
            )
            entry["weights"].append(edge_w)
            if rel in ("owns", "maintains", "decided", "backup_for"):
                entry["is_primary"] = True

        # Aggregate per-person score cleanly (max weight + diminishing 0.25 bonus for additional signals)
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for dst_id, pmap in raw_by_target.items():
            scored: Dict[str, Dict[str, Any]] = {}
            total_w = 0.0
            for pid, info in pmap.items():
                ws = sorted(info["weights"], reverse=True)
                agg = ws[0] + sum(0.25 * w for w in ws[1:])
                scored[pid] = {
                    "person_id": pid,
                    "name": info["name"],
                    "weight": round(agg, 4),
                    "is_primary": info["is_primary"],
                }
                total_w += agg
            if total_w > 0:
                for pid in scored:
                    scored[pid]["share"] = round(scored[pid]["weight"] / total_w, 4)
            else:
                for pid in scored:
                    scored[pid]["share"] = 0.0
            result[dst_id] = scored
        return result

    def detect_single_points_of_failure(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Identify components/services with single-owner or >=80% weighted BusFactor concentration."""
        ent_by_id = {e["id"]: e for e in entities}
        G = self.build_graph(entities, relationships)
        ownership = self._compute_weighted_ownership(entities, relationships)

        spofs: List[Dict[str, Any]] = []
        for target_id, owners_map in ownership.items():
            if not owners_map:
                continue
            comp = ent_by_id.get(target_id)
            if not comp:
                continue
            primary_owners = [info for info in owners_map.values() if info["is_primary"]]
            if not primary_owners:
                continue

            ranked = sorted(owners_map.values(), key=lambda x: x["weight"], reverse=True)
            top = ranked[0]
            shares = [info["share"] for info in ranked if info["share"] > 0]
            hhi = sum(s * s for s in shares) if shares else 1.0
            effective_bus_factor = round(1.0 / max(hhi, 1e-6), 2)

            is_single_primary = len(primary_owners) == 1 and len(owners_map) == 1
            is_dominant_concentration = top["share"] >= 0.80

            if is_single_primary or is_dominant_concentration:
                downstream = self.calculate_blast_radius(G, target_id)
                if top["share"] >= 0.99 and len(downstream) >= 2:
                    severity = "critical"
                elif is_single_primary or top["share"] >= 0.88:
                    severity = "high"
                else:
                    severity = "medium"

                spofs.append({
                    "component_id": target_id,
                    "component_name": comp.get("name"),
                    "component_type": comp.get("entity_type"),
                    "sole_owner": top["name"],
                    "downstream_impact_count": len(downstream),
                    "ownership_share": top["share"],
                    "effective_bus_factor": effective_bus_factor,
                    "spof_severity": severity,
                    "owner_breakdown": [
                        {"name": o["name"], "share": o["share"], "weight": o["weight"]}
                        for o in ranked
                    ],
                })
        return spofs

    def _compute_layout(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        G: nx.DiGraph,
        layout: str = "vertical",
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

        is_horizontal = (layout or "vertical").lower() == "horizontal"
        positions: Dict[str, Dict[str, float]] = {}

        if is_horizontal:
            col_gap = 285.0
            slot_gap = 128.0
            subcol_gap = 250.0
            max_rows = 5
            current_x = 0.0
            for l_idx in sorted(by_layer.keys()):
                col_ids = by_layer[l_idx]
                chunks = [col_ids[i : i + max_rows] for i in range(0, len(col_ids), max_rows)]
                for c_idx, chunk in enumerate(chunks):
                    col_height = (len(chunk) - 1) * slot_gap
                    start_y = -col_height / 2.0
                    for idx, nid in enumerate(chunk):
                        positions[nid] = {
                            "x": round(current_x + c_idx * subcol_gap, 1),
                            "y": round(start_y + idx * slot_gap, 1),
                        }
                current_x += max(1, len(chunks)) * subcol_gap + (col_gap - subcol_gap)
            return positions

        x_gap = 255.0
        y_gap = 155.0
        subrow_gap = 125.0
        max_cols = 5

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

    def simulate_person_departure(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        person_id: str,
    ) -> Dict[str, Any]:
        """Simulate weighted ownership disruption, orphaned SPOFs, and downstream blast radius on departure."""
        ent_by_id = {e["id"]: e for e in entities}
        person = ent_by_id.get(person_id)
        if not person:
            return {
                "person_id": person_id,
                "person_name": "Unknown",
                "orphaned_spofs": [],
                "backed_up_components": [],
                "affected_node_ids": [],
                "affected_entities": [],
                "bus_factor_risk_score": 0,
            }

        G = self.build_graph(entities, relationships)
        ownership = self._compute_weighted_ownership(entities, relationships)

        person_owned_ids: List[str] = []
        for dst_id, pmap in ownership.items():
            pinfo = pmap.get(person_id)
            if pinfo and (pinfo["is_primary"] or pinfo["share"] >= 0.25):
                person_owned_ids.append(dst_id)

        orphaned_spofs: List[Dict[str, Any]] = []
        backed_up_components: List[Dict[str, Any]] = []
        affected_ids_set: set[str] = set()

        for comp_id in person_owned_ids:
            comp = ent_by_id.get(comp_id)
            if not comp:
                continue
            pmap = ownership.get(comp_id, {})
            person_share = pmap.get(person_id, {}).get("share", 1.0)
            other_entries = [info for oid, info in pmap.items() if oid != person_id]
            other_owners = [info["name"] for info in other_entries]
            downstream_ids = self.calculate_blast_radius(G, comp_id)
            entry = {
                "id": comp_id,
                "name": comp.get("name"),
                "entity_type": comp.get("entity_type"),
                "downstream_count": len(downstream_ids),
                "other_owners": other_owners,
                "departing_share": person_share,
            }
            # Component becomes orphaned if no other primary/meaningful owner remains OR departing held >=80%
            if not other_owners or person_share >= 0.80:
                orphaned_spofs.append(entry)
                affected_ids_set.add(comp_id)
                affected_ids_set.update(downstream_ids)
            else:
                backed_up_components.append(entry)

        total_non_person = max(
            1, sum(1 for e in entities if (e.get("entity_type") or "").lower() != "person")
        )
        orphan_ratio = sum(o.get("departing_share", 1.0) for o in orphaned_spofs) / total_non_person
        blast_ratio = len(affected_ids_set) / max(1, len(entities))
        risk_score = min(100, round((orphan_ratio * 65 + blast_ratio * 35) * 100)) if orphaned_spofs else 0

        affected_entities = [
            {
                "id": e["id"],
                "name": e.get("name"),
                "entity_type": e.get("entity_type"),
            }
            for e in entities
            if e["id"] in affected_ids_set and e["id"] != person_id
        ]

        return {
            "person_id": person_id,
            "person_name": person.get("name"),
            "owned_count": len(person_owned_ids),
            "orphaned_spofs": orphaned_spofs,
            "backed_up_components": backed_up_components,
            "affected_node_ids": sorted(affected_ids_set),
            "affected_entities": affected_entities,
            "bus_factor_risk_score": risk_score,
        }

    def to_mermaid(self, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]]) -> str:
        """Render a clean Mermaid flowchart TD diagram of project entities and dependencies."""
        lines = ["flowchart TD"]
        id_map: Dict[str, str] = {}
        for idx, e in enumerate(entities):
            raw_id = str(e.get("id") or f"n{idx}")
            safe_id = "N_" + re.sub(r"[^A-Za-z0-9_]", "_", raw_id)[:32]
            id_map[raw_id] = safe_id
            label = str(e.get("name") or "Entity").replace('"', "'").replace("\n", " ")[:60]
            etype = str(e.get("entity_type") or "component").upper()
            lines.append(f'    {safe_id}["{etype}: {label}"]')

        for r in relationships:
            src = id_map.get(str(r.get("source_entity_id")))
            dst = id_map.get(str(r.get("target_entity_id")))
            if src and dst:
                rel_lbl = str(r.get("relation_type") or "depends_on").replace("_", " ").replace('"', "'")[:32]
                lines.append(f"    {src} -->|{rel_lbl}| {dst}")

        return "\n".join(lines)

    def to_react_flow(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        layout: str = "vertical",
        hide_isolated: bool = False,
    ) -> Dict[str, Any]:
        full_graph = self.build_graph(entities, relationships)
        spofs = self.detect_single_points_of_failure(entities, relationships)
        spof_by_id = {s["component_id"]: s for s in spofs}

        # Summarize people nodes for What-If Departure selector
        spofs_by_owner: Dict[str, int] = {}
        for s in spofs:
            owner_name = s.get("sole_owner")
            if owner_name:
                spofs_by_owner[owner_name] = spofs_by_owner.get(owner_name, 0) + 1

        people_summary: List[Dict[str, Any]] = []
        for e in entities:
            if (e.get("entity_type") or "").lower() == "person":
                eid = e["id"]
                owned_cnt = sum(
                    1
                    for r in relationships
                    if r.get("source_entity_id") == eid
                    and (r.get("relation_type") or "").lower() in ("owns", "maintains", "decided")
                )
                people_summary.append({
                    "id": eid,
                    "name": e.get("name"),
                    "owned_count": owned_cnt,
                    "spof_count": spofs_by_owner.get(e.get("name") or "", 0),
                })

        active_entities = entities
        active_relationships = relationships
        hidden_isolated_count = 0
        if hide_isolated and len(entities) > 0:
            connected_entities = [e for e in entities if full_graph.degree(e["id"]) > 0]
            if connected_entities:
                hidden_isolated_count = len(entities) - len(connected_entities)
                active_entities = connected_entities
                allowed = {e["id"] for e in active_entities}
                active_relationships = [
                    r for r in relationships
                    if r.get("source_entity_id") in allowed and r.get("target_entity_id") in allowed
                ]

        G = self.build_graph(active_entities, active_relationships)
        pageranks = self.calculate_centrality(G)

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

        clean_layout = "horizontal" if (layout or "").lower() == "horizontal" else "vertical"
        positions = self._compute_layout(active_entities, active_relationships, G, layout=clean_layout)
        nodes = []

        for e in active_entities:
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
                    "ownershipShare": spof_info.get("ownership_share") if spof_info else None,
                    "effectiveBusFactor": spof_info.get("effective_bus_factor") if spof_info else None,
                    "spofSeverity": spof_info.get("spof_severity") if spof_info else None,
                    "layout": clean_layout,
                    "color": theme["border"],
                    "bg": theme["bg"],
                    "textColor": theme["text"],
                },
            })

        edges = []
        for i, r in enumerate(active_relationships):
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
            "people": people_summary,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "spof_count": len(spofs),
                "hidden_isolated_count": hidden_isolated_count,
                "layout": clean_layout,
                "density": round(nx.density(G), 3) if len(nodes) > 1 else 0,
            },
        }


graph_service = GraphService()
