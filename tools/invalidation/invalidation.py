#!/usr/bin/env python3
"""
invalidation.py -- dependency-invalidation engine and CLI for
verification-gated research projects.

When a source, a quotation or a claim changes, which downstream records
does that make STALE, and why. The engine keeps a directed graph
(Source -> Quotation -> Claim -> ManuscriptUse, plus Ratification nodes for
anything that needs an owner's sign-off), a fixed vocabulary of nine
change events, and a deterministic dispatch table from event to affected
set. STALE propagates downstream transitively.

Parts of the module:

1. Graph model and dispatch table (`Graph`, `Node`, `Edge`,
   `compute_affected_set`).
2. Live-ledger loading (`load_live_graph`) and content-hash change
   detection (`compute_content_hash`, `detect_row_events`).
3. Schema-v2/v3 CSV and JSON migrations, each with a backup and an
   optimistic-concurrency check before any write.
4. The engine-status state machine (FRESH, STALE, CHECKING, ERROR, ...)
   and the `logs/invalidation_events.csv` writer.
5. A CLI: build-graph, check, mark-stale, report and the migrations.

Comments that cite "section N.M" refer to the numbered design notes of the
engine's original specification, which is not part of this repository.
The behaviour they describe is implemented here and covered by
`tests/test_live_engine.py`.

Default ledger paths (research/quote_ledger.csv, research/claim_ledger.csv,
Sources/source_manifest.csv and .json) are module constants near the top;
change them to match your project. No third-party dependency. Python 3
standard library only. Deterministic.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths (project-relative; this file lives at tools/invalidation/invalidation.py)
# ---------------------------------------------------------------------------

_THIS_FILE = os.path.abspath(__file__)
TOOLS_DIR = os.path.dirname(_THIS_FILE)
PROJECT_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, "..", ".."))

QUOTE_LEDGER_PATH = os.path.join(PROJECT_ROOT, "research", "quote_ledger.csv")
CLAIM_LEDGER_PATH = os.path.join(PROJECT_ROOT, "research", "claim_ledger.csv")
MANIFEST_CSV_PATH = os.path.join(PROJECT_ROOT, "Sources", "source_manifest.csv")
MANIFEST_JSON_PATH = os.path.join(PROJECT_ROOT, "Sources", "source_manifest.json")
EVENTS_LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "invalidation_events.csv")
PRE_SCHEMA_V2_DIR = os.path.join(PROJECT_ROOT, "logs", "pre_schema_v2")
PRE_SCHEMA_V3_DIR = os.path.join(PROJECT_ROOT, "logs", "pre_schema_v3")
ENGINE_VERSION = "1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


NODE_TYPES = ("Source", "Quotation", "Claim", "ManuscriptUse", "Ratification")
EDGE_TYPES = ("wasQuotedFrom", "quote_id_join", "locator_pin", "governs")


class TerminalState(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    ERROR_MALFORMED_INPUT = "ERROR_MALFORMED_INPUT"
    ERROR_CYCLE_DETECTED = "ERROR_CYCLE_DETECTED"


class EngineStatus(str, Enum):
    """section 3.5 -- the live engine's own persistent per-row status, layered
    on top of (never replacing) each predicate's existing verdict vocabulary."""

    FRESH = "FRESH"
    STALE = "STALE"
    CHECKING = "CHECKING"
    ERROR = "ERROR"
    RATIFICATION_PENDING = "RATIFICATION-PENDING"
    UNTRACKED = "UNTRACKED"


# ---------------------------------------------------------------------------
# Section 1 -- Graph data model (ported verbatim from invalidation_ref.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    payload: dict = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self):
        if self.type not in NODE_TYPES:
            raise ValueError(f"unknown node type {self.type!r} for node {self.id!r}")


@dataclass(frozen=True)
class Edge:
    src: str  # id of the node the dependent relies on (the "input")
    dst: str  # id of the dependent node (the "output" / downstream record)
    type: str

    def __post_init__(self):
        if self.type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {self.type!r}")


class MalformedGraphError(Exception):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.details = details or {}


class Graph:
    """Directed graph of Source/Quotation/Claim/ManuscriptUse/Ratification
    nodes. Edge direction: src is the thing depended ON (the input); dst is
    the thing that DEPENDS on it (the downstream record). "Invalidation
    flows this direction," the opposite of "citation points at its source."
    """

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._forward: Dict[str, Set[str]] = {}
        self._backward: Dict[str, Set[str]] = {}

    def add_node(self, node: Node) -> None:
        existing = self.nodes.get(node.id)
        if existing is not None and existing.type != node.type:
            raise MalformedGraphError(
                f"node id {node.id!r} redefined with a different type "
                f"({existing.type!r} -> {node.type!r})",
                {"node_id": node.id, "old_type": existing.type, "new_type": node.type},
            )
        self.nodes[node.id] = node
        self._forward.setdefault(node.id, set())
        self._backward.setdefault(node.id, set())

    def add_edge(self, edge: Edge) -> None:
        for end in (edge.src, edge.dst):
            if end not in self.nodes:
                raise MalformedGraphError(
                    f"edge references unknown node {end!r}",
                    {"edge": (edge.src, edge.dst, edge.type)},
                )
        self.edges.append(edge)
        self._forward[edge.src].add(edge.dst)
        self._backward[edge.dst].add(edge.src)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def node_type(self, node_id: str) -> Optional[str]:
        n = self.nodes.get(node_id)
        return n.type if n else None

    def forward_neighbors(self, node_id: str, of_type: Optional[str] = None) -> Set[str]:
        out = set(self._forward.get(node_id, ()))
        if of_type is not None:
            out = {n for n in out if self.node_type(n) == of_type}
        return out

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return
        for other in list(self._forward.get(node_id, ())):
            self._backward[other].discard(node_id)
        for other in list(self._backward.get(node_id, ())):
            self._forward[other].discard(node_id)
        self._forward.pop(node_id, None)
        self._backward.pop(node_id, None)
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges if e.src != node_id and e.dst != node_id]

    def downstream_closure(
        self, start_ids: Iterable[str], via_types: Optional[Set[str]] = None
    ) -> Set[str]:
        seen: Set[str] = set()
        stack: List[str] = list(start_ids)
        edge_index = self._forward
        if via_types is not None:
            edge_index = self._filtered_forward(via_types)
        while stack:
            cur = stack.pop()
            for nxt in edge_index.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def _filtered_forward(self, via_types: Set[str]) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {n: set() for n in self.nodes}
        for e in self.edges:
            if e.type in via_types:
                out.setdefault(e.src, set()).add(e.dst)
        return out

    def detect_cycle(self) -> Optional[List[str]]:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        parent: Dict[str, Optional[str]] = {n: None for n in self.nodes}

        for start in self.nodes:
            if color[start] != WHITE:
                continue
            stack: List[Tuple[str, Iterable[str]]] = [(start, iter(self._forward.get(start, ())))]
            color[start] = GRAY
            while stack:
                node, it = stack[-1]
                advanced = False
                for nxt in it:
                    advanced = True
                    if color[nxt] == WHITE:
                        color[nxt] = GRAY
                        parent[nxt] = node
                        stack.append((nxt, iter(self._forward.get(nxt, ()))))
                    elif color[nxt] == GRAY:
                        path = [node]
                        cur = node
                        while cur != nxt and parent[cur] is not None:
                            cur = parent[cur]
                            path.append(cur)
                        path.reverse()
                        return path + [nxt]
                    break
                if not advanced:
                    color[stack.pop()[0]] = BLACK
        return None


# ---------------------------------------------------------------------------
# Frozen-snapshot loading (ported verbatim -- kept for parity/self-test use;
# never touches the live, mutable ledgers)
# ---------------------------------------------------------------------------

import re as _re

_MULTI_SPLIT_RE = _re.compile(r"\s*;\s*")


def parse_quote_id_field(raw: str) -> Tuple[List[str], Optional[str]]:
    s = raw.strip()
    if s == "":
        return [], None
    if s.startswith(";") or s.endswith(";") or ";;" in s:
        return [], f"malformed multi-value quote_id: {raw!r} (leading/trailing/doubled semicolon)"
    parts = [p.strip() for p in _MULTI_SPLIT_RE.split(s)]
    if any(p == "" for p in parts):
        return [], f"malformed multi-value quote_id: {raw!r} (empty segment after split)"
    return parts, None


@dataclass
class BuildReport:
    sources_loaded: int = 0
    quotations_loaded: int = 0
    claims_loaded: int = 0
    edges_was_quoted_from: int = 0
    edges_quote_id_join: int = 0
    multi_value_claim_rows: int = 0
    malformed_claim_rows: List[dict] = field(default_factory=list)
    quotations_with_unresolved_source: List[str] = field(default_factory=list)
    claims_with_unresolved_quote_ref: List[dict] = field(default_factory=list)
    cycle_detected: Optional[List[str]] = None

    def to_dict(self) -> dict:
        return {
            "sources_loaded": self.sources_loaded,
            "quotations_loaded": self.quotations_loaded,
            "claims_loaded": self.claims_loaded,
            "edges_was_quoted_from": self.edges_was_quoted_from,
            "edges_quote_id_join": self.edges_quote_id_join,
            "multi_value_claim_rows": self.multi_value_claim_rows,
            "malformed_claim_rows": self.malformed_claim_rows,
            "quotations_with_unresolved_source": self.quotations_with_unresolved_source,
            "claims_with_unresolved_quote_ref": self.claims_with_unresolved_quote_ref,
            "cycle_detected": self.cycle_detected,
        }


def _build_graph_from_rows(
    manifest_rows: List[dict],
    quote_rows: List[dict],
    claim_rows: List[dict],
    strict: bool = False,
) -> Tuple[Graph, BuildReport]:
    report = BuildReport()
    g = Graph()

    for row in manifest_rows:
        slug = (row.get("slug") or "").strip()
        if not slug:
            continue
        g.add_node(Node(slug, "Source", payload=row))
        report.sources_loaded += 1

    for row in quote_rows:
        qid = (row.get("quote_id") or "").strip()
        if not qid:
            continue
        g.add_node(Node(qid, "Quotation", payload=row))
        report.quotations_loaded += 1
        slug = (row.get("slug") or "").strip()
        if slug and g.has_node(slug):
            g.add_edge(Edge(slug, qid, "wasQuotedFrom"))
            report.edges_was_quoted_from += 1
        else:
            report.quotations_with_unresolved_source.append(qid)

    for row in claim_rows:
        cid = (row.get("claim_id") or "").strip()
        if not cid:
            continue
        g.add_node(Node(cid, "Claim", payload=row))
        report.claims_loaded += 1
        raw_qid = row.get("quote_id") or ""
        ids, err = parse_quote_id_field(raw_qid)
        if err is not None:
            if strict:
                raise MalformedGraphError(err, {"claim_id": cid, "raw_quote_id": raw_qid})
            report.malformed_claim_rows.append({"claim_id": cid, "raw_quote_id": raw_qid, "reason": err})
            continue
        if len(ids) > 1:
            report.multi_value_claim_rows += 1
        for qid in ids:
            if g.has_node(qid) and g.node_type(qid) == "Quotation":
                g.add_edge(Edge(qid, cid, "quote_id_join"))
                report.edges_quote_id_join += 1
            else:
                report.claims_with_unresolved_quote_ref.append({"claim_id": cid, "quote_id": qid})

    report.cycle_detected = g.detect_cycle()
    return g, report


