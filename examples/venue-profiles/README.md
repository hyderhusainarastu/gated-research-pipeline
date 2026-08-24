# Venue profiles — quickstart

A **venue profile** is a small YAML file that holds every venue-specific
number and rule this template's skills need: word caps, anonymization
requirements, accessibility rules, a citation style, banned phrases, and so
on. The skills themselves (`gate-e-sweeps`, `ai-review`) never hard-code a
venue's numbers — they read a profile. This is what makes the same skill
set usable for a conference paper, a journal submission, a grant report, or
an internal audit.

`generic-conference-profile.yaml` in this directory is the **template** —
every field present, every value a placeholder or a safe default. Copy it
into your own project as `config/venue-profile.yaml` and fill it in for
whatever you are actually producing.

## 30-minute quickstart: initializing a fresh project

These steps work whether your "manuscript" is a conference paper, a lab
report, a policy brief, or a piece of long-form journalism — anything
where you make claims, need to trace them to sources, and want a defined
readiness bar before you call the piece done.

1. **Copy this template into a new project directory.**
   ```
   cp -r verification-gated-pipeline/.claude  your-project/.claude
   cp -r verification-gated-pipeline/tools    your-project/tools
   cp -r verification-gated-pipeline/docs     your-project/docs
   cp -r verification-gated-pipeline/templates your-project/templates
   cp verification-gated-pipeline/examples/venue-profiles/generic-conference-profile.yaml \
      your-project/config/venue-profile.yaml
   ```
2. **Fill in `config/venue-profile.yaml`** with your actual target's
   numbers — word cap, citation style, anonymization rule, whatever
   applies. Leave irrelevant sections at their template defaults (empty
   lists, `false`, `null`); the tooling treats an unset rule as "not
   checked," never as an error.
3. **Set up your records.** Create the four files `docs/records-format-
   conventions.md` describes: a decisions log, a task ledger, an open-
   questions log, and — if your work makes source-grounded claims — a
   quote ledger and a claim ledger. Empty files with just the header row
   are enough to start.
4. **Point `tools/counters.py` at your project root** (`--root
   /path/to/your-project`) and confirm it runs cleanly against your empty
   ledgers — this is your baseline snapshot, re-run it after every work
   session.
5. **Install the skills.** If you use Claude Code, the `.claude/skills/`
   directory is picked up automatically once it sits at your project
   root — each `SKILL.md` describes when to invoke it. If you use a
   different agent or work by hand, read each `SKILL.md` as a checklist
   and run its steps yourself.
6. **Run the round template** (`templates/ROUND_TEMPLATE.md`) once, even
   in miniature, before your first real work session — it is meant to be
   run every cycle, and running it once on a near-empty project is the
   fastest way to see what each stage actually asks for.
7. **Before you call anything final**, work through `docs/venue-
   readiness-checklist.md`'s twelve conditions against your filled-in
   profile. Submit only when all twelve are MET, or DEFER with the unmet
   conditions named — the checklist itself is domain-neutral; your
   profile supplies the numbers.

## Three worked examples

The same twelve-condition checklist and the same four skills apply to
domains that look nothing alike. These sketches show how the *numbers*
change while the *method* does not.

### Example A — a humanities research article

A scholar is writing an argument-driven article that leans on close
reading of primary texts plus a secondary-literature review, targeting a
peer-reviewed humanities journal.

- **Venue profile:** citation style `footnote` (Chicago/MLA-family);
  `hard_cap_word_count` set to the journal's stated limit; anonymization
  `required: true` for double-blind review; no artifact/reproduction
  package (there is no code, but the profile can still require a
  quotation-verification ledger as this project's own `quote_ledger`
  concept generalizes to any primary-source quotation).
- **What source-intake tracks:** editions of primary texts, translations
  used, secondary scholarship, with the citability rule distinguishing
  peer-reviewed monographs from trade books.
- **What gate-e-sweeps checks:** every direct quotation from a primary or
  secondary source resolves against the actual page image or transcription
  on file (Sweep 6's "resolve the file, not just the author" logic applies
  unchanged — a chapter's held document is still the volume it was
  published in, not the chapter alone).

### Example B — a biology preprint with a wet-lab dataset

A lab is preparing a preprint reporting an experimental result, to be
followed by journal submission.

- **Venue profile:** `artifact_and_reproducibility.supplementary_package_
  required: true`; `data_availability_statement_required: true`;
  `reproduction_package_standard` states what "reproduces cleanly" means
  here — e.g., a fresh environment can re-run the analysis scripts against
  the deposited raw data and regenerate the reported figures/statistics
  bit-for-bit or within a stated numerical tolerance.
- **What source-intake tracks:** cited prior studies (the "sources"), plus
  the lab's own raw datasets and analysis scripts as first-class tracked
  artifacts with their own provenance records.
- **What the invalidation engine is for:** if a raw dataset file is
  corrected after a figure was generated from it, every downstream
  claim/figure that depended on that dataset is marked STALE until
  re-verified — the same dependency-propagation problem this template's
  invalidation engine solves for a citation ledger, applied to a data
  pipeline instead.

### Example C — a software-engineering technical report

A team is writing an internal (or public) report on a system's design and
evaluation, to be reviewed before a public blog post or a technical
publication.

- **Venue profile:** `accessibility.full_document_tagging_required` per
  the publishing platform's standard; `ai_assistance_disclosure_required:
  true` if AI tools were used in drafting or in the system itself;
  `banned_effect_verbs_hard_fail` populated with the marketing-language
  words the team wants to keep out of a report that claims to be an
  engineering evaluation, not marketing copy.
- **What source-intake tracks:** cited benchmarks, prior systems compared
  against, and internal design documents referenced as sources of claims.
  Every quantitative claim about the system under report is a `claim`
  linked to a `quote`/artifact the way this template already models: a
  benchmark number, a log excerpt, a test-run output.
- **What the mutation-harness pattern is for:** stress-testing whatever
  automated verification checker the report leans on (a citation checker,
  a benchmark-number checker) against seeded faults, so a clean report is
  evidence the checker actually works, not evidence it never looked hard.
