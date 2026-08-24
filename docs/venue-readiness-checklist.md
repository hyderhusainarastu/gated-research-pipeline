# Venue-readiness checklist (submit/defer rule)

A twelve-condition hard rule for deciding whether a piece of work is ready
to submit to its target venue, or should be deferred for another round.
The rule is domain-neutral by design: every condition names a property a
serious piece of evidence-grounded writing should have, regardless of
whether the venue is an academic conference, a journal, a grant report, or
a public technical report. The **numbers** (word caps, format rules,
disclosure requirements) live in your venue profile
(`examples/venue-profiles/`), never in this checklist.

## How to use it

Run this checklist once per round, after the mechanical sweeps and the
adversarial/AI-review stages have already run (this checklist assumes
their output exists — it does not re-run them). For each of the twelve
conditions, record one of:

- **MET** — with the evidence that established it (a file, a re-run
  command's output, a specific check), not an assertion.
- **NOT MET** — with what specifically is missing or wrong.
- **N/A** — only when a condition genuinely does not apply to this kind of
  work (state why); never used to avoid an inconvenient check.

**Result:** submit only when all twelve conditions read MET (or
justified N/A). Any NOT MET condition means DEFER, with the unmet
condition(s) named as the reason. A partial pass is not a pass — this
mirrors how a real venue's desk-reject checks work: one hard failure blocks
regardless of how strong everything else is.

**Verification-transcript rule.** Every MET/NOT MET verdict must be backed
by a command this round's own author actually ran and a transcript of its
actual output — never accepted on a prior report's word alone. If a prior
round already established a condition and nothing has changed, re-run the
check anyway; state that the result matches the prior round's, and show
the fresh transcript. A condition that "should still be true" and was not
re-checked is not MET.

## The twelve conditions

1. **Identity and contribution unambiguous.** The piece states, in one
   place, what it is claiming to contribute, and that statement has not
   drifted from what the rest of the piece actually argues or reports.
2. **Contract/registry and implementation agree.** If the work makes
   claims about what a system, method, or protocol does, the documented
   specification and the actual implementation/behavior match — check
   this directly, not by re-reading the documentation alone.
3. **Central results regenerate from frozen raw inputs.** Whatever
   quantitative or empirical claims anchor the piece can be regenerated
   from a frozen, hash-verified copy of the raw inputs, not merely
   re-asserted from a prior run's output file. State the exact
   regeneration command and its checksum evidence.
4. **Seeded-fault and invalidation tests have valid ground truth and
   complete denominators.** If the work reports a checker's or a
   verification process's accuracy (e.g., "the citation checker caught
   38 of 51 seeded faults"), the seeded-fault set and its ground-truth
   labels are documented and complete — no undisclosed exclusions, no
   denominator that quietly shrank between rounds.
5. **Semantic claims have independent labels OR have been removed.** Any
   claim requiring a human or model judgment call to verify (as opposed
   to a mechanical check) carries its own independent verification label,
   or the claim has been narrowed/removed to only what a mechanical check
   can support.
6. **Nearest literature/prior work directly and accurately compared.**
   The closest existing work, system, or precedent is named, its actual
   claims and scope are represented accurately (not straw-manned or
   under-cited), and the piece's own novelty claim is stated relative to
   it, not merely asserted in isolation.
7. **No central claim exceeds its evidence level.** Every load-bearing
   claim sits at the strength its actual evidence supports — existence,
   feasibility, demonstrated correctness, reliability, robustness,
   superiority, or generalizability are different rungs, and a claim must
   not borrow a higher rung's confidence than its evidence earns.
8. **Length compliant and defensible.** The piece is under the venue's
   hard cap by the venue's own authoritative counting method (state which
   method, and re-run it fresh — do not trust a stale count). If it
   exceeds the venue's encouraged (soft) length, a length-justification
   note names what could be cut and why it was kept, so the decision is
   visible rather than assumed.
9. **The piece stands alone.** A reader with no access to the project's
   internal records, prior drafts, or supplementary material can still
   follow the argument and evaluate the evidence from the piece itself.
   Anything the piece leans on that lives outside itself is either
   included, cited, or explicitly disclosed as external and non-load-
   bearing.
10. **Reproduction/supplementary package works to its declared
    standard.** If the venue requires or the work offers a supplementary
    package (code, data, an artifact bundle), a fresh unpack-and-verify
    run — not the original build environment — actually reproduces what
    the package's own README claims it reproduces.
11. **Final-artifact and metadata checks pass.** Whatever the venue's
    format requires — a compiled PDF, a formatted manuscript, tables and
    figures rendering correctly, a supplementary bundle, disclosure
    statements, anonymization, accessibility tagging, submission
    metadata — all pass a fresh mechanical check, not a memory of having
    passed before.
12. **No submission-critical review finding open.** Every open finding
    from the adversarial review and the AI-review stage is either
    resolved with evidence, or explicitly routed to the person with
    authority to rule on it (see `docs/records-format-conventions.md`'s
    AUTHOR-RULED disposition) and that ruling has actually been made —
    not merely scheduled. Zero open S0/blocking-class findings is the
    floor; a nonzero count of lower-severity open items should be stated
    and reasoned about, not silently ignored.

## Worked example of the output format

| # | Condition | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Identity and contribution unambiguous | MET | Title/abstract cross-checked against §§2–7 this round; no contradicting finding. |
| 8 | Length compliant and defensible | MET | Fresh word-count run: 10,860 words against a 12,000 hard cap (1,140 under) and an 8,000 encouraged length (justification note names two appendices as the first cut candidates if further trimming is required). |
| 10 | Reproduction package works to its declared standard | NOT MET | Fresh unzip + `sha256sum -c manifest.sha256`: 2 of 41 files fail checksum — package predates the latest source fix. |
| 12 | No submission-critical review finding open | NOT MET | 0 open S0 findings; 3 open S1 findings with no disposition recorded yet. |

**Result:** DEFER — conditions 10 and 12 NOT MET.
