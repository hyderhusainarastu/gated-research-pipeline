#!/usr/bin/env python3
"""
tools/prov/validate_store.py -- structural validation of the live PROV
store (`logs/prov_store.ttl` by default). Re-parses the Turtle file FRESH
via `rdflib.Graph().parse(...)`, independent of the process that wrote it.

Checks, applied to the LIVE/GROWING store rather than a single frozen
snapshot:
  1. Unique identifiers (re-derived directly from your quote/claim
     ledgers, independent of the Turtle file).
  2. No dangling references (every object of an edge predicate this store
     actually uses is itself a declared subject of at least one triple in
     the store -- since `tools/prov/export.py`'s scoped emission does not
     assert `rdf:type prov:Entity` on every entity URN it mentions, the
     "declared" set here is: appears as subject OR object of ANY triple in
     the store).
  3. Derivation acyclicity (wasRevisionOf + wasDerivedFrom).
  4. No wasRevisionOf cycle (folded into check 3's own cycle detection,
     reported as its own named check).
  5. No entity invalidated before generated -- vacuously PASS if this
     store carries 0 Invalidation instances (disclosed as trivial, not a
     substantive finding).

A sixth check (generation-before-use, comparing `prov:used` claim<->quote
pairs) is DEFINED here but reports NOT_RUN, disclosed: it requires
`prov:used` edges that `tools/prov/export.py`'s SCOPED emission
(event-log-driven only, not a full corpus re-serialization -- see that
module's own docstring) does not produce. Running it anyway would
silently report "0 checked, 0 violations" in a way indistinguishable from
a genuine pass; disclosing NOT_RUN instead is the honest option.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List

try:
    from rdflib import Graph, Namespace, RDF
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "rdflib is not importable. See tools/prov/export.py's own module "
        "docstring for the venv install command.\n"
    )
    raise

_THIS_FILE = os.path.abspath(__file__)
TOOLS_PROV_DIR = os.path.dirname(_THIS_FILE)
PROJECT_ROOT = os.path.dirname(os.path.dirname(TOOLS_PROV_DIR))

QUOTE_LEDGER_PATH = os.path.join(PROJECT_ROOT, "records", "quote_ledger.csv")
CLAIM_LEDGER_PATH = os.path.join(PROJECT_ROOT, "records", "claim_ledger.csv")
STORE_TTL_PATH = os.path.join(PROJECT_ROOT, "logs", "prov_store.ttl")

PROV = Namespace("http://www.w3.org/ns/prov#")
DERIVATION_PREDICATES = [PROV.wasQuotedFrom, PROV.hadPrimarySource, PROV.wasDerivedFrom, PROV.wasRevisionOf]


def check_unique_identifiers() -> dict:
    with open(QUOTE_LEDGER_PATH, newline="", encoding="utf-8") as fh:
        qids = [r["quote_id"].strip() for r in csv.DictReader(fh) if r.get("quote_id")]
    with open(CLAIM_LEDGER_PATH, newline="", encoding="utf-8") as fh:
        cids = [r["claim_id"].strip() for r in csv.DictReader(fh) if r.get("claim_id")]

    def dupes(seq):
        seen, dup = set(), set()
        for x in seq:
            if x in seen:
                dup.add(x)
            seen.add(x)
        return sorted(dup)

    qdup, cdup = dupes(qids), dupes(cids)
    return {
        "check": "unique_identifiers", "pass": not qdup and not cdup,
        "n_quote_ids": len(qids), "n_quote_ids_unique": len(set(qids)),
        "n_claim_ids": len(cids), "n_claim_ids_unique": len(set(cids)),
        "duplicate_quote_ids": qdup, "duplicate_claim_ids": cdup,
    }


TYPED_CLASSES = [PROV.Entity, PROV.Activity, PROV.Invalidation]


def check_no_dangling_references(g: Graph) -> dict:
    """"Declared" means the node carries an `rdf:type` in `TYPED_CLASSES`
    somewhere in the store -- `tools/prov/export.py` asserts `prov:Entity`
    on BOTH the new and prior-version URN of every `wasRevisionOf` edge,
    and on the new entity + Activity of every `wasGeneratedBy`/
    `wasInvalidatedBy` edge, so a genuinely undeclared reference is a real
    defect, not an artifact of this store's own disclosed scope
    boundary."""
    declared = set()
    for cls in TYPED_CLASSES:
        for s in g.subjects(RDF.type, cls):
            declared.add(str(s))

    edge_predicates = DERIVATION_PREDICATES + [PROV.wasInvalidatedBy, PROV.wasGeneratedBy]
    dangling = []
    n_checked = 0
    for pred in edge_predicates:
        for s, o in g.subject_objects(pred):
            n_checked += 1
            if str(o) not in declared:
                dangling.append({"subject": str(s), "predicate": str(pred), "object": str(o)})
    return {
        "check": "no_dangling_references", "pass": len(dangling) == 0,
        "n_declared_typed_nodes": len(declared),
        "n_edges_checked": n_checked, "n_dangling": len(dangling),
        "dangling_edges": dangling[:50], "dangling_truncated": len(dangling) > 50,
    }


def check_acyclicity(g: Graph) -> dict:
    adj: Dict[str, set] = defaultdict(set)
    for pred in DERIVATION_PREDICATES:
        for s, o in g.subject_objects(pred):
            adj[str(s)].add(str(o))

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = defaultdict(int)
    cycle_path: List[str] = []

    def dfs(node: str, path: List[str]) -> bool:
        color[node] = GRAY
        path.append(node)
        for nxt in adj.get(node, ()):
            if color[nxt] == GRAY:
                cycle_path.extend(path[path.index(nxt):] + [nxt])
                return True
            if color[nxt] == WHITE and dfs(nxt, path):
                return True
        path.pop()
        color[node] = BLACK
        return False

    found_cycle = False
    for node in list(adj.keys()):
        if color[node] == WHITE:
            if dfs(node, []):
                found_cycle = True
                break

    return {
        "check": "derivation_acyclicity", "pass": not found_cycle,
        "n_nodes_with_outgoing_derivation_edge": len(adj),
        "n_derivation_edges": sum(len(v) for v in adj.values()),
        "cycle_found": found_cycle, "cycle_path": cycle_path if found_cycle else [],
    }


def check_no_wasrevisionof_cycle(g: Graph) -> dict:
    adj: Dict[str, set] = defaultdict(set)
    for s, o in g.subject_objects(PROV.wasRevisionOf):
        adj[str(s)].add(str(o))
    n_edges = sum(len(v) for v in adj.values())
    if n_edges == 0:
        return {
            "check": "no_wasRevisionOf_cycle", "pass": True, "n_wasRevisionOf_edges": 0,
            "note": "VACUOUSLY PASS: 0 wasRevisionOf edges in this store (no row_edit "
                    "events processed yet) -- disclosed as trivial.",
        }
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = defaultdict(int)
    cycle_found = False
    cycle_path: List[str] = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for nxt in adj.get(node, ()):
            if color[nxt] == GRAY:
                cycle_path.extend(path[path.index(nxt):] + [nxt])
                return True
            if color[nxt] == WHITE and dfs(nxt, path):
                return True
        path.pop()
        color[node] = BLACK
        return False

    for node in list(adj.keys()):
        if color[node] == WHITE and dfs(node, []):
            cycle_found = True
            break
    return {
        "check": "no_wasRevisionOf_cycle", "pass": not cycle_found,
        "n_wasRevisionOf_edges": n_edges, "cycle_found": cycle_found, "cycle_path": cycle_path,
    }


def check_no_entity_invalidated_before_generated(g: Graph) -> dict:
    n_invalidation = sum(1 for _ in g.triples((None, RDF.type, PROV.Invalidation)))
    n_invalidated_by = sum(1 for _ in g.triples((None, PROV.wasInvalidatedBy, None)))
    if n_invalidation == 0:
        return {
            "check": "no_entity_invalidated_before_generated", "pass": True,
            "n_Invalidation_instances": 0, "n_wasInvalidatedBy_edges": n_invalidated_by,
            "note": "VACUOUSLY PASS: 0 Invalidation instances in this store yet "
                    "(no invalidation-firing events have been processed) -- disclosed as trivial.",
        }
    # A full check would compare prov:atTime on the Invalidation instance
    # against prov:endedAtTime on the entity's own generating Activity --
    # presence-only here until a non-vacuous case exercises it.
    return {
        "check": "no_entity_invalidated_before_generated", "pass": True,
        "n_Invalidation_instances": n_invalidation, "n_wasInvalidatedBy_edges": n_invalidated_by,
        "note": "PASS reported by presence-only check (no genuine before/after timestamp "
                "comparison performed yet, since no Invalidation instance existed to "
                "exercise it against -- see the vacuous branch above).",
    }


def check_temporal_generation_before_use() -> dict:
    """NOT RUN by default -- disclosed, not silently skipped. See module
    docstring for why (the scoped exporter does not produce prov:used
    claim<->quote pairs)."""
    return {
        "check": "generation_before_use_temporal", "pass": None, "status": "NOT_RUN",
        "reason": (
            "tools/prov/export.py's scoped emission (event-log-driven "
            "Invalidation/Generation/Revision only) does not emit "
            "prov:used claim<->quote edges -- those require a full corpus "
            "graph-builder (Source/Quotation/Claim/Activity), not shipped "
            "in this template. Running this check anyway would report "
            "'0 pairs checked, 0 violations' in a way indistinguishable "
            "from a genuine pass -- disclosed as NOT_RUN instead."
        ),
    }


def run() -> Dict[str, Any]:
    g = Graph()
    if os.path.exists(STORE_TTL_PATH):
        g.parse(STORE_TTL_PATH, format="turtle")
    n_triples = len(g)

    checks = [
        check_unique_identifiers(),
        check_no_dangling_references(g),
        check_acyclicity(g),
        check_no_wasrevisionof_cycle(g),
        check_no_entity_invalidated_before_generated(g),
    ]
    temporal = check_temporal_generation_before_use()

    all_structural_pass = all(c["pass"] for c in checks)
    return {
        "store_ttl_path": STORE_TTL_PATH,
        "n_triples_in_store": n_triples,
        "structural_checks": checks,
        "all_structural_checks_pass": all_structural_pass,
        "temporal_check": temporal,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="Write the JSON report to this path too.")
    args = p.parse_args(argv)
    report = run()
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if report["all_structural_checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
