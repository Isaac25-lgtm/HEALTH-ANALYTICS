# MPDSR field candidates for owner confirmation (D-063)

Discovered read-only (GET only) from `https://hmis.health.go.ug` on 2026-09-25. Nothing below is
wired into HPIP. Each row needs an owner decision (accept, replace, or reject) before the MPDSR
event contract is configured. Raw discovery output: `.local/dhis2/mpdsr-programs.json` (gitignored).

## Programs (all event programs without registration)

| Program | UID | Stage | Event date is labelled |
|---|---|---|---|
| HMIS MCH 004 - Maternal Death Notifications | `ZJRDIb1joXP` | `vdKfzGrAVXa` (20 fields) | Death Notification Date |
| HMIS MCH 020 - Maternal Death Review Form | `k7i7qPFQV5n` | `YXed7PnLRco` (284 fields) | Date of notification |
| HMIS MCH 019 - Perinatal Death Notification Form | `gMC8hUMD4Zi` | `XO582jJT6aP` (28 fields) | Date of notification |
| HMIS MCH 017 - Perinatal Death Review Form | `HjkGOlFiGij` | `CGz50G2MY16` (119 fields) | Date of review |

A further program `L2RaWVByDxA` has stages named "017: Perinatal Death Review" and "019: Perinatal
Death Notification"; its metadata request was rejected (validation error) and it is not proposed.

## Candidate bindings

| Contract item | Candidate | Type | Note / question for the owner |
|---|---|---|---|
| Maternal death date | 020-AD06 `WzauwhVOwM0` "Date and time of death" | DATETIME | Preferred (structured). Alternative 004-DN13 `qWAqTjmR6Dj` is **free TEXT**, unsafe to parse |
| Maternal notification date | 004 event date ("Death Notification Date") | event date | |
| Maternal review date | 020 event date | event date | **Labelled "Date of notification" in DHIS2**, not review. Confirm which date is the review date (020-CB5 `FMI7W2kKWMx` "Date" in the committee block is another candidate) |
| Maternal pregnancy outcome | 020-DP27 `aCzqBYUkfDe` "Outcome of pregnancy" | option set (9) | Not Delivered, Live Birth, Fresh/Macerated Still Birth, Abortion/Miscarriage, Termination... |
| Maternal cause of death (coded) | 020-CD* TRUE_ONLY cause items (e.g. `D5E0lOCtKdM`, `c2Sn7Z6RuK4`, `czaXNYJ31Rv`, `p2TjG5L7gfw`) | TRUE_ONLY | Structured and suitable for a cause taxonomy. The HMIS_100 chain-of-events and "Other cause" fields are free text and should stay excluded |
| Perinatal death date | 019-PD17 `lN4hzVULEdF` "Date of Death" | DATE | Review form alternative 017-LB04 `Dq9aH0aZ2wb` (DATETIME) |
| Perinatal notification date | 019 event date ("Date of notification") | event date | |
| Perinatal review date | 017 event date ("Date of review") | event date | |
| Perinatal death type | 019-PD18 `gBhV2LXen0l` "Type of Perinatal Death" | option set | MSB (Macerated Stillbirth), FSB (Fresh Stillbirth), Neonatal Death (0-7 days). Review form: 017-LB39 `TiPl1iLI30H` |
| Perinatal cause of death (coded) | 017-LB53..LB59 TRUE_ONLY items, ICD-labelled (Q80, A33, P36, P15, P22) | TRUE_ONLY | Structured; LB54/LB60 are free text and should stay excluded |
| Avoidable factors | 017-LB61..LB69, 020-AF*a TRUE_ONLY items | TRUE_ONLY | Suitable for aggregate patterns; the "specify"/comment fields are free text and excluded |

## Identifying fields that must never be extracted

Names of the deceased or mother (004-DN02, 019-PD02, 020-CB1), NIN (004-DN21, 020-DD10), village
and residence (004-DN04, 019-PD04, 017-ID03, 020-DD04..DD06), telephone numbers (004-DN17, DN19,
019-PD08, PD23, PD28), names of people handling forms (004-DN18, DN20, 019-PD22, PD25, PD27),
inpatient numbers (017-ID02), and all LONG_TEXT narratives (causes, comments, recommendations).
These stay out of the extraction field list and are never sent to AI (AGENTS.md rule 6).

## Decisions requested

1. Accept or replace each candidate binding above.
2. Which date is the maternal review date (020 event date or 020-CB5)?
3. Whether HPIP should extract the coded cause and avoidable-factor TRUE_ONLY items for aggregate
   cause patterns, together with an approved cause taxonomy (codes, labels, version).
