# V32 Public Research Benchmark — Palmer Penguins

This benchmark is based on a real public research article, not a synthetic report.

- Article: Horst AM, Hill AP, Gorman KB (2022), *The R Journal* 14(1):244–254, DOI 10.32614/RJ-2022-020.
- Article URL: https://journal.r-project.org/articles/RJ-2022-020/
- Public curated data: `palmerpenguins::penguins` (344 rows × 8 columns).
- Official data repository: https://github.com/allisonhorst/palmerpenguins/blob/main/inst/extdata/penguins.csv
- Data license described by the article: CC0.
- Article reuse: CC BY 4.0.

## Bundled benchmark cache

`penguins_public_benchmark.csv` is a local cache of the same curated 344×8 Palmer Penguins data available in the build environment. Before inclusion it was checked against article-reported dimensions, missing-value count, and species-by-sex counts. For a formal external benchmark, replace this cache with a freshly downloaded official CSV and compare its SHA-256.

## Claims checked

PB-01 dimensions 8×344; PB-02 19 missing values / 2752 total; PB-03 Table 2 species-by-sex counts; PB-04 negative pooled bill-length/depth correlation; PB-05 positive within-species correlations; PB-06 first two standardized PCA components explain 88.15%.

This benchmark does **not** claim full-paper reproduction. It is the first real-public-research benchmark harness and deliberately reports its scope.
