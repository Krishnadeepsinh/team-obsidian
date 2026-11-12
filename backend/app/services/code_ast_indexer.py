import ast
import base64
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.knowledge import Dependency, KnowledgeEntity, KnowledgeRelationship
from app.services.connectors.base import compute_sha256

logger = logging.getLogger("team_obsidian.ast_indexer")

_PRIORITY_MANIFESTS = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "procfile",
}


def _file_priority(path: str) -> Tuple[int, int]:
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    if base in _PRIORITY_MANIFESTS:
        return (0, len(path))
    if any(seg in lower for seg in ("main.", "app.", "server.", "router", "api/", "auth", "database", "config")):
        return (1, len(path))
    if lower.endswith((".py", ".ts", ".tsx", ".js")):
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
            "dist/",
            "build/",
            ".git/",
            ".min.js",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        )
    ):
        return False
    base = lower.rsplit("/", 1)[-1]
    if base in _PRIORITY_MANIFESTS:
        return True
    return lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))


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
        "imports": sorted(set(imports))[:30],
        "classes": sorted(set(classes))[:20],
        "functions": sorted(set(functions))[:25],
        "routes": routes[:20],
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
        "imports": sorted(imports)[:30],
        "exports": sorted(exports)[:25],
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
                    deps.extend(list(pkg_map.keys())[:40])
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
        "dependencies": sorted(set(deps))[:50],
        "services": sorted(set(services))[:20],
    }


def summarize_repository_ast(
    owner_repo: str,
    branch: str,
    files: List[Dict[str, str]],
    tree_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Analyze fetched repo source & manifests into normalized SourceRecords and structural graph items."""
    py_modules: List[Dict[str, Any]] = []
    ts_modules: List[Dict[str, Any]] = []
    manifests: List[Dict[str, Any]] = []
    all_routes: List[str] = []
    external_pkgs: set = set()
    internal_edges: List[Tuple[str, str]] = []

    for item in files:
        path = item.get("path") or ""
        content = item.get("content") or ""
        base = path.lower().rsplit("/", 1)[-1]
        if base in _PRIORITY_MANIFESTS:
            mf = parse_manifest_file(path, content)
            manifests.append(mf)
            external_pkgs.update(mf["dependencies"])
        elif path.lower().endswith(".py"):
            parsed = parse_python_source(path, content)
            py_modules.append(parsed)
            all_routes.extend(f"{path}: {r}" for r in parsed["routes"])
            for imp in parsed["imports"]:
                if imp in ("app", "services", "models", "core", "api"):
                    internal_edges.append((path, imp))
                elif not imp.startswith("_") and imp not in ("os", "sys", "re", "json", "typing", "datetime", "uuid", "logging", "io"):
                    external_pkgs.add(imp)
        elif path.lower().endswith((".ts", ".tsx", ".js", ".jsx")):
            parsed = parse_ts_js_source(path, content)
            ts_modules.append(parsed)
            for imp in parsed["imports"]:
                if imp.startswith("@/") or imp.startswith("./") or imp.startswith("../"):
                    internal_edges.append((path, imp))
                else:
                    pkg_root = imp.split("/")[0] if not imp.startswith("@") else "/".join(imp.split("/")[:2])
                    external_pkgs.add(pkg_root)

    # Top-level directories from tree
    top_dirs = sorted({p.split("/")[0] for p in (tree_paths or []) if "/" in p})[:20]

    lines = [
        f"Codebase Architecture & AST Summary for {owner_repo} (branch: {branch})",
        f"Top-Level Modules/Directories: {', '.join(top_dirs) if top_dirs else 'root'}",
        f"Indexed Files: {len(files)} ({len(py_modules)} Python, {len(ts_modules)} TS/JS, {len(manifests)} Manifests)",
    ]
    if all_routes:
        lines.append("\nDiscovered API Routes:\n" + "\n".join(f"- {r}" for r in all_routes[:30]))
    if manifests:
        lines.append("\nManifests & Runtime Dependencies:")
        for mf in manifests:
            lines.append(
                f"- {mf['path']}: {len(mf['dependencies'])} packages ({', '.join(mf['dependencies'][:12])})"
            )
    if py_modules:
        lines.append("\nKey Python Modules & Symbols:")
        for mod in py_modules[:15]:
            lines.append(
                f"- {mod['path']}: classes={mod['classes'][:5]}, funcs={mod['functions'][:6]}, imports={mod['imports'][:8]}"
            )
    if ts_modules:
        lines.append("\nKey TypeScript/JS Modules:")
        for mod in ts_modules[:15]:
            lines.append(
                f"- {mod['path']}: exports={mod['exports'][:6]}, imports={mod['imports'][:8]}"
            )

    summary_text = "\n".join(lines)
    records = [
        {
            "source_type": "github_ast",
            "external_id": f"{owner_repo}#ast-architecture",
            "title": f"Code-Tree AST & Dependency Map ({owner_repo})",
            "author": "Code AST Indexer",
            "url": f"https://github.com/{owner_repo}/tree/{branch}",
            "content": summary_text,
            "sha256": compute_sha256(summary_text),
            "source_timestamp": datetime.now(timezone.utc),
            "metadata": {
                "repository": owner_repo,
                "branch": branch,
                "indexed_file_count": len(files),
                "routes_count": len(all_routes),
                "external_packages": sorted(external_pkgs)[:40],
                "top_directories": top_dirs,
            },
            "raw_payload": {
                "python_modules": py_modules[:20],
                "ts_modules": ts_modules[:20],
                "manifests": manifests,
            },
        }
    ]

    return {
        "records": records,
        "external_packages": sorted(external_pkgs)[:40],
        "internal_edges": internal_edges[:40],
        "top_directories": top_dirs,
        "manifests": manifests,
    }


def persist_ast_graph_facts(
    db: Session,
    project_id: str,
    owner_repo: str,
    ast_summary: Dict[str, Any],
) -> int:
    """Create structural KnowledgeEntity & Dependency rows directly from AST manifests/imports."""
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

    # Persist critical external runtime frameworks/services as dependencies
    key_pkg_markers = {
        "fastapi", "sqlalchemy", "psycopg", "pgvector", "next", "react", "pydantic",
        "pymupdf", "networkx", "google-genai", "httpx", "redis", "celery", "prisma", "tailwindcss",
    }
    existing_deps = {
        (d.source_component.strip().lower(), d.target_component.strip().lower())
        for d in db.query(Dependency).filter(Dependency.project_id == project_id).all()
    }

    for pkg in ast_summary.get("external_packages") or []:
        pkg_clean = pkg.strip()
        if not pkg_clean:
            continue
        if pkg_clean.lower() not in key_pkg_markers and len(existing_deps) >= 12:
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

