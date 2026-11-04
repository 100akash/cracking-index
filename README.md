# Cracking Test Analyzer

A tool for processing asphalt mixture cracking test files.
Upload the load and displacement files from your test frame.
The tool maps the columns, checks the loading rate, fits the curves and reports the indices.

**Use it online:** https://akashto.com/cracking-index/

It runs entirely in your browser. Your files are read in the page and never uploaded.

## Tests

| Domain | Test | Standard | Main outputs |
|---|---|---|---|
| Service temperature | I-FIT | AASHTO T 393-21 | Flexibility index, G<sub>f</sub>, post-peak slope |
| Service temperature | IDEAL-CT | ASTM D8225-19 | CT<sub>index</sub>, G<sub>f</sub>, \|m<sub>75</sub>\|, N<sub>flex</sub> |
| Service temperature | DONUT | *Draft* ASTM | DONUT index, G<sub>f</sub>, \|S<sub>75</sub>\| |
| Low temperature | SCB | AASHTO T 394-21 | G<sub>f</sub> with power-law tail, K<sub>IC</sub>, stiffness |
| Low temperature | SLT-SCB | *Draft* ASTM | LCI, pre-peak G<sub>f</sub>, loading stiffness |
| Low temperature | DCT | ASTM D7313-20 | G<sub>f</sub> from load vs. measured CMOD (fitted CMOD optional) |
| Low temperature | IDT strength | AASHTO T 322-07 | Tensile strength. Creep compliance is not supported. |

N<sub>flex</sub> follows Yin et al. (2018). The two draft methods may change before they are published.

## How it works

1. **Test.** Pick low or service temperature, record the test temperature, and pick the test.
2. **Upload.** Add one file per replicate (CSV, TXT or XLSX). The tool finds time, load, LLD and CMOD columns and their units. Confirm the mapping. Time is optional for every test except DCT. Without it, the tool still processes the file but skips the loading-rate and sampling checks. If a frame records load or displacement as negative, the tool flips the sign and says so in the checks and the report. It checks the loading rate and sampling rate against the standard and plots each curve.
3. **Process.** Choose raw or fitted data, trims, seating energy and load tare. Look at the fit. Enter the specimen dimensions and the batch details. Then run.
4. **Results.** Mean, SD and COV of each output, with each replicate's values and checks. Remove one outlier or exclude replicates by hand. Export a zip with:
   - one Excel workbook per replicate (summary, processed data with a chart, fit details),
   - a batch summary workbook,
   - a PDF report (summary page, one page per replicate, methods and references),
   - a settings JSON.

Checks only warn. They never block a run. Anything changed from the standard is flagged in the report.

**Check results against the standard before use.**

## Run it on your own computer

```
pip install numpy scipy openpyxl matplotlib
python server.py
```

Then open http://localhost:8765/?local=1. The page then uses the same engine through the local server.

## Files

| Path | What it is |
|---|---|
| `index.html`, `web/` | The page. `worker.js` runs the engine in the browser with [Pyodide](https://pyodide.org). |
| `engine/` | All calculations in Python: file reading (`parse.py`), shared fits (`core.py`), each test (`methods.py`), test definitions (`specs.py`), exports (`report.py`) and routes (`routes.py`). |
| `examples/` | Example files. I-FIT and IDEAL-CT: two lab sets each (Mix A, Mix B) with names, IDs and dates removed. Other tests: synthetic curves for a made-up Mix A. |
| `tools/make_examples.py` | Makes the synthetic example files (all tests except I-FIT and IDEAL-CT). |
| `tests/test_engine.py` | Engine checks: `python -m pytest tests` |
| `vendor/` | openpyxl wheels for the browser (MIT). |
| `server.py` | Optional local server. |

## Cite

Bajaj, A. (2026). *Cracking Test Analyzer* (Version 0.1). https://akashto.com/cracking-index/

## Credits

Developed by Akash Bajaj, University of Illinois Urbana-Champaign.

## References

The [References page](https://akashto.com/cracking-index/references.html) lists the standard and the key papers for each test.


- AASHTO T 393-21. Determining the Fracture Potential of Asphalt Mixtures Using the Illinois Flexibility Index Test (I-FIT).
- ASTM D8225-19. Determination of Cracking Tolerance Index of Asphalt Mixture Using the Indirect Tensile Cracking Test at Intermediate Temperature.
- AASHTO T 394-21. Determining the Fracture Energy of Asphalt Mixtures Using the Semicircular Bend Geometry (SCB).
- ASTM D7313-20. Determining Fracture Energy of Asphalt Mixtures Using the Disk-Shaped Compact Tension Geometry.
- AASHTO T 322-07. Determining the Creep Compliance and Strength of Hot Mix Asphalt (HMA) Using the Indirect Tensile Test Device.
- Yin, F., Garita, J., Taylor, A., and West, R. (2018). Refining the indirect tensile (IDT) Nflex Factor test to evaluate cracking resistance of asphalt mixtures for mix design and quality assurance. *Construction and Building Materials*, 172, 396-405. https://doi.org/10.1016/j.conbuildmat.2018.03.251

This is an independent tool. It is not endorsed by AASHTO, ASTM or any agency.

Fonts: IBM Plex Sans, IBM Plex Mono and Overpass from Google Fonts.

## Versions

The current version is v0.1. See [CHANGELOG.md](CHANGELOG.md). Major updates get a new version.

## License

MIT. See [LICENSE](LICENSE).
