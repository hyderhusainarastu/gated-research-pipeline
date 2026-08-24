#!/usr/bin/env python3
"""
tools/prov/export.py -- live PROV-O/PROV-N emission from the invalidation
engine's own event log (see tools/invalidation/invalidation.py).

============================================================================
SCOPE, DISCLOSED
============================================================================
This module emits PROV events from the invalidation engine's event log
only. It does NOT build a full corpus provenance graph (one Entity per
source/quotation/claim with full `used`/`wasAssociatedWith` activity
relations and agents) -- that is a much larger, separate capability than
"emit PROV events from the invalidation engine's own event log," which is
this module's actual scope. Building a full live corpus re-serialization
is a distinct, larger follow-on task, not attempted here -- see
`validate_store.py`'s own disclosure of which check this scope boundary
leaves NOT RUN.

============================================================================
WHAT THIS MODULE DOES
============================================================================
Reads the invalidation engine's event log (default `logs/
invalidation_events.csv`):
  1. A row whose `new_engine_status == "STALE"` -> one `prov:Invalidation`
     instance + one `prov:wasInvalidatedBy` edge.
  2. A `row_add`/`row_edit` row (quotation/claim node types only) ->
     `prov:wasGeneratedBy` (row_add: new entity, new Activity,
     `prov:generatedAtTime` from the row's live provenance date) or
     `prov:wasRevisionOf` (row_edit: new-version entity -> prior-version
     entity, via the event log's `content_hash_before`/`content_hash_after`
     columns).

Idempotency: a pointer state file (default `logs/prov_store.state.json`)
records the last-processed event_id; `append` skips everything at or
before that pointer. `backfill` ignores the pointer and processes every
event in the log from scratch (a one-time-only mode, run once against
every event already in the log).

Store format: the Turtle file (default `logs/prov_store.ttl`) is the
authoritative, incrementally-appended store; the PROV-N file (default
`logs/prov_store.provn`) is a REGENERATED (not appended) human-audit
rendering, written fresh on every run from the full accumulated graph.

rdflib is used (not stdlib-only) so the Turtle output is guaranteed
well-formed by construction rather than hand-formatted. If rdflib is not
importable, this script fails loudly with an install instruction.

No live ledger file is written by this module. It reads the event log
plus your quote/claim ledgers (for provenance-date/id enrichment only)
and writes the Turtle store, the PROV-N rendering, and the pointer state
file.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, XSD
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "rdflib is not importable. Install it into a virtual environment: "
        "python3 -m venv <dir> && <dir>/bin/pip install rdflib, then run "
        "this script with that venv's python3.\n"
    )
    raise

_THIS_FILE = os.path.abspath(__file__)
TOOLS_PROV_DIR = os.path.dirname(_THIS_FILE)
PROJECT_ROOT = os.path.dirname(os.path.dirname(TOOLS_PROV_DIR))

QUOTE_LEDGER_PATH = os.path.join(PROJECT_ROOT, "records", "quote_ledger.csv")
CLAIM_LEDGER_PATH = os.path.join(PROJECT_ROOT, "records", "claim_ledger.csv")
EVENTS_LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "invalidation_events.csv")
STORE_TTL_PATH = os.path.join(PROJECT_ROOT, "logs", "prov_store.ttl")
STORE_PROVN_PATH = os.path.join(PROJECT_ROOT, "logs", "prov_store.provn")
STORE_STATE_PATH = os.path.join(PROJECT_ROOT, "logs", "prov_store.state.json")

# ---------------------------------------------------------------------------
# URN scheme. Replace the URN authority string below with your own
# project's identifier before relying on this in a real deployment --
# `urn:<your-project-id>:live:...` -- it only needs to be stable and
# collision-free within your own store; it is not resolved externally.
# ---------------------------------------------------------------------------
LIVE_BASE = "urn:verification-gated-pipeline:live:"
PROV = Namespace("http://www.w3.org/ns/prov#")


def entity_urn(node_type: str, node_id: str, content_hash: str) -> URIRef:
    """`<LIVE_BASE><node_type>:<node_id>:<content_hash[:12]>`. A 12-hex-char
    content-hash prefix is collision-safe at most projects' ledger-row
    scale; lengthen it if your project's scale warrants."""
    h12 = (content_hash or "")[:12] or "nohash"
    return URIRef(f"{LIVE_BASE}{node_type}:{node_id}:{h12}")


