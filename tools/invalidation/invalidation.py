#!/usr/bin/env python3
"""
invalidation.py -- a dependency-invalidation engine for verification-gated
projects: when a source, a piece of evidence, or a claim changes, which
other records does that change make STALE, and why.

============================================================================
WHY THIS EXISTS
============================================================================
A project with an evidence ledger and a claim ledger accumulates
dependencies: a claim depends on the evidence it cites, evidence depends
on the source it was drawn from, a piece of prose depends on the claim it
states. When one of those upstream things changes -- a source is
re-extracted and its text shifts, an evidence excerpt is corrected, a
claim's status is revised -- everything downstream of it is now
potentially wrong until it is re-checked. Tracking that by hand does not
scale past a handful of records; this module makes it mechanical.

The engine is a small directed graph (Source -> Evidence -> Claim -> Use,
plus an Approval/ratification node type for anything requiring an
owner's sign-off) with a fixed vocabulary of change events and a
deterministic dispatch table mapping each event to the set of nodes it
marks STALE. STALE propagates downstream through the graph: if a Claim
goes STALE, every Use that depends on it goes STALE too, transitively.

============================================================================
SCOPE, DISCLOSED
============================================================================
This is a reference implementation of the engine's *architecture* --
node/edge types, event vocabulary, dispatch rules, staleness propagation,
and a CSV event-log format -- not a byte-for-byte port of any specific
project's production tool. It is deliberately smaller than a real
project's engine will likely grow to be: it does not include schema-
migration machinery, project-specific repair functions for historically
malformed data, or a live-ledger-scanning CLI wired to your exact column
names. Wire `load_live_graph` and `detect_row_events` below to your own
ledger schema; everything else (the graph, the dispatch table, the
propagation algorithm, the event log writer) is reusable as-is.

No third-party dependencies. Python 3 standard library only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

# ============================================================================
# Section 1 -- Graph model
# ============================================================================

NODE_TYPES = ("Source", "Evidence", "Claim", "Use", "Approval")
EDGE_TYPES = ("wasDrawnFrom", "supports", "citedIn", "governs")
# wasDrawnFrom: Evidence -> Source (this excerpt came from this source)
# supports:     Claim -> Evidence (this claim rests on this evidence)
# citedIn:      Use -> Claim (this passage in the work states this claim)
# governs:      Approval -> {Source|Evidence|Claim} (this ruling licenses this node)


class EngineStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


@dataclass
class Node:
    id: str
    type: str
    content_hash: str = ""
    engine_status: str = EngineStatus.FRESH.value
    stale_since: str = ""
    stale_reason: str = ""

    def __post_init__(self):
        if self.type not in NODE_TYPES:
            raise ValueError(f"unknown node type {self.type!r}; must be one of {NODE_TYPES}")


@dataclass
class Edge:
    src: str
    dst: str
    type: str

    def __post_init__(self):
        if self.type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {self.type!r}; must be one of {EDGE_TYPES}")


class MalformedGraphError(Exception):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.details = details or {}


class Graph:
    """A small directed multigraph. Edges point from the DEPENDENT node to
    the node it depends on (Evidence -wasDrawnFrom-> Source), so
    `downstream_closure` (below) walks edges in REVERSE to find everything
    that depends, directly or transitively, on a changed node."""

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._reverse_adj: Dict[str, Set[str]] = {}  # dst -> {src, ...}

    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            raise MalformedGraphError(f"duplicate node id {node.id!r}")
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        if edge.src not in self.nodes:
            raise MalformedGraphError(f"edge source {edge.src!r} is not a known node")
        if edge.dst not in self.nodes:
            raise MalformedGraphError(f"edge destination {edge.dst!r} is not a known node")
        self.edges.append(edge)
        self._reverse_adj.setdefault(edge.dst, set()).add(edge.src)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def node_type(self, node_id: str) -> Optional[str]:
        n = self.nodes.get(node_id)
        return n.type if n else None

    def downstream_closure(self, node_id: str) -> Set[str]:
        """Every node that depends, directly or transitively, on `node_id`
        (via any edge type) -- the set that must be considered for STALE
        propagation when `node_id` changes."""
        seen: Set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for dependent in self._reverse_adj.get(current, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    frontier.append(dependent)
        return seen

    def detect_cycle(self) -> Optional[List[str]]:
        """DFS cycle detection over the dependency edges (src depends on
        dst). Returns the cycle as a list of node ids if one exists, else
        None. A verification-gated project's dependency graph must be
        acyclic by construction -- a cycle here is a data-integrity defect
        to fix, not a case for the engine to handle gracefully."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {nid: WHITE for nid in self.nodes}
        adj: Dict[str, List[str]] = {}
        for e in self.edges:
            adj.setdefault(e.src, []).append(e.dst)

        cycle_path: List[str] = []

        def dfs(node: str, path: List[str]) -> bool:
            color[node] = GRAY
            path.append(node)
            for nxt in adj.get(node, []):
                if color.get(nxt) == GRAY:
                    cycle_path.extend(path[path.index(nxt):] + [nxt])
                    return True
                if color.get(nxt) == WHITE and dfs(nxt, path):
                    return True
            path.pop()
            color[node] = BLACK
            return False

        for node in list(self.nodes):
            if color[node] == WHITE and dfs(node, []):
                return cycle_path
        return None


