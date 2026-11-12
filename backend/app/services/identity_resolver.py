"""Cross-platform contributor identity resolution and duplicate person entity stitching."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.integration import SourceRecord
from app.models.knowledge import (
    KnowledgeEntity,
    KnowledgeRelationship,
    Responsibility,
)
from app.models.workspace import Project, User


def normalize_identifier(value: Optional[str]) -> str:
    """Normalize names, handles, and email local-parts for comparison."""
    text = (value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("@"):
        text = text[1:]
    # Strip trailing platform tags like (github) or [bot]
    text = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def _extract_keys_from_raw(raw: str) -> Tuple[Set[str], Optional[str], Optional[str]]:
    """Return strong match keys, optional email, and optional display score info."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return set(), None, None

    keys: Set[str] = set()
    email: Optional[str] = None

    email_match = re.search(r"([A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+)", cleaned)
    if email_match:
        email = email_match.group(1).lower()
        keys.add(f"email:{email}")
        local = email.split("@", 1)[0]
        local_norm = re.sub(r"[._\-]+", " ", local).strip()
        if local_norm:
            keys.add(f"slug:{local_norm.replace(' ', '')}")
            if " " in local_norm:
                keys.add(f"full:{local_norm}")

    # Remove <email> angle brackets for display/name key extraction
    name_part = re.sub(r"<[^>]+>", "", cleaned).strip()
    norm = normalize_identifier(name_part)
    if norm and "@" not in norm:
        # Strip common dev handle suffixes like -dev, _dev, -gh before splitting tokens
        handle_base = re.sub(r"(?:[-_](?:dev|gh|eng|ops|bot))$", "", norm)
        words = [w for w in re.split(r"[._\-\s]+", handle_base) if w]
        if len(words) >= 2:
            keys.add(f"full:{' '.join(words)}")
            keys.add(f"slug:{''.join(words)}")
        elif words:
            keys.add(f"handle:{words[0]}")
        if handle_base != norm:
            keys.add(f"handle:{re.sub(r'[._\-]+', '', handle_base)}")
            keys.add(f"handle:{norm}")

    display = name_part if name_part and "@" not in name_part else None
    return keys, email, display


def _score_display_name(candidate: str) -> Tuple[int, int, int]:
    """Rank display names so clean 'First Last' wins over emails/@handles."""
    clean = (candidate or "").strip()
    if not clean:
        return (0, 0, 0)
    is_email = 1 if "@" in clean and " " not in clean else 0
    is_at = 1 if clean.startswith("@") else 0
    words = [w for w in re.split(r"\s+", clean) if w]
    has_cap = 1 if any(w[:1].isupper() for w in words) else 0
    return (1 - is_email - is_at, len(words) >= 2 and has_cap or 0, len(clean))


def _extract_raw_authors_from_record(rec: SourceRecord) -> List[Tuple[str, str]]:
    """Collect (raw_identifier, platform) pairs from a SourceRecord."""
    pairs: List[Tuple[str, str]] = []
    platform = (rec.source_type or "source").split("_", 1)[0].lower()
    if rec.author:
        pairs.append((rec.author, platform))

    meta = rec.metadata_json or {}
    payload = rec.raw_payload or {}
    for blob in (meta, payload):
        if not isinstance(blob, dict):
            continue
        for field in (
            "author", "author_name", "author_email", "login", "username",
            "user_name", "real_name", "display_name", "assignee", "reporter",
            "creator", "email", "commit_author",
        ):
            val = blob.get(field)
            if isinstance(val, str) and val.strip():
                pairs.append((val.strip(), platform))
            elif isinstance(val, dict):
                for subk in ("name", "displayName", "login", "username", "email", "real_name"):
                    sv = val.get(subk)
                    if isinstance(sv, str) and sv.strip():
                        pairs.append((sv.strip(), platform))
        user_obj = blob.get("user")
        if isinstance(user_obj, dict):
            for subk in ("name", "login", "real_name", "email", "display_name"):
                sv = user_obj.get(subk)
                if isinstance(sv, str) and sv.strip():
                    pairs.append((sv.strip(), platform))
    return pairs