def load_frozen_graph(
    quote_ledger_csv: str,
    claim_ledger_csv: str,
    manifest_csv: str,
    strict: bool = False,
) -> Tuple[Graph, BuildReport]:
    """Builds a Graph from a FROZEN snapshot. Never touches the live ledgers
    -- the caller supplies frozen_inputs/-style paths. Kept for parity with
    the original research engine and for testing against any future frozen
    snapshot; the live production path is `load_live_graph` below."""
    with open(manifest_csv, newline="", encoding="utf-8") as fh:
        manifest_rows = list(csv.DictReader(fh))
    with open(quote_ledger_csv, newline="", encoding="utf-8") as fh:
        quote_rows = list(csv.DictReader(fh))
    with open(claim_ledger_csv, newline="", encoding="utf-8") as fh:
        claim_rows = list(csv.DictReader(fh))
    return _build_graph_from_rows(manifest_rows, quote_rows, claim_rows, strict=strict)


# ---------------------------------------------------------------------------
# Live-graph loader. Same graph model,
# new input source: the current, mutable ledgers, read fresh every call.
# ---------------------------------------------------------------------------


def _normalize_manifest_raw(raw: Any) -> List[dict]:
    """Shared list/dict normalization for a manifest JSON value already
    parsed into memory (as opposed to `manifest_json_entries`, which also
    does the file read) -- used by `cmd_check` for both the --since
    (git show text) and --against (snapshot file) code paths so both share
    exactly one normalization rule."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        out = []
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                raise MalformedGraphError(f"manifest JSON entry for key {key!r} is not itself an object")
            e = dict(entry)
            e.setdefault("slug", key)
            out.append(e)
        return out
    raise MalformedGraphError("manifest JSON value is neither a list nor a dict of entries")


def manifest_json_entries(manifest_json_path: str) -> List[dict]:
    """Loads the manifest JSON into a flat list of entry dicts, tolerating
    two shapes:
      (a) a list of entry dicts, and
      (b) a dict keyed by slug -> entry dict, where each value already
          carries its own 'slug' field.
    The manifest JSON's per-entry field names may differ from
    `source_manifest.csv`'s header; this function does not assume
    field-name parity between the two, only that each entry is a dict."""
    with open(manifest_json_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        out = []
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                raise MalformedGraphError(
                    f"manifest JSON entry for key {key!r} is not itself an object"
                )
            e = dict(entry)
            e.setdefault("slug", key)
            out.append(e)
        return out
    raise MalformedGraphError(
        f"manifest JSON at {manifest_json_path!r} is neither a list nor a dict of entries"
    )


def load_live_graph(
    quote_ledger_path: str = QUOTE_LEDGER_PATH,
    claim_ledger_path: str = CLAIM_LEDGER_PATH,
    manifest_json_path: str = MANIFEST_JSON_PATH,
    strict: bool = False,
) -> Tuple[Graph, BuildReport]:
    """Mirrors `load_frozen_graph`'s signature and logic exactly (same graph model,
    different input), reading the live, mutable paths instead of frozen_inputs/.
    Reads the manifest from its JSON form via `manifest_json_entries` (see
    that function's docstring for the dict-vs-list shape) rather than assuming a single fixed JSON shape."""
    manifest_rows = manifest_json_entries(manifest_json_path)
    with open(quote_ledger_path, newline="", encoding="utf-8") as fh:
        quote_rows = list(csv.DictReader(fh))
    with open(claim_ledger_path, newline="", encoding="utf-8") as fh:
        claim_rows = list(csv.DictReader(fh))
    return _build_graph_from_rows(manifest_rows, quote_rows, claim_rows, strict=strict)


# ---------------------------------------------------------------------------
# Section 2 -- Change events and affected-set computation (ported verbatim)
# ---------------------------------------------------------------------------


@dataclass
class ChangeEvent:
    kind: str
    detail: dict = field(default_factory=dict)


@dataclass
class AffectedSetResult:
    terminal_state: TerminalState
    affected_ids: List[str]
    error: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "terminal_state": self.terminal_state.value,
            "affected_ids": sorted(self.affected_ids),
            "error": self.error,
            "notes": self.notes,
        }


class MalformedChangeError(Exception):
    pass


EVENT_KINDS = (
    "quotation_content_changed",
    "source_content_changed",
    "source_merge",
    "claim_revised",
    "evidence_deleted",
    "corpus_added",
    "corpus_removed",
    "ratification_superseded",
    "irrelevant_metadata_edited",
)


def compute_affected_set(graph: Graph, event: ChangeEvent) -> AffectedSetResult:
    cyc = graph.detect_cycle()
    if cyc is not None:
        return AffectedSetResult(
            TerminalState.ERROR_CYCLE_DETECTED,
            [],
            error=f"cycle detected: {' -> '.join(cyc)}",
            notes="affected-set computation aborted before traversal to avoid an unbounded walk",
        )
    try:
        return _dispatch_event(graph, event)
    except MalformedChangeError as exc:
        return AffectedSetResult(TerminalState.ERROR_MALFORMED_INPUT, [], error=str(exc))


def _finish(affected: Set[str]) -> AffectedSetResult:
    ids = sorted(affected)
    state = TerminalState.DIRTY if ids else TerminalState.CLEAN
    return AffectedSetResult(state, ids)


def _dispatch_event(graph: Graph, event: ChangeEvent) -> AffectedSetResult:
    kind = event.kind
    d = event.detail

    if kind not in EVENT_KINDS:
        raise MalformedChangeError(f"unrecognized change-event kind {kind!r}")

    if kind == "quotation_content_changed":
        qid = d["quotation_id"]
        if not graph.has_node(qid):
            raise MalformedChangeError(f"quotation_content_changed: unknown node {qid!r}")
        affected = {qid} | graph.downstream_closure({qid})
        return _finish(affected)

    if kind == "source_content_changed":
        sid = d["source_id"]
        if not graph.has_node(sid):
            raise MalformedChangeError(f"source_content_changed: unknown node {sid!r}")
        affected = graph.downstream_closure({sid})
        return _finish(affected)

    if kind == "source_merge":
        old_id, new_id = d["old_source_id"], d["new_source_id"]
        if not graph.has_node(old_id):
            raise MalformedChangeError(f"source_merge: unknown old_source_id {old_id!r}")
        if not graph.has_node(new_id):
            raise MalformedChangeError(f"source_merge: unknown new_source_id {new_id!r}")
        affected = graph.forward_neighbors(old_id, of_type="Quotation")
        return _finish(affected)

    if kind == "claim_revised":
        cid = d["claim_id"]
        if not graph.has_node(cid):
            raise MalformedChangeError(f"claim_revised: unknown node {cid!r}")
        affected = {cid} | graph.downstream_closure({cid})
        return _finish(affected)

    if kind == "evidence_deleted":
        qid = d["quotation_id"]
        if not graph.has_node(qid):
            raise MalformedChangeError(f"evidence_deleted: unknown node {qid!r}")
        affected = graph.downstream_closure({qid})
        graph.remove_node(qid)
        return _finish(affected)

    if kind == "corpus_added":
        sid = d["source_id"]
        if not graph.has_node(sid):
            raise MalformedChangeError(f"corpus_added: node {sid!r} must already be added to the graph")
        affected = graph.downstream_closure({sid})
        return _finish(affected)

    if kind == "corpus_removed":
        sid = d["source_id"]
        if not graph.has_node(sid):
            raise MalformedChangeError(f"corpus_removed: unknown node {sid!r}")
        direct_quotes = graph.forward_neighbors(sid, of_type="Quotation")
        direct_claims_by_slug = {
            n for n, node in graph.nodes.items()
            if node.type == "Claim" and (node.payload.get("slug") or "").strip() == sid
        }
        transitive_claims: Set[str] = set()
        for q in direct_quotes:
            transitive_claims |= graph.downstream_closure({q})
        affected = direct_quotes | direct_claims_by_slug | transitive_claims
        graph.remove_node(sid)
        return _finish(affected)

    if kind == "ratification_superseded":
        rid = d["ratification_id"]
        if not graph.has_node(rid):
            raise MalformedChangeError(f"ratification_superseded: unknown node {rid!r}")
        affected = graph.downstream_closure({rid}, via_types={"governs"})
        bad = {a for a in affected if graph.node_type(a) not in ("ManuscriptUse",)}
        if bad:
            raise MalformedChangeError(
                "ratification_superseded reached non-ManuscriptUse node(s) via a "
                f"'governs' edge -- graph modeled incorrectly for this fixture: {sorted(bad)}"
            )
        return _finish(affected)

    if kind == "irrelevant_metadata_edited":
        return AffectedSetResult(TerminalState.CLEAN, [])

    raise MalformedChangeError(f"unhandled change-event kind {kind!r}")  # pragma: no cover


def live_system_affected_set(_event: ChangeEvent) -> List[str]:
    """The earlier live posture's answer: always empty (full-resweep-
    only, no selective invalidation -- the verification contract).
    Retained for delta-reporting parity with the original fixture suite.
    Superseded, as of this module, by the fact that a live engine now
    exists (Sections 3-6) -- this function documents the PRIOR posture and
    is not the live engine's own answer."""
    return []


def invalidate_everything_baseline(graph: Graph) -> List[str]:
    return sorted(n for n, node in graph.nodes.items() if node.type in ("Quotation", "Claim"))


# ---------------------------------------------------------------------------
# Section 3 -- Schema-v2 columns (section 3.1)
# ---------------------------------------------------------------------------

# field -> which content-hash formula it feeds, per section 3.1's table.
QUOTE_CONTENT_HASH_FIELDS = ["exact_quote", "slug", "citable_status"]
CLAIM_CONTENT_HASH_FIELDS = ["claim_text", "quote_id", "slug", "citable_status"]
MANIFEST_IDENTITY_HASH_FIELDS = ["sha256", "peer_review_status", "duplicate_of", "version"]
MANIFEST_EXTRACTION_HASH_FIELDS = ["extraction_status", "extracted_chars", "word_count"]

# node_type -> its content-hash field list, keyed the same way DetectedEvent.node_type
# is populated ("quotation"/"claim"). This is the lookup
# `detect_row_events` uses to populate content_hash_before/content_hash_after on every
# row_edit/row_add/row_remove event it emits, so `log_firing` never has to fall
# back to a hardcoded "" (tools/prov/export.py's entity_urn() maps an empty hash to
# the literal suffix ":nohash" for BOTH the before- and after-node of a
# wasRevisionOf edge, so two empty hashes collapse onto one self-referencing URN
# that tools/prov/validate_store.py's acyclicity checks correctly flag).
NODE_TYPE_CONTENT_HASH_FIELDS: Dict[str, List[str]] = {
    "quotation": QUOTE_CONTENT_HASH_FIELDS,
    "claim": CLAIM_CONTENT_HASH_FIELDS,
}

# Design note on manifest hashing:
#
# The CSV manifest and the JSON manifest use different schemas. The
# identity/extraction field lists above name the CSV's column names. The
# JSON manifest has no peer_review_status, duplicate_of, version,
# extraction_status, extracted_chars or word_count, so feeding the CSV
# field names to `compute_content_hash` against a JSON entry would resolve
# them all to "" (missing fields count as empty strings) and the JSON's
# extraction_hash would be constant across the whole manifest. The JSON
# lists below therefore use the closest analog fields:
#   - identity: `citability` (the JSON analog of peer_review_status),
#     plus `doi` and `pub_year` as bibliographic identity facts.
#     duplicate_of and version have no JSON equivalent, so the JSON
#     identity formula is deliberately narrower (4 fields, not 4 matching).
#   - extraction: `extracted_on`, `extracted_size` (the analog of
#     extracted_chars) and `intake_notes` as a free-text discriminator,
#     since the JSON has no word_count.
MANIFEST_IDENTITY_HASH_FIELDS_JSON = ["sha256", "citability", "doi", "pub_year"]
MANIFEST_EXTRACTION_HASH_FIELDS_JSON = ["extracted_on", "extracted_size", "intake_notes"]

