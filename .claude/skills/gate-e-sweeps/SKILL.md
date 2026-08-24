---
name: gate-e-sweeps
description: "Run the mandatory mechanical sweeps on the working draft: instruction-leak grep, path-leak grep, stale-tense check, prohibited-claim-strength check, compile/typography gate, quote/evidence verification, banned-construction check. Use before any adversarial review or after any substantive edit."
---

# Mechanical Sweeps

Seven sweeps run against your project's target source glob, which you set
in `config/venue-profile.yaml` (`format.target_source_glob`; defaults to
`manuscript/sections/*.tex` in the template). Two of the sweeps (4 and 7)
have a review tier that requires human judgment on top of the grep — do
not treat either as a blanket hard-fail; every hit gets a ruling, and only
specific rulings block the gate. Do not thin or "simplify" Sweep 6's
witness-resolution logic without re-deriving the reasoning below — it
exists because a naive substring check manufactures false citation-defect
findings that look identical to real ones, and this project's own history
(documented in your git log once you start using this template) is the
best warning against reintroducing that class of bug.

**Scope note.** If your project retires a section from the compiled build
but the file still exists (kept for history, or awaiting a decision), the
sweep's glob will still match it. Record any hit in a retired file as
OUT-OF-BUILD and rule on it separately rather than letting it block the
gate.

## Sweep 1 — Instruction-leak (meta-framing directives in prose)

```
grep -n "framed as\|framed throughout\|described throughout\|per the approach\|per the section" <target_glob>
```

**Pass criterion:** zero hits. Any hit is a leaked writing-process
directive ("we frame X as", "described throughout as") and must be
dropped entirely or converted into a substantive claim anchored to a
cited source. A framing must be enacted through the prose itself, never
announced.

## Sweep 2 — Path-leak (internal process artifacts in prose)

```
grep -n "research/\|logs/\|Sources/\|\.md\|\.csv\|\.json\|\\\\texttt" <target_glob>
```

**Pass criterion:** zero hits in prose. Lines that are comments in your
markup language (LaTeX `%`, Markdown `<!-- -->`) are exempt — inspect
each hit and record comment-line hits as exempt, with file:line, in the
output table. For each prose hit: DELETE (a bare process pointer),
REPLACE with a proper citation of a published source, or REPHRASE to
generic prose (e.g., "a verification ledger" — never an internal
filename). The piece may describe its own verification discipline
generically; it must never name internal file/directory names.

## Sweep 3 — Stale-tense check

```
grep -n "as of this writing" <target_glob>
```

