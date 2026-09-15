# Population workbook reconciliation

Generated 2026-09-15T12:23:57.938209+00:00 by `scripts/import_population_workbook.py` (hpip-population-workbook-2). Read-only: the workbook was not modified.

## Source identity

| Field | Value |
|---|---|
| Owner-supplied display name | `Uganda_District_City_Populations_2024_2030 (1).xlsx` |
| Filesystem name | `Uganda_District_City_Populations_2024_2030.xlsx` |
| SHA-256 | `5AE43DCA4533347FBB95C3F9B4E08A25C953C90905445614BA7D4E4BD3E75072` |
| Checksum verified | True |
| Sheet | `District_City_Populations` |
| Administrative units | 146 (135 districts, 11 cities) |
| Years | 2024, 2025, 2026, 2027, 2028, 2029, 2030 |
| Population cells | 1022 |

## Structure validation

- No differences from the expected structure (135 districts + 11 cities, 2024-2030).

## Derived national totals

National population is **derived** as the sum of the 146 district and city rows and compared with the workbook's own total row. It is never hard-coded.

| Year | Derived total | Workbook total row | Match |
|---|---|---|---|
| 2024 | 45,905,417 | 45,905,417 | yes |
| 2025 | 48,152,090 | 48,152,090 | yes |
| 2026 | 49,554,040 | 49,554,040 | yes |
| 2027 | 50,969,560 | 50,969,560 | yes |
| 2028 | 52,397,490 | 52,397,490 | yes |
| 2029 | 53,835,020 | 53,835,020 | yes |
| 2030 | 55,280,260 | 55,280,260 | yes |

## Broad-region totals

| Region | 2024 | 2025 | 2026 | 2027 | 2028 | 2029 | 2030 |
|---|---|---|---|---|---|---|---|
| Central | 12,969,646 | 13,739,320 | 14,096,850 | 14,454,120 | 14,810,240 | 15,164,940 | 15,519,800 |
| Eastern | 11,403,222 | 11,904,880 | 12,298,090 | 12,698,260 | 13,105,080 | 13,517,520 | 13,930,030 |
| Northern | 9,955,990 | 10,388,100 | 10,692,930 | 10,998,150 | 11,306,740 | 11,617,940 | 11,934,760 |
| Western | 11,576,559 | 12,119,790 | 12,466,170 | 12,819,030 | 13,175,430 | 13,534,620 | 13,895,670 |

Regions are the workbook's four broad statistical regions. They are descriptive metadata for reconciliation only, never an analytical parent, and never health sub-regions. Health sub-region totals are not calculated because no approved membership mapping exists.

## Organisation-unit crosswalk

Candidate matches were matched only against synthetic development fixtures, so **no match below is a production mapping**.

| Match state | Units |
|---|---|
| `matched_exact` | 3 |
| `unmatched` | 143 |

| Measure | Units |
|---|---|
| Reconciliation matched (exact or approved alias) | 3 |
| Reconciliation unmatched | 143 |
| Production resolved | 0 |
| **Production unresolved** | **146** of 146 |

Only a match against an authoritative, owner-approved hierarchy reduces production-unresolved units. Reconciliation matches against anything else are candidates only.

### Non-production candidates

These names matched synthetic or unapproved organisation units. They are **not** production mappings and create no denominator.

| Row | Source unit | Type | Matched state | Candidate organisation unit |
|---|---|---|---|---|
| 78 | Kitgum | District | `matched_exact` (non-production candidate) | Kitgum |
| 131 | Pader | District | `matched_exact` (non-production candidate) | Pader |
| 143 | Soroti | District | `matched_exact` (non-production candidate) | Soroti |

### Units needing an explicit decision

