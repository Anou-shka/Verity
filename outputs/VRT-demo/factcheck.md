# Fact-check log: VRT (rules mode)

| Round | Claims | Verified | Wrong | Unverifiable |
|---|---:|---:|---:|---:|
| 0 | 26 | 22 | 4 | 0 |
| 1 | 25 | 25 | 0 | 0 |

Run: 0 LLM calls (0 from cache), 0 input + 0 output tokens, $0.0000, 23 tool calls, 2.14s.

| Claim | Status | Source | Note |
|---|---|---|---|
| 27.7% | verified | S2: VRT FY2025 revenue growth = 27.7% (derived; revenue / revenue_prior_year - 1) |  |
| $10,229.9m | verified | S1: VRT FY2025 revenue = $10,229.9m (xbrl; 0001674101-26-000008) |  |
| $8,011.8m | verified | S16: VRT FY2024 revenue = $8,011.8m (xbrl; 0001674101-26-000008) |  |
| $1,332.8m | verified | S6: VRT FY2025 net income = $1,332.8m (xbrl; 0001674101-26-000008) |  |
| $3.41 | verified | S7: VRT FY2025 diluted EPS = $3.41 (xbrl; 0001674101-26-000008) |  |
| $2,138.3m | verified | S8: VRT FY2025 EBITDA = $2,138.3m (derived; operating_income + d_and_a) |  |
| 36.3% | verified | S3: VRT FY2025 gross margin = 36.3% (derived; gross_profit / revenue) |  |
| 36.6% | verified | S17: VRT FY2024 gross margin = 36.6% (derived; gross_profit / revenue) |  |
| 17.9% | verified | S5: VRT FY2025 EBIT margin = 17.9% (derived; operating_income / revenue) |  |
| 17.1% | corrected | S18: VRT FY2024 EBIT margin = 17.1% (derived; operating_income / revenue) |  |
| 30.2% | verified | S9: VRT FY2025 ROIC = 30.2% (derived; operating_income * (1 - tax_rate) / average(equity + debt - cash)) |  |
| $1,728.4m | verified | S11: VRT FY2025 cash = $1,728.4m (xbrl; 0001674101-26-000008) |  |
| $2,913.0m | verified | S12: VRT FY2025 total debt = $2,913.0m (xbrl; 0001674101-26-000008) |  |
| $1,184.6m | verified | S13: VRT FY2025 net debt = $1,184.6m (derived; total_debt - cash) |  |
| $2,113.8m | verified | S14: VRT FY2025 operating cash flow = $2,113.8m (xbrl; 0001674101-26-000008) |  |
| $220.0m | corrected | S15: VRT FY2025 capex = $220.0m (xbrl; 0001674101-26-000008) |  |
| $206.42 | verified | S19: VRT share price = $206.42 (price; 2026-10-16) |  |
| 37.7x | verified | S25: VRT FY2025 EV/EBITDA = 37.7x (valuation; ev / ebitda (LFY)) |  |
| 24.7x | verified | S126:  peer median EV/EBITDA = 24.7x (computed; median(ev_ebitda) over 9 peers) |  |
| 7.9x | corrected | S24: VRT FY2025 EV/Sales = 7.9x (valuation; ev / revenue (LFY)) |  |
| 4.9x | verified | S127:  peer median EV/Sales = 4.9x (computed; median(ev_sales) over 9 peers) |  |
| 60.5x | verified | S26: VRT FY2025 P/E = 60.5x (valuation; price / eps_diluted (LFY, split-adjusted)) |  |
| 33.3x | verified | S128:  peer median P/E = 33.3x (computed; median(pe) over 9 peers) |  |
| 17.9% | verified | S5: VRT FY2025 EBIT margin = 17.9% (derived; operating_income / revenue) |  |
| 15.8% | verified | S129:  peer median EBIT margin = 15.8% (computed; median(ebit_margin) over 9 peers) |  |
| $4,784.6m | removed (fabricated) | S16: VRT FY2024 revenue = $8,011.8m (xbrl; 0001674101-26-000008) | value: source says $8,011.8m; year: source is FY2024, text says FY2025; the text does not describe revenue |

## Quotes

| Quote | Status | Filing |
|---|---|---|
| Vertiv is a global leader in critical digital infrastructure for applications in data cent… | verified | 0001674101-26-000008 |
| We may not realize all of the sales expected from our backlog of orders and contracts.… | verified | 0001674101-26-000008 |
| Any disruption or consolidation of our customers’ markets or reduction in customer spendin… | verified | 0001674101-26-000008 |
| Larger customers often require terms and conditions that are more favorable to the custome… | verified | 0001674101-26-000008 |

Comps table: 110 cells re-fetched, 0 mismatches.