def build_project_identity_map(project_id: str, db: Session) -> Dict[str, Any]:
    """Build cross-platform contributor identity resolution map for a project."""
    raw_observations: List[Tuple[str, str]] = []  # (raw_value, platform)

    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj and proj.workspace and proj.workspace.org_id:
        users = db.query(User).filter(User.org_id == proj.workspace.org_id).all()
        for u in users:
            if u.name and u.email:
                raw_observations.append((f"{u.name} <{u.email}>", "workspace"))
            elif u.name:
                raw_observations.append((u.name, "workspace"))
            elif u.email:
                raw_observations.append((u.email, "workspace"))

    for rec in db.query(SourceRecord).filter(SourceRecord.project_id == project_id).all():
        raw_observations.extend(_extract_raw_authors_from_record(rec))

    for resp in db.query(Responsibility).filter(Responsibility.project_id == project_id).all():
        if resp.owner:
            raw_observations.append((resp.owner, "responsibility"))
        if resp.backup_owner:
            raw_observations.append((resp.backup_owner, "responsibility"))

    for ent in (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.project_id == project_id, KnowledgeEntity.entity_type == "person")
        .all()
    ):
        if ent.name:
            raw_observations.append((ent.name, "knowledge_graph"))

    # Group distinct normalized raw identifiers via Union-Find on strong keys
    raw_entries: Dict[str, Dict[str, Any]] = {}
    for raw, plat in raw_observations:
        clean = (raw or "").strip()
        if not clean or clean.lower() in ("unknown", "unassigned", "contributor", "code ast indexer", "bot"):
            continue
        norm_raw = clean.lower()
        entry = raw_entries.setdefault(
            norm_raw,
            {"raw_variants": set(), "platforms": set(), "keys": set(), "emails": set(), "displays": set()},
        )
        entry["raw_variants"].add(clean)
        entry["platforms"].add(plat)
        keys, email, disp = _extract_keys_from_raw(clean)
        entry["keys"].update(keys)
        if email:
            entry["emails"].add(email)
        if disp:
            entry["displays"].add(disp)

    # Disjoint set over norm_raw strings
    nodes = list(raw_entries.keys())
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    key_to_nodes: Dict[str, List[str]] = defaultdict(list)
    first_name_to_full_nodes: Dict[str, List[str]] = defaultdict(list)
    for n in nodes:
        for k in raw_entries[n]["keys"]:
            key_to_nodes[k].append(n)
            if k.startswith("full:"):
                first_tok = k[5:].split(" ", 1)[0]
                if len(first_tok) >= 3:
                    first_name_to_full_nodes[first_tok].append(n)

    for k, group in key_to_nodes.items():
        if len(group) > 1:
            anchor = group[0]
            for other in group[1:]:
                union(anchor, other)

    # Connect unambiguous single-token handles (e.g. '@alice' or 'alice-dev') to a single matching First Last
    for n in nodes:
        for k in raw_entries[n]["keys"]:
            if k.startswith("handle:"):
                tok = k[7:]
                # Only match first-name if all full-name hits resolve to the same root
                full_matches = first_name_to_full_nodes.get(tok, [])
                if full_matches:
                    roots = {find(m) for m in full_matches}
                    if len(roots) == 1:
                        union(n, full_matches[0])

    clusters: Dict[str, List[str]] = defaultdict(list)
    for n in nodes:
        clusters[find(n)].append(n)

    profiles: List[Dict[str, Any]] = []
    alias_lookup: Dict[str, str] = {}

    for members in clusters.values():
        all_variants: Set[str] = set()
        all_displays: Set[str] = set()
        all_emails: Set[str] = set()
        platforms: Set[str] = set()
        for m in members:
            ent = raw_entries[m]
            all_variants.update(ent["raw_variants"])
            all_displays.update(ent["displays"])
            all_emails.update(ent["emails"])
            platforms.update(ent["platforms"])

        display_pool = list(all_displays) or list(all_variants)
        canonical_name = max(display_pool, key=_score_display_name)
        canonical_email = sorted(all_emails)[0] if all_emails else None

        aliases_sorted = sorted(all_variants)
        profiles.append(
            {
                "canonical_name": canonical_name,
                "canonical_email": canonical_email,
                "aliases": aliases_sorted,
                "platforms": sorted(platforms),
            }
        )
        for v in all_variants:
            alias_lookup[v.strip().lower()] = canonical_name
            norm_v = normalize_identifier(v)
            if norm_v:
                alias_lookup[norm_v] = canonical_name
        for em in all_emails:
            alias_lookup[em] = canonical_name

    return {"profiles": profiles, "alias_lookup": alias_lookup}


