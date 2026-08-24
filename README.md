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
  these), `invalidation/` (a dependency-invalidation engine: when a
  source changes, what does that make stale downstream, and why),
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

## Quickstart

See `examples/venue-profiles/README.md` for the full 30-minute walkthrough
of initializing a fresh project from this template, including three
worked domain examples. In short:

```
cp -r .claude tools docs templates  /path/to/your-project/
cp examples/venue-profiles/generic-conference-profile.yaml \
   /path/to/your-project/config/venue-profile.yaml
# fill in config/venue-profile.yaml with your actual target's numbers
```

## License

MIT — see `LICENSE`. Contributions welcome; see `CONTRIBUTING.md`.
