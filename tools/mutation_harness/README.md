# Mutation-harness pattern

A verification checker (a quote/evidence verifier, a citation checker, a
fact-checking pass) that reports zero problems is not, by itself,
evidence the checker works. It might just never have been given a
problem to find. **Mutation testing** answers that: seed known-wrong
mutations into a copy of your records, run the checker against them, and
measure what fraction it actually catches. A clean report on real data is
credible only alongside a mutation score on seeded faults — the same
logic as software mutation testing, applied to a verification pipeline
instead of a codebase.

This directory ships a **pattern**, not a drop-in production tool: a
generalized mutation catalogue and harness (`mutation_harness.py`) with
eight representative mutation classes and a toy example checker, plus a
scoring report. Real projects should extend the catalogue with classes
specific to their own domain (see "Extending the catalogue" below) and
swap in their own checker.

## The eight classes shipped here

Two families, matching how you generate a mutant:

**Sampled from real records** (draw a real row, mutate it — a genuine
capability test of your checker against realistic-looking faults):

1. `fabricated_evidence` — replace a genuine excerpt with plausible but
   invented text.
2. `truncation` — cut an excerpt short in a way that changes its meaning.
3. `polarity_reversal` — negate or flip the sense of a claim/excerpt.
4. `omitted_source_item` — drop a source/evidence item the checker should
   have flagged as missing.

**Hand-built** (small, disclosed, non-random fixtures — some fault
shapes are rare enough in real data that a random draw would not
reliably produce the exact topology needed):

5. `attribution_error` — attach a real excerpt to the wrong source.
6. `citation_retained_claim_changed` — keep the citation, change what the
   claim actually asserts (the checker must catch a mismatch between
   citation and claim content, not just confirm the citation resolves).
7. `stale_status` — a verification status that no longer matches the
   underlying evidence (e.g., marked `VERIFIED` after the source text it
   pointed to was corrected).
8. `contradictory_evidence` — two evidence items that cannot both be true
   attached to the same claim.

## Running it

```
python3 mutation_harness.py --smoke            # n=2/class self-test, fast
python3 mutation_harness.py --n-per-class 30   # a fuller run
```

Outputs `<out_dir>/mutation_results.json` and `.md`: per-mutant pass/fail
against the example checker, and a per-class detection rate. **A checker
that catches 100% of a mutation suite it was tuned against is a weaker
result than a checker that catches a stated majority of a suite it never
saw during development** — disclose which is which. If any class's
detection rate is a documented, known blind spot (a real capability
your checker genuinely lacks, e.g. this template's own worked example
below), report that plainly rather than omitting the class from the
denominator.

## Extending the catalogue

Add a domain-specific mutation class by writing a function that takes a
real row from your evidence/claim store and a source of randomness, and
returns a `Mutant` (see the dataclass in `mutation_harness.py`) carrying
the mutated content plus a `ground_truth_detectable: True` flag and a
plain-language description of what was changed. Register it in
`MUTATION_CLASSES`. Keep every mutation deterministic given a fixed seed
(`PROTOCOL_SEED` below) so a reported mutation score is reproducible.

## Honesty rules for reporting a mutation score

- State the seed and the exact `n` per class used.
- Report every class's detection rate individually, not just an
  aggregate — an aggregate can hide a class at 0%.
- Disclose any class your checker is known not to catch, rather than
  quietly dropping it from the suite.
- Never tune the checker against the exact mutation set you are about to
  score it on and then report that score as a generalization claim —
  hold out at least one class, or use a fresh random seed, for the score
  you actually publish.