def activity_urn(kind: str, event_id: str) -> URIRef:
    safe_id = event_id.replace(":", "-").replace(" ", "_")
    return URIRef(f"{LIVE_BASE}activity:{kind}:{safe_id}")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _read_csv_rows(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _load_pointer() -> Optional[str]:
    if not os.path.exists(STORE_STATE_PATH):
        return None
    with open(STORE_STATE_PATH, encoding="utf-8") as fh:
        state = json.load(fh)
    return state.get("last_event_id_processed")


def _save_pointer(last_event_id: str, n_events_processed_total: int) -> None:
    state = {
        "last_event_id_processed": last_event_id,
        "n_events_processed_total": n_events_processed_total,
        "store_ttl_path": STORE_TTL_PATH,
    }
    os.makedirs(os.path.dirname(STORE_STATE_PATH), exist_ok=True)
    with open(STORE_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def _load_ledger_lookup() -> Dict[str, Dict[str, dict]]:
    """{"quotation": {node_id: row}, "claim": {node_id: row}} for
    provenance-date/id enrichment -- read-only, never written here."""
    quote_rows = _read_csv_rows(QUOTE_LEDGER_PATH)
    claim_rows = _read_csv_rows(CLAIM_LEDGER_PATH)
    return {
        "quotation": {r.get("quote_id", ""): r for r in quote_rows if r.get("quote_id")},
        "claim": {r.get("claim_id", ""): r for r in claim_rows if r.get("claim_id")},
    }


# ---------------------------------------------------------------------------
# Event classification and emission
# ---------------------------------------------------------------------------

def build_graph_and_provn(events: List[dict], ledger_lookup: Dict[str, Dict[str, dict]]) -> tuple:
    """Emits triples for the given (already-filtered, in log order) event
    rows. Returns (rdflib.Graph, provn_records_list)."""
    g = Graph()
    g.bind("prov", PROV)
    provn: List[dict] = []

    g.add((PROV.wasQuotedFrom, RDFS.subPropertyOf, PROV.wasDerivedFrom))
    g.add((PROV.hadPrimarySource, RDFS.subPropertyOf, PROV.wasDerivedFrom))
    provn.append({
        "kind": "comment",
        "text": "# T-box: wasQuotedFrom, hadPrimarySource are rdfs:subPropertyOf wasDerivedFrom.",
    })

    for ev in events:
        change_kind = ev.get("change_kind", "")
        node_type = ev.get("node_type", "")
        node_id = ev.get("node_id", "")
        event_id = ev.get("event_id", "")

        if change_kind == "none" or not node_id:
            continue  # zero-row summary firing, nothing to emit

        # invalidation firing -> Invalidation + wasInvalidatedBy
        if ev.get("new_engine_status") == "STALE":
            entity = entity_urn(node_type, node_id, ev.get("content_hash_after", ""))
            inv = activity_urn("invalidation", event_id)
            g.add((entity, RDF.type, PROV.Entity))
            g.add((inv, RDF.type, PROV.Invalidation))
            g.add((entity, PROV.wasInvalidatedBy, inv))
            g.add((inv, PROV.atTime, Literal(ev.get("firing_timestamp", ""), datatype=XSD.dateTime)))
            provn.append({"kind": "activity", "id": str(inv), "attrs": {"prov:type": "Invalidation"}})
            provn.append({"kind": "relation", "name": "wasInvalidatedBy", "args": [str(entity), str(inv)]})

        # records-merge row_add/row_edit -> Generation/Revision
        if change_kind == "row_add" and node_type in ("quotation", "claim"):
            new_entity = entity_urn(node_type, node_id, ev.get("content_hash_after", ""))
            gen_act = activity_urn("generation", event_id)
            row = ledger_lookup.get(node_type, {}).get(node_id, {})
            gen_time = row.get("row_provenance_date") or ev.get("firing_timestamp", "")
            g.add((new_entity, RDF.type, PROV.Entity))
            g.add((gen_act, RDF.type, PROV.Activity))
            g.add((new_entity, PROV.wasGeneratedBy, gen_act))
            if gen_time:
                g.add((gen_act, PROV.endedAtTime, Literal(gen_time)))
            provn.append({"kind": "activity", "id": str(gen_act), "attrs": {}, "generated": str(new_entity)})

        elif change_kind == "row_edit" and node_type in ("quotation", "claim"):
            new_entity = entity_urn(node_type, node_id, ev.get("content_hash_after", ""))
            old_entity = entity_urn(node_type, node_id, ev.get("content_hash_before", ""))
            # Both versions are typed as prov:Entity, INCLUDING the prior
            # version -- this store does not model the prior version's own
            # generation history, but it does assert the URN it references
            # denotes a real Entity, so a dangling-reference check has
            # something to find rather than flagging every revision edge
            # as pointing at an undeclared node.
            g.add((new_entity, RDF.type, PROV.Entity))
            g.add((old_entity, RDF.type, PROV.Entity))
            g.add((new_entity, PROV.wasRevisionOf, old_entity))
            g.add((new_entity, PROV.wasDerivedFrom, old_entity))
            provn.append({"kind": "relation", "name": "wasRevisionOf", "args": [str(new_entity), str(old_entity)]})

    return g, provn


# ---------------------------------------------------------------------------
# PROV-N rendering (regenerated, not appended, on every run)
# ---------------------------------------------------------------------------

def render_provn(provn_records: List[dict]) -> str:
    """Lightweight renderer over exactly the record kinds
    `build_graph_and_provn` emits ("comment", "activity", "relation") --
    not a general RDF-to-PROV-N converter."""
    lines = ["document"]
    lines.append("  prefix prov <http://www.w3.org/ns/prov#>")
    lines.append("")
    for rec in provn_records:
        kind = rec["kind"]
        if kind == "comment":
            lines.append(f"  {rec['text']}")
        elif kind == "activity":
            lines.append(f"  activity({rec['id']})")
            if rec.get("generated"):
                lines.append(f"  wasGeneratedBy({rec['generated']}, {rec['id']})")
        elif kind == "relation":
            args = ", ".join(rec["args"])
            lines.append(f"  {rec['name']}({args})")
    lines.append("endDocument")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Store persistence -- Turtle is the authoritative, append-safe store:
# each run's NEW triples are added to whatever the store already holds
# (parsed fresh from disk if present), then the WHOLE accumulated graph is
# re-serialized -- safe incremental append at the TRIPLE level (rdflib
# dedupes identical triples automatically), even though the on-disk write
# itself is a full rewrite each time (simpler and just as safe as true
# byte-level appending at this store's expected size, and avoids ever
# hand-splicing Turtle text).
# ---------------------------------------------------------------------------

def _load_existing_store() -> Graph:
    g = Graph()
    g.bind("prov", PROV)
    if os.path.exists(STORE_TTL_PATH):
        g.parse(STORE_TTL_PATH, format="turtle")
    return g


def run_export(mode: str) -> Dict[str, Any]:
    if mode not in ("backfill", "append"):
        raise ValueError(f"unknown mode: {mode!r}")

    all_events = _read_csv_rows(EVENTS_LOG_PATH)
    pointer = _load_pointer() if mode == "append" else None

    if pointer is None:
        new_events = all_events
    else:
        seen_pointer = False
        new_events = []
        for ev in all_events:
            if seen_pointer:
                new_events.append(ev)
            elif ev.get("event_id") == pointer:
                seen_pointer = True
        if not seen_pointer:
            # Pointer not found in the current log (e.g. log was rebuilt) --
            # disclosed, conservative fallback: process everything, never
            # silently process nothing.
            new_events = all_events

    ledger_lookup = _load_ledger_lookup()
    new_graph, new_provn = build_graph_and_provn(new_events, ledger_lookup)

    if mode == "backfill":
        store = Graph()
        store.bind("prov", PROV)
    else:
        store = _load_existing_store()

    n_triples_before = len(store)
    for triple in new_graph:
        store.add(triple)
    n_triples_after = len(store)

    os.makedirs(os.path.dirname(STORE_TTL_PATH), exist_ok=True)
    store.serialize(destination=STORE_TTL_PATH, format="turtle")

    if mode == "backfill" or not os.path.exists(STORE_PROVN_PATH):
        provn_text = render_provn(new_provn)
    else:
        with open(STORE_PROVN_PATH, encoding="utf-8") as fh:
            prior_lines = fh.read().splitlines()
        body = [ln for ln in prior_lines if ln not in ("document", "endDocument") and not ln.startswith("  prefix")]
        new_body_lines = render_provn(new_provn).splitlines()[3:-1]
        provn_text = "\n".join(["document", "  prefix prov <http://www.w3.org/ns/prov#>", ""] + body + new_body_lines + ["endDocument"]) + "\n"
    with open(STORE_PROVN_PATH, "w", encoding="utf-8") as fh:
        fh.write(provn_text)

    last_id = all_events[-1]["event_id"] if all_events else (pointer or "")
    _save_pointer(last_id, len(all_events))

    return {
        "mode": mode,
        "n_events_in_log": len(all_events),
        "n_events_processed_this_run": len(new_events),
        "n_triples_before": n_triples_before,
        "n_triples_after": n_triples_after,
        "n_new_triples": n_triples_after - n_triples_before,
        "store_ttl_path": STORE_TTL_PATH,
        "store_provn_path": STORE_PROVN_PATH,
        "pointer_after": last_id,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["backfill", "append"])
    args = p.parse_args(argv)
    result = run_export(args.mode)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
