"""Approved MPDSR cause taxonomy.

Cause values are stored and presented only as codes from an explicitly approved taxonomy.
No taxonomy has been supplied by the owner (D-048 allows MPDSR cause analysis to stay
disabled), so ``APPROVED_CAUSE_TAXONOMY`` is ``None``: every cause value is dropped at
ingestion and cause presentation stays withheld.

Configuring a taxonomy is a governance change reviewed in code, not a runtime setting. Codes
are never inferred from free text, never fuzzy-matched and never derived from labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A short code such as an ICD-MM group ("O72") or a programme category key ("OBST_HAEM").
CAUSE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.]{0,31}$")


@dataclass(frozen=True)
class CauseTaxonomy:
    version: str
    approval_reference: str
    labels: dict[str, str]

    def __post_init__(self) -> None:
        if not self.version or not self.approval_reference:
            raise ValueError("A cause taxonomy needs a version and an approval reference.")
        invalid = [code for code in self.labels if not CAUSE_CODE_PATTERN.fullmatch(code)]
        if invalid:
            raise ValueError("Cause taxonomy codes must be short upper-case codes.")

    def contains(self, code: object) -> bool:
        return isinstance(code, str) and CAUSE_CODE_PATTERN.fullmatch(code) is not None and code in self.labels

    def label(self, code: str) -> str:
        return self.labels[code]


# Owner input required. Leave None until an approved taxonomy (codes, labels, version and the
# approval reference) is supplied; see docs/project-context/OPEN_ITEMS.md.
APPROVED_CAUSE_TAXONOMY: CauseTaxonomy | None = None


def current_cause_taxonomy() -> CauseTaxonomy | None:
    return APPROVED_CAUSE_TAXONOMY
