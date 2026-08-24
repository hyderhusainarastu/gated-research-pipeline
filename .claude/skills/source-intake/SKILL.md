---
name: source-intake
description: "Source intake pipeline: metadata verification, citability classification, extraction, manifest registration, dedupe, provenance, request-tracking updates. Use for every new source file entering your project's source library."
---

# Source Intake Pipeline

Every new source passes through this pipeline, in order, before it may be
annotated, mined, or cited. Set your project's writable root once and
keep all intake actions inside it.

## Pipeline steps (in order)

1. **Verify metadata.** Title, authors, venue, year, and any stable
   identifier (DOI/ISBN/URL) confirmed against the document itself (title
   page, running headers, copyright page) — never taken on faith from a
   filename or a citing source's paraphrase. **Never guess metadata:** if
   a field is genuinely unrecoverable from the document, record explicit
   `UNKNOWN`.

2. **Classify citability** under a four-status rule (adapt the exact
   labels to your field, but keep the distinctions):
   - `peer_reviewed` — formal peer review, verifiable through the
     venue's own apparatus or a registry record.
   - `primary_exempt` — a primary source analyzed as an object of study
     rather than cited as an authority.
   - `accepted_exempt` — accepted for publication even if not yet in
     final typeset form.
   - `scholarly_empirical_exempt` — scholarly empirical reports/syntheses
     with identifiable researcher authors, stated methods/data, and
     verifiable provenance. Explicitly excludes journalism, blogs,
     how-to guides, slide decks, and trade books — cite the underlying
     study instead.
   - Anything else → `not_peer_reviewed`: background only, never cited as
     evidence for a load-bearing claim.

   **Institutional-imprint rule.** Scholarly monographs and edited-volume
   chapters from a refereed, reputable scholarly press (or a comparable
   imprint with editorial-board/peer-vetting for its list) classify as
   `peer_reviewed` when the work is genuine scholarship addressed to a
   scholarly audience. Trade books aimed at a general audience are
   excluded and stay background-only. Document the press/series evidence
   in a `classification_evidence` field for every source, citable or not.

3. **Lawful acquisition only.** No paywall circumvention. If access is
   blocked, log the request (citation, link, why needed, which claim/
   workstream needs it, access attempts made, preprint availability,
   status) and wait for the project owner. Never substitute a
   lower-quality stand-in and treat it as equivalent.

4. **Work-level dedupe** before registering: check a content hash, a
   stable identifier, and a normalized-title+year against your existing
   manifest. Same work (any edition/scan) = **update the existing
   manifest row in place — never create a new row.** Quarantine
   superseded/duplicate files under a clearly named `excluded/duplicates/`
   location.

5. **Land, extract, manifest.** Deposit the file, extract text with a
   layout-preserving extractor (an OCR fallback for image-only files;
   log `extraction_status` accordingly). Route citable files into your
   library's topic structure, background-only files to an excluded
   folder. Register in **every** manifest file your project keeps in
   parallel (a CSV and a JSON mirror, for example) — they must never
   diverge. Minimum columns: `slug, original_filename, content_hash,
   bytes, filetype, extraction_status, extracted_chars, word_count,
   peer_review_status, venue, identifier, pub_year, version,
   classification_evidence, duplicate_of, location, notes` (plus `title`
   and `authors` wherever your format allows nested fields).

6. **Provenance.** Write/append one provenance record per source
   (acquisition route, upload/download date, original filename, rename
   applied, classification record).

7. **Annotation and mining.** One annotation note per source; evidence
   excerpts and claims staged to per-source draft files before merging.

8. **Ledger merge.** Merge staged evidence/claims into your evidence and
   claim ledgers (see `docs/records-format-conventions.md`) with a
   verification status. Any unverified or not-found item goes to your
   open-questions record, never silently dropped or used.

   **Validate before merge.** Before merging any staged CSV, parse it and
   confirm every row's field count equals the header's field count. A
   staging file that fails this check is **quarantined, not merged** —
   leave it staged, report the failing row numbers and field counts, and
   route the repair back to the file's owner. Never patch a failing row
   on the fly during a merge; repair and re-validate first, merge second.

9. **Request tracking.** If the source closes an open request, update its
   row/status in your request-tracking file (e.g., "Awaiting" →
   "Acquired") with a dated note.

10. **Ledger row for the intake itself.** Append exactly one row per
    intake task to your task ledger (objective, evidence, completion
    criteria, review agent, status). The source is not citable in any
    output until this row reads Complete.

## Standing notes

- Update whatever discipline/topic map you keep per new source (slug,
  title, citable, discipline, themes, relevance).
- Report discrepancies (manifest divergence, missing provenance,
  misclassification) rather than silently fixing them.
