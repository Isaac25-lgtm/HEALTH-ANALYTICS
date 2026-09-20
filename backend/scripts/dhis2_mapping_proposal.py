"""Generate a reviewable DHIS2 source-mapping proposal for every internal source key.

The indicator catalogue depends on a fixed set of internal source keys. Each one must be bound to
a live DHIS2 item before any programme can be calculated. This command builds *candidates* from
retrieved metadata and writes a coverage matrix; it never approves, applies or persists a mapping.

Why candidates are never auto-approved
--------------------------------------
Name similarity is actively misleading in this instance. ``MR`` (measles-rubella vaccination)
name-matches ``033B-CD10a. Measles - Cases``, a disease-surveillance count, and ``YF`` matches
``Yellow Fever - Cases`` the same way. Binding either would put outbreak counts into a vaccination
coverage indicator. Several keys are also category option combinations of one element rather than
elements of their own: ``105-AN01a. ANC 1st Visit for women`` carries the ``MCH Age`` category
combination, which is where the ANC1 age bands live.

Every candidate therefore carries its evidence — code, name, value type, aggregation type and
category combination — and every row starts at ``review_status: "unreviewed"``.

Usage:
    python scripts/dhis2_mapping_proposal.py --metadata .local/dhis2/metadata-full.json \
        --out .local/dhis2/source-mapping-proposal.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.indicator_catalog import INDICATOR_CATALOG  # noqa: E402

# Tokens that indicate a disease-surveillance element rather than a service/vaccination count.
# A candidate carrying one of these is demoted and labelled, never silently dropped.
_SURVEILLANCE_TOKENS = ("cases", "deaths", "case", "outbreak", "positive", "tested", "suspect")
# Tokens that indicate stock/logistics rather than service delivery.
_STOCK_TOKENS = ("open balance", "closing balance", "received", "stock", "expired", "wastage")

_WORD_RE = re.compile(r"[a-z0-9]+")


def source_keys_of(spec, acc: set[str]) -> None:
    """Collect every internal source key a formula depends on, across all formula shapes."""
    if isinstance(spec, dict):
        for key, value in spec.items():
            if key in {"numerator_keys", "keys", "source_keys"} and isinstance(value, list):
                acc.update(str(item) for item in value)
            elif key in {"key", "source_key"} and isinstance(value, str):
                acc.add(value)
            else:
                source_keys_of(value, acc)
    elif isinstance(spec, list):
        for value in spec:
            source_keys_of(value, acc)


# Words that appear in almost every indicator name and so cannot identify an element.
_ALIAS_STOPWORDS = {
    "coverage", "dropout", "rate", "ratio", "proportion", "percentage", "percent", "to", "and",
    "of", "the", "in", "for", "at", "by", "per", "total", "number", "no", "dose", "doses",
    "reported", "notification", "review", "timely", "months", "month", "years", "year", "women",
    "children", "child", "facility", "facilities", "all", "with", "who", "new", "first", "second",
}


def catalogue_source_keys() -> dict[str, dict]:
    """Every source key, with the indicators and programmes that require it.

    ``alias_terms`` are distinctive words taken from the approved indicator names that depend on
    the key. They exist because the internal key is often an abbreviation the national instance
    does not use: PENTA1's own indicator is named 'DPT-HepB-Hib1 coverage', which is what the
    element is actually called upstream.
    """
    usage: dict[str, dict] = {}
    for indicator in INDICATOR_CATALOG:
        found: set[str] = set()
        source_keys_of(indicator.get("formula_spec"), found)
        for key in found:
            entry = usage.setdefault(
                key, {"indicators": [], "programmes": set(), "indicator_names": [], "alias_terms": set()}
            )
            entry["indicators"].append(indicator["code"])
            entry["programmes"].add(indicator["programme"])
            entry["indicator_names"].append(indicator["name"])
            for token in _WORD_RE.findall(indicator["name"].lower()):
                if len(token) >= 4 and token not in _ALIAS_STOPWORDS and not token.isdigit():
                    entry["alias_terms"].add(token)
    for entry in usage.values():
        entry["programmes"] = sorted(entry["programmes"])
        entry["indicators"] = sorted(entry["indicators"])
        entry["indicator_names"] = sorted(set(entry["indicator_names"]))
        entry["alias_terms"] = sorted(entry["alias_terms"])
        entry["required_by_count"] = len(entry["indicators"])
    return usage


_ORDINALS = {"1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th", "6": "6th", "8": "8th"}


def _tokens(value: str) -> set[str]:
    return set(_WORD_RE.findall((value or "").lower()))


def _key_parts(key: str) -> tuple[set[str], set[str]]:
    """Split an internal key into its alphabetic stems and its numeric qualifiers.

    The stem carries the meaning (``anc``, ``penta``, ``opv``); the number only distinguishes doses
    or visits. Scoring on a bare digit matches thousands of unrelated elements, so the stem must
    match before a number is allowed to contribute anything.
    """
    stems: set[str] = set()
    numbers: set[str] = set()
    for part in key.lower().split("_"):
        if not part:
            continue
        match = re.match(r"^([a-z]+)(\d*)$", part)
        if match:
            if match.group(1):
                stems.add(match.group(1))
            if match.group(2):
                numbers.add(match.group(2))
        elif part.isdigit():
            numbers.add(part)
        else:
            stems.add(part)
    return stems, numbers


def score_candidate(key: str, element: dict, alias_terms: list[str] | None = None) -> tuple[int, list[str]]:
    """Rank one metadata item against one internal key, with the reasons for the rank."""
    reasons: list[str] = []
    score = 0
    code = str(element.get("code") or "")
    name = str(element.get("name") or "")
    lowered = name.lower()

    if code.upper() == key.upper():
        return 100, ["code equals the internal key"]

    stems, numbers = _key_parts(key)
    name_tokens = _tokens(name)
    # Every alphabetic stem must be present. Without this, a key matches on its digit alone and
    # the proposal fills up with unrelated elements that merely mention "1".
    matched_stems = {stem for stem in stems if stem in name_tokens}
    if not matched_stems or matched_stems != stems:
        # The instance may not use the internal abbreviation at all. Fall back to the distinctive
        # words of the approved indicator names that depend on this key.
        aliases = {term for term in (alias_terms or []) if term in name_tokens}
        if not aliases:
            return 0, []
        score = 20 * len(aliases)
        reasons.append(f"matched approved indicator wording {sorted(aliases)}")
        if any(token in lowered for token in _SURVEILLANCE_TOKENS):
            score -= 60
            reasons.append("looks like disease surveillance, not service delivery")
        if any(token in lowered for token in _STOCK_TOKENS):
            score -= 60
            reasons.append("looks like stock/logistics, not service delivery")
        return score, reasons
    score += 25 * len(matched_stems)
    reasons.append(f"name contains every stem {sorted(stems)}")

    if numbers:
        # A dose or visit number may be written as a digit or an ordinal.
        wanted = set()
        for number in numbers:
            wanted.add(number)
            if number in _ORDINALS:
                wanted.add(_ORDINALS[number])
        if wanted & name_tokens:
            score += 20
            reasons.append(f"qualifier {sorted(numbers)} present")
        else:
            score -= 15
            reasons.append(f"qualifier {sorted(numbers)} not found in the name")

    if any(token in lowered for token in _SURVEILLANCE_TOKENS):
        score -= 60
        reasons.append("looks like disease surveillance, not service delivery")
    if any(token in lowered for token in _STOCK_TOKENS):
        score -= 60
        reasons.append("looks like stock/logistics, not service delivery")
    if element.get("domainType") and element["domainType"] != "AGGREGATE":
        score -= 20
        reasons.append(f"domainType is {element['domainType']}")
    return score, reasons


def confidence_of(score: int) -> str:
    """Bands used only to steer review effort; none of them approves anything."""
    if score >= 100:
        return "exact_code"
    if score >= 60:
        return "strong"
    if score >= 30:
        return "weak"
    return "very_weak"


def build_proposal(metadata: dict, *, max_candidates: int) -> dict:
    resources = metadata.get("resources", {})
    elements = [item for item in resources.get("data-elements", {}).get("items", []) if isinstance(item, dict)]
    indicators = [item for item in resources.get("indicators", {}).get("items", []) if isinstance(item, dict)]
    truncated = [name for name, res in resources.items() if res.get("truncated")]

    usage = catalogue_source_keys()
    rows = []
    for key in sorted(usage):
        scored = []
        aliases = usage[key]["alias_terms"]
        for element in elements:
            score, reasons = score_candidate(key, element, aliases)
            if score > 0:
                scored.append((score, element, reasons, "data_element"))
        for indicator in indicators:
            score, reasons = score_candidate(key, indicator, aliases)
            if score > 0:
                scored.append((score, indicator, reasons, "indicator"))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("name"))))
        candidates = []
        for score, item, reasons, kind in scored[:max_candidates]:
            category_combo = item.get("categoryCombo") or {}
            candidates.append(
                {
                    "item_kind": kind,
                    "uid": item.get("id"),
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "value_type": item.get("valueType"),
                    "source_aggregation_type": item.get("aggregationType"),
                    "category_combo": category_combo.get("name"),
                    "category_combo_uid": category_combo.get("id"),
                    "requires_category_option_combo": bool(
                        category_combo.get("name") and category_combo.get("name") != "default"
                    ),
                    "score": score,
                    "confidence": confidence_of(score),
                    "evidence": reasons,
                    "approved": False,
                }
            )
        rows.append(
            {
                "internal_source_key": key,
                "programmes": usage[key]["programmes"],
                "required_by_indicators": usage[key]["indicators"],
                "approved_indicator_names": usage[key]["indicator_names"],
                "alias_terms_searched": usage[key]["alias_terms"],
                "required_by_count": usage[key]["required_by_count"],
                "candidate_count": len(candidates),
                "candidates": candidates,
                "review_status": "unreviewed",
                "approved_uid": None,
                "approved_item_kind": None,
                "approved_category_option_combo": None,
                "approved_aggregation_semantics": None,
                "mapping_version": None,
                "valid_from": None,
                "valid_to": None,
                "unresolved_reason": (
                    "no candidate scored above zero" if not candidates else "awaiting owner review"
                ),
            }
        )

    resolved = [row for row in rows if row["review_status"] == "approved"]
    return {
        "schema": "hpip.dhis2.source-mapping-proposal.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "applied": False,
        "approval_required": True,
        "metadata_generated_at": metadata.get("generated_at"),
        "metadata_truncated_resources": truncated,
        "metadata_is_complete": not truncated,
        "source_key_count": len(rows),
        "approved_count": len(resolved),
        "unresolved_count": len(rows) - len(resolved),
        "keys_without_candidates": [row["internal_source_key"] for row in rows if not row["candidates"]],
        "keys_with_a_strong_candidate": [
            row["internal_source_key"]
            for row in rows
            if any(c["confidence"] in {"exact_code", "strong"} for c in row["candidates"])
        ],
        "warning": (
            "Candidates are ranked suggestions built from names and codes. Name similarity in this "
            "instance maps vaccination keys onto disease-surveillance elements, so every row "
            "requires explicit clinical review before approval."
        ),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata", type=Path, required=True, help="Discovery artifact to read.")
    parser.add_argument("--out", type=Path, help="Write the proposal document here.")
    parser.add_argument("--max-candidates", type=int, default=5)
    args = parser.parse_args(argv)

    if not args.metadata.exists():
        print(json.dumps({"mode": "blocked", "reason": f"{args.metadata} does not exist."}, indent=2))
        return 3
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    proposal = build_proposal(metadata, max_candidates=args.max_candidates)

    summary = {
        "mode": "generated",
        "applied": False,
        "approval_required": True,
        "source_keys": proposal["source_key_count"],
        "keys_with_candidates": proposal["source_key_count"] - len(proposal["keys_without_candidates"]),
        "keys_without_candidates": proposal["keys_without_candidates"],
        "metadata_is_complete": proposal["metadata_is_complete"],
        "metadata_truncated_resources": proposal["metadata_truncated_resources"],
        "output": str(args.out) if args.out else "stdout",
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(proposal, indent=2, sort_keys=True))
    # A proposal built from incomplete metadata must not be mistaken for a usable one.
    return 5 if not proposal["metadata_is_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
