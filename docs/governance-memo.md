# AI governance memo: Verity pre-launch assessment

**To:** AI Risk Committee / Model Risk Management (second line)
**From:** Anoushka (use-case owner, Verity)
**Date:** 19 October 2026
**Status:** Pre-deployment review, version 0.2 (updated after the M5 evaluation). The fact-checker figures in Section 3 are measured with the deterministic writer and checker. The LLM-mode figures are still open because the evaluation environment had no model API key, so the launch decision stays open too.

---

## 1. The use case and its risk materiality

**What Verity does.** Verity is a multi-agent system that drafts equity research. A Researcher agent pulls figures from SEC XBRL filings through Python tools. A Writer agent produces a comps table and a 600-word note. A separate Fact-checker agent extracts every numeric claim, re-fetches the true value and labels it *verified*, *wrong* or *unverifiable*. Wrong claims go back to the Writer for at most two rounds. The LLM does no arithmetic: all ratios are computed in Python, and every figure carries a source (XBRL concept, period and accession number, or a price with its date).

**Intended use.** Verity is an internal analyst-assist tool. A licensed analyst reviews every draft before anything is published or used for a recommendation. It is **not** client-facing and does not make or execute investment decisions.

**Risk materiality.** This uses the three minimum dimensions in MAS's *Guidelines on AI Risk Management* (finalised 7 Oct 2026), which match the MindForge Handbook (Consideration 5).

| Dimension | Assessment | Rating |
|---|---|---|
| **Impact** | A wrong number in published research can mislead clients and creates conduct, reputational and regulatory exposure. It does not use personal data or make credit or customer decisions. | Medium–High |
| **Complexity** | Uses third-party foundation models (non-deterministic, opaque). Tool use and agent chaining add failure points. Outputs are free text. | High |
| **Reliance** | Human-in-the-loop: an analyst signs off every note. Automation bias rises with volume, though. If analysts "trust the green ticks", reliance becomes high in practice. | Medium (designed) |
| **Inherent materiality** | | **Medium–High** |
| **Residual target** (after the controls in Section 4) | | **Medium**. Deploy only with analyst sign-off, no client distribution without review |

## 2. What could go wrong

These failure modes are mapped to the MindForge / ABS "top risks" for generative AI.

| # | Failure mode | MindForge risk | Where it bites in Verity |
|---|---|---|---|
| R1 | **Fabricated or misattributed numbers.** The model writes a figure that no tool returned, or the right number for the wrong year or company. | Hallucination / fabrication | Note text, especially in revision rounds |
| R2 | **Correct data, wrong concept.** The filer tags the item differently, so the system reads the wrong line (e.g. a restructuring note instead of the income-statement line). | Insufficient accuracy / soundness | XBRL mapping layer (deterministic, but still a failure mode) |
| R3 | **Stale or recast figures.** A value changes after a restatement or discontinued-operations recast, or a per-share figure predates a stock split. | Data quality | Comps, P/E, growth rates |
| R4 | **Fact-checker false comfort.** The checker misses an error (low recall) or flags correct numbers (false alarms), and analysts learn to ignore it. | Overconfidence; inadequate human oversight | Final note and fact-check log |
| R5 | **Unverifiable qualitative claims.** Risks, strategy and "management said" statements cannot be checked against XBRL. | Hallucination; lack of explainability | Business and risk sections |
| R6 | **Model or vendor change.** The provider updates or deprecates a model, so behaviour drifts without any code change. | Model degradation; third-party risk | All agents |
| R7 | **Prompt injection through filing text.** 10-K text passed to the model contains instructions. | Security / adversarial input | `get_filing_section` tool |

## 3. How each risk was measured

**Already measured (M1, deterministic data layer, 10 companies, FY2021–FY2026):**

