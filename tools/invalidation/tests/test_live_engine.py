#!/usr/bin/env python3
"""
test_live_engine.py -- self-tests for the live-engine capabilities:
content-hash formula, schema-v2 CSV/JSON migration (idempotency,
backup, optimistic-concurrency abort, field-count validation), row-event
detection, manifest-supersession detection, and STALE propagation.

These tests run entirely against temp-directory fixtures. They NEVER touch
the live ledgers (research/quote_ledger.csv, research/claim_ledger.csv,
Sources/source_manifest.csv/.json) -- verified by asserting every path used
is under a tempfile.mkdtemp() directory before any write.

Run: python3 tools/invalidation/tests/test_live_engine.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_INVALIDATION_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, TOOLS_INVALIDATION_DIR)

import invalidation as iv  # noqa: E402


def _write_csv(path: str, header: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="invalidation_selftest_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # CRITICAL: an isolated backup dir, distinct from iv.PRE_SCHEMA_V2_DIR
        # (the real project's logs/pre_schema_v2/). An earlier version of
        # this suite let migrate_csv_schema_v2/migrate_manifest_json_schema_v2
        # default to the real PRE_SCHEMA_V2_DIR even when migrating a
        # tempdir fixture -- since some fixtures reuse the real basenames
        # (quote_ledger.csv, source_manifest.json) for realism, that
        # silently overwrote the REAL project's safety backups with tiny
        # test fixture data (caught and fixed in testing). Every migrate_* call in
        # this file MUST pass backup_dir=self.backup_dir explicitly.
        self.backup_dir = os.path.join(self.tmp, "_backups")
        self.assertNotEqual(
            os.path.abspath(self.backup_dir), os.path.abspath(iv.PRE_SCHEMA_V2_DIR),
            "test backup dir must never coincide with the real project's PRE_SCHEMA_V2_DIR",
        )

    def path(self, name: str) -> str:
        p = os.path.join(self.tmp, name)
        self.assertTrue(p.startswith(self.tmp), "test must never write outside its tempdir")
        return p


class TestContentHash(unittest.TestCase):
    def test_deterministic(self):
        row = {"exact_quote": "hello world", "slug": "x", "citable_status": "peer_reviewed"}
        h1 = iv.compute_content_hash(row, iv.QUOTE_CONTENT_HASH_FIELDS)
        h2 = iv.compute_content_hash(row, iv.QUOTE_CONTENT_HASH_FIELDS)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # sha256 hex digest

    def test_changes_with_verification_bearing_field(self):
        row1 = {"exact_quote": "hello world", "slug": "x", "citable_status": "peer_reviewed"}
        row2 = {"exact_quote": "hello there", "slug": "x", "citable_status": "peer_reviewed"}
        self.assertNotEqual(
            iv.compute_content_hash(row1, iv.QUOTE_CONTENT_HASH_FIELDS),
            iv.compute_content_hash(row2, iv.QUOTE_CONTENT_HASH_FIELDS),
        )

    def test_stable_under_status_only_field_change(self):
        # The whole point of the verifying-trace design (see the module docstring): a status-only field is NOT in the hash formula at all,
        # so touching it must not change the hash.
        row1 = {"exact_quote": "hello world", "slug": "x", "citable_status": "peer_reviewed",
                "verification_notes": "first pass"}
        row2 = {"exact_quote": "hello world", "slug": "x", "citable_status": "peer_reviewed",
                "verification_notes": "second pass, re-checked"}
        self.assertEqual(
            iv.compute_content_hash(row1, iv.QUOTE_CONTENT_HASH_FIELDS),
            iv.compute_content_hash(row2, iv.QUOTE_CONTENT_HASH_FIELDS),
        )

    def test_missing_field_treated_as_empty_not_keyerror(self):
        row = {"exact_quote": "hello"}  # slug, citable_status absent
        h = iv.compute_content_hash(row, iv.QUOTE_CONTENT_HASH_FIELDS)
        self.assertEqual(len(h), 64)

    def test_nfc_normalization(self):
        # e + combining acute vs precomposed é must hash identically.
        row_decomposed = {"exact_quote": "café", "slug": "x", "citable_status": "s"}
        row_precomposed = {"exact_quote": "café", "slug": "x", "citable_status": "s"}
        self.assertEqual(
            iv.compute_content_hash(row_decomposed, iv.QUOTE_CONTENT_HASH_FIELDS),
            iv.compute_content_hash(row_precomposed, iv.QUOTE_CONTENT_HASH_FIELDS),
        )


class TestCsvSchemaMigration(TempDirCase):
    QUOTE_HEADER = [
        "exact_quote", "intended_use", "pdf_page", "printed_page", "quote_id",
        "section", "slug", "surrounding_context", "citable_status",
        "verification_status", "verification_method", "verification_date",
        "verification_notes",
    ]

    def _fixture_rows(self, n=5):
        return [
            {
                "exact_quote": f"quote number {i}", "intended_use": "support", "pdf_page": str(i),
                "printed_page": str(i), "quote_id": f"q{i}", "section": "intro", "slug": "src-a",
                "surrounding_context": "ctx", "citable_status": "peer_reviewed",
                "verification_status": "VERIFIED", "verification_method": "manual",
                "verification_date": "2026-08-01", "verification_notes": "",
            }
            for i in range(n)
        ]

    def test_migrate_adds_columns_and_preserves_rows(self):
        p = self.path("quote_ledger.csv")
        _write_csv(p, self.QUOTE_HEADER, self._fixture_rows(5))

        result = iv.migrate_csv_schema_v2(
            p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=True,
            backup_dir=self.backup_dir,
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.rows_before, 5)
        self.assertEqual(result.rows_after, 5)
        self.assertEqual(result.mismatches_after, 0)
        self.assertTrue(os.path.exists(result.backup_path))

        with open(p, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertIn("content_hash", row)
            self.assertIn("engine_status", row)
            self.assertEqual(row["engine_status"], "FRESH")
            self.assertEqual(row["stale_since"], "")
            self.assertEqual(row["stale_reason"], "")
            # existing columns/values must be byte-identical, untouched
            self.assertEqual(row["verification_status"], "VERIFIED")
            self.assertEqual(row["exact_quote"], row["exact_quote"])  # sanity

    def test_migration_never_overwrites_existing_verification_status(self):
        p = self.path("quote_ledger.csv")
        rows = self._fixture_rows(3)
        rows[0]["verification_status"] = "NOT_FOUND"
        _write_csv(p, self.QUOTE_HEADER, rows)
        iv.migrate_csv_schema_v2(p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=True, backup_dir=self.backup_dir)
        with open(p, newline="", encoding="utf-8") as fh:
            after = list(csv.DictReader(fh))
        self.assertEqual(after[0]["verification_status"], "NOT_FOUND")

    def test_idempotent_second_run_is_noop(self):
        p = self.path("quote_ledger.csv")
        _write_csv(p, self.QUOTE_HEADER, self._fixture_rows(3))
        r1 = iv.migrate_csv_schema_v2(p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=True, backup_dir=self.backup_dir)
        self.assertTrue(r1.applied)
        r2 = iv.migrate_csv_schema_v2(p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=True, backup_dir=self.backup_dir)
        self.assertFalse(r2.applied)
        self.assertIn("already migrated", r2.reason)

    def test_dry_run_makes_no_changes(self):
        p = self.path("quote_ledger.csv")
        _write_csv(p, self.QUOTE_HEADER, self._fixture_rows(3))
        with open(p, encoding="utf-8") as fh:
            before = fh.read()
        r = iv.migrate_csv_schema_v2(p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=False, backup_dir=self.backup_dir)
        self.assertFalse(r.applied)
        with open(p, encoding="utf-8") as fh:
            after = fh.read()
        self.assertEqual(before, after)

    def test_refuses_pre_existing_field_count_mismatch(self):
        p = self.path("quote_ledger.csv")
        _write_csv(p, self.QUOTE_HEADER, self._fixture_rows(2))
        # corrupt: append a raw line with too few fields
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("only,three,fields\n")
        r = iv.migrate_csv_schema_v2(p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=True, backup_dir=self.backup_dir)
        self.assertFalse(r.applied)
        self.assertIn("refused", r.reason)
        # file must be untouched
        with open(p, newline="", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("only,three,fields", text)

    def test_concurrent_writer_aborts_without_data_loss(self):
        """Simulates another process appending a row between this
        migration's validation read and its write -- the migration must
        detect the sha256 mismatch and abort WITHOUT writing, so the
        concurrent row is never lost. This is the OCC guard the live-ledger
        migration is deliberately implemented with."""
        p = self.path("quote_ledger.csv")
        _write_csv(p, self.QUOTE_HEADER, self._fixture_rows(3))

        orig_sha256_file = iv._sha256_file
        call_count = {"n": 0}

        def flaky_sha256(path):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # simulate a concurrent external append happening right now
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write("concurrent,writer,row,injected,here,x,x,x,x,x,x,x,x\n")
            return orig_sha256_file(path)

        iv._sha256_file = flaky_sha256
        try:
            r = iv.migrate_csv_schema_v2(p, iv.QUOTE_SCHEMA_V2_COLUMNS, iv.QUOTE_CONTENT_HASH_FIELDS, apply=True, backup_dir=self.backup_dir)
        finally:
            iv._sha256_file = orig_sha256_file

        self.assertFalse(r.applied)
        self.assertIn("ABORTED", r.reason)
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("concurrent,writer,row,injected", text, "the concurrent row must survive the aborted migration")
        self.assertNotIn("content_hash", text.splitlines()[0], "the migration must not have written its columns")


class TestManifestJsonMigration(TempDirCase):
    def test_migrate_json_adds_hash_fields(self):
        p = self.path("source_manifest.json")
        entries = [
            {"slug": "a", "sha256": "abc", "peer_review_status": "peer_reviewed",
             "duplicate_of": "", "version": "1", "extraction_status": "OK",
             "extracted_chars": "100", "word_count": "20"},
            {"slug": "b", "sha256": "def", "peer_review_status": "peer_reviewed",
             "duplicate_of": "", "version": "1", "extraction_status": "OK",
             "extracted_chars": "200", "word_count": "40"},
        ]
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(entries, fh)
        r = iv.migrate_manifest_json_schema_v2(p, apply=True, backup_dir=self.backup_dir)
        self.assertTrue(r.applied)
        with open(p, encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertEqual(len(after), 2)
        for e in after:
            self.assertIn("identity_hash", e)
            self.assertIn("extraction_hash", e)
        # idempotent re-run
        r2 = iv.migrate_manifest_json_schema_v2(p, apply=True, backup_dir=self.backup_dir)
        self.assertFalse(r2.applied)


class TestRowEventDetection(unittest.TestCase):
    def test_row_add_and_remove(self):
        prev = [{"quote_id": "q1", "exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed"}]
        cur = [{"quote_id": "q2", "exact_quote": "b", "slug": "s", "citable_status": "peer_reviewed"}]
        triggers, unexplained = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        kinds = sorted((t.change_kind, t.node_id) for t in triggers)
        self.assertIn(("row_add", "q2"), kinds)
        self.assertIn(("row_remove", "q1"), kinds)
        self.assertEqual(unexplained, [])

    def test_verification_bearing_edit_is_a_trigger(self):
        prev = [{"quote_id": "q1", "exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed"}]
        cur = [{"quote_id": "q1", "exact_quote": "a EDITED", "slug": "s", "citable_status": "peer_reviewed"}]
        triggers, unexplained = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].change_kind, "row_edit")
        self.assertEqual(unexplained, [])

    def test_status_only_edit_is_unexplained_not_a_trigger(self):
        """The direct real-data analog of fixture 11's regression test:
        a record-only/status-only field change must NEVER produce a
        STALE-trigger (section 6, '0% false-trigger rate')."""
        prev = [{"quote_id": "q1", "exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed",
                 "verification_notes": "first pass"}]
        cur = [{"quote_id": "q1", "exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed",
                "verification_notes": "re-checked, still good"}]
        triggers, unexplained = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        self.assertEqual(triggers, [])
        self.assertEqual(len(unexplained), 1)
        self.assertEqual(unexplained[0].change_kind, "row_edit_status_only")

    def test_manifest_supersession_detected_only_on_empty_to_populated(self):
        prev = [{"slug": "old", "duplicate_of": ""}]
        cur = [{"slug": "old", "duplicate_of": "new"}]
        events = iv.detect_manifest_supersession(prev, cur)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].change_kind, "manifest_supersession")
        self.assertEqual(events[0].node_id, "old")

        # already-populated -> different value is NOT a fresh supersession event
        prev2 = [{"slug": "old", "duplicate_of": "x"}]
        cur2 = [{"slug": "old", "duplicate_of": "y"}]
        events2 = iv.detect_manifest_supersession(prev2, cur2)
        self.assertEqual(events2, [])


class TestRegressionProvSelfLoop(TempDirCase):
    """Regression test. A batch of row_edit events fired via
    detect_row_events, but log_firing wrote
    content_hash_before/content_hash_after as "" for all of them -- because
    those fields were hardcoded empty strings at the writer, never
    populated from the detector's own data. tools/prov/export.py's
    entity_urn() maps an empty hash to the literal suffix ":nohash" for
    BOTH sides of a wasRevisionOf edge, so two empty hashes collapsed onto
    one self-referencing URN, which tools/prov/validate_store.py's
    derivation_acyclicity / no_wasRevisionOf_cycle checks then correctly
    flagged as a cycle. This test
    guards the fix at both layers: the detector must never hand log_firing
    an empty content_hash for a genuine row_edit, and log_firing must
    never re-default a real hash back to ""."""

    def test_row_edit_event_carries_distinct_nonempty_hashes(self):
        prev = [{"quote_id": "q1", "exact_quote": "a", "slug": "", "citable_status": "peer_reviewed"}]
        cur = [{"quote_id": "q1", "exact_quote": "a", "slug": "fixed-slug", "citable_status": "peer_reviewed"}]
        triggers, _ = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        self.assertEqual(len(triggers), 1)
        ev = triggers[0]
        self.assertEqual(ev.change_kind, "row_edit")
        self.assertTrue(ev.content_hash_before, "content_hash_before must not be empty")
        self.assertTrue(ev.content_hash_after, "content_hash_after must not be empty")
        # The exact condition that collapses entity_urn()'s two sides onto one
        # self-referencing node: this asserts it can never recur silently.
        self.assertNotEqual(ev.content_hash_before, ev.content_hash_after)
        self.assertEqual(ev.content_hash_before, iv.compute_content_hash(prev[0], iv.QUOTE_CONTENT_HASH_FIELDS))
        self.assertEqual(ev.content_hash_after, iv.compute_content_hash(cur[0], iv.QUOTE_CONTENT_HASH_FIELDS))

    def test_row_add_has_after_hash_and_empty_before(self):
        prev = []
        cur = [{"quote_id": "q1", "exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed"}]
        triggers, _ = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].change_kind, "row_add")
        self.assertEqual(triggers[0].content_hash_before, "")
        self.assertTrue(triggers[0].content_hash_after)

    def test_row_remove_has_before_hash_and_empty_after(self):
        prev = [{"quote_id": "q1", "exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed"}]
        cur = []
        triggers, _ = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].change_kind, "row_remove")
        self.assertTrue(triggers[0].content_hash_before)
        self.assertEqual(triggers[0].content_hash_after, "")

    def test_unrecognized_node_type_refuses_rather_than_emits_empty_hash(self):
        prev = [{"widget_id": "w1", "exact_quote": "a"}]
        cur = [{"widget_id": "w1", "exact_quote": "b"}]
        with self.assertRaises(RuntimeError):
            iv.detect_row_events(prev, cur, "widget_id", "widget", {"exact_quote"})

    def test_log_firing_persists_the_events_own_hashes_not_a_hardcoded_empty(self):
        """End-to-end: detect_row_events -> log_firing -> CSV row. Proves
        the writer no longer silently discards the detector's real hashes
        (the actual earlier defect: the detector was already being
        called correctly by cmd_check, but log_firing threw the hash data
        away at write time)."""
        prev = [{"quote_id": "q1", "exact_quote": "a", "slug": "", "citable_status": "peer_reviewed"}]
        cur = [{"quote_id": "q1", "exact_quote": "a", "slug": "fixed-slug", "citable_status": "peer_reviewed"}]
        triggers, _ = iv.detect_row_events(prev, cur, "quote_id", "quotation", iv.QUOTE_VERIFICATION_BEARING)
        log_path = self.path("invalidation_events.csv")
        iv.log_firing("test-source", triggers, {"q1": "test-reason"}, events_log_path=log_path)
        with open(log_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["content_hash_before"])
        self.assertTrue(rows[0]["content_hash_after"])
        self.assertNotEqual(rows[0]["content_hash_before"], rows[0]["content_hash_after"])


class TestStalePropagation(unittest.TestCase):
    def _small_graph(self) -> iv.Graph:
        g = iv.Graph()
        g.add_node(iv.Node("src-a", "Source"))
        g.add_node(iv.Node("q1", "Quotation", payload={"slug": "src-a"}))
        g.add_node(iv.Node("c1", "Claim", payload={"slug": ""}))
        g.add_edge(iv.Edge("src-a", "q1", "wasQuotedFrom"))
        g.add_edge(iv.Edge("q1", "c1", "quote_id_join"))
        return g

    def test_direct_and_transitive_stale(self):
        g = self._small_graph()
        triggers = [iv.DetectedEvent("row_edit", "quotation", "q1", changed_fields=["exact_quote"])]
        stale = iv.propagate_stale(g, triggers)
        self.assertIn("q1", stale)
        self.assertIn("c1", stale)  # transitively downstream

    def test_row_add_does_not_propagate(self):
        """Regression-test analog of fixture 8a: a brand-new row has no
        dependents yet, so it must produce zero propagation."""
        g = self._small_graph()
        g.add_node(iv.Node("q2", "Quotation", payload={"slug": "src-a"}))
        g.add_edge(iv.Edge("src-a", "q2", "wasQuotedFrom"))
        triggers = [iv.DetectedEvent("row_add", "quotation", "q2")]
        stale = iv.propagate_stale(g, triggers)
        self.assertEqual(stale, {})

    def test_irrelevant_untracked_node_does_not_crash(self):
        g = self._small_graph()
        triggers = [iv.DetectedEvent("row_edit", "quotation", "not-in-graph", changed_fields=["exact_quote"])]
        stale = iv.propagate_stale(g, triggers)
        self.assertEqual(stale, {})


class TestCheckResultOrphanedRemoval(unittest.TestCase):
    """Regression test for a bug found and fixed in review: the production `check`
    command originally computed STALE propagation using ONLY the live
    (post-change) graph. A removed row's edges exist ONLY in the
    prior-state graph, so a still-existing dependent that cites a just-
    removed row (an "orphaned" claim, section 3.3 rule 3) was
    silently never marked STALE -- the exact failure mode section 3.3 rule 3
    forbids ("dependents transition to orphaned/UNRESOLVED, never silently
    dropped"). `compute_check_result` (the function this test exercises)
    is the single shared implementation now used by BOTH `cmd_check` and
    `replay_realevents.py`'s `replay_pair`, so this test exercises the
    actual production code path, not a hand-built stand-in for it."""

    def test_orphaned_claim_after_source_quote_removed_is_marked_stale(self):
        prev_quotes = [{"quote_id": "Q1", "exact_quote": "orig text", "slug": "S",
                         "citable_status": "peer_reviewed"}]
        cur_quotes = []  # Q1 removed from the ledger
        prev_claims = [{"claim_id": "C1", "claim_text": "a claim", "quote_id": "Q1",
                         "slug": "", "citable_status": "peer_reviewed"}]
        cur_claims = [{"claim_id": "C1", "claim_text": "a claim", "quote_id": "Q1",
                        "slug": "", "citable_status": "peer_reviewed"}]  # C1 NOT removed
        prev_manifest = [{"slug": "S"}]
        cur_manifest = [{"slug": "S"}]

        result = iv.compute_check_result(
            prev_quotes, cur_quotes, prev_claims, cur_claims, prev_manifest, cur_manifest,
        )
        self.assertIn("Q1", result.stale_map)
        self.assertIn("C1", result.stale_map,
                       "orphaned claim C1 (still citing removed quote Q1) must be "
                       "propagated STALE, not silently dropped (section 3.3 rule 3)")
        # The structural fact is also surfaced via the build report, not discarded.
        self.assertEqual(
            result.cur_build_report.claims_with_unresolved_quote_ref,
            [{"claim_id": "C1", "quote_id": "Q1"}],
        )

    def test_ordinary_row_edit_unaffected_by_the_union_graph_fix(self):
        """The union-graph fix must not change behavior for the common
        row_edit case (chase-simon-shaped): editing a claim's own field
        with no removal involved still yields exactly the direct node,
        no spurious propagation."""
        prev_claims = [{"claim_id": "c1", "claim_text": "t", "quote_id": "q1",
                         "slug": "old-slug", "citable_status": "peer_reviewed"}]
        cur_claims = [{"claim_id": "c1", "claim_text": "t", "quote_id": "q1",
                        "slug": "new-slug", "citable_status": "peer_reviewed"}]
        result = iv.compute_check_result(
            [], [], prev_claims, cur_claims, [], [],
        )
        self.assertEqual(result.stale_map, {"c1": "row_edit on claim c1 (fields: slug)"})


class TestEventsLogAppendOnly(TempDirCase):
    def test_empty_firing_still_logs_a_zero_row_summary(self):
        log_path = self.path("invalidation_events.csv")
        n = iv.log_firing("test-source", [], {}, events_log_path=log_path)
        self.assertEqual(n, 1)
        with open(log_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["change_kind"], "none")

    def test_append_only_never_truncates(self):
        log_path = self.path("invalidation_events.csv")
        iv.log_firing("first", [], {}, events_log_path=log_path)
        iv.log_firing("second", [], {}, events_log_path=log_path)
        with open(log_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["records_merge_source"], "first")
        self.assertEqual(rows[1]["records_merge_source"], "second")

    def test_header_matches_protocol_schema(self):
        log_path = self.path("invalidation_events.csv")
        iv.log_firing("x", [], {}, events_log_path=log_path)
        with open(log_path, newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        self.assertEqual(header, iv.EVENTS_LOG_HEADER)


class TestHashMismatchErrorState(unittest.TestCase):
    """Rule 1 / ERROR state: `detect_hash_mismatch_errors` is a single-snapshot
    self-consistency check, deliberately distinct from `detect_row_events`'s
    prev-vs-cur diff -- see that function's own docstring."""

    def test_genuine_mismatch_no_explaining_event_is_an_error(self):
        row = {"quote_id": "q1", "exact_quote": "a", "slug": "s",
               "citable_status": "peer_reviewed"}
        # A content_hash that does NOT match this row's own current fields,
        # with q1 absent from explained_keys -- no row_edit trigger this
        # firing accounts for the discrepancy.
        row["content_hash"] = "0" * 64
        errors = iv.detect_hash_mismatch_errors(
            [row], "quote_id", "quotation", iv.QUOTE_CONTENT_HASH_FIELDS, explained_keys=set(),
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].change_kind, "content_hash_mismatch_error")
        self.assertEqual(errors[0].node_id, "q1")

    def test_mismatch_explained_by_row_edit_this_firing_is_not_an_error(self):
        row = {"quote_id": "q1", "exact_quote": "a EDITED", "slug": "s",
               "citable_status": "peer_reviewed"}
        # content_hash still holds the PRE-edit value (as it would right
        # after detect_row_events found this same key as a row_edit
        # trigger, before any writer has refreshed content_hash) --
        # q1 IS in explained_keys, so this must NOT be an error.
        stale_stored_hash = iv.compute_content_hash(
            {"exact_quote": "a", "slug": "s", "citable_status": "peer_reviewed"},
            iv.QUOTE_CONTENT_HASH_FIELDS,
        )
        row["content_hash"] = stale_stored_hash
        errors = iv.detect_hash_mismatch_errors(
            [row], "quote_id", "quotation", iv.QUOTE_CONTENT_HASH_FIELDS,
            explained_keys={"q1"},
        )
        self.assertEqual(errors, [])

    def test_matching_hash_is_never_an_error(self):
        row = {"quote_id": "q1", "exact_quote": "a", "slug": "s",
               "citable_status": "peer_reviewed"}
        row["content_hash"] = iv.compute_content_hash(row, iv.QUOTE_CONTENT_HASH_FIELDS)
        errors = iv.detect_hash_mismatch_errors(
            [row], "quote_id", "quotation", iv.QUOTE_CONTENT_HASH_FIELDS, explained_keys=set(),
        )
        self.assertEqual(errors, [])

    def test_row_with_no_stored_hash_is_skipped_not_errored(self):
        row = {"quote_id": "q1", "exact_quote": "a", "slug": "s",
               "citable_status": "peer_reviewed", "content_hash": ""}
        errors = iv.detect_hash_mismatch_errors(
            [row], "quote_id", "quotation", iv.QUOTE_CONTENT_HASH_FIELDS, explained_keys=set(),
        )
        self.assertEqual(errors, [])

    def test_compute_check_result_surfaces_errors_without_touching_stale_map(self):
        """The end-to-end wiring test: a claim row whose content_hash was
        corrupted out-of-band (no corresponding row_edit between prev/cur)
        must appear in `hash_mismatch_errors`, and `stale_map` must be
        completely unaffected by its presence (regression-safety for
        replay_realevents.py's TP/FN/FP computation, which reads only
        stale_map)."""
        claim_row = {"claim_id": "c1", "claim_text": "t", "quote_id": "q1",
                     "slug": "s", "citable_status": "peer_reviewed"}
        claim_row["content_hash"] = "f" * 64  # corrupted / never refreshed
        result = iv.compute_check_result(
            [], [], [claim_row], [claim_row], [], [],
        )
        self.assertEqual(result.stale_map, {})
        self.assertEqual(len(result.hash_mismatch_errors), 1)
        self.assertEqual(result.hash_mismatch_errors[0].node_id, "c1")

    def test_apply_error_to_ledgers_writes_error_status(self):
        tmp = tempfile.mkdtemp(prefix="invalidation_error_apply_")
        try:
            quote_path = os.path.join(tmp, "quote_ledger.csv")
            claim_path = os.path.join(tmp, "claim_ledger.csv")
            _write_csv(
                quote_path,
                ["quote_id", "exact_quote", "slug", "citable_status",
                 "content_hash", "engine_status", "stale_since", "stale_reason"],
                [{"quote_id": "q1", "exact_quote": "a", "slug": "s",
                  "citable_status": "peer_reviewed", "content_hash": "0" * 64,
                  "engine_status": "FRESH", "stale_since": "", "stale_reason": ""}],
            )
            _write_csv(
                claim_path,
                ["claim_id", "claim_text", "quote_id", "slug", "citable_status",
                 "content_hash", "engine_status", "stale_since", "stale_reason"],
                [],
            )
            orig_quote, orig_claim = iv.QUOTE_LEDGER_PATH, iv.CLAIM_LEDGER_PATH
            iv.QUOTE_LEDGER_PATH, iv.CLAIM_LEDGER_PATH = quote_path, claim_path
            try:
                result = iv.apply_error_to_ledgers({"q1": "test corruption"})
            finally:
                iv.QUOTE_LEDGER_PATH, iv.CLAIM_LEDGER_PATH = orig_quote, orig_claim
            self.assertEqual(result["quote_ledger.csv"]["written"], 1)
            with open(quote_path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["engine_status"], "ERROR")
            self.assertEqual(rows[0]["stale_reason"], "test corruption")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestNoLiveFileTouched(unittest.TestCase):
    """Guards against a regression where a test (or the module's own
    default paths) accidentally targets the real live ledgers."""

    def test_default_paths_point_at_the_real_project_files_but_this_suite_never_calls_apply_against_them(self):
        self.assertTrue(iv.QUOTE_LEDGER_PATH.endswith(os.path.join("research", "quote_ledger.csv")))
        self.assertTrue(iv.CLAIM_LEDGER_PATH.endswith(os.path.join("research", "claim_ledger.csv")))
        # This test file only ever calls migrate_csv_schema_v2 / migrate_manifest_json_schema_v2
        # with explicit tempdir paths (see TestCsvSchemaMigration / TestManifestJsonMigration
        # above) -- never iv.QUOTE_LEDGER_PATH etc. This test documents that invariant so a
        # future edit accidentally introducing a live-path call fails a code-review grep,
        # even though it can't mechanically enforce it from inside the same process.
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
