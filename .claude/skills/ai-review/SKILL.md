---
name: ai-review
description: "Run the recurring AI-Review stage: a full-piece, analysis-only, exhaustive pre-submission audit of a draft that has cleared the mechanical sweeps and an adversarial review, before its owner reads it. Use once per round per target piece."
---

# AI-Review Stage

A full-piece, exhaustive, analysis-only audit that simulates the
skeptical, adversarial scrutiny a real venue's reviewers would apply, plus
a set of checks (quantitative-evidence re-derivation, formal
reconstruction, novelty falsification, reproducibility audit) that most
human reviewers never actually run. Its job is to find what would
otherwise surface for the first time in front of the venue or the piece's
owner.

## 1. Definition and placement

**Position in the cycle:**

```
draft -> mechanical sweep battery (gate-e-sweeps) -> adversarial review -> AI-Review -> owner review -> round close
```

Run the AI-Review stage only after the mechanical sweep battery is clean
and an adversarial review has been completed for the current round.
Reviewing a draft that has not cleared those upstream checks wastes the
AI-Review's exhaustive-search budget on defects a cheaper mechanical pass
would have caught, and buries the substantive findings this stage exists
to surface.

**What it does not replace.** The AI-Review stage does not replace the
adversarial review — that stage tests argument integrity, citation
defects, and the project's own governance rules; the AI-Review stage
tests the piece as a submission, against the standards of its intended
venue, outside reviewers, and the wider field. Nor does it replace the
owner's own read — both remain analysis; only the owner's sign-off closes
the round. A clean AI-Review report grants no ratification; it is an
input the owner reads before deciding whether to ratify.

## 2. Absolute no-edit rule

- Do **not** modify the piece under review.
- Do **not** modify its source markup.
- Do **not** modify its bibliography/reference database.
- Do **not** modify any ledger, manifest, or other project record.
- Do **not** implement any recommendation.
- Do **not** silently "fix" anything found during the review.

Every reviewing agent in this stage — dimension reviewers and the
synthesis agent alike — is **read-only** for the duration of the review.
Inspecting any project artifact (source, ledgers, manifests, logs, version
history, prior review files) is allowed and encouraged; writing to any of
them is not. The stage's only output is the report file specified in §5.
If a shell command is useful for analysis, use only read-only commands; do
not commit anything. This rule binds even when a fix looks trivial or
obviously correct — findings are routed through §7, never applied inline.

## 3. Standard of review

Review as if the piece must survive several unusually demanding reviewers
at once. Adapt this role-cluster list to your actual venue and field:

- a senior reviewer for the target venue, and a reviewer from each
  subcommittee/track the piece could plausibly be assigned to;
- a domain-theory reviewer for the piece's home field(s);
- a methods/statistics/reproducibility reviewer, skeptical by default;
- an evaluation-and-verification reviewer, if the piece makes claims
  about a system's or method's behavior;
- a meta-science / research-integrity reviewer;
- a technical editor, and a reviewer hunting specifically for unsupported
  claims, formulaic prose, and citation mistakes.

The goal is not to be agreeable. **Find weaknesses before the venue's
reviewers find them.** Read the whole piece and build an internal model
of its thesis, contribution claims, evidence structure, and limitations
before critiquing it — do not critique a straw man. **Do not manufacture
objections; every criticism must have a reason**, stated with file:line
or section evidence exactly as the mechanical sweeps require.

## 4. Severity scale

- **S0 — Blocking:** a likely rejection-level issue at the target venue.
- **S1 — Major:** substantially weakens the contribution but not
  independently fatal.
- **S2 — Moderate:** a meaningful improvement, not required for
  submission.
- **S3 — Minor:** polish.

Use this scale everywhere severity is recorded: the findings sections and
the master improvement register (§5.26).

## 5. Deliverable template

One report per run, at a path like `reviews/ai_reviews/<round>_<target>_ai_review_r<N>.md`.
`<N>` increments per re-run against the same target within a round.

The report has 27 numbered sections. Every section must appear in the
output, in order. **A section that does not apply to the piece under
review is marked N/A with one line of justification — it is never
silently omitted.**

1. **Executive verdict** — the strongest defensible version of the
   thesis; what is genuinely strong; what is weakest; present thesis
   versus strongest available thesis; the top 10 changes most likely to
   improve acceptance, ranked.
