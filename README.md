# Verification-gated research pipeline template

A template for producing evidence-grounded written work — a paper, a
report, an article, an audit — where every claim traces to a source,
every source traces to real, checkable text, and nothing gets called
"done" until it clears a defined, repeatable readiness bar. It grew out
of running that discipline for real across many rounds of one project;
this repository is the generalized, domain-neutral method, stripped of
anything specific to what it was originally used for.

It is not tied to any one field, venue, or writing tool. The worked
examples in `examples/venue-profiles/README.md` walk through a
humanities article, a biology preprint, and a software-engineering
technical report using the exact same pieces.

**Works with:** Claude Code (native skills), Codex, Cursor and Gemini CLI
(via `.agents/skills`), GitHub Copilot (instructions pointer), and any chat
model (paste `PROMPT.md`).

| Surface | How | Status |
| --- | --- | --- |
| Claude Code | native skills in `.claude/skills/`, `./install.sh --claude` | installer tested 2026-11-23 in a temp dir; skills not run in a live session |
| Codex, Cursor, Gemini CLI | `.agents/skills/` via `./install.sh --agents`; `AGENTS.md` | installer tested 2026-11-23 in a temp dir; skills not run in these tools |
| GitHub Copilot | pointer block via `./install.sh --copilot`, `.github/copilot-instructions.md` | not tested |
| ChatGPT, Claude.ai, Gemini, local models | paste `PROMPT.md` | not tested |
| Python tools in `tools/` | CLI | tested 2026-11-23, Python 3.14 (invalidation engine); `tools/prov` needs `rdflib`, not run here |

## What's in here

- **`.claude/skills/`** — four [Claude Code](https://claude.com/claude-code)
  skills implementing the pipeline's mechanical and analytical stages:
  `gate-e-sweeps` (mechanical prose/citation sweeps), `ai-review` (a
  27-section exhaustive pre-submission audit), `source-intake` (the
  pipeline every new source passes through before it's citable), and
  `records-update` (formats and rules for the governance records
  everything else depends on). If you don't use Claude Code, each
  `SKILL.md` still reads as a plain checklist — run its steps by hand or
  wire it into whatever agent/tooling you do use.
- **`docs/`** — the two conventions documents everything else assumes:
  `venue-readiness-checklist.md` (the twelve-condition submit/defer rule)
  and `records-format-conventions.md` (exact formats for the decisions
  log, task ledger, open-questions log, and evidence ledgers).
- **`templates/ROUND_TEMPLATE.md`** — the six-stage cycle (OPEN → BUILD →
  WRITE → INTEGRATE → REVIEW → CLOSE) a round of work runs through.
- **`tools/`** — working, tested Python (stdlib-only except where noted):
  `counters.py` (canonical, deterministic re-derivation of every
  governance number a project cites about itself — never hand-count
  these), `invalidation/` (a dependency-invalidation engine with a CLI: when a
  source, quotation or claim changes, what does that make stale
  downstream, and why; see `tools/invalidation/README.md`),
  `prov/` (PROV-O/PROV-N provenance export and structural validation,
  needs `rdflib`), `multivalue_join.py` (resolving claims that rest on
  more than one piece of evidence), and `mutation_harness/` (a pattern
  for stress-testing your own verification checker against seeded
  faults, so a clean report is evidence the checker works, not evidence
  it never looked hard).
- **`examples/venue-profiles/`** — the mechanism that keeps every skill
  and doc above domain-neutral: venue-specific numbers (word caps,
  anonymization rules, citation style) live in one YAML file per target,
  never hard-coded in a skill.

## The method, in one paragraph

Every claim in the written work links to a piece of evidence; every
piece of evidence links to a source; both live in append-only ledgers
with an explicit verification status. A dependency-invalidation engine
tracks what goes stale when an upstream source or evidence item changes.
Work proceeds in rounds (`templates/ROUND_TEMPLATE.md`): re-analyze
everything, not just what changed since last time; build what's missing
rather than disclosing around it by default; run a mechanical sweep
battery, an adversarial review, and an exhaustive AI-review stage before
the work's owner ever reads a draft; and check a domain-neutral,
twelve-condition readiness rule before calling anything submittable.
Every governance number the work cites about itself is re-derived by one
canonical script, never hand-counted — see `tools/counters.py`'s own
docstring for why that specific discipline exists.

## Quick start

Install the four skills with the shared installer. With no flag it changes
nothing and lists the tools it detects.

```
./install.sh --claude --user             # ~/.claude/skills/<skill>
./install.sh --claude --project DIR      # DIR/.claude/skills/<skill>
./install.sh --agents --project DIR      # DIR/.agents/skills/<skill>  (Codex, Cursor, Gemini CLI)
./install.sh --copilot --project DIR     # pointer block in DIR/.github/copilot-instructions.md
./install.sh --claude --agents --project DIR --uninstall   # remove only what it installed
```

`--copy` copies instead of symlinking; `--dry-run` prints the actions. The
installer never overwrites a path it does not own. For a chat model, paste
`PROMPT.md`.

To start a project from the template by hand:

```
cp -r .claude tools docs templates  /path/to/your-project/
cp examples/venue-profiles/generic-conference-profile.yaml \
   /path/to/your-project/config/venue-profile.yaml
# fill in config/venue-profile.yaml with your actual target's numbers
```

`examples/venue-profiles/README.md` has the full 30-minute walkthrough with
three worked domain examples. For `tools/prov/`, run
`python3 -m pip install -r requirements.txt` in a virtual environment.

## Example: what does one edit make stale?

```
$ bash examples/invalidation-demo/run_demo.sh
== check: what does that edit make STALE?
{
  ...
  "n_transitioned_to_stale": 2,
  "stale_nodes": {
    "q-002": "row_edit on quotation q-002 (fields: exact_quote)",
    "c-002": "upstream change: row_edit on quotation q-002 (fields: exact_quote)"
  },
  ...
}
```

The demo uses an invented two-source project. Editing one quotation marks
that quotation and the claim resting on it `STALE`; nothing else.

Run the tests (offline):

```
python3 -m unittest discover -s tools/invalidation/tests
bash test_install.sh
```

## How it differs

Reference managers (Zotero) store citations but do not track which claims
depend on which quotation. Build systems (make) track file dependencies but
not evidence verification status. This template adds the ledger conventions,
the readiness rule and the invalidation engine on top of whichever writing
and citation tools you already use.

## Limits

- The engine expects a fixed ledger column convention
  (`tools/invalidation/README.md`); other schemas need a field mapping.
- The skills are written as checklists for a human or an agent. They do not
  verify anything by themselves.
- `gate-e-sweeps/SKILL.md` is longer than 300 lines.
- The status table above lists what was and was not tested.

## Related

- [palimnote-skills](https://github.com/hyderhusainarastu/palimnote-skills):
  catalog of agent skills.
- [deep-research-skill](https://github.com/hyderhusainarastu/deep-research-skill):
  multi-source research with checked claims.
- [multi-agent-orchestration-playbook](https://github.com/hyderhusainarastu/multi-agent-orchestration-playbook):
  how to split work across agents.

## Keywords

research methods, academic writing, reproducible research, provenance,
citations, fact-checking, evidence ledger, claim verification, agent skills,
SKILL.md, AGENTS.md, PROV-O, dependency invalidation.

## License

MIT — see `LICENSE`. Contributions welcome; see `CONTRIBUTING.md`.

Part of palimnote-skills - more at https://github.com/hyderhusainarastu