def resolve_author_name(
    raw_author: Optional[str],
    identity_map: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Resolve an arbitrary author string to its canonical project name."""
    if not raw_author or not raw_author.strip():
        return raw_author
    clean = raw_author.strip()
    if not identity_map:
        return clean
    lookup = identity_map.get("alias_lookup") or {}
    hit = lookup.get(clean.lower()) or lookup.get(normalize_identifier(clean))
    if hit:
        return hit
    email_match = re.search(r"([A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+)", clean)
    if email_match:
        hit = lookup.get(email_match.group(1).lower())
        if hit:
            return hit
    return clean


def merge_duplicate_person_entities(
    db: Session,
    project_id: str,
    identity_map: Optional[Dict[str, Any]] = None,
) -> int:
    """Consolidate duplicate person KnowledgeEntity nodes and re-point KnowledgeRelationships."""
    if identity_map is None:
        identity_map = build_project_identity_map(project_id, db)

    person_entities = (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.project_id == project_id, KnowledgeEntity.entity_type == "person")
        .order_by(KnowledgeEntity.created_at.asc())
        .all()
    )
    if len(person_entities) <= 1:
        # Still normalize single node name if better canonical name exists
        for pe in person_entities:
            resolved = resolve_author_name(pe.name, identity_map)
            if resolved and resolved != pe.name:
                pe.name = resolved[:255]
        return 0

    grouped: Dict[str, List[KnowledgeEntity]] = defaultdict(list)
    for pe in person_entities:
        canon = resolve_author_name(pe.name, identity_map) or pe.name
        grouped[canon.strip().lower()].append(pe)

    merged_count = 0
    for canon_lower, group in grouped.items():
        if len(group) == 1:
            pe = group[0]
            resolved = resolve_author_name(pe.name, identity_map)
            if resolved and resolved != pe.name:
                pe.name = resolved[:255]
            continue

        # Keep primary entity (highest confidence, preferring canonical display name)
        canon_display = resolve_author_name(group[0].name, identity_map) or group[0].name
        group.sort(
            key=lambda e: (
                1 if e.name.strip().lower() == canon_display.strip().lower() else 0,
                float(e.confidence or 0.0),
            ),
            reverse=True,
        )
        primary = group[0]
        aliases = set((primary.properties or {}).get("aliases") or [])
        aliases.add(primary.name)

        dup_ids = []
        for dup in group[1:]:
            aliases.add(dup.name)
            aliases.update((dup.properties or {}).get("aliases") or [])
            if dup.description and (not primary.description or len(dup.description) > len(primary.description)):
                primary.description = dup.description
            dup_ids.append(dup.id)

        props = dict(primary.properties or {})
        props["aliases"] = sorted(a for a in aliases if a)
        primary.name = canon_display[:255]
        primary.properties = props

        # Re-point relationships cleanly avoiding duplicates & self-loops
        rels = (
            db.query(KnowledgeRelationship)
            .filter(KnowledgeRelationship.project_id == project_id)
            .all()
        )
        seen_tuples = {
            (r.source_entity_id, r.target_entity_id, r.relation_type)
            for r in rels
            if r.source_entity_id not in dup_ids and r.target_entity_id not in dup_ids
        }
        dup_id_set = set(dup_ids)
        for r in rels:
            touched = False
            src_id = r.source_entity_id
            tgt_id = r.target_entity_id
            if src_id in dup_id_set:
                src_id = primary.id
                touched = True
            if tgt_id in dup_id_set:
                tgt_id = primary.id
                touched = True
            if not touched:
                continue
            key = (src_id, tgt_id, r.relation_type)
            if src_id == tgt_id or key in seen_tuples:
                db.delete(r)
            else:
                r.source_entity_id = src_id
                r.target_entity_id = tgt_id
                seen_tuples.add(key)

        db.flush()
        db.query(KnowledgeEntity).filter(KnowledgeEntity.id.in_(dup_ids)).delete(synchronize_session=False)
        merged_count += len(dup_ids)

    return merged_count
