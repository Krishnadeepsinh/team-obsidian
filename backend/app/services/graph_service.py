import math
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

    def to_react_flow(self, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        G = self.build_graph(entities, relationships)
        pageranks = self.calculate_centrality(G)

        type_colors = {
            "Person": {"bg": "#F5F3FF", "border": "#7C3AED", "text": "#4C1D95"},
            "Project": {"bg": "#EFF6FF", "border": "#0284C7", "text": "#0C4A6E"},
            "Decision": {"bg": "#ECFDF5", "border": "#10B981", "text": "#065F46"},
            "Task": {"bg": "#FFFBEB", "border": "#F59E0B", "text": "#78350F"},
            "Risk": {"bg": "#FEF2F2", "border": "#EF4444", "text": "#7F1D1D"},
            "System": {"bg": "#EEF2FF", "border": "#6366F1", "text": "#312E81"},
            "Service": {"bg": "#EEF2FF", "border": "#6366F1", "text": "#312E81"},
            "Component": {"bg": "#F0F9FF", "border": "#0EA5E9", "text": "#0C4A6E"},
            "Database": {"bg": "#FAF5FF", "border": "#9333EA", "text": "#581C87"},
            "Infrastructure": {"bg": "#F8FAFC", "border": "#475569", "text": "#0F172A"},
            "Vendor": {"bg": "#FDF2F8", "border": "#DB2777", "text": "#831843"},
            "Document": {"bg": "#F8FAFC", "border": "#64748B", "text": "#1E293B"},
        }

        num_nodes = len(entities)
        nodes = []
        radius = max(220, num_nodes * 24)
        angle_step = (2 * math.pi) / max(1, num_nodes)

        for i, e in enumerate(entities):
            node_id = e["id"]
            e_type = e.get("entity_type", "Component")
            theme = type_colors.get(e_type, type_colors["Component"])

            angle = i * angle_step
            x = 450 + radius * math.cos(angle)
            y = 350 + radius * math.sin(angle)
            pr = pageranks.get(node_id, 0.05)

            nodes.append({
                "id": node_id,
                "type": "customKnowledgeNode",
                "position": {"x": round(x, 1), "y": round(y, 1)},
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
                "style": {
                    "stroke": "#EF4444" if is_blocker else "#7C3AED",
                    "strokeWidth": 2 if is_blocker else 1.5,
                },
            })

        spofs = self.detect_single_points_of_failure(entities, relationships)
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
