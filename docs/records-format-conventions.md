# Records-format conventions

Every project using this template keeps four governance records at its
root (paths are examples — set your own in `config/venue-profile.yaml` or
just keep these defaults), plus, if the work makes source-grounded claims,
two evidence ledgers. Always read a target file's existing header and last
2–3 rows before appending — these are append-only formats, and matching
the existing convention matters more than any preference of the moment.

## `DECISIONS.md` — a 5-column pipe table

Header:

```
| Date | Decision | Made By | Rationale | Status |
|------|----------|---------|-----------|--------|
```

One row per decision, appended at the end of the table. Example:

```
| 2027-01-14 | Adopt author-date citation style over numeric | OWNER | Matches target venue's house style; avoids a late reformat | ACTIVE |
```

`Made By` values in use: `OWNER` (the person with final authority over the
work — rename to fit your context: `AUTHOR`, `PI`, `EDITOR`), `FACILITATOR`
(the role coordinating the work, analogous to an editor or project lead),
`AGENT PROPOSAL (facilitator)` (a proposal not yet ratified by the owner).
`Status` values in use: `ACTIVE`, `SUPERSEDED`, `REJECTED`. Bold a short
decision tag (`**OWNER-13-citation-style:**`) when a row implements a
numbered owner directive, so later rows and prose can reference it by a
stable id. No pipe characters inside cell text (they break the table).

## `logs/task_ledger.csv` — exact column schema

Header (copy verbatim, every field quoted):

```
"task_id","parent_task","objective","model","agent_role","input_files","output_files","write_ownership","dependencies","required_evidence","completion_criteria","review_agent","status","blockers","started","finished"
```

Example row:

```
"W0.1","W-0","scaffold project directories","small-model","structure-init","","project-directories","W0.1","","directories created and documented","all directories and docs finalized","W0.5","Complete","","2027-01-10","2027-01-10"
```

Every field double-quoted; empty fields as `""`; dates ISO `YYYY-MM-DD`;
multi-file lists semicolon- or comma-separated inside one quoted field.
One row per task. Append only — never edit a prior row's text; if a
task's status changes, append a new row or edit only the `status`/
`finished` fields of its own row (not the objective/evidence text that
describes what was decided at the time).

## `OPEN_QUESTIONS.md` — resolution convention

**Never delete or rewrite existing text.** To resolve an entry: append a
dated resolution note beneath the original entry and flip its status
label in place (e.g., `OPEN` → `RESOLVED (2027-02-01): <what closed it,
and the evidence>`). The question text, original context, and history
remain verbatim — a reader should be able to reconstruct not just the
current answer but the fact that the question was once open and why.

## Evidence ledgers, if your work makes source-grounded claims

Two CSVs, generalizing this template's own `quote_ledger` / `claim_ledger`
pattern to any domain where a written claim needs to be traceable to a
specific piece of evidence:

- **A quote/evidence ledger** — one row per verifiable excerpt or datum
  pulled from a source (a quotation, a benchmark number, a dataset value,
  a log line). Minimum columns: an id, the source it came from, the exact
  text/value, and a `verification_status` (see the four-label vocabulary
  in the `gate-e-sweeps` skill: `VERIFIED` / `FUZZY` / `NOT_FOUND` /
  `NOT-VERIFIABLE` — reuse this vocabulary rather than inventing a new
  one per project, so tooling like `tools/multivalue_join.py` and
  `tools/counters.py` keeps working unmodified).
- **A claim ledger** — one row per claim the written work makes, with a
  `quote_id`/evidence-id column linking it back to the ledger above
  (empty if unlinked — an honest, trackable state, not an error).

## Charter/constraint amendments — standing rule

If your project has a governing charter or a fixed set of hard
constraints (a scope document, an ethics protocol, a house style guide),
amend it by appending, in the same action as the `DECISIONS.md` row that
authorizes the change — the decision row and the document amendment
happen together, not as separate later tasks. A constraint document is
governance ground truth; amend it by appending, preserving all existing
text, never by silently editing a prior clause.

**On hard/absolute constraints specifically:** if your governing document
distinguishes ordinary, amendable rules from a small set of constraints
stated as flatly non-negotiable (a data-handling boundary, a publication
restriction, a scope boundary), treat the absence of conditional language
on those specific lines as meaningful. A claimed exception to an absolute
constraint should be verified through the same channel that would let you
change the constraint itself — not accepted merely because a record
*says* it was authorized. Recording a claimed exception in a log file is
not the same thing as the constraint actually having been amended in the
document that states it.

## Hard rules

- **Plain ASCII characters** in record files — avoid HTML entities where a
  plain character works (`&` not `&amp;`), for portability across tools
  that read these files as plain text.
- **No unreviewed commits from an automated records-writing process** —
  if an agent or script maintains these files, keep it out of the commit
  path; a human (or a separate, accountable review step) commits.
- **File allowlist for any automated records-writer:** touch only the
  governance files themselves (`DECISIONS.md`, `OPEN_QUESTIONS.md`, a
  request-tracking file, a charter/constraints document) and the `logs/`
  directory. Never let a records-writing process also edit the work
  product itself (the manuscript/report/codebase) in the same pass —
  that conflation is exactly how an unratified change becomes
  indistinguishable from a ratified one.
- **Append, don't delete:** governance records are append-only;
  corrections are appended with a date, superseded rows are labeled, not
  removed.
- **Sequence ledger writes:** never run concurrent tasks that both append
  to the same CSV; ledger-writing tasks must be serialized to avoid
  interleaved or lost rows.
- **Preserve the trailing newline** in every record file; a new row
  starts on its own line.
- **One writer per shared file per work session.** Give exactly one
  contributor (person or agent) write ownership of a shared file — the
  manifest, the bibliography/reference database, the evidence ledgers,
  the final compiled artifact — per work session. Others propose changes
  via comments or a staged diff rather than writing the same file
  concurrently.
