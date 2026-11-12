import ast
import base64
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models.knowledge import Dependency, KnowledgeEntity, KnowledgeRelationship
from app.services.connectors.base import compute_sha256

logger = logging.getLogger("team_obsidian.ast_indexer")

_PRIORITY_MANIFESTS = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "procfile",
}


def build_repo_web_url(
    provider: str,
    base_url: Optional[str],
    owner_repo: str,
    branch: str,
    file_path: str = "",
) -> str:
    """Construct provider-accurate tree/blob web URLs for GitHub and GitLab (including self-hosted origins)."""
    prov = (provider or "").lower()
    default_host = "https://gitlab.com" if "gitlab" in prov else "https://github.com"
    host = (base_url or default_host).rstrip("/")
    clean_file = (file_path or "").lstrip("/")
    if "gitlab" in prov:
        suffix = f"/-/blob/{branch}/{clean_file}" if clean_file else f"/-/tree/{branch}"
    else:
        suffix = f"/blob/{branch}/{clean_file}" if clean_file else f"/tree/{branch}"
    return f"{host}/{owner_repo}{suffix}"


def _file_priority(path: str) -> Tuple[int, int]:
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    if base in _PRIORITY_MANIFESTS:
        return (0, len(path))
    if any(seg in lower for seg in ("main.", "app.", "server.", "router", "api/", "auth", "database", "config", "service")):
        return (1, len(path))
    if lower.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java")):
        return (2, len(path))
    return (3, len(path))


def _is_candidate_code_file(path: str) -> bool:
    lower = path.lower()
    if any(
        skip in lower
        for skip in (
            "node_modules/",
            ".next/",
            "__pycache__/",
            ".venv/",
            "venv/",
            "target/debug/",
            "target/release/",
            "vendor/",
            "dist/",
            "build/",
            ".git/",
            ".min.js",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "go.sum",
            "cargo.lock",
        )
    ):
        return False
    base = lower.rsplit("/", 1)[-1]
    if base in _PRIORITY_MANIFESTS:
        return True
    return lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"))


