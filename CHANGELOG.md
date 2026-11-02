# Changes

Major updates get a new version. Small fixes and tweaks between versions are not listed.

## v0.1 (November 2026)

First release.

- Tests: I-FIT (AASHTO T 393-21), IDEAL-CT (ASTM D8225-19), DONUT (Draft ASTM), SCB (AASHTO T 394-21), SLT-SCB (Draft ASTM), DCT (ASTM D7313-20) and IDT strength (AASHTO T 322-07).
- Upload: reads CSV, TXT and XLSX files, finds time, load, LLD and CMOD columns and their units, and checks loading and sampling rates.
- Process: raw or fitted data, trims, seating energy, load tare, fit preview and specimen dimensions.
- Results: summary statistics, one-outlier option, manual exclusion, and other indices from the literature (CRI and BCI for I-FIT, N<sub>flex</sub> for IDEAL-CT, FST for DCT).
- Export: one Excel workbook per replicate, a batch summary, a PDF report and a settings file.
- Runs in the browser. Files are not uploaded.