- **R2.** The concept mapping has to go beyond the first-choice tag. **72 of 663** core values (11%) are rebuilt from components because the filer does not tag the line directly. Eaton, Vertiv and Trane have no gross-profit tag, and Eaton and JCI have no operating-income tag. A first version of the JCI EBIT fallback used a restructuring tag that turned out to be a note disclosure (427m), not the income-statement line (546m). That is a 113m error, caught only by checking against the 10-K text. **Control result:** 25 values across 5 companies are pinned in unit tests to figures read from the filings, including the companies' own "Total debt" lines. All of them pass.
- **R3.** **70** company-year-concept combinations at **5 of 10** companies were recast in a later filing (mainly discontinued operations, e.g. nVent's FY2023 revenue moved from 3,263.6m to 2,668.9m). All are logged in `restatements.csv`. One stock split (Powell, 3:1, April 2026) would have tripled its P/E if left unadjusted.
- **Missing data stays missing.** Two values (GE Vernova FY2022 balance sheet, before the spin-off) are reported as *not reported*, never as zero. The one explicit zero (Powell's debt) is documented in config together with its reason.

**Measured in M5 (`docs/results.md`, all reproducible with `make eval`):**

The error-injection test planted 900 known errors of 7 types into correct notes for all 10 companies, then ran the fact-checker and the revision loop. The writer and checker were the deterministic ("rules") versions, with no LLM.

| Metric | Method | Result | Launch threshold (proposed) | Met? |
|---|---|---|---|---|
| Fact-checker **recall** (R4) | 900 planted errors: wrong number, wrong year, unit swap, changed %, invented figure (with and without a citation), true figure misdescribed | **98.2%** (884/900); 100% on invented figures without a citation, 99.1% with a fake citation | ≥ 95% overall, 100% on invented figures | Partly. Overall yes; the "100% on invented figures" bar is missed by one fake-cited figure. |
| Fact-checker **false-alarm rate** (R4) | Correct claims flagged, in clean and in injected notes | **0.0%** (0 of 7,117) | ≤ 5% | Yes (rules mode) |
| **Residual errors** after revision (R1, R4) | Planted errors still in the final note | **2.7%** (24/900), almost all "true number, wrong description" | 0 on the test set | **No** |
| Weakest error type (R1) | True, correctly cited figure described as something else | **87.7%** caught | — | Gap identified (see control 12) |
| Data layer vs filings (R2) | Values read by hand from five 10-Ks | 25/25 match | 100% | Yes |
| Comps table vs metrics table (R2) | Every cell compared | 110/110 identical | 100% | Yes |
| Quote checks (R5) | Quoted 10-K text found in the cited filing section | 40/40 across 10 notes | 100% | Yes |
| Cost, latency per note | Run traces | Rules mode: $0, ~2.3s, 23 tool calls | Monitored | — |
| Extraction accuracy (R1, R2) | 360 company × metric × year questions vs XBRL ground truth | **Pending:** needs a model API key; harness built and tested | ≥ 99% | Open |
| No-tool baseline accuracy (R1) | Same questions, one LLM call, no tools | **Pending** | Reference only | Open |
| LLM-mode recall and false alarms (R4) | The same injection test on LLM-written notes | **Pending** | Same as above | Open |

**What the evidence says.**
- **Value errors are reliably caught.** The check against the filings catches errors in a number's *value*, unit and year, because the checker re-fetches each cited figure with its own tools.
- **Meaning is the gap.** A true number that is cited correctly but described as the wrong thing ("data-centre revenue" quoting total revenue) gets through 12% of the time. When such a claim is caught only on its year, revision corrects the year and the misdescription survives.
- **These are upper bounds.** Template prose is regular, so these rates are an upper bound for LLM prose.

The thresholds are my proposal for the committee to set. They are not results.

## 4. Controls

**In the design (preventive):**

1. **Tool-only numbers.** LLMs never do arithmetic. Every figure in a note must come from a tool output with a source id, and any number without a source fails the final gate automatically.
2. **Independent checker.** The fact-checker is a separate agent with its own prompts. It re-fetches values and does not trust the Writer's citations. Configurable tolerances: 0.5% for reported figures, 0.1pp for ratios.
3. **Deterministic data layer with explicit mapping.** `concept_map.yaml` is version-controlled and logs the tag used for every value. Restatements and splits are logged, not silently absorbed.
4. **Full traceability.** Each run writes a JSONL trace of every agent step, tool call, token count, cost and timing. Replay mode re-runs any note bit-for-bit from cached responses.
5. **Filing text treated as data.** Retrieved text is delimited, and instructions in it are not followed (R7). Tests with planted instructions are still to be added.
6. **Fabrications are deleted, not patched.** Found in testing: the first revision loop "corrected" an invented figure with a borrowed citation into the cited true value, which laundered a fabrication into a true-looking claim. Now, if the sentence around a wrong number does not name the cited metric, the sentence is deleted.

**To add before a bank launch:**

7. **Mandatory analyst sign-off** in the app, with *unverifiable* claims shown in amber and blocked from publication until a human confirms or deletes them (R5). Track how often analysts override the checker, as an automation-bias signal.
8. **Golden-set regression gate.** Re-run the M5 suite on every prompt, model or concept-map change. A drop below threshold blocks deployment (MindForge C15, change management).
9. **Model and vendor pinning.** Pin model versions, re-evaluate on any provider change, and keep a fallback provider. Record the model in the AI inventory (R6; MAS third-party AI expectations).
10. **Post-deployment monitoring.** Weekly sample audit of published notes, plus KRIs: checker recall on fresh injected errors, false-alarm rate, override rate and cost per note (MindForge C14).
11. **AI inventory entry** with owner, materiality rating, models, data sources, limitations and review date. Periodic re-review should be at least annual and triggered by material change.
12. **Semantic check for misdescribed numbers.** This closes the measured gap (R1). Before publication, a second model or a human confirms that each sentence describes its cited metric. Until then, every "corrected" claim is shown to the analyst for confirmation.

## 5. Mapping to MAS FEAT

| FEAT principle | How Verity addresses it | Gap / action |
|---|---|---|
| **Fairness: accuracy and bias** (P3: data and models "regularly reviewed and validated for accuracy"; P4: decisions reviewed "so that models behave as designed") | Hand-checked unit tests, the M5 accuracy suite, a regression gate and checker recall measured on injected errors. No personal attributes are used (P1–P2 are largely not applicable). | Coverage bias: XBRL-rich large caps work best. Small or foreign filers are out of scope and must be labelled so. |
| **Ethics** (P5–P6: AI held "to at least the same ethical standards as human-driven decisions") | The research note is subject to the same research-conduct, independence and review rules as a human-written note. Public filings only, and no MNPI. | Add a disclosure that AI assisted the draft, in line with house research policy. |
| **Accountability: internal** (P7: approved by an "appropriate internal authority"; P8: accountable for "externally sourced" models; P9: Board awareness) | A named use-case owner. This memo goes to second-line review. Third-party LLMs are covered by vendor pinning and re-evaluation. | Formal approval and an inventory entry. Report AI KRIs in the regular risk MI. |
| **Accountability: external** (P10–P11: channels to enquire and appeal) | Every figure links to its filing, so a reader can query and correct any number. | Add a feedback channel on published notes that routes to the owner. |
| **Transparency** (P12–P14: proactive disclosure and clear explanations) | The fact-check log shows each claim's status and source, and the trace explains how each number was produced. | Disclose AI use in research and publish known limitations (US filers only, LFY multiples, qualitative claims are harder to verify). |

## 6. Recommendation

**Not ready for launch yet.** The data-layer controls (R2, R3) work and are tested. In the deterministic evaluation, the fact-checker meets the false-alarm and overall recall thresholds. It **fails the zero-residual-error threshold** (2.7% left after revision), and the failure has one identifiable cause: true numbers described as the wrong thing.

Before launch:
1. Build control 12 and re-run the test.
2. Run the LLM-mode evaluation (extraction accuracy, the no-tools baseline, and the injection test on LLM-written notes).
3. Put controls 7–11 in place.

The proposed deployment after that is a pilot with analysts on the ten-company universe, with a human signing off every note and a 3-month post-deployment review. This follows the phased-rollout practice in the MindForge Handbook (C13).

---

**Sources.** MAS, *Principles to Promote FEAT in the Use of AI and Data Analytics in Singapore's Financial Sector* (2018, updated Feb 2019). MAS, [Response to Feedback on Guidelines on AI Risk Management](https://www.mas.gov.sg/-/media/mas-media-library/publications/consultations/bd/2025/response-to-feedback-received-on-guidelines-on-artificial-intelligence-risk-management.pdf) (P017-2025, 7 Oct 2026): it sets Impact, Complexity and Reliance as the minimum materiality dimensions and requires frameworks, inventory and materiality within 12 months and full lifecycle controls within 24 months. HSBC is listed as a respondent. MindForge Consortium, [AI Risk Management: Executive Handbook](https://www.mas.gov.sg/-/media/mas-media-library/schemes-and-initiatives/ftig/project-mindforge/mindforge-ai-risk-management-executive-handbook.pdf) (Nov 2025): 17 Considerations and the ABS "top risks"; HSBC and HSBC Life are primary consortium members. MAS, [MindForge AI Risk Management Toolkit media release](https://www.mas.gov.sg/news/media-releases/2026/mas-partners-industry-to-develop-ai-risk-management-toolkit-for-the-financial-sector) (20 Mar 2026).