# section 4.3 field classification -- reused by both the live engine (section 3.3
# rule 2) and the retroactive replay (section 4.7).
QUOTE_VERIFICATION_BEARING = {"exact_quote", "slug", "citable_status"}
QUOTE_STATUS_ONLY = {
    "verification_status", "verification_method", "verification_date",
    "verification_notes", "intended_use", "pdf_page", "printed_page",
    "section", "surrounding_context",
}
CLAIM_VERIFICATION_BEARING = {"claim_text", "quote_id", "slug", "citable_status"}
CLAIM_STATUS_ONLY = {
    "claim_verification_status", "claim_verification_method",
    "claim_verification_date", "claim_verification_notes", "limits",
    "locus", "printed_page", "proposed_use",
}
MANIFEST_IDENTITY_FIELDS = {"sha256", "peer_review_status", "duplicate_of", "version"}
MANIFEST_EXTRACTION_FIELDS = {"extraction_status", "extracted_chars", "word_count"}
MANIFEST_SECONDARY_FIELDS = {"venue", "doi", "pub_year"}
MANIFEST_RECORD_ONLY_FIELDS = {
    "original_filename", "bytes", "filetype", "size_class",
    "classification_evidence", "location", "notes",
}

QUOTE_SCHEMA_V2_COLUMNS = ["content_hash", "engine_status", "stale_since", "stale_reason"]
CLAIM_SCHEMA_V2_COLUMNS = ["content_hash", "engine_status", "stale_since", "stale_reason"]
MANIFEST_SCHEMA_V2_COLUMNS = ["identity_hash", "extraction_hash"]

# Schema-v3: one additive per-row provenance-date
# column on each ledger. Named `row_provenance_date`, NOT `verification_date`,
# because `quote_ledger.csv` already
# has a column named `verification_date` with a DIFFERENT
# meaning (a checking-time fact, a status-only column) -- reusing
# that name for a generation/edit-time fact would silently overload one
# column name with two incompatible meanings on the same file.
QUOTE_SCHEMA_V3_COLUMNS = ["row_provenance_date"]
CLAIM_SCHEMA_V3_COLUMNS = ["row_provenance_date"]


