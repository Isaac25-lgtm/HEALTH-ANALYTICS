# Owner source artifact manifest

Identity and verified structure of the owner-supplied inputs. Large binary/geometry sources stay
on disk and are excluded from ordinary Git by `.gitignore`; this manifest is the tracked record of
what they are. Verified 2026-09-14 with a read-only reader; no source file was modified.

## Population workbook — approved source

| Field | Value |
|---|---|
| Owner-supplied display name | `Uganda_District_City_Populations_2024_2030 (1).xlsx` |
| Filesystem name in this repository | `Uganda_District_City_Populations_2024_2030.xlsx` |
| SHA-256 | `5ae43dca4533347fbb95c3f9b4e08a25c953c90905445614ba7d4e4bd3e75072` |
| Size | 17,980 bytes |
| Tracked in Git | Yes (small, and the approved denominator source) |
| Checksum recorded at receipt | `5AE43DCA…3E75072` — **matches**, so the file is the owner-approved workbook |

Verified structure:

- Sheets: `District_City_Populations` (151 rows), `Population_Use_Guide` (23 rows).
- Header row 4: Administrative Unit, Type, Region, `2024 Census`, `2025 Projection` … `2030 Projection`.
- 135 `District` + 11 `City` = **146 administrative units**, plus one `NATIONAL TOTAL` row.
- Cities: Arua, Fort Portal, Gulu, Hoima, Jinja, Kampala Capital City, Lira, Masaka, Mbale, Mbarara, Soroti.
- `Region` column holds the four broad statistical regions (Central, Eastern, Northern, Western), not
  health sub-regions.
- Source note: 2024 = final NPHC census; 2025–2030 = UBOS district/city mid-year projections.
- Guide rules: calendar year N uses population year N; FY YYYY/YY+1 uses YYYY. The guide does not
  state month, quarter or half-year rules (see the owner decision recorded in DECISION_REGISTER).

## Boundary candidates — not imported

| File | SHA-256 | Size | Type | Features |
|---|---|---|---|---|
| `UGANDA_DISTRICT.json` | `5a6024f5438cf38bbf1ea822ed4bc1d900005288585bd55294b29d730d7027b8` | 47,405,738 B | GeoJSON FeatureCollection | 146 |
| `UGANDA_SUBCOUNTIES.json` | `49c0d09380c5d9e7db824806217f1c8a6a072d7439342609b83dfdd2d5d29936` | 163,183,068 B | GeoJSON FeatureCollection | 2,190 |
| `UGANDA_DISTRICTS.json` | `9b406b469445e7be1f512a0e6f2a0726c743dc1ce7cb7452feb7ab8ce7f9cad5` | 19,842,192 B | **Esri JSON** (`esriGeometryPolygon`, wkid 4326) | 146 |

- District properties: `FID`, `District`, `RCode`. Sub-county properties: `FID`, `OBJECTID`,
  `Sub_County`, `County`, `District`, `RCode`, `Shape_Leng`, `Shape_Area`, `FScode`.
- `UGANDA_DISTRICTS.json` is an Esri JSON export, not GeoJSON, and must never be treated as the
  canonical layer; it is a comparison source only.
- Details, duplicates and validation findings: `docs/reconciliation/GEOJSON_RECONCILIATION.md`.

## Reference documents

| File | SHA-256 | Size | Tracked in Git |
|---|---|---|---|
| `index(1).html` | `0ec087bdd9e294fcba7b7a9c86d37ff139086fa00573f0be126cfe2845ec4ad1` | 310,811 B | Yes (visual/interaction reference only) |
| `ULTIMATE_IDE_HANDOFF_…​.md` | `4a90f8a088946e48b7920e0e9bb4b54d9cc542bedd50c1b9ab4da88efcfb10df` | 450,000 B | Yes |
| `Uganda_Health_…_Blueprint_v1_2 (3).docx` | `ce035b864ca116cb3740e6814a44ebe0062ad24ace8b4841a29e3dfb0b753b80` | 11,206,602 B | No (10.7 MB binary; kept on disk) |

`index(1).html` is a visual and interaction reference. Its demonstration values, populations,
thresholds, formulas and client-side algorithms are not authoritative and must never reach
production code paths (enforced by `backend/tests/test_prototype_contract.py` and
`frontend/src/test/prototype-contract.test.ts`).
