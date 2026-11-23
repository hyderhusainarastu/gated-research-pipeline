# Invalidation engine

`invalidation.py` is a dependency-invalidation engine for evidence-grounded
writing projects. It keeps a directed graph of
`Source -> Quotation -> Claim -> ManuscriptUse` (plus `Ratification` nodes
for anything that needs an owner's sign-off), detects what changed in your
ledgers, and marks every downstream record that the change could have
affected as `STALE`, with a reason. Records the change cannot reach stay
`FRESH`, so you re-verify only what you must.

Standard library only. Deterministic. Tested on Python 3.14.

## What is here

- `invalidation.py`: the graph model, the event dispatch table, change
  detection by content hash, the `engine_status` state machine (`FRESH`,
  `STALE`, `CHECKING`, `ERROR`, ...), one-time schema migrations (each takes
  a backup and aborts if the file changed underneath it), the
  `logs/invalidation_events.csv` writer that `tools/prov/export.py` reads,
  and a CLI.
- `tests/test_live_engine.py`: 36 unit tests, run against temporary
  directories only.
- `../../examples/invalidation-demo/`: an invented two-source project and
  `run_demo.sh`, which runs the CLI end to end offline.

## Ledger layout it expects

The engine reads these paths relative to the project root (two directories
above `tools/invalidation/`). They are constants near the top of
`invalidation.py`; change them to match your project.

| File | Key column | Role |
| --- | --- | --- |
| `research/quote_ledger.csv` | `quote_id` | one row per quotation (`exact_quote`, `slug`, `citable_status`, ...) |
| `research/claim_ledger.csv` | `claim_id` | one row per claim (`claim_text`, `quote_id`, `slug`, ...) |
| `Sources/source_manifest.json` | `slug` | one entry per source; a list, or a dict keyed by slug |
| `Sources/source_manifest.csv` | `slug` | the same manifest as CSV |

A claim's `quote_id` may hold several ids separated by `;`.

## CLI

```
python3 tools/invalidation/invalidation.py migrate-schema --apply   # once: add content_hash and engine_status columns
python3 tools/invalidation/invalidation.py check --since <git-ref>  # report what became STALE since a commit
python3 tools/invalidation/invalidation.py check --against <dir>    # same, against a snapshot directory
python3 tools/invalidation/invalidation.py check --against <dir> --apply   # also write STALE into the ledgers and log the firing
python3 tools/invalidation/invalidation.py mark-stale --node-id c-002 --reason "re-read the source"
python3 tools/invalidation/invalidation.py report
```

Without `--apply`, `check` and the migrations only report; they do not write.
Every migration backs up the file first (`logs/pre_schema_v2/`,
`logs/pre_schema_v3/`) and refuses to run on a CSV with ragged rows.

## Worked example

`examples/invalidation-demo/run_demo.sh` copies the engine and a toy project
to a temp directory, snapshots the ledgers, changes the wording of one
quotation, and runs `check`:

```
$ bash examples/invalidation-demo/run_demo.sh
== check: what does that edit make STALE?
{
  ...
  "n_quote_triggers": 1,
  "n_transitioned_to_stale": 2,
  "stale_nodes": {
    "q-002": "row_edit on quotation q-002 (fields: exact_quote)",
    "c-002": "upstream change: row_edit on quotation q-002 (fields: exact_quote)"
  },
  ...
}
```

The edited quotation and the one claim that rests on it go `STALE`. The other
two quotations and two claims are untouched.

From Python:

```python
from invalidation import load_live_graph
graph, report = load_live_graph()
print(report.to_dict())
```

## Limits

- The ledger column names above are a fixed convention. A project with a
  different schema has to change the field lists (`QUOTE_CONTENT_HASH_FIELDS`
  and the others near the top of the module) or map its ledgers to these
  names.
- Some comments cite "section N.M" of the original design notes. Those notes
  are not in this repository; the behaviour is covered by the tests.
- The original engine also had a parity test against a separate research
  prototype. That test depended on files outside this repository and is not
  included.
