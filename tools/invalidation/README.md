# Invalidation engine

`invalidation.py` is a small dependency-invalidation engine: a directed
graph of `Source -> Evidence -> Claim -> Use` (plus an `Approval` node
type for anything requiring an owner's sign-off), a fixed vocabulary of
change events, and a deterministic dispatch table that marks every
downstream-dependent node `STALE` when an upstream node changes.

## Why a project needs this

Once you have an evidence ledger and a claim ledger of any real size, you
cannot re-verify everything by hand every round. The invalidation engine
lets you re-verify only what a specific change could have affected: if a
source's extracted text is corrected, every piece of evidence drawn from
it, every claim resting on that evidence, and every passage in the work
citing that claim is marked `STALE` — and nothing else is, so you are not
re-checking records a change could not possibly have touched.

## What's here

- `invalidation.py` — the engine itself: `Graph`/`Node`/`Edge`, the event
  vocabulary (`EVENT_KINDS`), `compute_affected_set` (the dispatch
  table), `propagate_stale`, content-hash-based change detection
  (`compute_content_hash`, `detect_row_events`), and a CSV event-log
  writer (`append_invalidation_events`) that `tools/prov/export.py`
  consumes.
- `tests/test_engine.py` — a full test suite (17 cases) against the graph
  model, the dispatch table, and staleness propagation, runnable with
  stdlib `unittest` alone.

## What you need to wire up

`load_live_graph(root)` in `invalidation.py` is a stub. Replace it with
real reads of your own source manifest, evidence ledger, and claim
ledger, building one `Node` per row and one `Edge` per dependency. Once
that's wired, run `detect_row_events` against a prior-vs-current snapshot
of each ledger, feed the resulting `ChangeEvent`s to `propagate_stale`,
and append the results to your event log with
`append_invalidation_events`. Everything else in the module — the graph,
the dispatch table, the propagation algorithm — works unmodified.

## A worked example, by hand

```python
from invalidation import Graph, Node, Edge, ChangeEvent, propagate_stale

g = Graph()
g.add_node(Node(id="source-1", type="Source"))
g.add_node(Node(id="evidence-1", type="Evidence"))
g.add_node(Node(id="claim-1", type="Claim"))
g.add_edge(Edge(src="evidence-1", dst="source-1", type="wasDrawnFrom"))
g.add_edge(Edge(src="claim-1", dst="evidence-1", type="supports"))

# A source gets re-extracted with corrected text:
event = ChangeEvent(kind="source_reextracted", node_id="source-1", node_type="Source")
propagate_stale(g, [event])

g.nodes["evidence-1"].engine_status  # -> "STALE"
g.nodes["claim-1"].engine_status     # -> "STALE", transitively
```