def parse_python_source(path: str, code: str) -> Dict[str, Any]:
    """Parse Python file with stdlib ast to extract classes, functions, routes, and imports."""
    imports: List[str] = []
    classes: List[str] = []
    functions: List[str] = []
    routes: List[str] = []

    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return {"path": path, "language": "python", "imports": [], "classes": [], "functions": [], "routes": []}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                imports.append(mod.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if getattr(node, "col_offset", 0) == 0:
                functions.append(node.name)
            for dec in getattr(node, "decorator_list", []):
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr in ("get", "post", "put", "patch", "delete"):
                        route_arg = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else ""
                        if isinstance(route_arg, str):
                            routes.append(f"{dec.func.attr.upper()} {route_arg}")

    return {
        "path": path,
        "language": "python",
        "imports": sorted(set(imports))[:60],
        "classes": sorted(set(classes))[:50],
        "functions": sorted(set(functions))[:60],
        "routes": routes[:50],
    }


def parse_ts_js_source(path: str, code: str) -> Dict[str, Any]:
    """Extract ES/CJS imports, exports, and components from TypeScript/JavaScript source."""
    imports = set(re.findall(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", code or ""))
    exports = set(
        re.findall(
            r"""export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface|type)\s+([A-Za-z0-9_]+)""",
            code or "",
        )
    )
    return {
        "path": path,
        "language": "typescript" if path.lower().endswith((".ts", ".tsx")) else "javascript",
        "imports": sorted(imports)[:60],
        "exports": sorted(exports)[:50],
    }


def parse_go_source(path: str, code: str) -> Dict[str, Any]:
    """Extract Go package imports, structs/interfaces, functions, and HTTP routes."""
    imports = set(re.findall(r'^\s*(?:import\s+)?"([^"\n]+)"', code or "", flags=re.M))
    structs = set(re.findall(r"type\s+([A-Za-z0-9_]+)\s+(?:struct|interface)\b", code or ""))
    funcs = set(re.findall(r"func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(", code or ""))
    routes = re.findall(r'\.(?:GET|POST|PUT|PATCH|DELETE|HandleFunc?)\(\s*"([^"]+)"', code or "")
    return {
        "path": path,
        "language": "go",
        "imports": sorted(imports)[:60],
        "classes": sorted(structs)[:40],
        "functions": sorted(funcs)[:50],
        "routes": [f"HTTP {r}" for r in routes[:40]],
    }


def parse_rust_source(path: str, code: str) -> Dict[str, Any]:
    """Extract Rust crates, structs/enums/traits, functions, and web routes."""
    uses = set(re.findall(r"^\s*use\s+([A-Za-z0-9_]+)(?:::|\s*;)", code or "", flags=re.M))
    structs = set(re.findall(r"\b(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z0-9_]+)", code or ""))
    funcs = set(re.findall(r"\b(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)", code or ""))
    routes = re.findall(r'#\[(?:get|post|put|patch|delete)\(\s*"([^"]+)"', code or "")
    return {
        "path": path,
        "language": "rust",
        "imports": sorted(uses)[:60],
        "classes": sorted(structs)[:40],
        "functions": sorted(funcs)[:50],
        "routes": [f"HTTP {r}" for r in routes[:40]],
    }


def parse_java_source(path: str, code: str) -> Dict[str, Any]:
    """Extract Java imports, classes/interfaces, methods, and Spring mappings."""
    imports = set(re.findall(r"^\s*import\s+([A-Za-z0-9_.]+);", code or "", flags=re.M))
    classes = set(re.findall(r"\b(?:public|private|protected)?\s*(?:class|interface|record|enum)\s+([A-Za-z0-9_]+)", code or ""))
    methods = set(
        re.findall(
            r"^\s*(?:public|private|protected)\s+(?:static\s+|final\s+|synchronized\s+)?[A-Za-z0-9_<>\[\]]+\s+([A-Za-z0-9_]+)\s*\(",
            code or "",
            flags=re.M,
        )
    )
    routes = re.findall(r'@(?:Get|Post|Put|Patch|Delete|Request)Mapping\([^"\)]*"([^"]+)"', code or "")
    return {
        "path": path,
        "language": "java",
        "imports": sorted({i.split(".")[0] for i in imports})[:60],
        "classes": sorted(classes)[:40],
        "functions": sorted(methods - classes)[:60],
        "routes": [f"HTTP {r}" for r in routes[:40]],
    }


def parse_manifest_file(path: str, content: str) -> Dict[str, Any]:
    """Extract structured runtime dependencies and exposed services from repo manifests."""
    lower = path.lower().rsplit("/", 1)[-1]
    deps: List[str] = []
    services: List[str] = []

    if lower == "package.json":
        try:
            data = json.loads(content or "{}")
            for section in ("dependencies", "devDependencies"):
                pkg_map = data.get(section)
                if isinstance(pkg_map, dict):
                    deps.extend(list(pkg_map.keys())[:60])
        except Exception:
            pass
    elif lower == "requirements.txt":
        for line in (content or "").splitlines():
            clean = line.split("#", 1)[0].strip()
            if not clean:
                continue
            pkg = re.split(r"[=<>!~\[]", clean, maxsplit=1)[0].strip()
            if pkg:
                deps.append(pkg)
    elif lower == "pyproject.toml":
        in_deps = False
        for line in (content or "").splitlines():
            s = line.strip()
            if s.startswith("dependencies") and "[" in s:
                in_deps = True
            elif in_deps and "]" in s:
                in_deps = False
            if in_deps or ("==" in s or ">=" in s):
                m = re.search(r'"([A-Za-z0-9_.\-]+)', s)
                if m:
                    deps.append(m.group(1))
    elif lower == "go.mod":
        for m in re.findall(r"^\s*([a-zA-Z0-9.\-_/]+)\s+v[0-9]+\.[0-9]+", content or "", flags=re.M):
            if not m.startswith("module"):
                deps.append(m.split("/")[-1])
    elif lower == "cargo.toml":
        in_deps = False
        for line in (content or "").splitlines():
            s = line.strip()
            if s.startswith("[dependencies") or s.startswith("[dev-dependencies"):
                in_deps = True
                continue
            if s.startswith("[") and not s.startswith("[dependencies"):
                in_deps = False
            elif in_deps and "=" in s and not s.startswith("#"):
                deps.append(s.split("=", 1)[0].strip())
    elif lower == "pom.xml":
        for m in re.findall(r"<artifactId>([^<]+)</artifactId>", content or ""):
            deps.append(m.strip())
    elif lower == "dockerfile":
        for m in re.findall(r"^\s*FROM\s+([^\s]+)", content or "", flags=re.M | re.I):
            services.append(f"container:{m}")
        for port in re.findall(r"^\s*EXPOSE\s+([0-9]+)", content or "", flags=re.M | re.I):
            services.append(f"port:{port}")
    elif lower in ("docker-compose.yml", "docker-compose.yaml"):
        for svc in re.findall(r"^\s{2}([a-zA-Z0-9_-]+):\s*$", content or "", flags=re.M):
            if svc not in ("services", "volumes", "networks"):
                services.append(svc)

    return {
        "path": path,
        "manifest_type": lower,
        "dependencies": sorted(set(deps))[:80],
        "services": sorted(set(services))[:30],
    }


def summarize_repository_ast(
    owner_repo: str,
    branch: str,
    files: List[Dict[str, str]],
    tree_paths: Optional[List[str]] = None,
    source_type: str = "github_ast",
    tree_url: Optional[str] = None,
    repo_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze fetched repo source & manifests into parent + per-module SourceRecords and structural graph items."""
    from app.models.integration import SourceRecord  # local import check avoided at module top

    py_modules: List[Dict[str, Any]] = []
    ts_modules: List[Dict[str, Any]] = []
    polyglot_modules: List[Dict[str, Any]] = []
    manifests: List[Dict[str, Any]] = []
    all_routes: List[str] = []
    external_pkgs: set = set()
    internal_edges: List[Tuple[str, str]] = []

    stdlib_skip = {"os", "sys", "re", "json", "typing", "datetime", "uuid", "logging", "io", "math", "time", "pathlib", "fmt", "strings", "context"}

    for item in files:
        path = item.get("path") or ""
        content = item.get("content") or ""
        base = path.lower().rsplit("/", 1)[-1]
        lower_p = path.lower()
        if base in _PRIORITY_MANIFESTS:
            mf = parse_manifest_file(path, content)
            manifests.append(mf)
            external_pkgs.update(mf["dependencies"])
        elif lower_p.endswith(".py"):
            parsed = parse_python_source(path, content)
            py_modules.append(parsed)
            all_routes.extend(f"{path}: {r}" for r in parsed["routes"])
            for imp in parsed["imports"]:
                if imp in ("app", "services", "models", "core", "api"):
                    internal_edges.append((path, imp))
                elif not imp.startswith("_") and imp not in stdlib_skip:
                    external_pkgs.add(imp)
        elif lower_p.endswith((".ts", ".tsx", ".js", ".jsx")):
            parsed = parse_ts_js_source(path, content)
            ts_modules.append(parsed)
            for imp in parsed["imports"]:
                if imp.startswith("@/") or imp.startswith("./") or imp.startswith("../"):
                    internal_edges.append((path, imp))
                else:
                    pkg_root = imp.split("/")[0] if not imp.startswith("@") else "/".join(imp.split("/")[:2])
                    external_pkgs.add(pkg_root)
        elif lower_p.endswith(".go"):
            parsed = parse_go_source(path, content)
            polyglot_modules.append(parsed)
            all_routes.extend(f"{path}: {r}" for r in parsed["routes"])
            for imp in parsed["imports"]:
                pkg_tail = imp.split("/")[-1]
                if pkg_tail and pkg_tail not in stdlib_skip:
                    external_pkgs.add(pkg_tail)
        elif lower_p.endswith(".rs"):
            parsed = parse_rust_source(path, content)
            polyglot_modules.append(parsed)
            all_routes.extend(f"{path}: {r}" for r in parsed["routes"])
            for imp in parsed["imports"]:
                if imp not in ("std", "core", "alloc", "crate", "self", "super"):
                    external_pkgs.add(imp)
        elif lower_p.endswith(".java"):
            parsed = parse_java_source(path, content)
            polyglot_modules.append(parsed)
            all_routes.extend(f"{path}: {r}" for r in parsed["routes"])
            for imp in parsed["imports"]:
                if imp not in ("java", "javax"):
                    external_pkgs.add(imp)

    top_dirs = sorted({p.split("/")[0] for p in (tree_paths or []) if "/" in p})[:30]
    all_mods = py_modules + ts_modules + polyglot_modules

    lines = [
        f"Codebase Architecture & AST Summary for {owner_repo} (branch: {branch})",
        f"Top-Level Modules/Directories: {', '.join(top_dirs) if top_dirs else 'root'}",
        (
            f"Indexed Files: {len(files)} ({len(py_modules)} Python, {len(ts_modules)} TS/JS, "
            f"{len(polyglot_modules)} Go/Rust/Java, {len(manifests)} Manifests)"
        ),
    ]
    if all_routes:
        lines.append("\nDiscovered API Routes:\n" + "\n".join(f"- {r}" for r in all_routes[:50]))
    if manifests:
        lines.append("\nManifests & Runtime Dependencies:")
        for mf in manifests:
            lines.append(
                f"- {mf['path']}: {len(mf['dependencies'])} packages ({', '.join(mf['dependencies'][:20])})"
            )
    if py_modules:
        lines.append("\nPython Modules & Symbols:")
        for mod in py_modules[:35]:
            lines.append(
                f"- {mod['path']}: classes={mod['classes'][:10]}, funcs={mod['functions'][:12]}, imports={mod['imports'][:12]}"
            )
    if ts_modules:
        lines.append("\nTypeScript/JS Modules:")
        for mod in ts_modules[:35]:
            lines.append(
                f"- {mod['path']}: exports={mod['exports'][:10]}, imports={mod['imports'][:12]}"
            )
    if polyglot_modules:
        lines.append("\nGo/Rust/Java Modules:")
        for mod in polyglot_modules[:35]:
            lines.append(
                f"- {mod['path']} ({mod['language']}): classes={mod.get('classes', [])[:10]}, funcs={mod.get('functions', [])[:12]}"
            )

    summary_text = "\n".join(lines)
    prefix = "gitlab#" if "gitlab" in source_type else ""
    resolved_tree_url = tree_url or build_repo_web_url(source_type, repo_base_url, owner_repo, branch)

    records: List[Dict[str, Any]] = [
        {
            "source_type": source_type,
            "external_id": f"{prefix}{owner_repo}#ast-architecture",
            "title": f"Code-Tree AST & Dependency Map ({owner_repo})",
            "author": "Code AST Indexer",
            "url": resolved_tree_url,
            "content": summary_text,
            "sha256": compute_sha256(summary_text),
            "source_timestamp": datetime.now(timezone.utc),
            "metadata": {
                "repository": owner_repo,
                "branch": branch,
                "indexed_file_count": len(files),
                "routes_count": len(all_routes),
                "external_packages": sorted(external_pkgs)[:60],
                "top_directories": top_dirs,
            },
            "raw_payload": {
                "python_modules": py_modules[:40],
                "ts_modules": ts_modules[:40],
                "polyglot_modules": polyglot_modules[:40],
                "manifests": manifests,
            },
        }
    ]

    # Emit per-module AST records so RAG can pinpoint exact files, classes, functions, and endpoints
    mod_source_type = f"{source_type}_module"
    for mod in all_mods[:25]:
        mod_path = mod.get("path") or ""
        classes = mod.get("classes") or mod.get("exports") or []
        funcs = mod.get("functions") or []
        routes = mod.get("routes") or []
        imports = mod.get("imports") or []
        if not (classes or funcs or routes):
            continue
        mod_lines = [
            f"Module AST Profile: {mod_path} ({owner_repo} @ {branch})",
            f"Language: {mod.get('language')}",
        ]
        if routes:
            mod_lines.append("Routes:\n" + "\n".join(f"  - {r}" for r in routes))
        if classes:
            mod_lines.append(f"Classes/Exports: {', '.join(classes)}")
        if funcs:
            mod_lines.append(f"Functions: {', '.join(funcs)}")
        if imports:
            mod_lines.append(f"Imports: {', '.join(imports)}")
        mod_text = "\n".join(mod_lines)
        mod_hash = compute_sha256(mod_path)[:12]
        records.append({
            "source_type": mod_source_type,
            "external_id": f"{prefix}{owner_repo}#ast-mod:{mod_hash}",
            "title": f"AST Module: {mod_path} ({owner_repo})",
            "author": "Code AST Indexer",
            "url": build_repo_web_url(source_type, repo_base_url, owner_repo, branch, mod_path),
            "content": mod_text,
            "sha256": compute_sha256(mod_text),
            "source_timestamp": datetime.now(timezone.utc),
            "metadata": {
                "repository": owner_repo,
                "branch": branch,
                "file_path": mod_path,
                "language": mod.get("language"),
                "routes": routes,
            },
            "raw_payload": mod,
        })

    return {
        "records": records,
        "external_packages": sorted(external_pkgs)[:60],
        "internal_edges": internal_edges[:60],
        "top_directories": top_dirs,
        "manifests": manifests,
        "modules": all_mods,
    }


def persist_ast_graph_facts(
    db: Session,
    project_id: str,
    owner_repo: str,
    ast_summary: Dict[str, Any],
) -> int:
    """Create structural KnowledgeEntity, Dependency, and commit/Sentry provenance edges from AST analysis."""
    from app.models.integration import SourceRecord

    added = 0
    existing_entities = {
        e.name.strip().lower(): e
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).all()
    }

    def _ensure_entity(name: str, etype: str, desc: str) -> KnowledgeEntity:
        nonlocal added
        key = name.strip().lower()
        if key in existing_entities:
            return existing_entities[key]
        ke = KnowledgeEntity(
            project_id=project_id,
            entity_type=etype,
            name=name[:255],
            description=desc[:600],
            properties={"discovered_by": "code_ast_indexer", "repository": owner_repo},
            confidence=0.92,
            verification_status="Supported by Evidence",
        )
        db.add(ke)
        db.flush()
        existing_entities[key] = ke
        added += 1
        return ke

    repo_ent = _ensure_entity(owner_repo, "Service", f"Indexed repository {owner_repo}")

    existing_deps = {
        (d.source_component.strip().lower(), d.target_component.strip().lower())
        for d in db.query(Dependency).filter(Dependency.project_id == project_id).all()
    }
    existing_rels = {
        (r.source_entity_id, r.target_entity_id, r.relation_type)
        for r in db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == project_id).all()
    }

    for pkg in (ast_summary.get("external_packages") or [])[:45]:
        pkg_clean = pkg.strip()
        if not pkg_clean:
            continue
        pkg_ent = _ensure_entity(pkg_clean, "Component", f"Runtime package/dependency used by {owner_repo}")
        dep_pair = (owner_repo.lower(), pkg_clean.lower())
        if dep_pair not in existing_deps:
            db.add(
                Dependency(
                    project_id=project_id,
                    source_component=owner_repo[:255],
                    target_component=pkg_clean[:255],
                    dependency_type="runtime_package",
                    description=f"Detected via static AST/manifest analysis of {owner_repo}",
                    criticality="medium",
                    verification_status="Supported by Evidence",
                )
            )
            existing_deps.add(dep_pair)
            added += 1
        rel_key = (repo_ent.id, pkg_ent.id, "uses")
        if rel_key not in existing_rels:
            db.add(
                KnowledgeRelationship(
                    project_id=project_id,
                    source_entity_id=repo_ent.id,
                    target_entity_id=pkg_ent.id,
                    relation_type="uses",
                    context="Code AST & manifest import dependency",
                    confidence=0.92,
                    verification_status="Supported by Evidence",
                )
            )
            existing_rels.add(rel_key)
            added += 1

    # Cross-link existing commits / Sentry issues in the project to AST modules & services
    indexed_files = {
        (m.get("path") or "").rsplit("/", 1)[-1].lower(): m.get("path")
        for m in (ast_summary.get("modules") or [])
        if m.get("path")
    }
    if indexed_files:
        recent_sources = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.project_id == project_id,
                SourceRecord.source_type.in_(["github_commit", "gitlab_commit", "github_pr", "gitlab_mr", "sentry_issue"]),
            )
            .order_by(SourceRecord.ingested_at.desc())
            .limit(40)
            .all()
        )
        for src in recent_sources:
            hay = f"{src.title or ''} {src.content or ''}".lower()
            matched_file = next((fpath for fname, fpath in indexed_files.items() if len(fname) > 4 and fname in hay), None)
            if src.source_type == "sentry_issue" and (matched_file or owner_repo.split("/")[-1].lower() in hay):
                err_ent = _ensure_entity(src.title[:120], "Risk", f"Sentry error linked to {matched_file or owner_repo}")
                rel_key = (err_ent.id, repo_ent.id, "affects")
                if rel_key not in existing_rels:
                    db.add(
                        KnowledgeRelationship(
                            project_id=project_id,
                            source_entity_id=err_ent.id,
                            target_entity_id=repo_ent.id,
                            relation_type="affects",
                            context=f"Sentry stacktrace references {matched_file or owner_repo}",
                            confidence=0.85,
                            verification_status="Supported by Evidence",
                            source_record_id=src.id,
                        )
                    )
                    existing_rels.add(rel_key)
                    added += 1
            elif src.author and matched_file:
                person_ent = _ensure_entity(src.author, "Person", f"Contributor to {owner_repo}")
                rel_key = (person_ent.id, repo_ent.id, "maintains")
                if rel_key not in existing_rels:
                    db.add(
                        KnowledgeRelationship(
                            project_id=project_id,
                            source_entity_id=person_ent.id,
                            target_entity_id=repo_ent.id,
                            relation_type="maintains",
                            context=f"Modified/authored {matched_file}",
                            confidence=0.82,
                            verification_status="Supported by Evidence",
                            source_record_id=src.id,
                        )
                    )
                    existing_rels.add(rel_key)
                    added += 1

    return added


def fetch_and_index_github_ast(
    connector: Any,
    owner_repo: str,
    max_files: int = 18,
) -> Dict[str, Any]:
    """Fetch repository git tree & high-signal files from GitHub API and produce AST records & graph facts."""
    try:
        repo_res = connector._request_with_retry("GET", f"{connector.base_url}/repos/{owner_repo}", headers=connector.headers)
        if repo_res.status_code != 200:
            return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}
        branch = repo_res.json().get("default_branch") or "main"

        tree_res = connector._request_with_retry(
            "GET",
            f"{connector.base_url}/repos/{owner_repo}/git/trees/{branch}",
            headers=connector.headers,
            params={"recursive": "1"},
        )
        if tree_res.status_code != 200:
            return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}

        tree_items = tree_res.json().get("tree") or []
        blob_paths = [
            it.get("path")
            for it in tree_items
            if it.get("type") == "blob" and it.get("path") and _is_candidate_code_file(it.get("path"))
        ]
        blob_paths.sort(key=_file_priority)
        selected_paths = blob_paths[:max_files]

        fetched_files: List[Dict[str, str]] = []
        for path in selected_paths:
            try:
                c_res = connector._request_with_retry(
                    "GET",
                    f"{connector.base_url}/repos/{owner_repo}/contents/{path}",
                    headers=connector.headers,
                    params={"ref": branch},
                )
                if c_res.status_code != 200:
                    continue
                payload = c_res.json()
                raw_b64 = payload.get("content") or ""
                if raw_b64:
                    decoded = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
                    fetched_files.append({"path": path, "content": decoded[:30000]})
            except Exception:
                continue

        if not fetched_files and not tree_items:
            return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}

        return summarize_repository_ast(
            owner_repo=owner_repo,
            branch=branch,
            files=fetched_files,
            tree_paths=[it.get("path") for it in tree_items if it.get("path")],
        )
    except Exception as exc:
        logger.warning("GitHub AST indexing skipped for %s: %s", owner_repo, str(exc)[:140])
        return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}


def fetch_and_index_gitlab_ast(
    connector: Any,
    project_path: str,
    default_branch: str = "main",
    max_files: int = 18,
) -> Dict[str, Any]:
    """Fetch GitLab repository tree and high-signal files and produce AST records and graph facts."""
    try:
        enc_proj = quote(project_path, safe="")
        tree_res = connector._request_with_retry(
            "GET",
            f"{connector.base_url}/projects/{enc_proj}/repository/tree",
            headers=connector.headers,
            params={"ref": default_branch, "recursive": "true", "per_page": 100},
        )
        if tree_res.status_code != 200:
            return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}

        tree_items = tree_res.json() or []
        blob_paths = [
            it.get("path")
            for it in tree_items
            if it.get("type") == "blob" and it.get("path") and _is_candidate_code_file(it.get("path"))
        ]
        blob_paths.sort(key=_file_priority)
        selected_paths = blob_paths[:max_files]

        fetched_files: List[Dict[str, str]] = []
        for path in selected_paths:
            try:
                enc_file = quote(path, safe="")
                c_res = connector._request_with_retry(
                    "GET",
                    f"{connector.base_url}/projects/{enc_proj}/repository/files/{enc_file}/raw",
                    headers=connector.headers,
                    params={"ref": default_branch},
                )
                if c_res.status_code == 200 and c_res.text:
                    fetched_files.append({"path": path, "content": c_res.text[:30000]})
            except Exception:
                continue

        if not fetched_files and not tree_items:
            return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}

        return summarize_repository_ast(
            owner_repo=project_path,
            branch=default_branch,
            files=fetched_files,
            tree_paths=[it.get("path") for it in tree_items if it.get("path")],
            source_type="gitlab_ast",
            tree_url=f"{getattr(connector, 'gitlab_origin', 'https://gitlab.com')}/{project_path}/-/tree/{default_branch}",
        )
    except Exception as exc:
        logger.warning("GitLab AST indexing skipped for %s: %s", project_path, str(exc)[:140])
        return {"records": [], "external_packages": [], "internal_edges": [], "top_directories": [], "manifests": []}

