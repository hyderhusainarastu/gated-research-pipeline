#!/usr/bin/env python3
"""
mutation_harness.py -- a generalized mutation-testing pattern for scoring
a verification checker against seeded faults. See README.md in this
directory for the rationale and the honesty rules for reporting a score.

This file ships a runnable, self-contained example: eight mutation
classes, a toy `example_checker` (a naive substring-match "does this
excerpt appear in this source" checker, standing in for whatever real
verification logic your project uses), and a harness that generates
mutants, runs the checker, and scores detection per class.

Wire your own checker in by replacing `example_checker` with a call into
your project's real verification logic, and replace `load_source_pool`
with a real read of your evidence/claim ledgers. Everything else --
the mutation classes, the harness loop, the scoring/report logic -- is
reusable as-is.

No third-party dependencies. Python 3 standard library only.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

PROTOCOL_SEED = 20270101  # fixed for reproducibility; change deliberately, not silently


@dataclass
class Mutant:
    mutation_class: str
    claim_id: str
    original_text: str
    mutated_text: str
    source_id: str
    ground_truth_detectable: bool  # should a correct checker flag this mutant?
    description: str


@dataclass
class MutationResult:
    mutant: Mutant
    checker_flagged: bool
    correct: bool  # checker_flagged == ground_truth_detectable

    def to_dict(self) -> dict:
        return {
            "mutation_class": self.mutant.mutation_class,
            "claim_id": self.mutant.claim_id,
            "description": self.mutant.description,
            "ground_truth_detectable": self.mutant.ground_truth_detectable,
            "checker_flagged": self.checker_flagged,
            "correct": self.correct,
        }


# ---------------------------------------------------------------------------
# Toy source pool -- replace load_source_pool() with a real read of your
# evidence ledger; each entry needs, at minimum, an id, a source id, and a
# genuine excerpt/claim text.
# ---------------------------------------------------------------------------

def load_source_pool() -> List[dict]:
    """Returns a list of {"claim_id", "source_id", "source_text", "excerpt"}.
    This stub returns a small illustrative fixture; replace with a real
    ledger read in your own project."""
    return [
        {"claim_id": "c1", "source_id": "s1", "source_text": "the observed effect was small but reliably positive across trials",
         "excerpt": "the observed effect was small but reliably positive"},
        {"claim_id": "c2", "source_id": "s2", "source_text": "no significant difference was found between the two conditions",
         "excerpt": "no significant difference was found"},
        {"claim_id": "c3", "source_id": "s3", "source_text": "participants reported higher satisfaction with the revised interface",
         "excerpt": "participants reported higher satisfaction"},
        {"claim_id": "c4", "source_id": "s4", "source_text": "the method scales linearly with corpus size in the tested range",
         "excerpt": "the method scales linearly with corpus size"},
    ]


# ---------------------------------------------------------------------------
# Mutation classes
# ---------------------------------------------------------------------------

ANTONYM_MAP = {
    "small": "large", "large": "small", "positive": "negative", "negative": "positive",
    "significant": "insignificant", "higher": "lower", "lower": "higher",
    "linearly": "unpredictably", "reliably": "unreliably",
}


def mutate_fabricated_evidence(row: dict, rng: random.Random) -> Mutant:
    fabricated = "the results were inconclusive due to an unrelated methodological error"
    return Mutant(
        mutation_class="fabricated_evidence", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text=fabricated, source_id=row["source_id"],
        ground_truth_detectable=True,
        description="excerpt replaced with plausible but invented text not present in the source",
    )


def mutate_truncation(row: dict, rng: random.Random) -> Mutant:
    words = row["excerpt"].split()
    cut = max(1, len(words) // 2)
    truncated = " ".join(words[:cut])
    return Mutant(
        mutation_class="truncation", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text=truncated, source_id=row["source_id"],
        ground_truth_detectable=True,
        description=f"excerpt truncated from {len(words)} to {cut} words, changing its meaning",
    )


def mutate_polarity_reversal(row: dict, rng: random.Random) -> Mutant:
    text = row["excerpt"]
    for word, antonym in ANTONYM_MAP.items():
        if re.search(rf"\b{word}\b", text):
            reversed_text = re.sub(rf"\b{word}\b", antonym, text, count=1)
            return Mutant(
                mutation_class="polarity_reversal", claim_id=row["claim_id"],
                original_text=text, mutated_text=reversed_text, source_id=row["source_id"],
                ground_truth_detectable=True,
                description=f"'{word}' replaced with its antonym '{antonym}'",
            )
    # Fallback per the antonym-map convention: insert a negation near the
    # midpoint if no mapped word is present.
    idx = len(text.split()) // 2
    words = text.split()
    words.insert(idx, "not")
    return Mutant(
        mutation_class="polarity_reversal", claim_id=row["claim_id"],
        original_text=text, mutated_text=" ".join(words), source_id=row["source_id"],
        ground_truth_detectable=True, description="no antonym match; 'not' inserted at midpoint",
    )


def mutate_omitted_source_item(row: dict, rng: random.Random) -> Mutant:
    return Mutant(
        mutation_class="omitted_source_item", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text="", source_id="MISSING",
        ground_truth_detectable=True,
        description="source item omitted entirely; claim now cites a source id that does not exist",
    )


def mutate_attribution_error(row: dict, rng: random.Random, pool: List[dict]) -> Mutant:
    other = rng.choice([r for r in pool if r["source_id"] != row["source_id"]] or [row])
    return Mutant(
        mutation_class="attribution_error", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text=row["excerpt"], source_id=other["source_id"],
        ground_truth_detectable=True,
        description=f"genuine excerpt kept verbatim but attributed to the wrong source ({other['source_id']} instead of {row['source_id']})",
    )


def mutate_citation_retained_claim_changed(row: dict, rng: random.Random) -> Mutant:
    changed_claim = "this establishes a causal mechanism, not merely a correlation"
    return Mutant(
        mutation_class="citation_retained_claim_changed", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text=row["excerpt"], source_id=row["source_id"],
        ground_truth_detectable=True,
        description=(
            f"citation and excerpt unchanged, but the claim text attached to it now reads "
            f"{changed_claim!r} -- a checker that only verifies the excerpt resolves, without "
            f"checking whether the excerpt supports the CLAIM, will miss this"
        ),
    )


def mutate_stale_status(row: dict, rng: random.Random) -> Mutant:
    return Mutant(
        mutation_class="stale_status", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text=row["excerpt"] + " [SOURCE SINCE CORRECTED]",
        source_id=row["source_id"], ground_truth_detectable=True,
        description="status still reads VERIFIED after the underlying source was corrected -- a checker that trusts a stored status without re-deriving it will miss this",
    )


def mutate_contradictory_evidence(row: dict, rng: random.Random) -> Mutant:
    contradiction = row["excerpt"].replace("positive", "negative").replace("higher", "lower") \
        if row["excerpt"] != mutate_polarity_reversal(row, rng).mutated_text else row["excerpt"] + " (but see the contradicting finding below)"
    return Mutant(
        mutation_class="contradictory_evidence", claim_id=row["claim_id"],
        original_text=row["excerpt"], mutated_text=contradiction, source_id=row["source_id"],
        ground_truth_detectable=True,
        description="a second, contradicting piece of evidence attached to the same claim",
    )


MUTATION_CLASSES: Dict[str, Callable] = {
    "fabricated_evidence": mutate_fabricated_evidence,
    "truncation": mutate_truncation,
    "polarity_reversal": mutate_polarity_reversal,
    "omitted_source_item": mutate_omitted_source_item,
    "attribution_error": lambda row, rng, pool=None: mutate_attribution_error(row, rng, pool or [row]),
    "citation_retained_claim_changed": mutate_citation_retained_claim_changed,
    "stale_status": mutate_stale_status,
    "contradictory_evidence": mutate_contradictory_evidence,
}


def generate_mutants(pool: List[dict], n_per_class: int, seed: int) -> List[Mutant]:
    rng = random.Random(seed)
    mutants: List[Mutant] = []
    for cls_name, fn in MUTATION_CLASSES.items():
        for _ in range(n_per_class):
            row = rng.choice(pool)
            if cls_name == "attribution_error":
                mutants.append(fn(row, rng, pool))
            else:
                mutants.append(fn(row, rng))
    return mutants


# ---------------------------------------------------------------------------
# Example checker -- replace with your project's real verification logic.
# This one is deliberately naive (exact-substring only) so its known blind
# spots are visible in the results below, illustrating why disclosure
# matters more than a high aggregate score.
# ---------------------------------------------------------------------------

def example_checker(mutant: Mutant, source_texts: Dict[str, str]) -> bool:
    """Returns True if the checker FLAGS this mutant as a problem (i.e.
    detects the fault). A naive substring checker: does the mutated text
    appear verbatim in the (real) text of the source it claims to cite?

    Known, disclosed blind spots of this toy checker (do not silently
    "fix" these away without updating the docstring, README, and
    KNOWN_BLIND_SPOTS below -- they exist to demonstrate why mutation
    testing matters, including surfacing blind spots nobody anticipated
    before running the suite):
      - citation_retained_claim_changed: this checker never looks at the
        claim text at all, only the excerpt, so it CANNOT catch this
        class by construction. Expect 0% detection here.
      - stale_status: this checker has no notion of a status column or a
        "since corrected" timestamp, so it also cannot catch this class
        by construction.
      - truncation: a truncated excerpt is, definitionally, still a
        substring of the original text it was cut from -- a pure
        substring-containment checker cannot distinguish "shorter but
        still verbatim" from "shorter and now misleading." This is a
        genuine limitation the suite surfaces, not a bug in the harness:
        it is exactly the kind of blind spot mutation testing exists to
        find.
      - omitted_source_item: this checker's empty-mutated-text case is a
        trivial substring of any text (including another empty string),
        so a naive containment test cannot flag it either. A real
        checker needs an explicit "does this source id exist at all"
        check, which this toy example deliberately omits.
    """
    source_text = source_texts.get(mutant.source_id, "")
    if mutant.mutation_class in ("citation_retained_claim_changed", "stale_status"):
        return False  # known blind spot, by construction -- see docstring
    return mutant.mutated_text not in source_text


def run_harness(n_per_class: int, out_dir: Path, seed: int = PROTOCOL_SEED) -> dict:
    pool = load_source_pool()
    source_texts = {row["source_id"]: row["source_text"] for row in pool}
    mutants = generate_mutants(pool, n_per_class, seed)

    results: List[MutationResult] = []
    for m in mutants:
        flagged = example_checker(m, source_texts)
        results.append(MutationResult(mutant=m, checker_flagged=flagged, correct=(flagged == m.ground_truth_detectable)))

    by_class: Dict[str, List[MutationResult]] = {}
    for r in results:
        by_class.setdefault(r.mutant.mutation_class, []).append(r)

    class_scores = {
        cls: {
            "n": len(rs),
            "n_correct": sum(1 for r in rs if r.correct),
            "detection_rate": sum(1 for r in rs if r.correct) / len(rs) if rs else None,
        }
        for cls, rs in by_class.items()
    }
    overall = sum(1 for r in results if r.correct) / len(results) if results else None

    report = {
        "seed": seed,
        "n_per_class": n_per_class,
        "n_total_mutants": len(results),
        "overall_detection_rate": overall,
        "class_scores": class_scores,
        "known_blind_spots": [
            "citation_retained_claim_changed (checker never inspects claim text)",
            "stale_status (checker has no status/timestamp model)",
            "truncation (a truncated excerpt is still a substring of the original)",
            "omitted_source_item (empty text is a trivial substring match)",
        ],
        "results": [r.to_dict() for r in results],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mutation_results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "mutation_results.md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    return report


def render_markdown(report: dict) -> str:
    lines = ["# Mutation-harness results", ""]
    lines.append(f"Seed: `{report['seed']}` | n per class: {report['n_per_class']} | total mutants: {report['n_total_mutants']}")
    lines.append("")
    overall = report["overall_detection_rate"]
    lines.append(f"**Overall detection rate: {overall:.1%}**" if overall is not None else "**Overall detection rate: n/a**")
    lines.append("")
    lines.append("| Class | n | correct | detection rate |")
    lines.append("|---|---|---|---|")
    for cls, s in sorted(report["class_scores"].items()):
        rate = f"{s['detection_rate']:.1%}" if s["detection_rate"] is not None else "n/a"
        lines.append(f"| {cls} | {s['n']} | {s['n_correct']} | {rate} |")
    lines.append("")
    lines.append("**Known, disclosed blind spots (not silently dropped from the denominator):**")
    for item in report["known_blind_spots"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--smoke", action="store_true", help="n=2/class self-test.")
    p.add_argument("--n-per-class", type=int, default=None, help="Override n per class (default: 2 with --smoke, else 10).")
    p.add_argument("--out-dir", default="results", help="Output directory for mutation_results.{json,md}.")
    p.add_argument("--seed", type=int, default=PROTOCOL_SEED)
    args = p.parse_args(argv)

    n = args.n_per_class if args.n_per_class is not None else (2 if args.smoke else 10)
    report = run_harness(n, Path(args.out_dir), seed=args.seed)
    print(json.dumps({"overall_detection_rate": report["overall_detection_rate"], "n_total_mutants": report["n_total_mutants"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
