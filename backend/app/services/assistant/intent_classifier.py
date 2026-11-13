from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

INTENT_DIRECT_METRIC = "direct_metric"
INTENT_DATA_RETRIEVAL = "data_retrieval"
INTENT_ANALYTICAL = "analytical"
INTENT_CROSS_SOURCE = "cross_source"
INTENT_HANDOVER = "handover"
INTENT_SEMANTIC_RAG = "semantic_rag"


class QueryIntent:
    def __init__(
        self,
        category: str,
        target_entity: str = "",
        action: str = "",
        filter_params: Optional[Dict[str, Any]] = None,
        specific_resource: Optional[str] = None,
        confidence: float = 1.0,
    ):
        self.category = category
        self.target_entity = target_entity  # "github_repos", "tasks", "decisions", "risks", "integrations", "commits", "members"
        self.action = action  # "count", "list", "recent", "contributors", "details"
        self.filter_params = filter_params or {}
        self.specific_resource = specific_resource
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"<QueryIntent category={self.category} target={self.target_entity} action={self.action} resource={self.specific_resource}>"


class IntentClassifier:
    """Lightweight, deterministic rule-based and entity-extracting intent classifier."""

    GITHUB_REPO_COUNT_PATTERNS = [
        r"\bhow\s+many\s+(?:repos?|repositories)\b",
        r"\bcount\s+(?:of\s+)?(?:my\s+)?(?:repos?|repositories)\b",
        r"\bnumber\s+of\s+(?:my\s+)?(?:repos?|repositories)\b",
        r"\btotal\s+(?:number\s+of\s+)?(?:repos?|repositories)\b",
        r"\brepos?(?:itory)?\s+count\b",
    ]

    GITHUB_REPO_LIST_PATTERNS = [
        r"\b(?:show|list|get|display|view|see)\s+(?:all\s+)?(?:my\s+)?(?:repos?|repositories)\b",
        r"\bwhat\s+(?:are\s+)?(?:my\s+)?(?:repos?|repositories)\b",
        r"\bwhich\s+(?:repos?|repositories)\s+do\s+i\s+have\b",
    ]

    TASK_COUNT_PATTERNS = [
        r"\bhow\s+many\s+(?:open\s+|unfinished\s+|pending\s+)?tasks\b",
        r"\bcount\s+of\s+tasks\b",
        r"\btask\s+count\b",
    ]

    TASK_LIST_PATTERNS = [
        r"\b(?:show|list|get|display|what\s+are)\s+(?:my\s+)?(?:open\s+|unfinished\s+|pending\s+)?tasks\b",
        r"\bwhat\s+tasks\s+are\s+(?:unfinished|open|pending)\b",
    ]

    DECISION_PATTERNS = [
        r"\b(?:show|list|what\s+are|get)\s+(?:my\s+)?(?:recent\s+|all\s+)?decisions\b",
        r"\bhow\s+many\s+decisions\b",
    ]

    RISK_PATTERNS = [
        r"\b(?:what\s+are|show|list)\s+(?:the\s+)?(?:biggest\s+|critical\s+|top\s+)?(?:project\s+)?risks\b",
        r"\bhow\s+many\s+risks\b",
    ]

    HANDOVER_PATTERNS = [
        r"\b(?:generate|create|build|export)\s+(?:a\s+)?(?:complete\s+)?(?:project\s+)?handover\b",
        r"\bwhat\s+does\s+(?:the\s+)?incoming\s+developer\s+need\s+to\s+know\b",
        r"\bwhich\s+responsibilities\s+(?:remain\s+)?unfinished\b",
        r"\bhandover\s+readiness\b",
    ]

    ARCHITECTURE_PATTERNS = [
        r"\banalyse\s+(?:my\s+)?(?:repository\s+|project\s+)?architecture\b",
        r"\banalyze\s+(?:my\s+)?(?:repository\s+|project\s+)?architecture\b",
        r"\barchitecture\s+analysis\b",
        r"\bexplain\s+(?:the\s+)?(?:project\s+)?architecture\b",
        r"\bexplain\s+(?:project\s+)?dependencies\b",
    ]

    @classmethod
    def classify(
        cls,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> QueryIntent:
        raw_query = (query or "").strip()
        q = raw_query.lower()

        def _resolve_context_repo() -> Optional[str]:
            if not conversation_history:
                return None
            for turn in reversed(conversation_history):
                content = turn.get("content", "")
                m = re.search(r"([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+)", content)
                if m:
                    return m.group(1)
                # Look for capitalized repo/project names
                m2 = re.search(r"\b([A-Z][a-zA-Z0-9_\-]+)\b", content)
                if m2 and m2.group(1).lower() not in ("user", "assistant", "what", "who", "tell", "this", "that", "the"):
                    return m2.group(1)
            return None

        # Context-aware follow-up resolution
        if conversation_history and len(conversation_history) > 0:
            if any(term in q for term in ["which one", "which of those", "which repo"]):
                ref_repo = _resolve_context_repo()
                if ref_repo:
                    if "contributor" in q:
                        return QueryIntent(
                            category=INTENT_DATA_RETRIEVAL,
                            target_entity="github_contributors",
                            action="contributors",
                            specific_resource=ref_repo,
                        )
                    if "commit" in q:
                        return QueryIntent(
                            category=INTENT_DATA_RETRIEVAL,
                            target_entity="github_commits",
                            action="commits",
                            specific_resource=ref_repo,
                        )

        # 1. GitHub Repository Count / Inventory
        for pat in cls.GITHUB_REPO_COUNT_PATTERNS:
            if re.search(pat, q):
                visibility = None
                if "public" in q:
                    visibility = "public"
                elif "private" in q:
                    visibility = "private"
                return QueryIntent(
                    category=INTENT_DIRECT_METRIC,
                    target_entity="github_repos",
                    action="count",
                    filter_params={"visibility": visibility},
                )

        # Public/Private specific counts
        if re.search(r"\bhow\s+many\s+are\s+public\b", q) or re.search(r"\bhow\s+many\s+public\b", q):
            return QueryIntent(
                category=INTENT_DIRECT_METRIC,
                target_entity="github_repos",
                action="count",
                filter_params={"visibility": "public"},
            )
        if re.search(r"\bhow\s+many\s+are\s+private\b", q) or re.search(r"\bhow\s+many\s+private\b", q):
            return QueryIntent(
                category=INTENT_DIRECT_METRIC,
                target_entity="github_repos",
                action="count",
                filter_params={"visibility": "private"},
            )

        # 2. GitHub Repository List / Details
        for pat in cls.GITHUB_REPO_LIST_PATTERNS:
            if re.search(pat, q):
                visibility = None
                if "public" in q:
                    visibility = "public"
                elif "private" in q:
                    visibility = "private"
                return QueryIntent(
                    category=INTENT_DATA_RETRIEVAL,
                    target_entity="github_repos",
                    action="list",
                    filter_params={"visibility": visibility},
                )

        # Most recently updated repository
        if re.search(r"\bwhich\s+(?:repos?|repository)\s+was\s+(?:updated|modified)\s+(?:most\s+)?recently\b", q):
            return QueryIntent(
                category=INTENT_DATA_RETRIEVAL,
                target_entity="github_repos",
                action="recent",
            )

        # Repository with most contributors
        if re.search(r"\bwhich\s+(?:repos?|repository)\s+has\s+the\s+most\s+contributors\b", q):
            return QueryIntent(
                category=INTENT_DATA_RETRIEVAL,
                target_entity="github_repos",
                action="most_contributors",
            )

        # Contributor query for specific repo (e.g. "Who contributes to Trustify?" or "Who contributes to it?")
        contrib_match = re.search(r"\bwho\s+contributes\s+to\s+([a-zA-Z0-9_\-\./]+)\b", raw_query, re.IGNORECASE)
        if contrib_match:
            repo_name = contrib_match.group(1).rstrip("?.,")
            if repo_name.lower() in ("it", "this", "that", "the", "there"):
                ref = _resolve_context_repo()
                if ref:
                    repo_name = ref
            return QueryIntent(
                category=INTENT_DATA_RETRIEVAL,
                target_entity="github_contributors",
                action="contributors",
                specific_resource=repo_name,
            )

        # Technology / Architecture of specific repo (e.g. "What technologies does Trustify use?")
        tech_match = re.search(r"\bwhat\s+technologies\s+does\s+([a-zA-Z0-9_\-\./]+)\s+use\b", raw_query, re.IGNORECASE)
        if tech_match:
            repo_name = tech_match.group(1).rstrip("?.,")
            if repo_name.lower() in ("it", "this", "that", "the"):
                ref = _resolve_context_repo()
                if ref:
                    repo_name = ref
            return QueryIntent(
                category=INTENT_ANALYTICAL,
                target_entity="repo_technologies",
                action="tech_stack",
                specific_resource=repo_name,
            )

        # Latest commits query
        if re.search(r"\bwhat\s+are\s+(?:the\s+)?latest\s+commits\b", q) or re.search(r"\bshow\s+(?:my\s+)?latest\s+commits\b", q):
            return QueryIntent(
                category=INTENT_DATA_RETRIEVAL,
                target_entity="github_commits",
                action="commits",
            )

        # Cross-source / Slack decisions query
        if re.search(r"\bwhat\s+did\s+we\s+decide\s+in\s+slack\b", q) or re.search(r"\bwhat\s+was\s+discussed\s+in\s+slack\b", q):
            return QueryIntent(
                category=INTENT_CROSS_SOURCE,
                target_entity="slack_discussions",
                action="decisions",
                filter_params={"source_type": "slack"},
            )

        # 3. Tasks
        for pat in cls.TASK_COUNT_PATTERNS:
            if re.search(pat, q):
                return QueryIntent(
                    category=INTENT_DIRECT_METRIC,
                    target_entity="tasks",
                    action="count",
                    filter_params={"status": "open"},
                )
        for pat in cls.TASK_LIST_PATTERNS:
            if re.search(pat, q):
                return QueryIntent(
                    category=INTENT_DATA_RETRIEVAL,
                    target_entity="tasks",
                    action="list",
                    filter_params={"status": "open"},
                )

        # 4. Decisions
        for pat in cls.DECISION_PATTERNS:
            if re.search(pat, q):
                return QueryIntent(
                    category=INTENT_DATA_RETRIEVAL,
                    target_entity="decisions",
                    action="list",
                )

        # 5. Risks
        for pat in cls.RISK_PATTERNS:
            if re.search(pat, q):
                return QueryIntent(
                    category=INTENT_ANALYTICAL,
                    target_entity="risks",
                    action="list",
                )

        # 6. Handover
        for pat in cls.HANDOVER_PATTERNS:
            if re.search(pat, q):
                return QueryIntent(
                    category=INTENT_HANDOVER,
                    target_entity="handover",
                    action="generate",
                )

        # 7. Architecture
        for pat in cls.ARCHITECTURE_PATTERNS:
            if re.search(pat, q):
                return QueryIntent(
                    category=INTENT_ANALYTICAL,
                    target_entity="architecture",
                    action="analysis",
                )

        # 8. Connected integrations
        if re.search(r"\bwhat\s+(?:accounts?|integrations?|sources?)\s+(?:are\s+)?connected\b", q) or re.search(r"\bwhich\s+github\s+account\b", q):
            return QueryIntent(
                category=INTENT_DIRECT_METRIC,
                target_entity="integrations",
                action="list",
            )

        # Default: Semantic RAG
        return QueryIntent(
            category=INTENT_SEMANTIC_RAG,
            action="rag_answer",
        )
