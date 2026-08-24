# Contributing

Thanks for considering a contribution to this template.

## What kinds of contributions are useful

- **New venue profiles** (`examples/venue-profiles/`): if you've used this
  template for a real target — a specific journal, a specific
  conference, a grant program, an internal review process — a sanitized
  profile for it (numbers and rules only, no content from the actual
  work you produced) helps the next person starting from scratch.
- **New domain examples**: the quickstart currently covers a humanities
  article, a biology preprint, and a software-engineering report. A
  worked sketch for another domain (law, journalism, economics, clinical
  research) that shows how the same twelve conditions and four skills
  apply is welcome.
- **New mutation classes** for `tools/mutation_harness/`: domain-specific
  fault shapes your project's verification checker needs to be tested
  against.
- **Bug reports and fixes** in `tools/`: these are working, tested Python;
  if you find a case the tests don't cover, a failing test alongside the
  fix is the most useful form of report.
- **Tightening the skills**: if you find a place where a skill still
  assumes something venue- or domain-specific that should instead be a
  venue-profile parameter, that's a real gap — please open an issue or a
  PR moving it out.

## What this project asks contributors to avoid

- Please do not add content, examples, or fixtures drawn from real,
  unpublished, or confidential work — including your own. Sanitize
  before contributing, the same way this template itself was built by
  generalizing away everything specific to the project it came from.
- Please do not hard-code a specific venue's numbers into a skill file —
  that defeats the point of the venue-profile mechanism. If a rule
  genuinely can't be parameterized, say so explicitly in a comment rather
  than silently baking in a default.

## How to propose a change

1. Open an issue describing the gap or the addition, if it's not a small
   fix.
2. For code changes in `tools/`: include or update tests
   (`python3 -m unittest` for the invalidation engine; a smoke run for
   `counters.py`, `multivalue_join.py`, and `mutation_harness.py` is
   sufficient given their I/O-heavy nature — show the transcript in your
   PR description).
3. For skill/doc changes: state which venue-profile field(s), if any,
   the change should have been reading from instead of a hard-coded
   value.

No CLA, no special process — a clear PR description of what changed and
why is enough.
