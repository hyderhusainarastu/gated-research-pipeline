#!/usr/bin/env python3
"""
Unit tests for tools/invalidation/invalidation.py. Stdlib `unittest` only
-- run with `python3 -m unittest tools/invalidation/tests/test_engine.py`
or `python3 tools/invalidation/tests/test_engine.py`, no third-party test
runner required.

These tests exercise the graph model, the dispatch table, and staleness
propagation directly (not through the live-ledger wiring stubs, which are
project-specific by design -- see the module docstring in
invalidation.py). A real project should add its own tests against
`load_live_graph` once that stub is wired to its actual ledger schema.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from invalidation import (  # noqa: E402
    ChangeEvent,
    EngineStatus,
    Graph,
    MalformedChangeError,
    MalformedGraphError,
    Node,
    Edge,
    compute_affected_set,
    compute_content_hash,
    detect_row_events,
    propagate_stale,
)


def _small_graph() -> Graph:
    """source-1 <-wasDrawnFrom- evidence-1 <-supports- claim-1 <-citedIn- use-1"""
    g = Graph()
    g.add_node(Node(id="source-1", type="Source"))
    g.add_node(Node(id="evidence-1", type="Evidence"))
    g.add_node(Node(id="claim-1", type="Claim"))
    g.add_node(Node(id="use-1", type="Use"))
    g.add_edge(Edge(src="evidence-1", dst="source-1", type="wasDrawnFrom"))
    g.add_edge(Edge(src="claim-1", dst="evidence-1", type="supports"))
    g.add_edge(Edge(src="use-1", dst="claim-1", type="citedIn"))
    return g


class TestGraph(unittest.TestCase):
    def test_duplicate_node_rejected(self):
        g = Graph()
        g.add_node(Node(id="a", type="Source"))
        with self.assertRaises(MalformedGraphError):
            g.add_node(Node(id="a", type="Source"))

    def test_edge_to_unknown_node_rejected(self):
        g = Graph()
        g.add_node(Node(id="a", type="Source"))
        with self.assertRaises(MalformedGraphError):
            g.add_edge(Edge(src="a", dst="nonexistent", type="wasDrawnFrom"))

    def test_unknown_node_type_rejected(self):
        with self.assertRaises(ValueError):
            Node(id="a", type="NotARealType")

    def test_downstream_closure_transitive(self):
        g = _small_graph()
        # source-1 changing must reach evidence-1, claim-1, and use-1.
        self.assertEqual(g.downstream_closure("source-1"), {"evidence-1", "claim-1", "use-1"})
        # evidence-1 changing reaches claim-1 and use-1, not source-1.
        self.assertEqual(g.downstream_closure("evidence-1"), {"claim-1", "use-1"})
        # A leaf (use-1) has nothing downstream of it.
        self.assertEqual(g.downstream_closure("use-1"), set())

    def test_no_cycle_in_acyclic_graph(self):
        g = _small_graph()
        self.assertIsNone(g.detect_cycle())

    def test_cycle_detected(self):
        g = Graph()
        g.add_node(Node(id="a", type="Source"))
        g.add_node(Node(id="b", type="Evidence"))
        g.add_edge(Edge(src="a", dst="b", type="wasDrawnFrom"))
        g.add_edge(Edge(src="b", dst="a", type="wasDrawnFrom"))
        cycle = g.detect_cycle()
        self.assertIsNotNone(cycle)
        self.assertIn("a", cycle)
        self.assertIn("b", cycle)


class TestDispatchTable(unittest.TestCase):
    def test_source_change_propagates_to_every_downstream_node(self):
        g = _small_graph()
        event = ChangeEvent(kind="source_reextracted", node_id="source-1", node_type="Source")
        result = compute_affected_set(g, event)
        self.assertEqual(result.directly_changed, {"source-1"})
        self.assertEqual(result.downstream_stale, {"evidence-1", "claim-1", "use-1"})

    def test_leaf_use_edit_has_no_downstream(self):
        g = _small_graph()
        event = ChangeEvent(kind="claim_edited", node_id="claim-1", node_type="Claim")
        result = compute_affected_set(g, event)
        self.assertEqual(result.directly_changed, {"claim-1"})
        self.assertEqual(result.downstream_stale, {"use-1"})

    def test_new_evidence_has_empty_affected_set(self):
        g = _small_graph()
        g.add_node(Node(id="evidence-2", type="Evidence"))
        event = ChangeEvent(kind="evidence_added", node_id="evidence-2", node_type="Evidence")
        result = compute_affected_set(g, event)
        self.assertEqual(result.directly_changed, set())
        self.assertEqual(result.downstream_stale, set())

    def test_unknown_event_kind_rejected_at_construction(self):
        with self.assertRaises(MalformedChangeError):
            ChangeEvent(kind="not_a_real_kind", node_id="source-1", node_type="Source")

    def test_event_against_unknown_node_rejected(self):
        g = _small_graph()
        event = ChangeEvent(kind="source_reextracted", node_id="does-not-exist", node_type="Source")
        with self.assertRaises(MalformedChangeError):
            compute_affected_set(g, event)


class TestPropagation(unittest.TestCase):
    def test_propagate_stale_marks_every_affected_node(self):
        g = _small_graph()
        events = [ChangeEvent(kind="source_reextracted", node_id="source-1", node_type="Source")]
        propagate_stale(g, events)
        for node_id in ("source-1", "evidence-1", "claim-1", "use-1"):
            self.assertEqual(g.nodes[node_id].engine_status, EngineStatus.STALE.value)
            self.assertNotEqual(g.nodes[node_id].stale_reason, "")

    def test_unaffected_sibling_stays_fresh(self):
        g = _small_graph()
        g.add_node(Node(id="claim-2", type="Claim"))
        g.add_edge(Edge(src="claim-2", dst="evidence-1", type="supports"))
        # Only claim-1 changes; claim-2 also depends on evidence-1 but not
        # on claim-1, so it must stay FRESH.
        events = [ChangeEvent(kind="claim_edited", node_id="claim-1", node_type="Claim")]
        propagate_stale(g, events)
        self.assertEqual(g.nodes["claim-1"].engine_status, EngineStatus.STALE.value)
        self.assertEqual(g.nodes["claim-2"].engine_status, EngineStatus.FRESH.value)


class TestContentHashAndRowDiff(unittest.TestCase):
    def test_unchanged_row_emits_no_event(self):
        prior = {"row-1": {"text": "the sky is blue", "note": "irrelevant column"}}
        current = {"row-1": {"text": "the sky is blue", "note": "a DIFFERENT irrelevant column"}}
        events = detect_row_events(
            "Evidence", prior, current, id_field="id", content_fields=["text"],
        )
        # Only `text` is a content field; `note` changing must not trigger
        # an event -- this is the point of restricting compute_content_hash
        # to a fixed field list.
        self.assertEqual(events, [])

    def test_changed_content_field_emits_edited_event(self):
        prior = {"row-1": {"text": "the sky is blue"}}
        current = {"row-1": {"text": "the sky is azure"}}
        events = detect_row_events(
            "Evidence", prior, current, id_field="id", content_fields=["text"],
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "evidence_edited")
        self.assertEqual(events[0].node_id, "row-1")
        self.assertNotEqual(events[0].content_hash_before, events[0].content_hash_after)

    def test_new_row_emits_added_event(self):
        prior: dict = {}
        current = {"row-1": {"text": "brand new"}}
        events = detect_row_events(
            "Claim", prior, current, id_field="id", content_fields=["text"],
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "claim_added")

    def test_hash_is_deterministic(self):
        row = {"a": "1", "b": "2", "c": "ignored"}
        h1 = compute_content_hash(row, ["a", "b"])
        h2 = compute_content_hash(row, ["a", "b"])
        self.assertEqual(h1, h2)
        h3 = compute_content_hash({"a": "1", "b": "different"}, ["a", "b"])
        self.assertNotEqual(h1, h3)


if __name__ == "__main__":
    unittest.main()
