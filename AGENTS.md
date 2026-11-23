# gated-research-pipeline

A template for evidence-grounded writing: every claim traces to a checkable
source, and nothing is called done until it clears a readiness gate. It ships
four skills, convention docs and Python tools.

## Using this in your project

- Skills live in `.claude/skills/<name>/SKILL.md`. Read the matching one when
  the task fits its `description`:
  - `source-intake`: any new source entering the library.
  - `gate-e-sweeps`: mechanical sweeps on a draft, before any review.
  - `ai-review`: exhaustive pre-submission audit, once per round per piece.
  - `records-update`: decisions log, task ledger and open-questions rows.
- Install with `./install.sh --claude|--agents --project DIR`. With no flag it
  changes nothing. Add `--dry-run` to preview. Use `--uninstall` to remove.
- Put venue-specific numbers (word caps, citation style) in a venue profile
  YAML, never in a skill. Start from
  `examples/venue-profiles/generic-conference-profile.yaml`.
- Invalidation engine: `python3 tools/invalidation/invalidation.py check
  --against <snapshot-dir>` reports what a ledger change made STALE. Exit 0
  means it ran; read the JSON. It only writes with `--apply`.
- Re-derive governance counts with `tools/counters.py`. Never hand-count them.
- Never mark a quotation or claim verified without opening the source text.
- Never run `--apply` or a migration on ledgers you have not backed up or
  committed.
- Chat users without a skills loader paste `PROMPT.md`.

## Working on this repo

- Setup: Python 3, stdlib only. `tools/prov` needs `pip install -r
  requirements.txt` in a virtual environment.
- Test (offline): `python3 -m unittest discover -s tools/invalidation/tests`
  and `bash test_install.sh`.
- Demo: `bash examples/invalidation-demo/run_demo.sh`.
- Use only invented or public-classic data in `examples/` and tests. No real
  manuscript text, names, paths or hashes.
- Do not commit `__pycache__/` or `.venv/`.
