#!/usr/bin/env python3
"""
multivalue_join.py -- REPORT-ONLY resolver for claim-ledger rows whose
`quote_id` cell carries a semicolon-separated multi-value link (a claim
that rests on more than one piece of evidence).

============================================================================
WHY THIS EXISTS
============================================================================
A straightforward single-value join between a claim ledger and an
evidence ledger (match one `quote_id` per claim row against one row in
the evidence ledger) is the common case, but real projects accumulate
claims resting on *several* pieces of evidence at once. If your primary
join logic explicitly excludes any row whose `quote_id` contains a `;`
from its strict/broad split (a reasonable, disclosed scope limit -- see
`docs/records-format-conventions.md`), this script closes that gap by
generalizing the SAME strict/broad rule the single-value join already
applies, to a SET of quote_ids per claim row.

============================================================================
RULE (generalized from a single-value strict/broad join; the set
generalization is the only new logic)
============================================================================
For a claim row's `quote_id` split on `;` (each segment stripped of
whitespace):

  - RESOLVED requires every sub-id to exist as a `quote_id` in the live
    evidence ledger. Any sub-id absent from the evidence ledger makes the
    WHOLE row `unresolved` (a claim citing evidence that does not exist
    cannot inherit anything from it -- one missing link breaks the chain
    for the row, not just for that one sub-id).
  - STRICT: every resolved sub-id's `verification_status` is exactly
    `VERIFIED` -- the direct set-generalization of the single-value rule's
    `status == "VERIFIED"` test.
  - BROAD (not strict): not every sub-id is `VERIFIED`, but at least one
    resolved sub-id's status is in the "TEXT-VERIFIED or above" tier
    (`VERIFIED`, `TEXT-VERIFIED`, `VERIFIED_PAGE_STRADDLE` by this
    template's default vocabulary -- confirm your own ledger's actual
    status vocabulary with a fresh Counter over the live file before
    assuming this list is exhaustive; see BROAD_OR_ABOVE_STATUSES below).
  - WEAK: resolved, but every sub-id's status is below the TEXT-VERIFIED
    tier -- a residual bucket the single-value rule has no direct analog
    for, since a single resolved-but-non-VERIFIED row is always
    classified `broad` there regardless of how weak its one status is.
    This is a genuine extension the set case needs and the single-value
    case does not, not a silent narrowing of the single-value rule.

This script NEVER writes a resolution column back into the live ledger --
it is report-only, by design. Whether to write a derived status back into
the live claim ledger (an --apply mode) is a separate, deliberate decision
your project should make explicitly, not a default this script assumes.

Usage:
    python3 tools/multivalue_join.py
    python3 tools/multivalue_join.py --quote-ledger path --claim-ledger path --out report.json
No third-party dependency. Python 3 standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

_THIS_FILE = os.path.abspath(__file__)
TOOLS_DIR = os.path.dirname(_THIS_FILE)
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)

QUOTE_LEDGER_PATH = os.path.join(PROJECT_ROOT, "records", "quote_ledger.csv")
CLAIM_LEDGER_PATH = os.path.join(PROJECT_ROOT, "records", "claim_ledger.csv")

# The "TEXT-VERIFIED or above" tier -- this template's default three-status
# vocabulary. If your project's evidence ledger uses a different status
# vocabulary, edit this set to match (a status value not in this set is
# conservatively treated as sub-TEXT-VERIFIED, never silently as strong
# evidence -- so an unrecognized status degrades gracefully rather than
# inflating your BROAD count).
STRICT_STATUSES = {"VERIFIED"}
BROAD_OR_ABOVE_STATUSES = {"VERIFIED", "TEXT-VERIFIED", "VERIFIED_PAGE_STRADDLE"}


@dataclass
class RowResolution:
    claim_id: str
    quote_id_raw: str
    sub_ids: List[str]
    found_sub_ids: List[str]
    missing_sub_ids: List[str]
    sub_statuses: Dict[str, str]
    disposition: str  # strict | broad | weak | unresolved

    def to_dict(self) -> dict:
        return dict(
            claim_id=self.claim_id, quote_id_raw=self.quote_id_raw,
            sub_ids=self.sub_ids, found_sub_ids=self.found_sub_ids,
            missing_sub_ids=self.missing_sub_ids, sub_statuses=self.sub_statuses,
            disposition=self.disposition,
        )


def _read_csv_rows(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def resolve_multivalue_row(claim_row: dict, qmap: Dict[str, str]) -> Optional[RowResolution]:
    """Returns None if the row's quote_id is not multi-value (no `;`) --
    single-value rows are handled by your project's primary join and are
    out of scope for this script by design."""
    raw = (claim_row.get("quote_id") or "").strip()
    if ";" not in raw:
        return None
    sub_ids = [s.strip() for s in raw.split(";") if s.strip()]
    found = [s for s in sub_ids if s in qmap]
    missing = [s for s in sub_ids if s not in qmap]
    statuses = {s: qmap[s] for s in found}

    if missing:
        disposition = "unresolved"
    elif all(st in STRICT_STATUSES for st in statuses.values()):
        disposition = "strict"
    elif any(st in BROAD_OR_ABOVE_STATUSES for st in statuses.values()):
        disposition = "broad"
    else:
        disposition = "weak"

    return RowResolution(
        claim_id=claim_row.get("claim_id", ""), quote_id_raw=raw, sub_ids=sub_ids,
        found_sub_ids=found, missing_sub_ids=missing, sub_statuses=statuses,
        disposition=disposition,
    )


def run(quote_ledger_path: str = QUOTE_LEDGER_PATH, claim_ledger_path: str = CLAIM_LEDGER_PATH) -> dict:
    quote_rows = _read_csv_rows(quote_ledger_path)
    claim_rows = _read_csv_rows(claim_ledger_path)
    qmap = {r["quote_id"].strip(): r["verification_status"].strip() for r in quote_rows if r.get("quote_id")}

    resolutions: List[RowResolution] = []
    for row in claim_rows:
        res = resolve_multivalue_row(row, qmap)
        if res is not None:
            resolutions.append(res)

    counts = Counter(r.disposition for r in resolutions)
    report = {
        "generated_by": "tools/multivalue_join.py (report-only)",
        "quote_ledger_path": quote_ledger_path,
        "claim_ledger_path": claim_ledger_path,
        "n_quote_ledger_rows": len(quote_rows),
        "n_claim_ledger_rows": len(claim_rows),
        "n_multivalue_claim_rows": len(resolutions),
        "disposition_counts": dict(counts),
        "resolved_strict_or_broad": counts.get("strict", 0) + counts.get("broad", 0),
        "rows": [r.to_dict() for r in resolutions],
        "note": (
            "REPORT-ONLY. No ledger file was written by this run. Whether "
            "to write a derived status back into the live claim ledger "
            "(an --apply mode) is a separate, deferred decision, not "
            "performed here."
        ),
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quote-ledger", default=QUOTE_LEDGER_PATH)
    p.add_argument("--claim-ledger", default=CLAIM_LEDGER_PATH)
    p.add_argument("--out", help="Write the JSON report to this path too (always prints to stdout).")
    args = p.parse_args(argv)

    report = run(args.quote_ledger, args.claim_ledger)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