# ============================================================================
# Section 2 -- Change events and the dispatch table
# ============================================================================

EVENT_KINDS = (
    "source_reextracted",      # a source's stored text changed materially
    "evidence_edited",         # an evidence-ledger row's excerpt/status changed
    "evidence_added",          # a new evidence-ledger row landed
    "claim_edited",            # a claim-ledger row's text/status changed
    "claim_added",             # a new claim-ledger row landed
    "approval_revoked",        # an Approval node governing something was revoked
    "manual_flag",             # an owner or reviewer manually flags a node stale
)


@dataclass
class ChangeEvent:
    kind: str
    node_id: str
    node_type: str
    content_hash_before: str = ""
    content_hash_after: str = ""
    reason: str = ""

    def __post_init__(self):
        if self.kind not in EVENT_KINDS:
            raise MalformedChangeError(f"unknown event kind {self.kind!r}; must be one of {EVENT_KINDS}")


class MalformedChangeError(Exception):
    pass


@dataclass
class AffectedSetResult:
    trigger: ChangeEvent
    directly_changed: Set[str]
    downstream_stale: Set[str]

    def to_dict(self) -> dict:
        return {
            "trigger_kind": self.trigger.kind,
            "trigger_node_id": self.trigger.node_id,
            "directly_changed": sorted(self.directly_changed),
            "downstream_stale": sorted(self.downstream_stale),
            "total_affected": len(self.directly_changed | self.downstream_stale),
        }


def compute_affected_set(graph: Graph, event: ChangeEvent) -> AffectedSetResult:
    """The dispatch table. Every event kind resolves to a set of directly-
    changed nodes; every directly-changed node's full downstream closure
    (per `Graph.downstream_closure`) is then STALE. This is the one
    function to extend if you add a new event kind -- keep every branch
    explicit rather than a default catch-all, so an unhandled kind fails
    loudly (see `MalformedChangeError` above) instead of silently
    computing an empty affected set."""
    if not graph.has_node(event.node_id):
        raise MalformedChangeError(
            f"event references node {event.node_id!r}, not present in the graph",
            )

    if event.kind in ("source_reextracted", "evidence_edited", "claim_edited", "approval_revoked", "manual_flag"):
        directly_changed = {event.node_id}
    elif event.kind in ("evidence_added", "claim_added"):
        # A brand-new node has no history to invalidate; it starts FRESH
        # and has no downstream dependents yet by construction.
        return AffectedSetResult(trigger=event, directly_changed=set(), downstream_stale=set())
    else:  # pragma: no cover -- unreachable given ChangeEvent's own validation
        raise MalformedChangeError(f"unhandled event kind {event.kind!r}")

    downstream: Set[str] = set()
    for node_id in directly_changed:
        downstream |= graph.downstream_closure(node_id)
    downstream -= directly_changed

    return AffectedSetResult(trigger=event, directly_changed=directly_changed, downstream_stale=downstream)


def propagate_stale(graph: Graph, events: List[ChangeEvent]) -> Dict[str, AffectedSetResult]:
    """Apply `compute_affected_set` for every event, mark every affected
    node's `engine_status` STALE with a `stale_reason` naming which
    trigger caused it (first trigger wins if more than one event affects
    the same node in one batch -- record every trigger id in the reason
    string rather than silently overwriting), and return the per-event
    results for logging."""
    results: Dict[str, AffectedSetResult] = {}
    now = _now_iso()
    for event in events:
        result = compute_affected_set(graph, event)
        results[f"{event.kind}:{event.node_id}"] = result
        for node_id in result.directly_changed | result.downstream_stale:
            node = graph.nodes[node_id]
            if node.engine_status == EngineStatus.STALE.value:
                node.stale_reason += f"; also stale via {event.kind}:{event.node_id}"
            else:
                node.engine_status = EngineStatus.STALE.value
                node.stale_since = now
                reason = "directly changed" if node_id in result.directly_changed else "downstream of"
                node.stale_reason = f"{reason} {event.kind}:{event.node_id}"
    return results


