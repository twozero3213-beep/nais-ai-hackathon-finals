# Horse paper: two explicitly separate evidence results

Source: Carmo et al. (2023), [PLOS ONE, 10.1371/journal.pone.0286045](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0286045). Author data/code: [Figshare version 1](https://doi.org/10.6084/m9.figshare.21714233.v1). PDF inspected on 2026-09-25. Original downloaded CSV/Rmd bytes were not modified.

## Real descriptive claim reproduced, with missingness disclosed

Table 3, printed page 8, reports elevated-neck totals of **1 in positive reinforcement and 4 in control**. Select all rows with `GRUPO=Experimental` or `Controle`, without the last-day filter. Sum observed binary `NECK_SUPERELEVADO` values within phase.

| Raw group | Selected sessions | Nonmissing | Missing | Recorded events | Published |
|---|---:|---:|---:|---:|---:|
| Experimental | 39 | 37 | 2 | 1 | 1 |
| Controle | 39 | 38 | 1 | 4 | 4 |

CSV line numbers include the header: the positive event is row 61; control events are rows 46, 104, 105, 106. This is `MATCH_DESCRIPTIVE_ONLY`: an exact match of the recorded binary totals, not a validation of missing sessions, all Table 3 columns, or the lowered-neck OR. Missing observations are disclosed and excluded rather than imputed as zero. No human has approved a benchmark label.

## Inferential claim remains BLOCK

The abstract (p.1) and section 3.2 (p.9) report a lowered-neck OR of **0.05**, printed 95% CI **0.00–0.56**, and **P=0.05**, comparing positive reinforcement with baseline. The CI zero is a rounded display value.

The exact author-script chain is:

- Rmd lines 128–134: exclude days 4, 5, 7, 8; exclude `GRUPO=Controle`.
- Lines 225–230: `glmer(NECK_ABAIXO ~ GRUPO + (1|NOME), data=data_wth, family=binomial)`; call `summary`; use profile CI.
- Lines 80–90: exponentiate fixed effects and confidence intervals, then round to two decimals.

| Model population | Selected | Observed outcome | Outcome=1 | Missing outcome |
|---|---:|---:|---:|---:|
| Baseline | 39 | 38 | 16 | 1 |
| Experimental | 13 | 12 | 1 | 1 |

Starting with 117 rows, author filters select 52; standard complete-case model handling leaves 50 observations from 13 horses. Missing response rows are CSV row 19 (Magic, day 9, Experimental) and row 83 (Troia, day 1, Baseline). Other selected predictor fields are present. This population audit does **not** estimate an OR.

`GRUPO` must use Baseline as reference and `NOME` as horse random intercept. The Rmd final formula omits period/sequence and age; the paper section 2.6 explains dropping order and age. Describe this as reproducing the final author model, not a newly period-adjusted crossover analysis.

### Missing execution requirements

1. R/lme4 execution with recorded environment: paper reports R 4.0.4, but the local Rmd has no pinned package versions or `sessionInfo`. `Rscript` was not available on PATH during this audit; no R installation or model execution was attempted.
2. Record actual contrast coding, `na.action`, optimizer and `nAGQ`; retain full-precision coefficient, standard error, Wald z p-value and profile likelihood CI.
3. Inspect convergence, singularity and profile diagnostics before comparing rounded values. Save those outputs with source hashes. An installed R runtime or matching event count alone cannot satisfy this requirement.

The full Rmd also imports `data_EquiFACS.csv` and `ICC_laize_lais.csv`, absent from this local bundle. These are required for running the whole document, **not** for the isolated lowered-neck model, which uses only `Dados_Laize_ISAE2021.csv`. Do not mislabel their absence as missing OR input data. The two other included facial CSVs are not inputs to either audited claim.

## Executable audit

From the project root:

```text
python tools/reproduce_horse.py
python -m pytest tests/test_v57_paper.py tests/test_v55.py -q
```

The audit verifies source SHA-256 values before calculating counts, emits deterministic JSON, and exits **2** because the OR is BLOCKed. `audit_result.json` is its saved snapshot. It has no path that promotes an unexecuted OR to PASS. Missing or modified sources prevent even a descriptive match from being emitted. There are no external calls or model-fitting package dependencies.

Validation: new test initially failed because the auditor did not exist; after implementation, **6 targeted tests passed** (four new, two existing). Checks cover exact populations/totals, no invented OR, tampered and missing source rejection, and nonzero CLI exit on BLOCK. Statistical-model reanalysis is still outstanding.
