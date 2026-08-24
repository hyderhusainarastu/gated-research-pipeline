# Standing round template

Every improvement round on a piece of evidence-grounded work runs these
six stages, in order. A "round" is one full pass from re-reading the
current state through to a submit/defer decision — run it repeatedly
until the venue-readiness checklist (`docs/venue-readiness-checklist.md`)
reads all-MET. The template is stage names and what each stage is
responsible for; how long a round takes and how many people/agents work
each stage is up to you.

**Standing principle: every sentence is re-analyzed every round, not just
new material.** A round is not "process the diff since last time" — it is
"re-justify the whole piece against the current state of the evidence,
the current framing, and the current rulings." Stale sentences survive
specifically because incremental review skips them.

## OPEN (parallel)

Run these five checks in parallel; none depends on another's output.

1. **Capability-gap harvest.** For every claim about what a system,
   method, or process can do, check it against its actual current
   behavior. Build a table of gaps found, and for each: build the missing
   capability, or explicitly disclose the gap in the piece. Building is
   the default; disclosing-without-building is the exception that needs a
   stated reason.
2. **Demonstrability sweep.** Classify every hedge, concession, or
   qualified claim in the current draft into one of four buckets:
   **(A)** cannot be demonstrated with available resources — state it
   plainly as a limitation; **(B)** evidence for it already exists
   somewhere in the project's own records — update the sentence to cite
   it; **(C)** a cheap demonstration is feasible — specify it as a task;
   **(D)** requires an action only the work's owner can take (a ruling, a
   resource commitment) — route it to them.
3. **Sentence-currency re-analysis.** Re-read every sentence of every
   section against the *current* framing, comparator set, evidence base,
   and prior rulings — not against what was true when the sentence was
   written. A sentence that was accurate two rounds ago but has since been
   overtaken (a comparator system changed, a number was recomputed, a
   claim was narrowed elsewhere) gets replacement text this round, not a
   note to fix it "eventually."
4. **Literature/precedent currency sweep.** Re-check that the nearest
   prior work and comparator set are still the nearest — new work gets
   published continuously; a comparison that was exhaustive last round can
   be stale this round. Pair with a citation-completeness audit: does
   every load-bearing claim actually have a citation, and does every
   citation actually support the specific claim it is attached to.
5. **Deferred-backlog resurfacing.** Re-surface every item deferred in a
   prior round that has not been explicitly closed or re-deferred with a
   reason. Spot-audit a sample of past rounds' review-and-fix transcripts
   (a sample of roughly a dozen to twenty items is a reasonable default)
   to catch drift between what a prior round claimed to have fixed and
   what the record actually shows.

## BUILD

Execute the capability-gap harvest's build items and the demonstrability
sweep's class-C items, under a version-pinned protocol if the build
produces anything empirical (seeded-fault tests, benchmark runs) — pin
the protocol version before running, not after seeing results. Maintain
whatever correspondence audit ties the written piece's claims to the
underlying implementation/data, so the two cannot silently drift apart.

## WRITE

Apply: the demonstrability sweep's class-B sentence fixes; the
sentence-currency re-analysis's replacement text; any new evidence the
BUILD stage produced. Prefer present-tense description of the current
method; keep historical narrative (what changed between rounds, why)
confined to a dedicated case-study or changelog section rather than
scattered through the main argument. If the piece includes a
self-application or worked-example table, extend it with this round's
dated events rather than rewriting prior rows.

## INTEGRATE

One person (or one agent, per your one-writer-per-shared-file rule) owns
the integration pass — merging BUILD and WRITE output into the single
current draft. Re-derive every governance/status counter the piece cites
about itself using the canonical tool (`tools/counters.py`), never by
hand. Enforce length/format discipline against the venue profile. Freeze
a versioned snapshot of the draft at the end of this stage.

## REVIEW

Run, in whatever combination your project's skills support:

- an adversarial review (an agent or reviewer whose job is to find the
  strongest case against the piece, not to be agreeable);
- a cold-read framing check — someone reading only the final artifact
  (e.g. the compiled PDF), with no access to internal process records,
  checking that the piece stands alone;
- the AI-review stage (see the `ai-review` skill) if you use it;
- an audience/reviewer-panel simulation, if useful for your venue;
- the mechanical sweep battery (see the `gate-e-sweeps` skill);
- a supplementary/artifact-package audit — a fresh unpack-and-verify run
  against a documented verify command, not the original build
  environment.

## CLOSE

1. **Disposition** every finding from REVIEW, with coverage checked (no
   finding silently dropped).
2. **Fix**, grouped by owner, in the same pass — a records-integrity
   finding (a stale counter, a broken cross-reference) gets fixed
   immediately, never queued for "next round." Verification transcripts
   for every fix are part of the fix, not a follow-up.
3. **Freeze** a second versioned snapshot reflecting the fixes.
4. **Independent closure check** — someone who did not do the fixing
   confirms the disposition table is actually discharged.
5. **Run the venue-readiness checklist** (`docs/venue-readiness-
   checklist.md`) against the frozen snapshot: submit or defer.
6. **Round report and handoff** — update whatever persistent memory/state
   file carries context to the next round (a project memory file, a
   status dashboard, a handoff note), so a fresh round can start with full
   context. This stage does not include committing the work to version
   control — that is a separate, explicit action outside the template.
