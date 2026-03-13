"""Keyword search index over the RouterOS OpenAPI 2.0 spec."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("mikrotik_mcp.api_index")

# Resolve default spec relative to this package.
DEFAULT_OAS_PATH = Path(__file__).resolve().parent / "data" / "routeros-7.16-oas2.json"

# Scripting/CLI commands that are not real REST resources.
SCRIPTING_COMMANDS: frozenset[str] = frozenset({
    "/if", "/foreach", "/while", "/do", "/for", "/put", "/global", "/local",
    "/nothing", "/error", "/execute", "/find", "/len", "/onerror", "/parse",
    "/pick", "/resolve", "/retry", "/return", "/rndnum", "/rndstr",
    "/serialize", "/deserialize", "/set", "/terminal", "/time", "/timestamp",
    "/typeof", "/toarray", "/tobool", "/toid", "/toip", "/toip6", "/tonum",
    "/tostr", "/totime", "/environment", "/beep", "/convert", "/delay",
    "/grep", "/lock", "/jobname", "/console", "/task",
})

# CRUD suffixes that get consolidated under the base resource.
CRUD_SUFFIXES: frozenset[str] = frozenset({
    "add", "remove", "set", "get", "find", "edit", "comment",
    "disable", "enable", "unset", "export", "print", "reset", "move",
})


@dataclass
class EndpointInfo:
    """Consolidated info about one REST resource."""

    path: str
    methods: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
    group: str = ""
    subgroup: str = ""
    has_id: bool = False
    actions: list[str] = field(default_factory=list)


class ApiIndex:
    """In-memory keyword search index built from an OAS2 spec.

    Loads the full spec once at startup and builds a compact index
    of EndpointInfo entries for keyword-based search.
    """

    def __init__(self, oas_path: str | Path | None = None) -> None:
        path = Path(oas_path) if oas_path else DEFAULT_OAS_PATH
        with open(path) as f:
            self._spec: dict[str, Any] = json.load(f)
        self._entries: dict[str, EndpointInfo] = {}
        self._build_index()
        logger.info("Loaded API index: %d resources from OAS2 spec", len(self._entries))

    def _build_index(self) -> None:
        """Parse OAS2 paths into consolidated EndpointInfo entries."""
        paths: dict[str, Any] = self._spec.get("paths", {})

        for raw_path, path_obj in paths.items():
            # Skip scripting commands.
            if self._is_scripting(raw_path):
                continue

            # Skip {id} variants — we'll flag them on the base resource.
            if raw_path.endswith("/{id}"):
                base = raw_path.removesuffix("/{id}")
                # Ensure base entry exists and mark has_id.
                entry = self._get_or_create(base, paths)
                entry.has_id = True
                # Collect methods from the {id} variant.
                for method in self._extract_methods(path_obj):
                    if method not in entry.methods:
                        entry.methods.append(method)
                # Collect params from {id} PATCH/PUT.
                for param_name in self._extract_params(path_obj):
                    if param_name not in entry.params:
                        entry.params.append(param_name)
                continue

            segments = raw_path.strip("/").split("/")
            last_segment = segments[-1] if segments else ""

            # CRUD suffix → consolidate under parent.
            if last_segment in CRUD_SUFFIXES and len(segments) > 1:
                parent_path = "/" + "/".join(segments[:-1])
                if self._is_scripting(parent_path):
                    continue
                entry = self._get_or_create(parent_path, paths)
                if last_segment not in entry.actions:
                    entry.actions.append(last_segment)
                # Collect params from add/set operations.
                for param_name in self._extract_params(path_obj):
                    if param_name not in entry.params:
                        entry.params.append(param_name)
                continue

            # Domain-specific action (make-static, release, monitor, etc.).
            # Check if parent resource exists or could exist.
            if len(segments) > 2:
                parent_path = "/" + "/".join(segments[:-1])
                # If parent has CRUD operations, this is a domain action.
                parent_has_crud = any(
                    f"{parent_path}/{suffix}" in paths for suffix in CRUD_SUFFIXES
                )
                if parent_has_crud:
                    entry = self._get_or_create(raw_path, paths)
                    for method in self._extract_methods(path_obj):
                        if method not in entry.methods:
                            entry.methods.append(method)
                    for param_name in self._extract_params(path_obj):
                        if param_name not in entry.params:
                            entry.params.append(param_name)
                    continue

            # Regular resource.
            entry = self._get_or_create(raw_path, paths)
            for method in self._extract_methods(path_obj):
                if method not in entry.methods:
                    entry.methods.append(method)
            for param_name in self._extract_params(path_obj):
                if param_name not in entry.params:
                    entry.params.append(param_name)

    def _is_scripting(self, path: str) -> bool:
        """Check if a path is a scripting command or belongs to one."""
        if path in SCRIPTING_COMMANDS:
            return True
        # Check if first segment matches a scripting root.
        first = "/" + path.strip("/").split("/")[0]
        return first in SCRIPTING_COMMANDS

    def _get_or_create(self, path: str, paths: dict[str, Any]) -> EndpointInfo:
        """Get existing entry or create a new one with group/subgroup set."""
        if path not in self._entries:
            segments = path.strip("/").split("/")
            entry = EndpointInfo(
                path=path,
                group=segments[0] if segments else "",
                subgroup=segments[1] if len(segments) > 1 else "",
            )
            self._entries[path] = entry
            # Collect methods from the base path itself if it exists in spec.
            if path in paths:
                for method in self._extract_methods(paths[path]):
                    if method not in entry.methods:
                        entry.methods.append(method)
        return self._entries[path]

    @staticmethod
    def _extract_methods(path_obj: dict[str, Any]) -> list[str]:
        """Extract HTTP methods from a path object."""
        http_methods = {"get", "put", "post", "patch", "delete", "head", "options"}
        return [m.upper() for m in path_obj if m.lower() in http_methods]

    @staticmethod
    def _extract_params(path_obj: dict[str, Any]) -> list[str]:
        """Extract parameter names from PUT/POST/PATCH body schemas."""
        params: list[str] = []
        for method in ("put", "post", "patch"):
            if method not in path_obj:
                continue
            for param in path_obj[method].get("parameters", []):
                schema = param.get("schema", {})
                for prop_name in schema.get("properties", {}):
                    if prop_name not in params:
                        params.append(prop_name)
        return params

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def endpoint_count(self) -> int:
        """Number of consolidated endpoint entries."""
        return len(self._entries)

    def search(self, query: str, limit: int = 10) -> list[EndpointInfo]:
        """Keyword search over the index.

        Tokenizes the query on spaces and hyphens, then scores each entry:
        - +3 for exact match on a path segment
        - +2 for substring match on a path segment
        - +1 for match on a parameter name
        """
        tokens = self._tokenize(query)
        if not tokens:
            return []

        scored: list[tuple[int, EndpointInfo]] = []
        for entry in self._entries.values():
            score = self._score(entry, tokens)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: (-x[0], x[1].path))
        return [entry for _, entry in scored[:limit]]

    def get_groups_summary(self) -> str:
        """Markdown summary of API groups with resource counts."""
        groups: dict[str, dict[str, int]] = {}
        for entry in self._entries.values():
            g = entry.group or "(root)"
            if g not in groups:
                groups[g] = {"count": 0, "subgroups": set()}  # type: ignore[dict-item]
            groups[g]["count"] += 1  # type: ignore[operator]
            if entry.subgroup:
                groups[g]["subgroups"].add(entry.subgroup)  # type: ignore[union-attr]

        lines = ["# RouterOS API Groups", ""]
        for group in sorted(groups):
            info = groups[group]
            subs = sorted(info["subgroups"])  # type: ignore[arg-type]
            sub_text = f" ({', '.join(subs[:8])}{'...' if len(subs) > 8 else ''})" if subs else ""
            lines.append(f"- **{group}**: {info['count']} resources{sub_text}")

        lines.append(f"\nTotal: {self.endpoint_count} resources")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Scoring internals
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(query: str) -> list[str]:
        """Split query on spaces and hyphens, lowercase."""
        parts: list[str] = []
        for word in query.lower().split():
            for sub in word.split("-"):
                sub = sub.strip()
                if sub:
                    parts.append(sub)
        return parts

    @staticmethod
    def _score(entry: EndpointInfo, tokens: list[str]) -> int:
        """Score an entry against search tokens."""
        segments = [s.lower() for s in entry.path.strip("/").split("/")]
        param_names = [p.lower() for p in entry.params]
        # Also tokenize hyphenated segments for matching.
        segment_tokens: list[str] = []
        for seg in segments:
            for part in seg.split("-"):
                if part:
                    segment_tokens.append(part)

        score = 0
        for token in tokens:
            # Exact segment match.
            if token in segments or token in segment_tokens:
                score += 3
            # Substring in a segment.
            elif any(token in seg for seg in segments):
                score += 2
            # Match in params.
            elif any(token in p for p in param_names):
                score += 1
        return score