def compute_content_hash(row: dict, fields: List[str]) -> str:
    """section 3.1's formula: field values joined with \\x1f, UTF-8, NFC-
    normalized, then sha256. Missing fields are treated as empty strings
    (never as a KeyError) so a schema that later gains an optional field
    does not change every prior hash retroactively for rows that lack it."""
    parts = []
    for f in fields:
        v = row.get(f, "")
        if v is None:
            v = ""
        parts.append(unicodedata.normalize("NFC", str(v)))
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Live-ledger IO helpers -- csv.reader-validated read, atomic write,
# optimistic-concurrency check, pre-change backup.
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv_rows_and_header(path: str) -> Tuple[List[str], List[dict]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return header, rows


def _validate_csv_field_counts(path: str) -> Tuple[int, int]:
    """Returns (row_count, mismatch_count) via a raw csv.reader parse --
    counts any data row whose field count differs from the header's."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        n_header = len(header)
        n_rows = 0
        n_mismatch = 0
        for row in reader:
            n_rows += 1
            if len(row) != n_header:
                n_mismatch += 1
    return n_rows, n_mismatch


def _atomic_write_text(path: str, text: str) -> None:
    """Writes to a same-directory temp file then os.replace()s it over the
    target -- never leaves a half-written file at `path` if interrupted."""
    directory = os.path.dirname(path)
    fd_path = path + f".tmp_{os.getpid()}_{int(time.time()*1000)}"
    with open(fd_path, "w", newline="", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(fd_path, path)


def _backup_pre_schema_v2(path: str, backup_dir: str = PRE_SCHEMA_V2_DIR, suffix: str = ".pre_v2") -> str:
    """Copies `path` to `backup_dir/<basename><suffix>` (suffix defaults to
    `.pre_v2`, unchanged for every pre-existing call site). `backup_dir`
    MUST be explicitly passed by any caller operating on a non-live file
    (tests, fixtures) -- it defaults to the project's
    `logs/pre_schema_v2/` ONLY so that a direct call with no override
    still does the production-correct thing. This parameter exists
    specifically because an earlier version of this function used the
    global PRE_SCHEMA_V2_DIR unconditionally: test fixtures that
    reused the real basenames (`quote_ledger.csv`, `source_manifest.json`)
    silently overwrote the project's safety backups for those names (caught and fixed in testing). `suffix` exists
    so `migrate_csv_schema_v3` can write
    `<basename>.pre_v3` into `logs/pre_schema_v3/` while reusing this
    same backup primitive rather than forking it."""
    os.makedirs(backup_dir, exist_ok=True)
    base = os.path.basename(path)
    dest = os.path.join(backup_dir, base + suffix)
    shutil.copy2(path, dest)
    return dest


@dataclass
class MigrationResult:
    path: str
    applied: bool
    reason: str
    rows_before: int = 0
    rows_after: int = 0
    mismatches_before: int = 0
    mismatches_after: int = 0
    backup_path: Optional[str] = None
    columns_added: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(
            path=self.path, applied=self.applied, reason=self.reason,
            rows_before=self.rows_before, rows_after=self.rows_after,
            mismatches_before=self.mismatches_before, mismatches_after=self.mismatches_after,
            backup_path=self.backup_path, columns_added=self.columns_added,
        )


def migrate_csv_schema_v2(
    path: str,
    new_columns: List[str],
    content_hash_fields: Optional[List[str]] = None,
    apply: bool = True,
    backup_dir: str = PRE_SCHEMA_V2_DIR,
) -> MigrationResult:
    """Additive-only schema migration for one CSV ledger:
      1. Backs up the pre-migration file to `backup_dir` (defaults to the
         real logs/pre_schema_v2/ -- callers operating on non-live/fixture
         files, e.g. tests, MUST override this to an isolated directory;
         see `_backup_pre_schema_v2`'s docstring for why this matters).
      2. Validates the file with csv.reader (0 field-count mismatches
         required before proceeding -- a corrupt input is refused, not
         silently repaired).
      3. If the new columns already exist, this is a no-op (idempotent
         re-run -- reports applied=False, reason='already migrated').
      4. Computes content_hash (if content_hash_fields given) per row and
         sets engine_status=FRESH, stale_since='', stale_reason='' for
         every row -- a freshly-migrated row's hash is defined to match its
         own current content, so FRESH is correct, not presumptive.
      5. Re-reads the file immediately before writing and compares its
         sha256 to the value captured at step 2 (optimistic concurrency
         check) -- if any other process touched the file in between, the
         migration ABORTS without writing, rather than silently clobbering
         a concurrent writer's rows (one writer per shared file; delete nothing).
      6. Writes atomically (temp file + os.replace).
      7. Re-validates with csv.reader; requires rows_after == rows_before
         and 0 field-count mismatches, or raises.
    """
    if not os.path.exists(path):
        return MigrationResult(path, False, f"file not found: {path}")

    rows_before_n, mism_before = _validate_csv_field_counts(path)
    if mism_before != 0:
        return MigrationResult(
            path, False,
            f"refused: {mism_before} pre-existing field-count mismatch(es) in {path}; "
            "fix the source defect before migrating (this tool does not silently repair)",
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    header, rows = _read_csv_rows_and_header(path)
    already_present = [c for c in new_columns if c in header]
    if already_present:
        return MigrationResult(
            path, False,
            f"already migrated: columns {already_present} already present in header",
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    pre_hash = _sha256_file(path)

    if not apply:
        return MigrationResult(
            path, False, "dry-run (apply=False); no changes made",
            rows_before=rows_before_n, mismatches_before=mism_before,
            columns_added=new_columns,
        )

    backup_path = _backup_pre_schema_v2(path, backup_dir=backup_dir)

    new_header = header + new_columns
    out_rows = []
    for row in rows:
        new_row = dict(row)
        if content_hash_fields is not None and "content_hash" in new_columns:
            new_row["content_hash"] = compute_content_hash(row, content_hash_fields)
        if "engine_status" in new_columns:
            new_row["engine_status"] = EngineStatus.FRESH.value
        if "stale_since" in new_columns:
            new_row["stale_since"] = ""
        if "stale_reason" in new_columns:
            new_row["stale_reason"] = ""
        if "identity_hash" in new_columns:
            new_row["identity_hash"] = compute_content_hash(row, MANIFEST_IDENTITY_HASH_FIELDS)
        if "extraction_hash" in new_columns:
            new_row["extraction_hash"] = compute_content_hash(row, MANIFEST_EXTRACTION_HASH_FIELDS)
        out_rows.append(new_row)

    # Optimistic-concurrency re-check, as close to the write as practical.
    post_check_hash = _sha256_file(path)
    if post_check_hash != pre_hash:
        return MigrationResult(
            path, False,
            "ABORTED: file changed on disk between read and write "
            "(concurrent writer detected via sha256 mismatch) -- no write "
            "performed; re-run once no other process is touching this file",
            rows_before=rows_before_n, mismatches_before=mism_before,
            backup_path=backup_path,
        )

    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=new_header)
    writer.writeheader()
    for row in out_rows:
        writer.writerow(row)
    _atomic_write_text(path, buf.getvalue())

    rows_after_n, mism_after = _validate_csv_field_counts(path)
    result = MigrationResult(
        path, True, "migrated",
        rows_before=rows_before_n, rows_after=rows_after_n,
        mismatches_before=mism_before, mismatches_after=mism_after,
        backup_path=backup_path, columns_added=new_columns,
    )
    if rows_after_n != rows_before_n or mism_after != 0:
        raise RuntimeError(
            f"POST-MIGRATION VALIDATION FAILED for {path}: "
            f"rows_before={rows_before_n} rows_after={rows_after_n} "
            f"mismatches_after={mism_after}. Backup preserved at {backup_path}. "
            "Restore from backup and investigate before re-running."
        )
    return result


def migrate_csv_schema_v3(
    path: str,
    new_columns: List[str],
    apply: bool = True,
    backup_dir: str = PRE_SCHEMA_V3_DIR,
) -> MigrationResult:
    """Schema-v3 migration: adds `row_provenance_date` to one live ledger, additive-only, ZERO
    content change to any existing cell. Every PRE-EXISTING row gets
    `row_provenance_date = ""` -- an explicit empty string, never a
    synthesized "best guess" date (the literal mechanism
    of the 'no retroactive claims' rule). New/edited rows are stamped
    by the live-engine firing that creates/edits them (by design), NOT by this migration step -- see `stamp_row_provenance_dates`
    below, which is what a records-merge firing calls instead.

    Steps, identical in shape to `migrate_csv_schema_v2` (section 2.2 explicitly
    specifies reusing that exact pattern) but with the STRONGER
    post-migration check section 2.2 step 7 requires for this migration
    specifically: a full column-value equality check on every PRE-EXISTING
    column, every row, before vs. after (cheap here because this migration
    adds exactly one column with a single fixed value for every row -- no
    per-row computation, unlike v2's content hashes -- so a spot-check is
    not the strongest available check and is not used)."""
    if not os.path.exists(path):
        return MigrationResult(path, False, f"file not found: {path}")

    rows_before_n, mism_before = _validate_csv_field_counts(path)
    if mism_before != 0:
        return MigrationResult(
            path, False,
            f"refused: {mism_before} pre-existing field-count mismatch(es) in {path}; "
            "fix the source defect before migrating",
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    header, rows = _read_csv_rows_and_header(path)
    already_present = [c for c in new_columns if c in header]
    if already_present:
        return MigrationResult(
            path, False,
            f"already migrated: columns {already_present} already present in header",
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    pre_hash = _sha256_file(path)

    if not apply:
        return MigrationResult(
            path, False, "dry-run (apply=False); no changes made",
            rows_before=rows_before_n, mismatches_before=mism_before,
            columns_added=new_columns,
        )

    backup_path = _backup_pre_schema_v2(path, backup_dir=backup_dir, suffix=".pre_v3")

    new_header = header + new_columns
    out_rows = []
    for row in rows:
        new_row = dict(row)
        for col in new_columns:
            new_row[col] = ""  # section 2.2 step 4: additive, never backfilled
        out_rows.append(new_row)

    # Optimistic-concurrency re-check, as close to the write as practical.
    post_check_hash = _sha256_file(path)
    if post_check_hash != pre_hash:
        return MigrationResult(
            path, False,
            "ABORTED: file changed on disk between read and write "
            "(concurrent writer detected via sha256 mismatch) -- no write performed",
            rows_before=rows_before_n, mismatches_before=mism_before, backup_path=backup_path,
        )

    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=new_header)
    writer.writeheader()
    for row in out_rows:
        writer.writerow(row)
    _atomic_write_text(path, buf.getvalue())

    rows_after_n, mism_after = _validate_csv_field_counts(path)

    # section 2.2 step 7: FULL column-value equality check, every pre-existing
    # column, every row -- not a spot-check.
    _, rows_after_full = _read_csv_rows_and_header(path)
    n_field_drift = 0
    drift_examples: List[str] = []
    for before, after in zip(rows, rows_after_full):
        for col in header:
            if str(before.get(col, "")) != str(after.get(col, "")):
                n_field_drift += 1
                if len(drift_examples) < 5:
                    drift_examples.append(f"{before.get(header[0], '?')}.{col}")

    result = MigrationResult(
        path, True, f"migrated (full pre-existing-column equality check: {n_field_drift} drifts)",
        rows_before=rows_before_n, rows_after=rows_after_n,
        mismatches_before=mism_before, mismatches_after=mism_after,
        backup_path=backup_path, columns_added=new_columns,
    )
    if rows_after_n != rows_before_n or mism_after != 0 or n_field_drift != 0:
        raise RuntimeError(
            f"POST-MIGRATION VALIDATION FAILED for {path}: "
            f"rows_before={rows_before_n} rows_after={rows_after_n} "
            f"mismatches_after={mism_after} field_drift={n_field_drift} "
            f"(examples: {drift_examples}). Backup preserved at {backup_path}. "
            "Restore from backup and investigate before re-running."
        )
    return result


def migrate_schema_v3(apply: bool = True) -> Dict[str, dict]:
    """Runs the schema-v3 migration against both live ledgers. Mirrors
    `migrate_schema_v2`'s own aggregate-wrapper shape. Only the two
    ledgers section 2 specifies get `row_provenance_date` --
    the source manifest is out of scope for schema v3 (section 1's own scope
    list names only `quote_ledger.csv`/`claim_ledger.csv`)."""
    results = {}
    results["quote_ledger"] = migrate_csv_schema_v3(
        QUOTE_LEDGER_PATH, QUOTE_SCHEMA_V3_COLUMNS, apply=apply
    ).to_dict()
    results["claim_ledger"] = migrate_csv_schema_v3(
        CLAIM_LEDGER_PATH, CLAIM_SCHEMA_V3_COLUMNS, apply=apply
    ).to_dict()
    return results


def stamp_row_provenance_dates(node_ids: Dict[str, List[str]]) -> Dict[str, Any]:
    """section 2.2's final paragraph: new/edited rows are
    stamped with the ISO-8601 date of the records-merge firing that
    created/edited them, by that SAME firing -- not by the migration step.
    `node_ids` is {"quote_id": [...], "claim_id": [...]} -- exactly the
    keys of rows this firing's own row_add/row_edit detection found.
    Writes ONLY the `row_provenance_date` cell for the given keys; every
    other column, on every row (including rows NOT in `node_ids`), is
    required to be byte-identical before vs. after."""
    results: Dict[str, Any] = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for path, key_field, key_name in (
        (QUOTE_LEDGER_PATH, "quote_id", "quote_id"),
        (CLAIM_LEDGER_PATH, "claim_id", "claim_id"),
    ):
        keys = set(node_ids.get(key_name, []))
        if not keys:
            results[os.path.basename(path)] = {"written": 0, "note": "no keys given for this ledger"}
            continue
        header, rows = _read_csv_rows_and_header(path)
        if "row_provenance_date" not in header:
            results[os.path.basename(path)] = {
                "written": 0, "error": "row_provenance_date column absent -- run migrate-schema-v3 first",
            }
            continue
        pre_hash = _sha256_file(path)
        n_written = 0
        for row in rows:
            if (row.get(key_field) or "").strip() in keys:
                row["row_provenance_date"] = today
                n_written += 1
        if n_written == 0:
            results[os.path.basename(path)] = {"written": 0, "note": "none of the given keys matched a row in this ledger"}
            continue
        post_hash = _sha256_file(path)
        if post_hash != pre_hash:
            results[os.path.basename(path)] = {
                "written": 0, "error": "ABORTED: concurrent writer detected -- no write performed",
            }
            continue
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        _atomic_write_text(path, buf.getvalue())
        n_rows_after, n_mismatch_after = _validate_csv_field_counts(path)
        results[os.path.basename(path)] = {
            "written": n_written, "rows_after": n_rows_after, "mismatches_after": n_mismatch_after,
        }
    return results


def migrate_manifest_json_schema_v2(
    path: str, apply: bool = True, backup_dir: str = PRE_SCHEMA_V2_DIR
) -> MigrationResult:
    """Additive-only schema migration for the manifest JSON. Preserves the
    file's own top-level shape (list-of-entries OR dict-keyed-by-slug --
    see `manifest_json_entries`'s docstring for why both are handled): a
    dict-shaped input is written back as a dict, a list-shaped input as a
    list, never silently converted from one to the other, since other
    project tooling (the source-intake skill, prior tasks) may depend on
    the existing shape."""
    if not os.path.exists(path):
        return MigrationResult(path, False, f"file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        pre_text = fh.read()
    try:
        raw = json.loads(pre_text)
    except json.JSONDecodeError as exc:
        return MigrationResult(path, False, f"refused: JSON parse error: {exc}")
    if isinstance(raw, list):
        shape = "list"
        entries_by_ref = {i: e for i, e in enumerate(raw)}
    elif isinstance(raw, dict):
        shape = "dict"
        entries_by_ref = dict(raw)
    else:
        return MigrationResult(path, False, "refused: manifest JSON root is neither a list nor a dict")

    n_before = len(entries_by_ref)
    already = [e for e in entries_by_ref.values() if "identity_hash" in e or "extraction_hash" in e]
    if already:
        return MigrationResult(
            path, False,
            f"already migrated: {len(already)} entries already carry identity_hash/extraction_hash",
            rows_before=n_before,
        )

    if not apply:
        return MigrationResult(
            path, False, "dry-run (apply=False); no changes made",
            rows_before=n_before, columns_added=MANIFEST_SCHEMA_V2_COLUMNS,
        )

    backup_path = _backup_pre_schema_v2(path, backup_dir=backup_dir)

    new_entries_by_ref = {}
    for ref, e in entries_by_ref.items():
        ne = dict(e)
        ne["identity_hash"] = compute_content_hash(e, MANIFEST_IDENTITY_HASH_FIELDS)
        ne["extraction_hash"] = compute_content_hash(e, MANIFEST_EXTRACTION_HASH_FIELDS)
        new_entries_by_ref[ref] = ne

    # optimistic-concurrency re-check
    with open(path, encoding="utf-8") as fh:
        post_text = fh.read()
    if post_text != pre_text:
        return MigrationResult(
            path, False,
            "ABORTED: file changed on disk between read and write "
            "(concurrent writer detected) -- no write performed",
            rows_before=n_before, backup_path=backup_path,
        )

    if shape == "list":
        payload: Any = [new_entries_by_ref[i] for i in range(len(new_entries_by_ref))]
    else:
        payload = new_entries_by_ref
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    with open(path, encoding="utf-8") as fh:
        check = json.load(fh)
    n_after = len(check)
    result = MigrationResult(
        path, True, "migrated", rows_before=n_before, rows_after=n_after,
        backup_path=backup_path, columns_added=MANIFEST_SCHEMA_V2_COLUMNS,
    )
    if n_after != n_before:
        raise RuntimeError(
            f"POST-MIGRATION VALIDATION FAILED for {path}: "
            f"entries_before={n_before} entries_after={n_after}. "
            f"Backup preserved at {backup_path}."
        )
    return result


def rehash_manifest_json_identity_extraction(
    path: str, apply: bool = True, backup_dir: str = PRE_SCHEMA_V2_DIR
) -> MigrationResult:
    """: recomputes
    `identity_hash`/`extraction_hash` on every entry of the manifest JSON
    using `MANIFEST_IDENTITY_HASH_FIELDS_JSON`/`MANIFEST_EXTRACTION_HASH_FIELDS_JSON`
    (the JSON-schema-native field lists; see the adjudication note above
    those constants) in place of the CSV-only field lists
    `migrate_manifest_json_schema_v2` originally used at initial migration.

    This is NOT a schema migration (the two columns already exist on every
    entry, written by `migrate_manifest_json_schema_v2`) -- it is a
    corrective re-write of those two columns' VALUES only. Every other
    field, on every entry, is required to be byte-identical before vs.
    after (checked directly, not merely trusted) -- the strongest
    available guarantee that this function touches nothing but the two
    hash columns it is scoped to fix. `Sources/source_manifest.csv` is
    untouched by this function and by this fix generally: the CSV schema carries every field
    its hash formulas name -- only the JSON schema's field-name mismatch
    needed a fix."""
    if not os.path.exists(path):
        return MigrationResult(path, False, f"file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        pre_text = fh.read()
    try:
        raw = json.loads(pre_text)
    except json.JSONDecodeError as exc:
        return MigrationResult(path, False, f"refused: JSON parse error: {exc}")

    if isinstance(raw, list):
        shape = "list"
        entries_by_ref: Dict[Any, dict] = {i: e for i, e in enumerate(raw)}
    elif isinstance(raw, dict):
        shape = "dict"
        entries_by_ref = dict(raw)
    else:
        return MigrationResult(path, False, "refused: manifest JSON root is neither a list nor a dict")

    n_before = len(entries_by_ref)
    missing_cols = [
        ref for ref, e in entries_by_ref.items()
        if "identity_hash" not in e or "extraction_hash" not in e
    ]
    if missing_cols:
        return MigrationResult(
            path, False,
            f"refused: {len(missing_cols)} entries lack identity_hash/extraction_hash -- "
            "run migrate-schema first",
            rows_before=n_before,
        )

    new_entries_by_ref: Dict[Any, dict] = {}
    n_identity_changed = 0
    n_extraction_changed = 0
    for ref, e in entries_by_ref.items():
        ne = dict(e)
        new_identity = compute_content_hash(e, MANIFEST_IDENTITY_HASH_FIELDS_JSON)
        new_extraction = compute_content_hash(e, MANIFEST_EXTRACTION_HASH_FIELDS_JSON)
        if new_identity != e.get("identity_hash"):
            n_identity_changed += 1
        if new_extraction != e.get("extraction_hash"):
            n_extraction_changed += 1
        ne["identity_hash"] = new_identity
        ne["extraction_hash"] = new_extraction
        new_entries_by_ref[ref] = ne

    if not apply:
        return MigrationResult(
            path, False,
            f"dry-run (apply=False); would change identity_hash on {n_identity_changed} "
            f"entries, extraction_hash on {n_extraction_changed} entries",
            rows_before=n_before,
        )

    backup_path = _backup_pre_schema_v2(path, backup_dir=backup_dir)

    # Optimistic-concurrency re-check.
    with open(path, encoding="utf-8") as fh:
        post_check_text = fh.read()
    if post_check_text != pre_text:
        return MigrationResult(
            path, False,
            "ABORTED: file changed on disk between read and write "
            "(concurrent writer detected) -- no write performed",
            rows_before=n_before, backup_path=backup_path,
        )

    if shape == "list":
        payload: Any = [new_entries_by_ref[i] for i in range(len(new_entries_by_ref))]
    else:
        payload = new_entries_by_ref
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    with open(path, encoding="utf-8") as fh:
        check_raw = json.load(fh)
    check_entries = check_raw if isinstance(check_raw, list) else list(check_raw.values())
    n_after = len(check_entries)

    # Strongest available guarantee: every field OTHER than identity_hash/
    # extraction_hash is byte-identical, on every entry, before vs. after.
    before_list = list(entries_by_ref.values())
    n_field_drift = 0
    drift_examples: List[str] = []
    for before, after in zip(before_list, check_entries):
        for k in before:
            if k in ("identity_hash", "extraction_hash"):
                continue
            if before.get(k) != after.get(k):
                n_field_drift += 1
                if len(drift_examples) < 5:
                    drift_examples.append(f"{before.get('slug', '?')}.{k}")

    result = MigrationResult(
        path, True,
        f"rehashed: identity_hash changed on {n_identity_changed}/{n_before} entries, "
        f"extraction_hash changed on {n_extraction_changed}/{n_before} entries "
        f"(no other field touched: {n_field_drift} unexpected field-value differences)",
        rows_before=n_before, rows_after=n_after, backup_path=backup_path,
    )
    if n_after != n_before or n_field_drift != 0:
        raise RuntimeError(
            f"POST-REHASH VALIDATION FAILED for {path}: entries_before={n_before} "
            f"entries_after={n_after} unexpected_field_drift={n_field_drift} "
            f"(examples: {drift_examples}). Backup preserved at {backup_path}."
        )
    return result


def migrate_schema_v2(apply: bool = True) -> Dict[str, dict]:
    """Runs all four live-ledger schema-v2 migrations (section 3.1's table).
    Each file is independently backed up, validated, and optimistic-
    concurrency-checked; a failure/abort on one file does not prevent the
    others from being attempted, and every result (applied or not) is
    reported, never silently dropped."""
    results = {}
    results["quote_ledger"] = migrate_csv_schema_v2(
        QUOTE_LEDGER_PATH, QUOTE_SCHEMA_V2_COLUMNS, QUOTE_CONTENT_HASH_FIELDS, apply=apply
    ).to_dict()
    results["claim_ledger"] = migrate_csv_schema_v2(
        CLAIM_LEDGER_PATH, CLAIM_SCHEMA_V2_COLUMNS, CLAIM_CONTENT_HASH_FIELDS, apply=apply
    ).to_dict()
    results["manifest_csv"] = migrate_csv_schema_v2(
        MANIFEST_CSV_PATH, MANIFEST_SCHEMA_V2_COLUMNS, None, apply=apply
    ).to_dict()
    results["manifest_json"] = migrate_manifest_json_schema_v2(MANIFEST_JSON_PATH, apply=apply).to_dict()
    return results


def repair_citable_status_dict_repr(
    path: str,
    key_field: str,
    content_hash_fields: List[str],
    apply: bool = True,
    backup_dir: str = PRE_SCHEMA_V2_DIR,
) -> MigrationResult:
    """: repairs
    live-ledger rows whose `citable_status` cell holds a raw Python
    dict-repr string (e.g. "{'assigned': 'peer_reviewed', 'basis': ...}")
    instead of a clean tier label -- a defect an earlier intake task
    introduced by writing its full classification-decision dict to the
    ledger cell instead of extracting the label. Never invents a value:
    the correct label is parsed OUT of the malformed cell's own
    `'assigned'` key via `ast.literal_eval` (a safe literal parser, never
    `eval`) -- a malformed cell that does not parse as a dict with a
    non-empty string `assigned` key is left untouched and reported as
    `unparseable`, never guessed at.

    Because `citable_status` is a VERIFICATION-BEARING field (feeds
    `compute_content_hash`, section 3.1's own field table), every row this
    function actually repairs also gets its `content_hash` column
    refreshed in the SAME write to match the corrected value -- otherwise
    the very next `check` firing would see a genuine field-value change
    with no upstream row_edit event explaining it (this repair never runs
    through `detect_row_events`'s prev-vs-cur diff) and misreport it as a
    section 3.5 ERROR (section 3.3 rule 1, `detect_hash_mismatch_errors`) rather
    than the disclosed mechanical repair it actually is. Reuses the exact
    backup/OCC-check/atomic-write/field-count-revalidation primitives
    `migrate_csv_schema_v2` already established -- no new I/O primitive."""
    if not os.path.exists(path):
        return MigrationResult(path, False, f"file not found: {path}")

    rows_before_n, mism_before = _validate_csv_field_counts(path)
    if mism_before != 0:
        return MigrationResult(
            path, False,
            f"refused: {mism_before} pre-existing field-count mismatch(es) in {path}; "
            "fix the source defect before repairing",
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    header, rows = _read_csv_rows_and_header(path)
    if "citable_status" not in header:
        return MigrationResult(
            path, False, "citable_status column absent from header",
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    pre_hash = _sha256_file(path)

    repaired_keys: List[str] = []
    unparseable_keys: List[str] = []
    for row in rows:
        raw = row.get("citable_status") or ""
        if not raw.strip().startswith("{"):
            continue
        k = (row.get(key_field) or "").strip()
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            unparseable_keys.append(k)
            continue
        label = parsed.get("assigned") if isinstance(parsed, dict) else None
        if not isinstance(label, str) or not label.strip():
            unparseable_keys.append(k)
            continue
        row["citable_status"] = label
        if content_hash_fields is not None and "content_hash" in row:
            row["content_hash"] = compute_content_hash(row, content_hash_fields)
        repaired_keys.append(k)

    if not repaired_keys:
        reason = "no dict-repr citable_status cells found"
        if unparseable_keys:
            reason = f"no repairable dict-repr cells; unparseable (left untouched): {unparseable_keys}"
        return MigrationResult(
            path, False, reason, rows_before=rows_before_n, mismatches_before=mism_before,
        )

    if not apply:
        return MigrationResult(
            path, False,
            f"dry-run (apply=False); would repair {len(repaired_keys)} rows: {repaired_keys}"
            + (f"; unparseable (would be left untouched): {unparseable_keys}" if unparseable_keys else ""),
            rows_before=rows_before_n, mismatches_before=mism_before,
        )

    backup_path = _backup_pre_schema_v2(path, backup_dir=backup_dir)

    # Optimistic-concurrency re-check, as close to the write as practical
    # (identical placement/semantics to migrate_csv_schema_v2's own check).
    post_check_hash = _sha256_file(path)
    if post_check_hash != pre_hash:
        return MigrationResult(
            path, False,
            "ABORTED: file changed on disk between read and write "
            "(concurrent writer detected via sha256 mismatch) -- no write performed",
            rows_before=rows_before_n, mismatches_before=mism_before, backup_path=backup_path,
        )

    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    _atomic_write_text(path, buf.getvalue())

    rows_after_n, mism_after = _validate_csv_field_counts(path)
    result = MigrationResult(
        path, True,
        f"repaired {len(repaired_keys)} rows: {repaired_keys}"
        + (f"; unparseable (left untouched): {unparseable_keys}" if unparseable_keys else ""),
        rows_before=rows_before_n, rows_after=rows_after_n,
        mismatches_before=mism_before, mismatches_after=mism_after,
        backup_path=backup_path,
    )
    if rows_after_n != rows_before_n or mism_after != 0:
        raise RuntimeError(
            f"POST-REPAIR VALIDATION FAILED for {path}: rows_before={rows_before_n} "
            f"rows_after={rows_after_n} mismatches_after={mism_after}. "
            f"Backup preserved at {backup_path}. Restore and investigate before re-running."
        )
    return result


def repair_citable_status_v2(apply: bool = True) -> Dict[str, dict]:
    """Runs `repair_citable_status_dict_repr` against both live ledgers.
    Mirrors `migrate_schema_v2`'s own aggregate-wrapper shape."""
    results = {}
    results["quote_ledger"] = repair_citable_status_dict_repr(
        QUOTE_LEDGER_PATH, "quote_id", QUOTE_CONTENT_HASH_FIELDS, apply=apply
    ).to_dict()
    results["claim_ledger"] = repair_citable_status_dict_repr(
        CLAIM_LEDGER_PATH, "claim_id", CLAIM_CONTENT_HASH_FIELDS, apply=apply
    ).to_dict()
    return results


# ---------------------------------------------------------------------------
# Section 4 -- Live change-detection rules (section 3.3) and STALE propagation
# (section 3.4). Operates on two dict-by-key row snapshots (previous vs current).
# ---------------------------------------------------------------------------


def _keyed(rows: List[dict], key_field: str) -> Dict[str, dict]:
    out = {}
    for row in rows:
        k = (row.get(key_field) or "").strip()
        if k:
            out[k] = row
    return out


@dataclass
class DetectedEvent:
    change_kind: str  # one of section 3.3's five kinds
    node_type: str
    node_id: str
    changed_fields: List[str] = field(default_factory=list)
    detail: str = ""
    # populated by detect_row_events (never left to the
    # writer to default) so log_firing has real content-hash values to log instead
    # of a hardcoded "". row_add legitimately has no prior content (content_hash_before
    # stays ""); row_remove legitimately has no surviving content (content_hash_after
    # stays ""); row_edit populates both from the same content-hash formula
    # compute_content_hash already uses everywhere else in this module.
    content_hash_before: str = ""
    content_hash_after: str = ""


def detect_row_events(
    previous_rows: List[dict],
    current_rows: List[dict],
    key_field: str,
    node_type: str,
    verification_bearing_fields: Set[str],
    content_hash_fields: Optional[List[str]] = None,
) -> Tuple[List[DetectedEvent], List[DetectedEvent]]:
    """section 3.3 rules 2 and 3 (row edit / row add-remove), restricted to a
    single ledger. Returns (triggering_events, unexplained_re_verification)
    -- the second list is section 4.7 clause 3's own bucket: rows whose ONLY
    changed fields are status-only, reported but never treated as a
    STALE-trigger.

    every returned `triggers` event now carries a
    real `content_hash_before`/`content_hash_after` (computed via
    `compute_content_hash`, the same formula used everywhere else in this
    module), rather than leaving those fields for `log_firing` to default
    to "". `content_hash_fields` lets a caller override the field list
    explicitly; if omitted, it is looked up from `node_type` via
    `NODE_TYPE_CONTENT_HASH_FIELDS`. An unrecognized `node_type` with no
    override is refused outright (ERROR, not a silent empty hash) --
    `tools/prov/export.py`'s `entity_urn()` maps an empty hash to the
    literal suffix ":nohash" for both sides of a `wasRevisionOf` edge, so
    two empty hashes collapse onto one self-referencing URN. That
    collapse is exactly the earlier `derivation_acyclicity` /
    `no_wasRevisionOf_cycle` regression this fix closes; refusing here
    means it can never recur silently."""
    hash_fields = (
        content_hash_fields if content_hash_fields is not None
        else NODE_TYPE_CONTENT_HASH_FIELDS.get(node_type)
    )
    if hash_fields is None:
        raise RuntimeError(
            f"detect_row_events: no content-hash field list for node_type={node_type!r} "
            "-- pass content_hash_fields explicitly or register it in "
            "NODE_TYPE_CONTENT_HASH_FIELDS. Refusing to emit an event with an "
            "empty/unrecoverable content_hash rather than silently reproducing "
            "the earlier self-loop regression (see this function's own docstring)."
        )

    prev = _keyed(previous_rows, key_field)
    cur = _keyed(current_rows, key_field)
    prev_keys, cur_keys = set(prev), set(cur)

    triggers: List[DetectedEvent] = []
    unexplained: List[DetectedEvent] = []

    for k in sorted(cur_keys - prev_keys):
        # row_add: legitimately no prior content -- content_hash_before stays "".
        triggers.append(DetectedEvent(
            "row_add", node_type, k, detail="new row",
            content_hash_after=compute_content_hash(cur[k], hash_fields),
        ))
    for k in sorted(prev_keys - cur_keys):
        # row_remove: legitimately no surviving content -- content_hash_after stays "".
        triggers.append(DetectedEvent(
            "row_remove", node_type, k, detail="row removed",
            content_hash_before=compute_content_hash(prev[k], hash_fields),
        ))

    for k in sorted(prev_keys & cur_keys):
        old, new = prev[k], cur[k]
        # csv.DictReader assigns key `None` (collecting a list under
        # `restkey`) when a raw data row has MORE fields than the header --
        # i.e. a genuine field-count-mismatch defect in that specific
        # ledger snapshot (a real, disclosable data-quality fact about that
        # historical commit, not a bug in this detector). Field names must
        # be strings to be comparable/sortable; a None-keyed overflow is
        # reported as its own malformed-row note rather than crashing or
        # being silently dropped.
        old_field_names = {f for f in old if isinstance(f, str)}
        new_field_names = {f for f in new if isinstance(f, str)}
        changed = sorted(
            f for f in old_field_names | new_field_names
            if str(old.get(f, "")) != str(new.get(f, ""))
        )
        overflow_note = None
        if None in old or None in new:
            overflow_note = (
                f"field-count-mismatch overflow detected on key {k!r} "
                f"(old extra={old.get(None)!r}, new extra={new.get(None)!r})"
            )
        if not changed and overflow_note is None:
            continue
        bearing_changed = [f for f in changed if f in verification_bearing_fields]
        if bearing_changed or overflow_note:
            triggers.append(DetectedEvent(
                "row_edit", node_type, k, changed_fields=bearing_changed,
                detail=overflow_note or "",
                content_hash_before=compute_content_hash(old, hash_fields),
                content_hash_after=compute_content_hash(new, hash_fields),
            ))
        else:
            unexplained.append(DetectedEvent("row_edit_status_only", node_type, k, changed_fields=changed))

    return triggers, unexplained


def detect_manifest_supersession(
    previous_entries: List[dict], current_entries: List[dict]
) -> List[DetectedEvent]:
    """section 3.3 rule 4: a manifest entry's duplicate_of transitions empty -> populated."""
    prev = _keyed(previous_entries, "slug")
    cur = _keyed(current_entries, "slug")
    out = []
    for slug in sorted(set(prev) & set(cur)):
        old_dup = (prev[slug].get("duplicate_of") or "").strip()
        new_dup = (cur[slug].get("duplicate_of") or "").strip()
        if old_dup == "" and new_dup != "":
            out.append(
                DetectedEvent(
                    "manifest_supersession", "Source", slug,
                    detail=f"manifest supersession: {slug} -> {new_dup}",
                )
            )
    return out


def detect_hash_mismatch_errors(
    cur_rows: List[dict],
    key_field: str,
    node_type: str,
    hash_fields: List[str],
    explained_keys: Set[str],
) -> List[DetectedEvent]:
    """Rule 1, the ERROR-state detection. This is a SINGLE-SNAPSHOT self-
    consistency check, deliberately distinct from `detect_row_events`'s
    prev-vs-cur diff: for every current row carrying a non-empty schema-v2
    `content_hash`, recompute the hash from THAT SAME row's own current
    field values and compare to the stored value.

    A mismatch is EXPECTED and benign for any key already present in
    `explained_keys` (i.e. `detect_row_events` already found a
    verification-bearing field change for it this firing, so of course the
    freshly-recomputed hash differs from the value the ledger's
    `content_hash` column currently holds until a writer refreshes it) --
    that case is left entirely to the ordinary STALE path (section 3.4) and
    produces NO event here, by design: this function must never re-flag
    an already-explained edit as an anomaly.

    A mismatch on a key NOT in `explained_keys` means the row's own
    current field values, hashed right now, do not match its own
    `content_hash` column's recorded value, with no detected row-level
    change accounting for the difference. Per section 3.5's own wording, that
    is precisely the ERROR case: 'the engine's own bookkeeping, not the
    underlying data, is suspect' -- e.g. the `content_hash` cell was
    corrupted, hand-edited out of band, or (see `apply_stale_to_ledgers`'s
    own docstring) never refreshed by a prior writer that changed a
    verification-bearing field without recomputing the trace. Never
    silently folded into STALE or FRESH; always reported as its own
    `content_hash_mismatch_error` event, per section 3.5's 'an explicit error
    report is required, never a silent pass-through.'"""
    errors: List[DetectedEvent] = []
    for row in cur_rows:
        k = (row.get(key_field) or "").strip()
        if not k or k in explained_keys:
            continue
        stored_hash = (row.get("content_hash") or "").strip()
        if not stored_hash:
            continue  # row not yet on schema-v2 / no trace recorded to check
        recomputed = compute_content_hash(row, hash_fields)
        if recomputed != stored_hash:
            errors.append(DetectedEvent(
                "content_hash_mismatch_error", node_type, k,
                detail=(
                    f"stored content_hash={stored_hash[:12]}... does not match "
                    f"recomputed={recomputed[:12]}... from this row's own current "
                    "field values, with no row_edit trigger this firing explaining "
                    "the difference -- engine bookkeeping, not the underlying "
                    "predicate data, is suspect (section 3.5 ERROR state, section 3.3 rule 1)"
                ),
            ))
    return errors


def propagate_stale(graph: Graph, triggers: List[DetectedEvent]) -> Dict[str, str]:
    """section 3.4's propagation rule: every node reachable by a forward edge
    from a directly-changed node is also STALE, transitively. Returns
    {node_id: stale_reason}. A row_add cannot itself have downstream
    dependents at the moment it's added (nothing points to it yet), so it
    contributes no propagation, matching fixture 8a's own regression-test
    semantics (`corpus_added` -> empty affected set)."""
    stale: Dict[str, str] = {}
    for ev in triggers:
        if ev.change_kind == "row_add":
            continue  # section 3.3 rule 3 / fixture 8a: no propagation on add
        if not graph.has_node(ev.node_id):
            continue
        origin_reason = (
            f"{ev.change_kind} on {ev.node_type} {ev.node_id}"
            + (f" (fields: {', '.join(ev.changed_fields)})" if ev.changed_fields else "")
        )
        stale.setdefault(ev.node_id, origin_reason)
        for downstream in graph.downstream_closure({ev.node_id}):
            stale.setdefault(downstream, f"upstream change: {origin_reason}")
    return stale


def merge_graphs(g1: Graph, g2: Graph) -> Graph:
    """Unions two graphs' nodes and edges into a new Graph.

    Why this exists (found and fixed in review):
    `propagate_stale`'s forward walk can only discover a node's dependents
    by using a graph that actually contains that node and its outgoing
    edges. For a `row_remove` event (section 3.3 rule 3), the removed node and
    its edges exist ONLY in the PRIOR-state graph -- a graph built from the
    current/live ledgers alone never contains a just-removed row, so a
    downstream dependent that is still present in the current ledgers (an
    "orphaned" claim still citing a deleted quote_id) would never be
    reached and would be silently left FRESH -- exactly the failure mode
    section 3.3 rule 3 forbids ("dependents ... never silently dropped").
    Using the union of the prior-state and current-state graphs fixes this
    for `row_remove` while changing nothing for `row_edit`/
    `manifest_supersession` (those nodes exist, with identical forward-
    reachability, in both graphs in every case this engine's own field
    classification cares about -- 's analysis)."""
    merged = Graph()
    for g in (g1, g2):
        for node in g.nodes.values():
            merged.add_node(Node(node.id, node.type, payload=node.payload))
        for edge in g.edges:
            merged.add_edge(Edge(edge.src, edge.dst, edge.type))
    return merged


@dataclass
class CheckResult:
    quote_triggers: List[DetectedEvent]
    claim_triggers: List[DetectedEvent]
    manifest_events: List[DetectedEvent]
    quote_unexplained: List[DetectedEvent]
    claim_unexplained: List[DetectedEvent]
    stale_map: Dict[str, str]
    prev_build_report: BuildReport
    cur_build_report: BuildReport
    # section 3.3 rule 1 / section 3.5 ERROR state. Kept
    # STRICTLY SEPARATE from `stale_map` by design: these are never
    # propagated, never folded into engine_status=STALE, and never change
    # what `replay_realevents.py`'s TP/FN/FP computation (which reads only
    # `stale_map`) sees -- adding this field cannot regress the existing
    # 14-pair real-event replay or the 12/12 fixture-parity suite.
    hash_mismatch_errors: List[DetectedEvent] = field(default_factory=list)


def compute_check_result(
    prev_quotes: List[dict], cur_quotes: List[dict],
    prev_claims: List[dict], cur_claims: List[dict],
    prev_manifest: List[dict], cur_manifest: List[dict],
) -> CheckResult:
    """Core, path-free computation shared by `cmd_check` (the production
    `check` CLI command) and `replay_realevents.py`'s `replay_pair` (the
    section 4 retroactive-replay/self-test harness) -- section 3.3's five
    change-detection rules plus section 3.4's STALE propagation, run against
    the UNION of the prior-state and current-state graphs (`merge_graphs`,
    above). Sharing this one function between the production path and the
    validation harness is deliberate: in an earlier version, `cmd_check`
    built its propagation graph from the live ledgers only while the
    replay harness built it from the prior-state ledgers only, so the
    replay's PASS results validated logic that the deployed `check`
    command did not actually run. A single shared function makes that
    divergence structurally impossible going forward."""
    quote_triggers, quote_unexplained = detect_row_events(
        prev_quotes, cur_quotes, "quote_id", "quotation", QUOTE_VERIFICATION_BEARING
    )
    claim_triggers, claim_unexplained = detect_row_events(
        prev_claims, cur_claims, "claim_id", "claim", CLAIM_VERIFICATION_BEARING
    )
    manifest_events = detect_manifest_supersession(prev_manifest, cur_manifest)

    prev_graph, prev_report = _build_graph_from_rows(prev_manifest, prev_quotes, prev_claims)
    cur_graph, cur_report = _build_graph_from_rows(cur_manifest, cur_quotes, cur_claims)
    union_graph = merge_graphs(prev_graph, cur_graph)

    all_triggers = quote_triggers + claim_triggers + manifest_events
    stale_map = propagate_stale(union_graph, all_triggers)

    # section 3.3 rule 1: a key already explained by a
    # row_edit/row_add/row_remove trigger THIS firing is never re-flagged
    # as an ERROR -- only a mismatch with NO explaining trigger is.
    quote_explained = {ev.node_id for ev in quote_triggers}
    claim_explained = {ev.node_id for ev in claim_triggers}
    hash_mismatch_errors = (
        detect_hash_mismatch_errors(
            cur_quotes, "quote_id", "quotation", QUOTE_CONTENT_HASH_FIELDS, quote_explained,
        )
        + detect_hash_mismatch_errors(
            cur_claims, "claim_id", "claim", CLAIM_CONTENT_HASH_FIELDS, claim_explained,
        )
    )

    return CheckResult(
        quote_triggers=quote_triggers, claim_triggers=claim_triggers,
        manifest_events=manifest_events, quote_unexplained=quote_unexplained,
        claim_unexplained=claim_unexplained, stale_map=stale_map,
        prev_build_report=prev_report, cur_build_report=cur_report,
        hash_mismatch_errors=hash_mismatch_errors,
    )


# ---------------------------------------------------------------------------
# Section 5 -- logs/invalidation_events.csv writer (section 5's schema)
# ---------------------------------------------------------------------------

EVENTS_LOG_HEADER = [
    "event_id", "firing_timestamp", "records_merge_source", "change_kind",
    "node_type", "node_id", "origin_node_id", "prior_engine_status",
    "new_engine_status", "stale_reason", "content_hash_before",
    "content_hash_after", "resolved_by", "backstop_resweep_flag",
]


def append_invalidation_events(rows: List[dict], events_log_path: str = EVENTS_LOG_PATH) -> int:
    """Append-only writer -- never truncates or rewrites logs/invalidation_events.csv
    in place, mirroring logs/agent_task_ledger.csv's own convention (section 5).
    Creates the file with a header if it does not yet exist. An empty
    `rows` list still writes exactly one zero-row summary entry (section 5's
    'an empty firing... is still logged, not silently skipped' rule) when
    called via `log_firing` below; this low-level function itself just
    appends whatever rows it is given."""
    exists = os.path.exists(events_log_path)
    os.makedirs(os.path.dirname(events_log_path), exist_ok=True)
    with open(events_log_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVENTS_LOG_HEADER)
        if not exists:
            writer.writeheader()
        for row in rows:
            full = {k: row.get(k, "") for k in EVENTS_LOG_HEADER}
            writer.writerow(full)
    return len(rows)


def log_firing(
    records_merge_source: str,
    detected: List[DetectedEvent],
    stale_map: Dict[str, str],
    events_log_path: str = EVENTS_LOG_PATH,
    flagged_status: str = EngineStatus.STALE.value,
) -> int:
    """Builds and appends one logs/invalidation_events.csv row per detected
    event (plus a zero-row summary if nothing fired), per section 5.
    `flagged_status` (new in; defaults to STALE,
    unchanged behavior for every pre-existing call site) is the status
    recorded for a node present in `stale_map` -- callers logging an
    ERROR-state firing pass `flagged_status=EngineStatus.ERROR.value` and
    an `error_map` in place of `stale_map`."""
    ts = _now_iso()
    rows = []
    if not detected:
        rows.append({
            "event_id": f"{ts}-0",
            "firing_timestamp": ts,
            "records_merge_source": records_merge_source,
            "change_kind": "none",
            "node_type": "",
            "node_id": "",
            "origin_node_id": "",
            "prior_engine_status": "",
            "new_engine_status": "",
            "stale_reason": "",
            "content_hash_before": "",
            "content_hash_after": "",
            "resolved_by": "",
            "backstop_resweep_flag": "false",
        })
    else:
        for i, ev in enumerate(detected):
            new_status = (
                flagged_status if ev.node_id in stale_map else EngineStatus.FRESH.value
            )
            rows.append({
                "event_id": f"{ts}-{i}",
                "firing_timestamp": ts,
                "records_merge_source": records_merge_source,
                "change_kind": ev.change_kind,
                "node_type": ev.node_type,
                "node_id": ev.node_id,
                "origin_node_id": "",
                "prior_engine_status": "",
                "new_engine_status": new_status,
                "stale_reason": stale_map.get(ev.node_id, ""),
                "content_hash_before": ev.content_hash_before,
                "content_hash_after": ev.content_hash_after,
                "resolved_by": "",
                "backstop_resweep_flag": "false",
            })
    return append_invalidation_events(rows, events_log_path)


# ---------------------------------------------------------------------------
# git helper (read-only)
# ---------------------------------------------------------------------------


def git_show(ref: str, path: str) -> Optional[str]:
    """Read-only `git show <ref>:<path>` -- returns None if the path does
    not exist at that ref (e.g. pre-genesis)."""
    rel = os.path.relpath(path, PROJECT_ROOT)
    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _csv_rows_from_text(text: str) -> List[dict]:
    import io
    return list(csv.DictReader(io.StringIO(text)))


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_build_graph(args: argparse.Namespace) -> int:
    if args.frozen:
        g, report = load_frozen_graph(args.frozen[0], args.frozen[1], args.frozen[2])
    else:
        g, report = load_live_graph()
    out = {
        "mode": "frozen" if args.frozen else "live",
        "n_nodes": len(g.nodes),
        "n_edges": len(g.edges),
        "build_report": report.to_dict(),
    }
    text = json.dumps(out, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Compares the live ledgers against either a git ref (--since) or a
    snapshot directory (--against), detects section 3.3 events, propagates
    STALE (section 3.4), and (if --apply) writes engine_status/stale_reason/
    stale_since into the live ledgers (never touching verification_status/
    claim_verification_status) and appends to logs/invalidation_events.csv."""
    if bool(args.since) == bool(args.against):
        print("error: exactly one of --since or --against is required", file=sys.stderr)
        return 2

    if args.since:
        q_text = git_show(args.since, QUOTE_LEDGER_PATH)
        c_text = git_show(args.since, CLAIM_LEDGER_PATH)
        m_text = git_show(args.since, MANIFEST_JSON_PATH)
        if q_text is None or c_text is None or m_text is None:
            print(f"error: one or more target files not found at ref {args.since!r}", file=sys.stderr)
            return 2
        prev_quotes = _csv_rows_from_text(q_text)
        prev_claims = _csv_rows_from_text(c_text)
        prev_manifest = _normalize_manifest_raw(json.loads(m_text))
        source_label = args.since
    else:
        snap = args.against
        with open(os.path.join(snap, "quote_ledger.csv"), newline="", encoding="utf-8") as fh:
            prev_quotes = list(csv.DictReader(fh))
        with open(os.path.join(snap, "claim_ledger.csv"), newline="", encoding="utf-8") as fh:
            prev_claims = list(csv.DictReader(fh))
        with open(os.path.join(snap, "source_manifest.json"), encoding="utf-8") as fh:
            prev_manifest = _normalize_manifest_raw(json.load(fh))
        source_label = f"snapshot:{snap}"

    with open(QUOTE_LEDGER_PATH, newline="", encoding="utf-8") as fh:
        cur_quotes = list(csv.DictReader(fh))
    with open(CLAIM_LEDGER_PATH, newline="", encoding="utf-8") as fh:
        cur_claims = list(csv.DictReader(fh))
    cur_manifest = manifest_json_entries(MANIFEST_JSON_PATH)

    result = compute_check_result(
        prev_quotes, cur_quotes, prev_claims, cur_claims, prev_manifest, cur_manifest,
    )
    all_triggers = result.quote_triggers + result.claim_triggers + result.manifest_events
    stale_map = result.stale_map

    # section 3.3 rule 3 / section 3.5 ERROR discipline: a claim whose quote_id no
    # longer resolves to any live Quotation node (e.g. the quote row it
    # cited was removed) is a structural fact the graph build already
    # detects (BuildReport.claims_with_unresolved_quote_ref) -- surfaced
    # here rather than silently discarded, as the pre-fix version of this
    # function did by throwing the build report away.
    orphaned_quote_refs = result.cur_build_report.claims_with_unresolved_quote_ref
    # section 3.5 ERROR state / fixture 4-10's own named case: a malformed
    # multi-value quote_id (leading/trailing/doubled semicolon, empty
    # segment) is detected at graph-build time (BuildReport.malformed_claim_rows)
    # but was previously discarded here along with the rest of the build
    # report -- surfaced now for the same "never silently dropped" reason.
    malformed_claim_rows = result.cur_build_report.malformed_claim_rows

    # section 3.3 rule 1 / section 3.5: ERROR-state nodes
    # are reported and, on --apply, written -- but strictly disjoint from
    # stale_map (a node in both would be a logic bug in the two detectors'
    # own explained-key bookkeeping, so it is asserted, not silently
    # tolerated).
    error_map = {ev.node_id: ev.detail for ev in result.hash_mismatch_errors}
    overlap = set(error_map) & set(stale_map)
    if overlap:
        raise RuntimeError(
            f"invariant violated: {sorted(overlap)} flagged as BOTH STALE and "
            "ERROR in the same firing -- detect_hash_mismatch_errors' "
            "explained_keys exclusion should make this impossible"
        )

    report = {
        "records_merge_source": source_label,
        "firing_timestamp": _now_iso(),
        "engine_version": ENGINE_VERSION,
        "n_quote_triggers": len(result.quote_triggers),
        "n_claim_triggers": len(result.claim_triggers),
        "n_manifest_supersession": len(result.manifest_events),
        "n_unexplained_re_verification": len(result.quote_unexplained) + len(result.claim_unexplained),
        "n_transitioned_to_stale": len(stale_map),
        "stale_nodes": stale_map,
        "n_hash_mismatch_errors": len(error_map),
        "hash_mismatch_errors": [
            {"node_type": e.node_type, "node_id": e.node_id, "detail": e.detail}
            for e in result.hash_mismatch_errors
        ],
        "unexplained_re_verification": [
            {"node_type": e.node_type, "node_id": e.node_id, "changed_fields": e.changed_fields}
            for e in result.quote_unexplained + result.claim_unexplained
        ],
        "orphaned_claims_unresolved_quote_ref": orphaned_quote_refs,
        "malformed_claim_rows": malformed_claim_rows,
    }
    print(json.dumps(report, indent=2))

    if args.apply:
        n_logged = log_firing(source_label, all_triggers, stale_map)
        write_result = apply_stale_to_ledgers(stale_map)
        report["events_appended_this_firing"] = n_logged
        report["ledger_write_result"] = write_result
        if error_map:
            n_error_logged = log_firing(
                f"{source_label}:hash-mismatch-error",
                result.hash_mismatch_errors, error_map,
                flagged_status=EngineStatus.ERROR.value,
            )
            error_write_result = apply_error_to_ledgers(error_map)
            report["error_events_appended_this_firing"] = n_error_logged
            report["error_ledger_write_result"] = error_write_result
        print(json.dumps({"applied": True, "events_appended_this_firing": n_logged, "ledger_write_result": write_result}, indent=2))
    return 0


def _apply_engine_status_to_ledgers(status_map: Dict[str, Tuple[str, str]]) -> Dict[str, Any]:
    """Shared write path for `apply_stale_to_ledgers` and
    `apply_error_to_ledgers`: writes
    engine_status=<status> + stale_reason + stale_since for the given
    node ids into the live ledgers, via schema-v2 columns only -- never
    touches verification_status/claim_verification_status/citable_status
    or any other existing column. `status_map` is {node_id: (engine_status,
    reason)}. Requires the schema-v2 columns to already exist (run
    `migrate-schema` first); if they don't, reports that plainly rather
    than silently adding them mid-write. `stale_since`/`stale_reason` are
    reused verbatim as the write target for BOTH the STALE and ERROR
    states -- section 3.5's own table defines `stale_reason` as populated 'on
    a transition into STALE or ERROR', so no new column is needed."""
    results: Dict[str, Any] = {}
    for path, key_field in ((QUOTE_LEDGER_PATH, "quote_id"), (CLAIM_LEDGER_PATH, "claim_id")):
        header, rows = _read_csv_rows_and_header(path)
        if "engine_status" not in header:
            results[os.path.basename(path)] = {
                "written": 0,
                "error": "engine_status column absent -- run `migrate-schema --apply` first",
            }
            continue
        pre_hash = _sha256_file(path)
        n_written = 0
        ts = _now_iso()
        for row in rows:
            k = (row.get(key_field) or "").strip()
            if k in status_map:
                status, reason = status_map[k]
                row["engine_status"] = status
                row["stale_since"] = ts
                row["stale_reason"] = reason
                n_written += 1
        if n_written == 0:
            results[os.path.basename(path)] = {"written": 0, "note": "no rows in this ledger were flagged"}
            continue
        post_hash = _sha256_file(path)
        if post_hash != pre_hash:
            results[os.path.basename(path)] = {
                "written": 0,
                "error": "ABORTED: concurrent writer detected (sha256 changed between "
                         "read and write) -- no write performed",
            }
            continue
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        _atomic_write_text(path, buf.getvalue())
        n_rows_after, n_mismatch_after = _validate_csv_field_counts(path)
        results[os.path.basename(path)] = {
            "written": n_written, "rows_after": n_rows_after, "mismatches_after": n_mismatch_after,
        }
    return results


def apply_stale_to_ledgers(stale_map: Dict[str, str]) -> Dict[str, Any]:
    """Thin wrapper over `_apply_engine_status_to_ledgers`, unchanged
    signature/behavior from the earlier version -- writes
    engine_status=STALE for every {node_id: reason} pair given."""
    return _apply_engine_status_to_ledgers(
        {k: (EngineStatus.STALE.value, v) for k, v in stale_map.items()}
    )


def apply_error_to_ledgers(error_map: Dict[str, str]) -> Dict[str, Any]:
    """New (section 3.3 rule 1 / section 3.5 ERROR
    state): writes engine_status=ERROR for every {node_id: reason} pair
    given -- the write-side counterpart to `detect_hash_mismatch_errors`.
    Never called on a node also present in the same firing's stale_map;
    `cmd_check` enforces that disjointness before calling either writer
    (section 3.5's ERROR/STALE states are presented as mutually exclusive
    per-row outcomes of a single firing, never both written for one row
    in the same firing)."""
    return _apply_engine_status_to_ledgers(
        {k: (EngineStatus.ERROR.value, v) for k, v in error_map.items()}
    )


MARK_STALE_LEDGER_BY_NODE_TYPE: Dict[str, Tuple[str, str]] = {
    "quotation": (QUOTE_LEDGER_PATH, "quote_id"),
    "claim": (CLAIM_LEDGER_PATH, "claim_id"),
}


def cmd_mark_stale(args: argparse.Namespace) -> int:
    """Manual override path: mark one node STALE with an explicit reason
    (e.g. a governance/ratification event the automatic detectors can't
    see). Applies the same OCC-checked, atomic write as apply_stale_to_ledgers,
    scoped to a single node.

    this used to log a change_kind="row_edit"
    event with no content_hash_before/content_hash_after at all (both
    silently defaulted to "" by log_firing) -- the same empty-hash defect
    that caused the earlier self-loop regression in the automatic
    detector path. A STALE mark does not itself change any content-hash-bearing
    field, so content_hash_before and content_hash_after are the SAME
    real, freshly-computed hash of the node's current row -- correct
    (not a revision, just a status flag) and never empty. `--node-type`
    must resolve to a known ledger (`MARK_STALE_LEDGER_BY_NODE_TYPE`);
    an unrecognized or missing value is refused (ERROR, exit 2) rather
    than silently emitting an event with an unrecoverable hash."""
    node_type = args.node_type or ""
    ledger_info = MARK_STALE_LEDGER_BY_NODE_TYPE.get(node_type)
    if ledger_info is None:
        print(
            f"error: --node-type={node_type!r} is not a recognized node type "
            f"({sorted(MARK_STALE_LEDGER_BY_NODE_TYPE)}) -- refusing to log an "
            "event with no content-hash to compute it from.",
            file=sys.stderr,
        )
        return 2
    ledger_path, key_field = ledger_info
    hash_fields = NODE_TYPE_CONTENT_HASH_FIELDS[node_type]
    with open(ledger_path, newline="", encoding="utf-8") as fh:
        row = next(
            (r for r in csv.DictReader(fh) if (r.get(key_field) or "").strip() == args.node_id),
            None,
        )
    if row is None:
        print(
            f"error: node_id={args.node_id!r} not found in {os.path.basename(ledger_path)} "
            f"(key field {key_field!r}) -- refusing to log an event with no content-hash "
            "to compute it from.",
            file=sys.stderr,
        )
        return 2
    content_hash = compute_content_hash(row, hash_fields)

    stale_map = {args.node_id: args.reason}
    result = apply_stale_to_ledgers(stale_map)
    log_firing(
        f"manual:{args.node_id}",
        [DetectedEvent(
            "row_edit", node_type, args.node_id, detail=args.reason,
            content_hash_before=content_hash, content_hash_after=content_hash,
        )],
        stale_map,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Summarizes current engine_status distribution across the live
    ledgers plus a tail of logs/invalidation_events.csv."""
    out: Dict[str, Any] = {"generated": _now_iso()}
    for path, key in ((QUOTE_LEDGER_PATH, "quote_ledger"), (CLAIM_LEDGER_PATH, "claim_ledger")):
        if not os.path.exists(path):
            out[key] = {"error": "file not found"}
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if rows and "engine_status" not in rows[0]:
            out[key] = {"schema_v2": False, "n_rows": len(rows)}
            continue
        counts: Dict[str, int] = {}
        for row in rows:
            s = row.get("engine_status") or "UNTRACKED"
            counts[s] = counts.get(s, 0) + 1
        out[key] = {"schema_v2": True, "n_rows": len(rows), "engine_status_counts": counts}

    if os.path.exists(EVENTS_LOG_PATH):
        with open(EVENTS_LOG_PATH, newline="", encoding="utf-8") as fh:
            events = list(csv.DictReader(fh))
        out["invalidation_events"] = {"total_rows": len(events), "tail": events[-10:]}
    else:
        out["invalidation_events"] = {"total_rows": 0, "note": f"{EVENTS_LOG_PATH} does not exist yet"}

    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


def cmd_migrate_schema(args: argparse.Namespace) -> int:
    results = migrate_schema_v2(apply=args.apply)
    print(json.dumps(results, indent=2))
    any_error = any(
        (not r["applied"]) and ("error" in r.get("reason", "").lower() or "ABORTED" in r.get("reason", ""))
        for r in results.values()
    )
    return 1 if any_error else 0


def cmd_repair_citable_status(args: argparse.Namespace) -> int:
    """ CLI entry point."""
    results = repair_citable_status_v2(apply=args.apply)
    print(json.dumps(results, indent=2))
    any_error = any(
        (not r["applied"]) and ("ABORTED" in r.get("reason", "") or "refused" in r.get("reason", ""))
        for r in results.values()
    )
    return 1 if any_error else 0


def cmd_rehash_manifest_json(args: argparse.Namespace) -> int:
    """ CLI entry point."""
    result = rehash_manifest_json_identity_extraction(MANIFEST_JSON_PATH, apply=args.apply)
    print(json.dumps(result.to_dict(), indent=2))
    if not result.applied and ("ABORTED" in result.reason or "refused" in result.reason):
        return 1
    return 0


def cmd_migrate_schema_v3(args: argparse.Namespace) -> int:
    """ CLI entry point (section 2)."""
    results = migrate_schema_v3(apply=args.apply)
    print(json.dumps(results, indent=2))
    any_error = any(
        (not r["applied"]) and ("error" in r.get("reason", "").lower() or "ABORTED" in r.get("reason", ""))
        for r in results.values()
    )
    return 1 if any_error else 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="invalidation.py",
        description="Production dependency-invalidation engine (section 3).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build-graph", help="Build the graph (live by default) and report its shape.")
    p_build.add_argument("--frozen", nargs=3, metavar=("QUOTE_CSV", "CLAIM_CSV", "MANIFEST_CSV"),
                          help="Build from a frozen snapshot instead of the live ledgers.")
    p_build.add_argument("--out", help="Write the JSON report to this path too.")
    p_build.set_defaults(func=cmd_build_graph)

    p_check = sub.add_parser("check", help="Detect changes since a git ref or snapshot and compute STALE propagation.")
    p_check.add_argument("--since", help="A git ref (commit hash/tag) to diff the live ledgers against.")
    p_check.add_argument("--against", help="A snapshot directory (quote_ledger.csv/claim_ledger.csv/source_manifest.json) to diff against.")
    p_check.add_argument("--apply", action="store_true", help="Write engine_status=STALE into the live ledgers and log the firing (default: report only, no writes).")
    p_check.set_defaults(func=cmd_check)

    p_mark = sub.add_parser("mark-stale", help="Manually mark one node STALE with an explicit reason.")
    p_mark.add_argument("--node-id", required=True)
    p_mark.add_argument("--node-type", default="")
    p_mark.add_argument("--reason", required=True)
    p_mark.set_defaults(func=cmd_mark_stale)

    p_report = sub.add_parser("report", help="Summarize current engine_status distribution and recent events.")
    p_report.add_argument("--out", help="Write the JSON report to this path too.")
    p_report.set_defaults(func=cmd_report)

    p_migrate = sub.add_parser("migrate-schema", help="One-time (idempotent) schema-v2 column addition to the live ledgers.")
    p_migrate.add_argument("--apply", action="store_true", help="Actually write; default is a dry-run report.")
    p_migrate.set_defaults(func=cmd_migrate_schema)

    p_repair_cs = sub.add_parser(
        "repair-citable-status",
        help="Repair citable_status cells holding a raw dict-repr string.",
    )
    p_repair_cs.add_argument("--apply", action="store_true", help="Actually write; default is a dry-run report.")
    p_repair_cs.set_defaults(func=cmd_repair_citable_status)

    p_rehash_mj = sub.add_parser(
        "rehash-manifest-json",
        help="Recompute identity_hash/extraction_hash on source_manifest.json with JSON-native fields.",
    )
    p_rehash_mj.add_argument("--apply", action="store_true", help="Actually write; default is a dry-run report.")
    p_rehash_mj.set_defaults(func=cmd_rehash_manifest_json)

    p_migrate_v3 = sub.add_parser(
        "migrate-schema-v3",
        help="One-time (idempotent) schema-v3 row_provenance_date column addition.",
    )
    p_migrate_v3.add_argument("--apply", action="store_true", help="Actually write; default is a dry-run report.")
    p_migrate_v3.set_defaults(func=cmd_migrate_schema_v3)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