# ============================================================================
# Section 3 -- Content hashing and change detection
# ============================================================================

def compute_content_hash(row: dict, fields: List[str]) -> str:
    """A stable content hash over a fixed field list -- the fields that
    define a row's substantive content, deliberately excluding bookkeeping
    columns like `engine_status`/`stale_since` (hashing those would make
    every staleness update look like a content change and defeat the
    engine's own idempotency)."""
    payload = "\x1f".join(str(row.get(f, "")) for f in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detect_row_events(
    node_type: str,
    prior_rows_by_id: Dict[str, dict],
    current_rows_by_id: Dict[str, dict],
    id_field: str,
    content_fields: List[str],
) -> List[ChangeEvent]:
    """Diff a ledger's prior snapshot against its current state and emit
    one `ChangeEvent` per added or content-changed row. A row present in
    both snapshots with an unchanged content hash emits nothing -- this is
    the mechanism that keeps the engine from re-flagging unchanged records
    on every run."""
    events: List[ChangeEvent] = []
    for row_id, row in current_rows_by_id.items():
        current_hash = compute_content_hash(row, content_fields)
        prior = prior_rows_by_id.get(row_id)
        if prior is None:
            events.append(ChangeEvent(
                kind=f"{node_type.lower()}_added", node_id=row_id, node_type=node_type,
                content_hash_after=current_hash,
            ))
            continue
        prior_hash = compute_content_hash(prior, content_fields)
        if prior_hash != current_hash:
            events.append(ChangeEvent(
                kind=f"{node_type.lower()}_edited", node_id=row_id, node_type=node_type,
                content_hash_before=prior_hash, content_hash_after=current_hash,
            ))
    return events


# ============================================================================
# Section 4 -- Event log (CSV, append-only)
# ============================================================================

EVENT_LOG_COLUMNS = [
    "event_id", "timestamp", "kind", "node_type", "node_id",
    "content_hash_before", "content_hash_after", "reason",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_invalidation_events(
    results: Dict[str, AffectedSetResult], events_log_path: str,
) -> int:
    """Append one row per (trigger, affected-node) pair to the event log,
    creating the file with a header if it does not yet exist. Returns the
    number of rows written. This is the file `tools/prov/export.py`
    expects to read."""
    os.makedirs(os.path.dirname(events_log_path) or ".", exist_ok=True)
    file_exists = os.path.exists(events_log_path)
    n_written = 0
    with open(events_log_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVENT_LOG_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for key, result in results.items():
            event = result.trigger
            for node_id in sorted(result.directly_changed | result.downstream_stale):
                writer.writerow({
                    "event_id": f"{key}:{node_id}",
                    "timestamp": _now_iso(),
                    "kind": event.kind,
                    "node_type": event.node_type,
                    "node_id": node_id,
                    "content_hash_before": event.content_hash_before,
                    "content_hash_after": event.content_hash_after,
                    "reason": event.reason,
                })
                n_written += 1
    return n_written


# ============================================================================
# Section 5 -- Wiring points for your own ledger schema
# ============================================================================
# The two functions below are stubs: everything above this line is
# reusable unmodified; everything below is where you connect the engine to
# your project's actual file layout. Replace the bodies with real CSV
# reads against your evidence/claim ledgers and your source manifest.

def load_live_graph(root: str) -> Graph:
    """Build a `Graph` from your project's live records. Replace this
    stub with real reads of your source manifest, evidence ledger, and
    claim ledger, adding one Node per row and one Edge per dependency
    (Evidence -wasDrawnFrom-> Source, Claim -supports-> Evidence, and so
    on for Use/Approval nodes if your project tracks them)."""
    raise NotImplementedError(
        "wire this to your project's manifest/evidence-ledger/claim-ledger "
        "file layout -- see the module docstring."
    )


def main() -> int:  # pragma: no cover -- illustrative entry point only
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument(
        "--events-log", default="logs/invalidation_events.csv",
        help="Path (relative to --root) to append the event log to.",
    )
    args = parser.parse_args()
    graph = load_live_graph(args.root)
    cycle = graph.detect_cycle()
    if cycle:
        raise MalformedGraphError("dependency graph contains a cycle", {"cycle": cycle})
    print(json.dumps({"n_nodes": len(graph.nodes), "n_edges": len(graph.edges)}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