**Pass criterion:** every hit uses present perfect or present tense ("has
not occurred as of this writing", "is X as of this writing"). Simple past
("had not occurred as of this writing") is a FAIL and must be corrected
to present perfect. Inspect the verb phrase at each hit manually — a
regex alone cannot distinguish the two tenses reliably.

## Sweep 4 — Prohibited claim-strength verbs

Two tiers, both run every time, reported as two rows (4a/4b) counting as
one sweep. Populate both word lists in `config/venue-profile.yaml`
(`prose_rules.banned_effect_verbs_hard_fail` /
`banned_effect_verbs_review_tier`) — an empty list means "nothing to
check," not an error.

### 4a — Hard-fail tier

```
grep -n "<pipe-separated list from prose_rules.banned_effect_verbs_hard_fail>" <target_glob>
```

**Pass criterion:** zero hits asserting an empirical effect the evidence
does not support. A hit is acceptable ONLY inside a negating clause
("no claim that the design improves...") or under an explicit
hedge ("designed to..."), and every hit must be manually inspected with
its negating/hedging context quoted in the output table. A bare positive
effect claim not backed by the evidence is a FAIL: no planned or proposed
capability may be presented as empirically demonstrated.

### 4b — Review tier: amplification/capacity-claim candidates

```
grep -n "<pipe-separated list from prose_rules.banned_effect_verbs_review_tier>" <target_glob>
```

**This tier is NOT a blanket hard-fail** — several stems have legitimate
non-claim uses (a cited work's own title, a direct quotation reporting
what a cited study found about its own subjects). Rule every hit as one
of:

- **`CITATION-TITLE`** — inside or adjacent to a cited title/key.
- **`QUOTED-SOURCE`** — inside a direct quotation from a cited source,
  reporting the source's own wording, not the piece's own claim.
- **`LITERATURE-REPORT`** — describing what a cited study found about its
  own subjects, not a claim the piece itself is making.
- **`GENUINE-VIOLATION`** — none of the above: a bare, un-hedged,
  un-quoted claim that the work itself has the amplifying/enhancing
  effect the word names. This FAILS and blocks the gate, exactly like a
  4a hit.

Only `GENUINE-VIOLATION` fails the sweep; the other three rulings are
review-only. Do not filter these mechanically before a human sees them —
a genuine violation can sit one clause away from a citation, and an
automatic proximity filter will swallow it silently.

## Sweep 5 — Compile + typography gate

Compile the piece with its actual toolchain (set in
`config/venue-profile.yaml`, `format.compile_command`):

```
<compile_command> 2>&1 | grep -i "overfull\|error"
```

**Pass criteria:**
- Compile completes with no errors, no undefined citations, no orphan
  bibliography entries.
- Zero overfull-line/box warnings attributable to internal-path
  references or unjustified monospace content.
- Any remaining overfull line beyond your toolchain's own significant
  threshold requires a prose reword — flag it; do not force-break with
  hacks. A small overfull may be recorded as MINOR and deferred to a
  style pass.
- URLs/DOIs use a proper link/URL macro so they break cleanly.

## Sweep 6 — Quote/evidence verification

**Why this sweep resolves a *file*, not just a source id.** A mechanical
substring check against the wrong extraction of a source — a
column-interleaved OCR pass, a stale re-scan, a superseded rebuild —
returns false `NOT_FOUND`/`FUZZY` verdicts that look exactly like citation
defects but are not. **A `NOT_FOUND`/`FUZZY` result from a substring check
is evidence about the extraction, not about the citation, until it has
been re-run against the best available extraction of that source.**
Conflating the two produces exactly the class of false severe finding
this discipline exists to prevent.

### 6.1 Resolve the source, then the file, before checking the quote

**A citation key is not a source-file slug.** Your citation system's key
for a source and the filename/id your evidence store uses for it are not
always the same string — a sweep that assumes they match will report
false `NOT_FOUND` verdicts on quotations that verify perfectly well.
Build the candidate resolution list in this order:

1. **Each citation key adjacent to the quoted span**, mapped to a source
   id via your bibliography's own container-title field, if present (for
   an edited-volume chapter, a conference paper, or any "the document I
   hold is the container, not just the cited unit" case) — see the
   "container field" note below.
2. **Then** the source id carried by the matching row of your evidence
   ledger. Match the quoted span against the ledger's `exact_quote`
   field, in either containment direction, and take the row with the
   **longest** overlap.

**The container-field rule, and why it must fall through rather than
stop.** For a chapter or a contribution to an edited volume, the document
you actually hold and extracted is the *volume*, so resolve on the
citation's container-title field first, matching it against your evidence
store's own title field. But a container field does not mean the same
thing for every entry type: for a conference paper it usually names the
*proceedings*, not a document you hold — you hold the paper itself, filed
under its own id. If the container-field match fails, **do not treat that
as the end of the search** — fall through to trying the citation key
itself as an id, then the entry's own title, and only then a
last-resort author-and-year match. A ladder that stops at a guaranteed-to-
fail container match for every proceedings-published paper will report a
false failure on every quotation from a conference paper in your corpus.

**Why author-and-year cannot come first.** Two different works edited or
authored by the identical author list in the identical year are
indistinguishable by an author+year test alone — it will silently pick
whichever entry your store happens to list first. Try the identity-based
steps (container/id/title match) before ever falling back to
author+year, and always record which candidate produced the resolution,
so a reviewer can see and distrust an author-fallback verdict on sight.

**Record the resolved id AND the resolving field for every span** (e.g.
`some-source-id (via container-title)`). A verdict whose witness was
chosen by the weakest fallback is a verdict a reviewer must be able to
see and distrust.

Then, for each candidate source id, in order: list every extraction file
matching that id; exclude anything explicitly marked rejected/superseded;
among what remains, prefer (in order) a from-scratch corpus-wide
re-extraction pass over an ad hoc single-source rebuild over the
originally stored extraction — the originally stored extraction is the
**last** resort, not the first, precisely because it is the one most
likely to carry an un-diagnosed extraction defect.

**Hard overrides above the ordering:**
- **SOURCE-DEFECT** (no sound extraction exists by any method tried — a
  damaged scan, an un-capturable binding-gutter shadow): a quotation
  citing such a source that fails to match is `NOT-VERIFIABLE`, never
  `NOT_FOUND`. A quotation that *does* match is `VERIFIED` regardless —
  a match is still evidence.
- **EXTRACTION-GAP** (a source is flagged as having a defective
  extraction, with no corrected file yet on disk): if resolution lands on
  the flagged-defective file and the quote fails to verify, report
  `NOT-VERIFIABLE` and flag a follow-up extraction pass — never a
  `NOT_FOUND` that would read as a citation defect.

### 6.2 Normalization, elision, and running the check

**Decompose to base characters before stripping punctuation.** A
normalizer that strips non-alphanumeric characters without first
decomposing precomposed/ligature characters (accented letters, `fi`/`fl`
ligatures) will silently destroy real words on one side of the
comparison and manufacture a false `NOT_FOUND`. Decompose (NFKD), strip
markup entities, lowercase, then delete everything that is not
`[a-z0-9]`, on **both** the quotation and the witness text. Compare by
substring; fall back to a sliding-window similarity ratio at a threshold
around 0.95.

**An elided quotation ("...") is a sequence of spans, matched in order —
never one substring.** Split the span on its ellipsis marker, then
require each segment to occur in the witness text after the end of the
previous one. Require at least one segment to be reasonably long (around
15 normalized characters) for the result to count as a real test.

**Order of operations matters, and it is the whole of a well-known class
of bug:** protect elision markers with a placeholder *before* any markup
macro-stripping pass runs, or a general macro/tag stripper will delete
the ellipsis silently along with everything else, leaving the
split-on-ellipsis test with nothing to split on and reporting a false
`NOT_FOUND` on a verbatim-correct quotation. Restore accent/escape
sequences to their base letters before your normalizer's own
decomposition step handles the rest.

### 6.3 Output contract — four labels, never merged into one FAIL bucket

- **`VERIFIED`** — exact substring match (similarity above roughly 0.99)
  against the resolved witness file.
- **`FUZZY`** — a near-match at similarity in a narrow band just below
  exact (state your project's exact cutoffs in one place and keep the
  `VERIFIED`/`FUZZY` bands non-overlapping — an ambiguous shared boundary
  is a known defect class to watch for). This **is** a citation-integrity
  candidate.
- **`NOT_FOUND`** — no match against the best available extraction. This
  **is** a citation-integrity candidate.
- **`NOT-VERIFIABLE`** — the quotation could not be checked because the
  *extraction* is broken or missing (the §6.1 hard-override cases). This
  is **never** a citation-integrity finding on its own; state the reason
  every time this label is used.

A span too short for a substring test to mean anything (a single common
word) is `TOO-SHORT`: present, but not a pass and not a failure.

**Pass criterion:** every direct quotation/evidentiary excerpt in the
piece resolves to `VERIFIED` under §6.1–6.2. Any `FUZZY` or `NOT_FOUND`
verdict is a FAIL for that item and must be logged to your open-questions
record, never silently used. Any `NOT-VERIFIABLE` verdict blocks the gate
exactly as a FAIL does, but must be reported separately with its reason,
so a reviewer does not read it as a citation defect.

## Sweep 7 — Banned constructions

Two lists come from `config/venue-profile.yaml`
(`prose_rules.banned_ornamental_phrases`) plus two sentence-length checks
(`max_sentence_length_soft` / `_hard`), reported as tiers 7a/7b/7c
counting as one sweep.

### 7a — Define-at-first-use family

```
grep -nEi "defined at first (technical )?use|are each defined|is defined at|at first use|defined below|explained below|described more fully (later|below)|see the section on|discussed below|as (defined|described) below" <target_glob>
```

**Pass criterion:** zero hits, and additionally no footnote/aside whose
entire content is a bare cross-reference — check by reading every short
footnote. A footnote must be self-sufficient: it carries the definition
or concession itself, and may then point to where the term is developed
at length.

### 7b — Section-list roadmaps

```
grep -nEi "what follows takes up|the remainder of this (paper|article|section)|this paper proceeds as follows|proceeds in [a-z]+ parts|and closes with|then turns to|the sections below|in the sections? that follows?" <target_glob>
```

**Pass criterion:** zero hits, and no sentence enumerating three or more
section titles in sequence. The replacement for a deleted roadmap is
nothing, by default — a transition that does argumentative work (stating
what the next stretch must establish) is fine; one that just names the
next heading is not.

### 7c — Ornamental prose and sentence length

```
grep -nEi "<pipe-separated list from prose_rules.banned_ornamental_phrases>" <target_glob>
```

Plus, on prose with markup stripped: every sentence over the soft length
threshold is reported and needs a reason a reader would accept; every
sentence over the hard threshold is a defect and must be split (never
joined by a semicolon); every sentence opening with a subordinate clause
longer than its main clause is a hit.

**Review tier, ruled like Sweep 4b.** Rule every hit as:

- **`QUOTED-SOURCE`** — the cited source's own wording; never adjust
  quoted matter to the piece's voice.
- **`CITATION-TITLE`** — inside or adjacent to a cited title.
- **`LOAD-BEARING`** — the word is doing real work a plainer word would
  not do (a technical term of art in your field). State what the word
  does.
- **`GENUINE-VIOLATION`** — none of the above. This FAILS and blocks the
  gate.

**The length-cutting rule binds the repair, not just the ruling.**
Concision is never achieved by dropping a concession, a bound, a
counter-argument, or a citation. A section that must lose length loses
ornament, transition, restatement, and hedging — in that order — and
never evidence.

## Required output format

Report results as a per-check PASS/FAIL table; every hit — passing or
failing — carries file:line evidence.

| # | Sweep | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Instruction-leak | PASS | zero hits |
| 2 | Path-leak | PASS | 2 hits, both comment lines — exempt |
| 3 | Tense | PASS | 1 hit, present perfect |
| 4a | Prohibited verbs (hard-fail) | PASS | 4 hits, all in negating clauses — quote each clause |
| 4b | Prohibited verbs (review) | PASS | 7 hits, rulings: CITATION-TITLE x2, QUOTED-SOURCE x1, LITERATURE-REPORT x4 — zero GENUINE-VIOLATION |
| 5 | Compile/typography | FAIL | one overfull line flagged for reword |
| 6 | Quotes/evidence | PASS | N spans: VERIFIED/TOO-SHORT/FUZZY/NOT_FOUND/NOT-VERIFIABLE counts — name resolved id, resolving field, and witness file per span |
| 7a | Define-at-first-use | PASS | zero grep hits; footnotes read, none purely cross-referential |
| 7b | Section-list roadmap | PASS | zero grep hits; closing paragraphs read, no heading enumeration |
| 7c | Ornamental prose | PASS | 1 hit ruled QUOTED-SOURCE; sentences over threshold reasoned or split |

All seven sweeps are gate-blocking: the gate cannot pass until every
sweep passes or every residual hit is explicitly ruled exempt with quoted
evidence. Sweeps 4 and 7 each count as one sweep toward that total but
report multiple rows; only a `GENUINE-VIOLATION` ruling blocks their
review tiers.

**One standing instruction, because getting this wrong once is expensive
enough to guard against explicitly.** A result a sweep *could not check*
is not the same finding as a result the sweep checked and found wrong.
`NOT-VERIFIABLE` is not `NOT_FOUND`; a `QUOTED-SOURCE` ruling is not a
violation; a mis-resolved witness is a fact about the resolver, not about
the citation. When a sweep reports a failure, establish which of the two
it is **before** writing it up, and say which in the report.
