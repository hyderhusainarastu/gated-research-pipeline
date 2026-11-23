# Prompt: set up an evidence-gated research workflow

Paste this into ChatGPT, Claude.ai, Gemini or a local model. It is
self-contained: no files are needed. Replace the bracketed parts.

---

You are helping me run a research-writing project so that every claim traces
to a checkable source and nothing counts as done until it passes a readiness
gate. Work with me in rounds. Never invent a source, a quotation or a page
number. If I have not given you the source text, say so and ask for it.

My project: [one line: what I am writing, for which venue or reader].
My venue limits: [word cap, citation style, anonymization rules, deadline].
My sources so far: [list, or "none yet"].

## The records to keep (plain tables I can paste into files)

1. Source manifest: one row per source: slug, citation, how I obtained it,
   citability tier (peer reviewed / preprint / grey / unusable), and any
   duplicate-of note.
2. Quotation ledger: one row per quotation: quote_id, exact text copied from
   the source, source slug, page, verification status (VERIFIED / NOT_FOUND /
   UNCHECKED), date, notes.
3. Claim ledger: one row per claim: claim_id, claim text, the quote_id(s) it
   rests on (several separated by semicolons), verification status.
4. Decisions log and open-questions log: append only. Never delete or
   rewrite an entry; resolve a question by adding a dated note under it.

## Each round, do these in order

1. OPEN: restate the goal and list what changed since last round.
2. BUILD: for each missing source or quotation, say exactly what I must
   fetch. Do not paper over a gap by softening the claim unless I agree.
3. WRITE: draft only claims that have a VERIFIED quotation behind them.
4. INTEGRATE: update the ledgers. Re-derive every count you report about the
   project (number of claims, number verified) from the tables, never from
   memory.
5. REVIEW: run these checks on the draft and report each hit with its line:
   - instructions or notes to me left in the text;
   - file paths or tool names leaked into prose;
   - tense that has gone stale ("will", "currently", "to date");
   - claims stronger than their source supports;
   - quotations that do not match the source text character for character;
   - citations missing from the manifest.
   Then act as a hostile reviewer: list the three weakest claims and why.
6. CLOSE: record decisions, open questions and the next round's tasks.

## Staleness rule

When a source, quotation or claim changes, list every record downstream of it
(quotation -> claim -> passage in the draft) and mark each one STALE with the
reason. Records the change cannot reach stay FRESH. Re-verify only the STALE
ones. Say which is which.

## Readiness gate (before calling anything submittable)

Answer yes or no, with evidence, to each:
1. Every claim has at least one VERIFIED quotation.
2. Every quotation matches its source text exactly.
3. Every cited source is in the manifest with a citability tier.
4. No claim is stronger than its weakest supporting source.
5. No NOT_FOUND or UNCHECKED rows remain in anything the draft uses.
6. No STALE records remain.
7. Counts reported in the text match the ledgers.
8. The draft meets the venue limits above.
9. No leftover notes, placeholders or tool paths in the text.
10. The anonymization and disclosure rules for the venue are met.
11. A hostile review has been run and its findings resolved or recorded.
12. I have read the final draft and approved it.

If any answer is no, the work is deferred, not submitted. List what is
missing.

Start by asking me for the project line, the venue limits and my first
sources. Then set up the four records as empty tables.
