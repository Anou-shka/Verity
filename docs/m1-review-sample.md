# M1 hand-check: 12 values to check against the 10-Ks

Open each filing, find the line, and tick the box if Verity's value matches. These are **different** from the 25 values already pinned in `tests/test_xbrl.py` (VRT, ETN, JCI, TT, POWL), so together they cover all 10 companies.

| # | Company | FY | Metric | Verity value | XBRL concept used | Period | Filing (accession) | Your check |
|---|---|---|---|---:|---|---|---|---|
| 1 | VRT | 2024 | net_income | 495.8m | `NetIncomeLoss` | 2024-01-01..2024-12-31 | [0001674101-26-000008](https://www.sec.gov/Archives/edgar/data/1674101/000167410126000008/vrt-20251231.htm) | ☐ |
| 2 | NVT | 2025 | revenue | 3,893.1m | `RevenueFromContractWithCustomerExcludingAssessedTax` | 2025-01-01..2025-12-31 | [0001628280-26-008608](https://www.sec.gov/Archives/edgar/data/1720635/000162828026008608/nvt-20251231.htm) | ☐ |
| 3 | NVT | 2025 | total_debt | 1,559.8m | `LongTermDebtNoncurrent + DebtCurrent` | 2025-12-31 | [0001628280-26-008608](https://www.sec.gov/Archives/edgar/data/1720635/000162828026008608/nvt-20251231.htm) | ☐ |
| 4 | MOD | 2026 | revenue | 3,181.1m | `RevenueFromContractWithCustomerExcludingAssessedTax` | 2025-04-01..2026-03-31 | [0001104659-26-066795](https://www.sec.gov/Archives/edgar/data/67347/000110465926066795/mod-20260331x10k.htm) | ☐ |
| 5 | MOD | 2026 | operating_income | 342.4m | `OperatingIncomeLoss` | 2025-04-01..2026-03-31 | [0001104659-26-066795](https://www.sec.gov/Archives/edgar/data/67347/000110465926066795/mod-20260331x10k.htm) | ☐ |
| 6 | HUBB | 2025 | eps_diluted | 16.54 | `EarningsPerShareDiluted` | 2025-01-01..2025-12-31 | [0001628280-26-007500](https://www.sec.gov/Archives/edgar/data/48898/000162828026007500/hubb-20251231.htm) | ☐ |
| 7 | HUBB | 2025 | total_debt | 2,325.4m | `LongTermDebtNoncurrent + DebtCurrent` | 2025-12-31 | [0001628280-26-007500](https://www.sec.gov/Archives/edgar/data/48898/000162828026007500/hubb-20251231.htm) | ☐ |
| 8 | GEV | 2025 | revenue | 38,068.0m | `RevenueFromContractWithCustomerExcludingAssessedTax` | 2025-01-01..2025-12-31 | [0001996810-26-000015](https://www.sec.gov/Archives/edgar/data/1996810/000199681026000015/gev-20251231.htm) | ☐ |
| 9 | GEV | 2025 | cash | 8,848.0m | `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` ⚠ | 2025-12-31 | [0001996810-26-000015](https://www.sec.gov/Archives/edgar/data/1996810/000199681026000015/gev-20251231.htm) | ☐ |
| 10 | SMCI | 2026 | net_income | 2,230.5m | `NetIncomeLoss` | 2025-07-01..2026-06-30 | [0001375365-26-000022](https://www.sec.gov/Archives/edgar/data/1375365/000137536526000022/smci-20260630.htm) | ☐ |
| 11 | SMCI | 2026 | operating_cash_flow | -6,809.9m | `NetCashProvidedByUsedInOperatingActivities` | 2025-07-01..2026-06-30 | [0001375365-26-000022](https://www.sec.gov/Archives/edgar/data/1375365/000137536526000022/smci-20260630.htm) | ☐ |
| 12 | ETN | 2025 | capex | 919.0m | `PaymentsToAcquirePropertyPlantAndEquipment` | 2025-01-01..2025-12-31 | [0001551182-26-000007](https://www.sec.gov/Archives/edgar/data/1551182/000155118226000007/etn-20251231.htm) | ☐ |

⚠ GEV only tags cash *including restricted cash*. Check whether the balance sheet shows a separate restricted-cash amount. If it does, we should decide whether to subtract it.

Worth a look while you're in the filings: SMCI's operating cash flow is negative 6.8bn in a year when revenue was 39.1bn. Is that working capital (inventory build)? It will matter for the note.
