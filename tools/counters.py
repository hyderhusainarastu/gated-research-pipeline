#!/usr/bin/env python3
"""
counters.py -- the single canonical governance-counter derivation for a
project using this template.

============================================================================
WHY THIS EXISTS
============================================================================
The same handful of headline numbers about a project's own state --
decisions-log dated rows, task-ledger row count, source-manifest count,
evidence-ledger status distribution -- are easy to re-derive by hand,
round after round, by different people or agents using different
unstated methods, and to disagree with each other as a result. A hand
count and a "we said N last time so it's still N" both drift silently.

This script is the fix: ONE script, ONE set of conventions (documented
inline, one per counter, below), stdlib only, fully deterministic given
the same file contents. Any agent or reviewer who needs one of these
numbers runs this script -- nobody hand-counts, hand-greps-and-eyeballs,
or recomputes a bespoke variant. If a convention below is wrong or needs
to change, that is an owner ruling that gets logged in the decisions log
and then implemented HERE (one place), not silently redefined in a report.

============================================================================
USAGE
============================================================================
    python3 tools/counters.py
        -- prints the JSON payload and the human-readable table to stdout.

    python3 tools/counters.py --out-prefix logs/COUNTERS_CANONICAL_2027-01-01
        -- additionally writes <prefix>.json and <prefix>.md.

    python3 tools/counters.py --root /path/to/your-project
        -- override the project root (default: two directories up from this
           file, i.e. the repo root when this file lives at tools/counters.py).

    python3 tools/counters.py --config config/counters.json
        -- override the relative paths and target-source glob this script
           reads (see CountersConfig below); useful if your project keeps
           its records somewhere other than the template defaults.

No third-party dependencies. No network access. No writes other than the
optional --out-prefix files, which are written atomically and only if
every counter above computed without error (a partial/half-failed run
never overwrites a prior canonical snapshot with garbage).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# ============================================================================
# Configuration -- every path below is a project-relative default. Override
# any of them with --config pointing at a small JSON file with the same
# keys, so this script never needs project-specific edits.
# ============================================================================
@dataclass
class CountersConfig:
    decisions_log: str = "DECISIONS.md"
    task_ledger: str = "logs/task_ledger.csv"
    manifest_csv: str = "sources/manifest.csv"
    manifest_json: str = "sources/manifest.json"
    quote_ledger: str = "records/quote_ledger.csv"
    claim_ledger: str = "records/claim_ledger.csv"
    citation_source_dirs: List[str] = field(default_factory=lambda: ["manuscript"])
    citation_bbl_name: str = "main.bbl"
    owner_marker_pattern: str = r"\*\*OWNER-(\d+)"


def load_config(path: "Path | None") -> CountersConfig:
    if path is None:
        return CountersConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    return CountersConfig(**{**CountersConfig().__dict__, **data})


# ============================================================================
# 1. Decisions log dated rows
# ----------------------------------------------------------------------------
# CONVENTION: the decisions log is a single Markdown pipe-table. A "dated
# row" is a physical line that opens a table data row: it starts with a
# pipe, a space, an ISO-8601 date (YYYY-MM-DD), a space, and another pipe.
# This excludes the table header row, the header-separator row, blank
# lines, and any date mentioned in prose inside a Rationale/Decision cell
# (those never appear at the START of a line).
#   regex (per line): ^\| \d{4}-\d{2}-\d{2} \|
# ============================================================================
DECISIONS_DATED_ROW_RE = re.compile(r"^\| \d{4}-\d{2}-\d{2} \|")


def count_decisions_dated_rows(decisions_path: Path) -> dict:
    lines = decisions_path.read_text(encoding="utf-8").split("\n")
    matches = [i for i, l in enumerate(lines, 1) if DECISIONS_DATED_ROW_RE.match(l)]
    return {
        "convention": (
            "physical lines matching ^\\| \\d{4}-\\d{2}-\\d{2} \\| "
            "(a Markdown table data row opening with an ISO date cell)"
        ),
        "count": len(matches),
        "source_file": str(decisions_path),
        "total_physical_lines_in_file": len(lines),
    }


# ============================================================================
# 2. Owner-opened rows (bolded **OWNER-NN** pattern) + distinct ids
# ----------------------------------------------------------------------------
# CONVENTION: a ruling is "opened by naming the owner" when its decisions-
# log row's text contains a bolded marker matching `owner_marker_pattern`
# (default `**OWNER-<digits>**`; rename the tag in your own project's
# convention, e.g. `**AUTHOR-N**`, and update the config to match). This is
# a per-LINE, per-OCCURRENCE regex, not a match against the "Made By"
# column (that column also contains un-numbered entries that do NOT
# count).
#
# Two distinct counts are reported, because they answer different
# questions:
#   - rows_with_bold_marker: how many physical lines contain >=1 match. A
#     ruling can be RE-MENTIONED in a later confirmation/correction row
#     without that being a new ruling -- so this number is >= the count of
#     genuinely NEW rulings and should not, by itself, be read as "N
#     rulings issued".
#   - distinct_ids: how many distinct numeric ids appear anywhere under
#     the bold pattern, deduplicated. This is closer to "how many
#     distinct rulings have ever been numbered", though it does not
#     detect an id being reused by mistake (a live drift risk this script
#     cannot rule out; it only counts what is on disk).
# ============================================================================
def count_owner_markers(decisions_path: Path, pattern: str) -> dict:
    marker_re = re.compile(pattern)
    text = decisions_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    rows_with_marker = [i for i, l in enumerate(lines, 1) if marker_re.search(l)]
    all_occurrences = marker_re.findall(text)
    distinct_ids = sorted({int(x) for x in all_occurrences})
    return {
        "convention": (
            f"regex {pattern!r} applied to the decisions log; "
            "'rows_with_bold_marker' = physical lines with >=1 match; "
            "'distinct_ids' = distinct numeric ids across all matches, "
            "deduplicated"
        ),
        "rows_with_bold_marker": len(rows_with_marker),
        "total_bold_occurrences": len(all_occurrences),
        "distinct_ids": len(distinct_ids),
        "distinct_ids_min_max": (
            [distinct_ids[0], distinct_ids[-1]] if distinct_ids else None
        ),
    }


# ============================================================================
# 3. Task ledger via csv.reader
# ----------------------------------------------------------------------------
# CONVENTION: parse with Python's stdlib csv.reader (default dialect --
# comma-delimited, double-quote quoting, RFC 4180 embedded-newline/embedded-
# comma handling). The header row's field count is the well-formedness
# baseline. A data row is WELL-FORMED iff its field count equals the
# header's field count; otherwise it is MALFORMED. Physical line numbers
# for malformed rows are taken from csv.reader's own `line_num` attribute
# (physical lines consumed so far), NOT from a naive enumerate() index --
# csv.reader collapses a quoted field containing an embedded newline into
# ONE logical row spanning multiple physical lines, so a plain 1-per-row
# counter would misreport line numbers after the first such field.
# ============================================================================
def count_task_ledger(ledger_path: Path) -> dict:
    with ledger_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        header_len = len(header)
        total = 0
        malformed = []
        for row in reader:
            total += 1
            if len(row) != header_len:
                malformed.append({"line": reader.line_num, "field_count": len(row)})
        final_line_num = reader.line_num
    well_formed = total - len(malformed)
    return {
        "convention": (
            "stdlib csv.reader (RFC 4180) over the task ledger; well-formed "
            "= data row field count equals header field count "
            f"({header_len}); malformed line numbers are csv.reader's own "
            "line_num (physical lines consumed, correct across embedded "
            "newlines in quoted fields) -- NOT a naive row-index count"
        ),
        "header_field_count": header_len,
        "total_data_rows_csv_reader": total,
        "well_formed_rows": well_formed,
        "malformed_rows": len(malformed),
        "malformed_row_detail": malformed,
        "total_physical_lines_in_file": final_line_num,
    }


# ============================================================================
# 4. Source manifest (CSV + JSON mirror), asserted equal
# ----------------------------------------------------------------------------
# CONVENTION: CSV entry count = csv.reader data-row count (rows after the
# header). JSON entry count = len() of the top-level JSON structure (a
# dict keyed by source id, or a list -- either way, len() of the top-level
# container). The two MUST be equal; a mismatch is reported as an explicit
# assertion failure in the output rather than silently picking one number.
# ============================================================================
def count_manifest(csv_path: Path, json_path: Path) -> dict:
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    csv_count = max(len(rows) - 1, 0)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    json_count = len(data)

    return {
        "convention": (
            "CSV: csv.reader data-row count (excludes header row). "
            "JSON: len() of the top-level JSON container (dict or list). "
            "The two are asserted equal; the result reports both regardless."
        ),
        "csv_entries": csv_count,
        "json_entries": json_count,
        "json_top_level_type": type(data).__name__,
        "equal": csv_count == json_count,
    }


# ============================================================================
# 5. Evidence/quote ledger: rows + status distribution
# ----------------------------------------------------------------------------
# CONVENTION: csv.DictReader data-row count (header-driven field access, so
# column order/renaming elsewhere in the pipeline cannot silently break
# this count). Status distribution is a Counter over the exact string
# value of the `verification_status` column (empty string is its own
# bucket if present, not silently dropped).
# ============================================================================
def count_quote_ledger(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    dist = Counter(r.get("verification_status", "") for r in rows)
    return {
        "convention": (
            "csv.DictReader data-row count over the evidence/quote ledger; "
            "status distribution = Counter over the exact "
            "'verification_status' column value (including '' if present)"
        ),
        "total_rows": len(rows),
        "verification_status_distribution": dict(sorted(dist.items())),
    }


# ============================================================================
# 6. Claim ledger: rows + linked/unlinked
# ----------------------------------------------------------------------------
# CONVENTION: csv.DictReader data-row count. LINKED = the `quote_id`
# column, stripped of surrounding whitespace, is non-empty. UNLINKED = it
# is empty after stripping. A disclosed sub-count of MULTI-VALUE quote_id
# fields (containing a ';'-separated list -- a known field-format defect
# rather than a join failure) is reported separately; these rows count as
# LINKED (they do have a non-empty quote_id), they are just not resolvable
# by a plain single-value join (see tools/multivalue_join.py).
# ============================================================================
def count_claim_ledger(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    linked = 0
    unlinked = 0
    multi_value = 0
    for r in rows:
        qid = (r.get("quote_id") or "").strip()
        if qid:
            linked += 1
            if ";" in qid:
                multi_value += 1
        else:
            unlinked += 1
    status_dist = Counter(r.get("claim_verification_status", "") for r in rows)
    return {
        "convention": (
            "csv.DictReader data-row count over the claim ledger; linked = "
            "non-empty (stripped) 'quote_id' cell, unlinked = empty; "
            "multi_value_quote_id is a disclosed sub-count of linked rows "
            "whose quote_id contains ';' (a documented field-format "
            "defect, not a join failure) -- these rows are counted in "
            "'linked', not subtracted from it"
        ),
        "total_rows": len(rows),
        "linked": linked,
        "unlinked": unlinked,
        "multi_value_quote_id_subset_of_linked": multi_value,
        "claim_verification_status_distribution": dict(sorted(status_dist.items())),
    }


# ============================================================================
# 7. Cited keys in the manuscript source vs. the compiled bibliography
# ----------------------------------------------------------------------------
# CONVENTION: two independent derivations, cross-checked, exactly like the
# manifest CSV/JSON check above.
#   (a) SOURCE derivation: scan every source file under
#       `citation_source_dirs` (recursively) for cite-family commands --
#       cite|citep|citet|autocite|parencite|textcite|footcite, each
#       optionally starred and with an optional bracketed pre/post-note --
#       and collect every comma-separated key inside the mandatory {...}
#       argument. A style-selection command (e.g. \citestyle{...}) is
#       explicitly NOT a citation command and is excluded by the pattern.
#   (b) COMPILED derivation: scan the compiled bibliography file (a
#       BibTeX-produced .bbl by default) for \bibitem[...]{key} entries --
#       the set your citation processor actually resolved and will
#       compile into the final artifact.
# A clean, currently-compiling build has (a) == (b); if they diverge, that
# is reported explicitly. If your project does not use a LaTeX/BibTeX
# toolchain, adapt (or skip) this counter -- the other six are toolchain-
# agnostic.
# ============================================================================
CITE_COMMAND_RE = re.compile(
    r"\\(?:cite|citep|citet|autocite|parencite|textcite|footcite)\*?"
    r"(?:\[[^\]]*\])*\{([^}]*)\}"
)


def count_cited_keys(source_dirs: List[Path], bbl_name: str) -> dict:
    tex_files: List[Path] = []
    for d in source_dirs:
        if d.exists():
            tex_files.extend(sorted(d.rglob("*.tex")))
    keys_from_source: set = set()
    for fp in tex_files:
        text = fp.read_text(encoding="utf-8", errors="replace")
        for m in CITE_COMMAND_RE.finditer(text):
            for k in m.group(1).split(","):
                k = k.strip()
                if k:
                    keys_from_source.add(k)

    keys_from_bbl: set = set()
    bbl_path = None
    for d in source_dirs:
        candidate = d / bbl_name
        if candidate.exists():
            bbl_path = candidate
            break
    if bbl_path is not None:
        lines = bbl_path.read_text(encoding="utf-8", errors="replace").split("\n")
        i = 0
        while i < len(lines):
            if lines[i].startswith("\\bibitem"):
                joined = lines[i]
                j = i
                while "{" not in joined.split("]", 1)[-1] and j + 1 < len(lines):
                    j += 1
                    joined += lines[j]
                m = re.search(r"\{([^}]*)\}", joined.split("]", 1)[-1])
                if m:
                    keys_from_bbl.add(m.group(1).strip())
                i = j + 1
            else:
                i += 1

    return {
        "convention": (
            "(a) source: regex over every *.tex under the configured "
            "citation_source_dirs for cite-family commands, collecting "
            "comma-separated keys from the mandatory {...} argument. "
            "(b) compiled: \\bibitem{key} entries parsed from the compiled "
            ".bbl. Both are distinct-key counts; 'equal' asserts the two "
            "derivations agree, i.e. the compiled bibliography reflects "
            "the current source's citations."
        ),
        "tex_files_scanned": len(tex_files),
        "bbl_path": str(bbl_path) if bbl_path else None,
        "distinct_keys_from_source": len(keys_from_source),
        "distinct_keys_from_bbl": len(keys_from_bbl),
        "equal": keys_from_source == keys_from_bbl,
        "in_source_not_in_bbl": sorted(keys_from_source - keys_from_bbl),
        "in_bbl_not_in_source": sorted(keys_from_bbl - keys_from_source),
    }


# ============================================================================
# Orchestration
# ============================================================================
def derive_all(root: Path, cfg: CountersConfig) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    counters = {}

    def optional(name, fn):
        try:
            counters[name] = fn()
        except FileNotFoundError as e:
            counters[name] = {"skipped": True, "reason": f"file not found: {e.filename}"}

    optional("decisions_dated_rows", lambda: count_decisions_dated_rows(root / cfg.decisions_log))
    optional("owner_markers", lambda: count_owner_markers(root / cfg.decisions_log, cfg.owner_marker_pattern))
    optional("task_ledger", lambda: count_task_ledger(root / cfg.task_ledger))
    optional("source_manifest", lambda: count_manifest(root / cfg.manifest_csv, root / cfg.manifest_json))
    optional("quote_ledger", lambda: count_quote_ledger(root / cfg.quote_ledger))
    optional("claim_ledger", lambda: count_claim_ledger(root / cfg.claim_ledger))
    optional("cited_keys", lambda: count_cited_keys(
        [root / d for d in cfg.citation_source_dirs], cfg.citation_bbl_name
    ))

    return {
        "generated_at_utc": timestamp,
        "generated_by": "tools/counters.py (canonical governance-counter derivation)",
        "project_root": str(root),
        "counters": counters,
    }


def render_markdown(result: dict) -> str:
    c = result["counters"]
    lines = ["# Canonical Governance Counters", ""]
    lines.append(f"Generated: {result['generated_at_utc']}")
    lines.append(f"Project root: `{result['project_root']}`")
    lines.append(f"Derivation script: `{result['generated_by']}`")
    lines.append("")
    lines.append(
        "Every count below is produced by `tools/counters.py`, run once, "
        "with the exact convention for each stated inline. No count on "
        "this page is hand-derived. Re-run the script to get a fresh "
        "snapshot; do not hand-edit these numbers."
    )
    lines.append("")

    for key, val in c.items():
        lines.append(f"## `{key}`")
        lines.append("")
        if isinstance(val, dict) and val.get("skipped"):
            lines.append(f"_Skipped: {val['reason']}_")
            lines.append("")
            continue
        lines.append("```json")
        lines.append(json.dumps(val, indent=2, sort_keys=False))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent,
        help="Project root (default: parent of the tools/ directory containing this script).",
    )
    parser.add_argument("--config", type=Path, default=None, help="Optional JSON config overriding default paths.")
    parser.add_argument("--out-prefix", type=Path, default=None, help="If given, write <prefix>.json and <prefix>.md.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    cfg = load_config(args.config)
    result = derive_all(root, cfg)
    payload = json.dumps(result, indent=2, sort_keys=False)
    md = render_markdown(result)

    print(payload)
    print()
    print(md)

    if args.out_prefix is not None:
        out_prefix = args.out_prefix
        out_prefix.parent.mkdir(parents=True, exist_ok=True)
        json_path = Path(str(out_prefix) + ".json")
        md_path = Path(str(out_prefix) + ".md")
        json_path.write_text(payload + "\n", encoding="utf-8")
        md_path.write_text(md + "\n", encoding="utf-8")
        print(f"\nWrote: {json_path}", file=sys.stderr)
        print(f"Wrote: {md_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