2. **Argument map** — one-sentence thesis as currently argued;
   contribution map (classify each claimed contribution by type, and
   whether the piece supplies sufficient evidence for that type);
   premise-conclusion reconstruction, with every inferential leap
   flagged; claim-strength ladder for each important claim.
3. **Venue fit and compliance audit** — check the target venue's
   *current* official requirements live (never rely on memorized
   knowledge of a past year's call), covering contribution expectations,
   review criteria, format rules, anonymization, artifact/supplementary
   rules, accessibility, ethics, AI-assistance disclosure,
   reproducibility, and citation requirements. Separate mandatory
   requirements from recommended practice from informal reviewer
   expectation.
4. **Blocking problems (S0)** — every S0 finding, with a short id, the
   exact issue, and the evidence.
5. **Major problems (S1)** — same format, S1 findings.
6. **Missing literature/precedent** — tiered by how much it would change
   the thesis or contribution, from thesis-changing to peripheral;
   confirming, contrary, and adjacent work, not only supporting work;
   for each entry: full citation, credibility, the exact concept/result,
   why it matters, the exact section affected, and whether it supports,
   complicates, or threatens the piece.
7. **Novelty threats table** — for every novelty-flavored claim: piece's
   claim | best prior work found | does it threaten novelty | exact
   overlap | remaining novelty | recommended revised scope. Try to
   falsify the novelty claim; do not protect it.
8. **Citation and factual corrections** — proposition-level: for
   consequential sources, whether the piece accurately characterizes the
   source and whether the cited source actually supports the specific
   proposition attributed to it. Flag incorrect dates, preprints
   described too strongly, causal claims drawn from correlational
   studies, secondary sources standing in for primary ones.
9. **Argument and reasoning problems** — internal tensions, overclaiming
   words ("every", "always", "guarantees"), circularity, unacknowledged
   scope narrowing, qualifiers dropped between sections.
10. **New evidence available without new data collection** — feasible
    checks the project can run against its own records/artifacts (e.g.
    mutation/fault-injection testing of a verification checker,
    historical replay, component ablation, provenance/coverage census,
    clean-environment reproducibility runs). List each as a named, scoped
    check.
11. **Formalization opportunities** — candidate formal objects/relations
    the project's own records could support, and what each would let the
    project prove that prose alone cannot.
12. **Domain-model recommendations** — where applicable; N/A otherwise.
13. **Evaluation-framework recommendations** — where applicable; N/A
    otherwise.
14. **Threat model** — what could make the piece's central claims false,
    and by what mechanism.
15. **Reproducibility audit** — what a third party would need to
    reproduce the reported process/results, and what is currently
    missing.
16. **Quantitative-evidence audit** — **every number the piece states
    about the underlying project** re-derived from the live records as
    they stand at review time, with every mismatch flagged by exact value
    and location. State plainly that these are review-time snapshots, not
    self-updating figures.
17. **Formulaic/AI-generated-prose flags** — passages exhibiting stock
    phrasing, hedge-stacking, empty transitions; cross-reference the
    mechanical sweep's own ornamental-prose findings rather than
    re-deriving them from scratch.
18. **Sentence-level and vocabulary improvements** — concrete, quoted
    before/after examples.
19. **Structural and presentation improvements.**
20. **Material to cut.**
21. **Material to expand.**
22. **Reviewer simulations** — several personas from §3's cluster list,
    each producing a plausible score/recommendation and its stated
    reasons, run independently so the simulations are not anchored on a
    single read.
23. **Strongest plausible rejection** — the single strongest case a
    skeptical senior reviewer could make for rejecting the piece as it
    stands.
24. **Rebuttal-by-design** — for each point in §23, what the owner could
    say or do, distinguishing what is answerable in a rebuttal from what
    requires a revision.
25. **Alternative thesis candidates** — several restated or narrowed
    theses the evidence would actually support, each with what it gains
    and gives up relative to the current thesis.
26. **Master improvement register** — one row per finding: ID, severity,
    section, issue, why it matters, recommended action, data needed,
    effort, expected impact. This is the complete, deduplicated findings
    list; §§4/5/7 are excerpts of it, not separate inventories.
27. **Final priority plan** — before-anything-else / next / if-time-
    permits / do-not-spend-time-on, each referencing register IDs from
    §26. Close with a one-paragraph bottom line.

## 6. Execution vehicles

**(a) In-project multi-agent workflow.** Parallel dimension-reviewer
sub-agents, each independent of the agents that drafted the piece, each
producing one dimension's findings against the template above, feeding a
single synthesis agent that assembles the 27-section report and the
master register. Suggested split: argument/claim-strength, venue/
compliance, literature/novelty, citation/source, quantitative-evidence
(this dimension MUST re-derive figures from live records, never copy the
piece's own stated figures), prose/structure, and reviewer-simulation.
Use a lower-capability model tier for routine dimension work and reserve
your strongest available model for the synthesis agent and for any
dimension where a lower tier has previously produced a false finding.
Reviewing agents must be independent of the drafting agents for the round
under review — an agent that wrote or edited the section it is now asked
to audit does not perform that audit.

**(b) Owner-run external-model review.** The external tool must operate
as a local process reading the local repository, exactly as this
project's own agent tooling does — no project file may be transmitted to
a cloud-hosted service or remote endpoint. If a candidate external
reviewer cannot honor this, it may not be used; route the constraint to
the owner instead. The owner may commission a review from an external
model or tool, preferably from a **different model family** than the one
used for drafting and for the adversarial review — same-model reviewers
are prone to correlated error, so a genuinely independent second opinion
requires a different model family, not just a fresh context window.
Intake an external review as a provenance-documented package:

- the verbatim governing prompt supplied to the external reviewer;
- the complete delivered report;
- a conversation record (requests made, delivered result, scope,
  principal findings);
- a source-and-provenance record: reviewed-file path and checksum, a
  preserved-file table with line/word counts and checksums, a review-time
  quantitative snapshot with the explicit caveat that it is a snapshot
  and must be recomputed before being relied on later, and an integrity
  note confirming no source/bibliography/ledger/project file was edited
  during the review.

Route an intaken external package's findings into §7 (the disposition
protocol) exactly as an in-project run's findings are routed — an
external review is an input to triage, not a pre-ratified verdict.

## 7. Findings-disposition protocol

No AI-Review finding is self-executing. Triage every row of the master
register (§5.26) into exactly one disposition, recorded in a disposition
table appended to (or alongside) the report:

- **MECHANICAL-FIX** — a correction requiring no judgment call (a wrong
  figure corrected against the live record, a citation reformatted, a
  broken cross-reference repaired). Execute within the current round and
  record the executing task via `docs/records-format-conventions.md`'s
  conventions — do not write ledger rows directly outside that process.
- **SUBSTANTIVE** — a finding that requires drafting, research, or
  restructuring work but no policy or scope decision. Schedule as one or
  more numbered round tasks; do not fold into the AI-Review task itself.
- **OWNER-RULED** — a finding that touches thesis framing, scope,
  authorship, venue choice, or any other policy matter reserved to the
  work's owner, not delegable to an agent. Route to the owner; **never
  applied unilaterally**, however clearly correct the finding appears.

When a finding's classification is ambiguous between SUBSTANTIVE and
OWNER-RULED — in particular, any finding that touches the piece's central
claim, title, or framing — default to OWNER-RULED. Do not schedule it as
a round task until the owner has ruled.

The disposition table is mandatory — a report with findings and no
disposition table is incomplete. Columns: Register ID, disposition,
rationale, routed-to, status, discharge evidence.

| Register ID | Disposition | Rationale | Routed-to | Status | Discharge evidence |
|---|---|---|---|---|---|
| I07 | MECHANICAL-FIX | Count in text does not match the live record | records-update task | Open | — |

Findings are tracked to discharge across rounds exactly as adversarial-
review findings are: a disposition is not closed until the corrective
task's evidence exists, and an open disposition from one round's
AI-Review report is a standing item in the next round's blockers list
until discharged or explicitly superseded by a later owner ruling.

## 8. Honesty rules

- Every quantitative claim the AI-Review report makes about the project
  must be grounded in a named file or record — no rederived number
  without its source cited inline.
- No fabricated citations, sources, or statistics, in the report itself
  or attributed to the piece under review. If a claim in the piece cannot
  be traced to a source, say so; do not supply a plausible-looking one.
- Verdicts state what the evidence licenses and no more — do not upgrade
  a §2 claim-strength-ladder finding into report language that reads as a
  higher rung without new evidence.
- Any assertion the reviewing agent could not verify against a project
  artifact or a live external source is labeled **UNVERIFIED** in the
  report text, not presented as settled.
- Sanctioned external access during the venue/literature sections (§§3,
  6, 7) is read-only web search, used to check current, live facts (a
  call for papers, a venue's stated requirements, a candidate prior-art
  piece) — never to fetch or execute code, and never as a substitute for
  reading the piece and project records directly.