| Row | Source unit | Type | Region | State | Detail |
|---|---|---|---|---|---|
| 5 | Abim | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 6 | Adjumani | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 7 | Agago | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 8 | Alebtong | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 9 | Amolatar | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 10 | Amudat | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 11 | Amuria | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 12 | Amuru | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 13 | Apac | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 14 | Arua | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 15 | Arua City | City | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 16 | Budaka | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 17 | Bududa | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 18 | Bugiri | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 19 | Bugweri | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 20 | Buhweju | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 21 | Buikwe | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 22 | Bukedea | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 23 | Bukomansimbi | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 24 | Bukwo | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 25 | Bulambuli | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 26 | Buliisa | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 27 | Bundibugyo | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 28 | Bunyangabu | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 29 | Bushenyi | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 30 | Busia | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 31 | Butaleja | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 32 | Butambala | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 33 | Butebo | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 34 | Buvuma | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 35 | Buyende | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 36 | Dokolo | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 37 | Fort Portal City | City | Western | `unmatched` | No organisation unit has this exact name and type. |
| 38 | Gomba | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 39 | Gulu | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 40 | Gulu City | City | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 41 | Hoima | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 42 | Hoima City | City | Western | `unmatched` | No organisation unit has this exact name and type. |
| 43 | Ibanda | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 44 | Iganga | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 45 | Isingiro | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 46 | Jinja | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 47 | Jinja City | City | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 48 | Kaabong | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 49 | Kabale | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 50 | Kabarole | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 51 | Kaberamaido | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 52 | Kagadi | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 53 | Kakumiro | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 54 | Kalaki | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 55 | Kalangala | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 56 | Kaliro | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 57 | Kalungu | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 58 | Kampala Capital City | City | Central | `unmatched` | No organisation unit has this exact name and type. |
| 59 | Kamuli | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 60 | Kamwenge | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 61 | Kanungu | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 62 | Kapchorwa | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 63 | Kapelebyong | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 64 | Karenga | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 65 | Kasese | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 66 | Kassanda | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 67 | Katakwi | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 68 | Kayunga | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 69 | Kazo | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 70 | Kibaale | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 71 | Kiboga | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 72 | Kibuku | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 73 | Kikuube | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 74 | Kiruhura | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 75 | Kiryandongo | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 76 | Kisoro | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 77 | Kitagwenda | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 79 | Koboko | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 80 | Kole | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 81 | Kotido | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 82 | Kumi | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 83 | Kwania | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 84 | Kween | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 85 | Kyankwanzi | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 86 | Kyegegwa | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 87 | Kyenjojo | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 88 | Kyotera | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 89 | Lamwo | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 90 | Lira | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 91 | Lira City | City | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 92 | Luuka | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 93 | Luweero | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 94 | Lwengo | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 95 | Lyantonde | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 96 | Madi-Okollo | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 97 | Manafwa | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 98 | Maracha | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 99 | Masaka | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 100 | Masaka City | City | Central | `unmatched` | No organisation unit has this exact name and type. |
| 101 | Masindi | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 102 | Mayuge | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 103 | Mbale | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 104 | Mbale City | City | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 105 | Mbarara | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 106 | Mbarara City | City | Western | `unmatched` | No organisation unit has this exact name and type. |
| 107 | Mitooma | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 108 | Mityana | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 109 | Moroto | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 110 | Moyo | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 111 | Mpigi | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 112 | Mubende | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 113 | Mukono | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 114 | Nabilatuk | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 115 | Nakapiripirit | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 116 | Nakaseke | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 117 | Nakasongola | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 118 | Namayingo | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 119 | Namisindwa | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 120 | Namutumba | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 121 | Napak | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 122 | Nebbi | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 123 | Ngora | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 124 | Ntoroko | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 125 | Ntungamo | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 126 | Nwoya | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 127 | Obongi | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 128 | Omoro | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 129 | Otuke | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 130 | Oyam | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 132 | Pakwach | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 133 | Pallisa | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 134 | Rakai | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 135 | Rubanda | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 136 | Rubirizi | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 137 | Rukiga | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 138 | Rukungiri | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 139 | Rwampara | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 140 | Serere | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 141 | Sheema | District | Western | `unmatched` | No organisation unit has this exact name and type. |
| 142 | Sironko | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 144 | Soroti City | City | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 145 | Ssembabule | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 146 | Terego | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 147 | Tororo | District | Eastern | `unmatched` | No organisation unit has this exact name and type. |
| 148 | Wakiso | District | Central | `unmatched` | No organisation unit has this exact name and type. |
| 149 | Yumbe | District | Northern | `unmatched` | No organisation unit has this exact name and type. |
| 150 | Zombo | District | Northern | `unmatched` | No organisation unit has this exact name and type. |

### Named units the owner asked us to watch

| Source unit | State | Candidate organisation unit | Note |
|---|---|---|---|
| Gulu | `unmatched` | — | No organisation unit has this exact name and type. |
| Gulu City | `unmatched` | — | No organisation unit has this exact name and type. |
| Kampala Capital City | `unmatched` | — | No organisation unit has this exact name and type. |
| Manafwa | `unmatched` | — | No organisation unit has this exact name and type. |

## Rules that still apply

- No alias is approved because two names look similar; each needs a recorded decision by a second reviewer.
- Staged rows are not denominators. Applying creates DRAFT versions only, and approval is a separate audited step.
- Sub-county and facility populations are never derived from this workbook.
