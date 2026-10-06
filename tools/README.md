# Local study downloaders

Source code lives here in the labelling repository. Images, metadata, manifests,
logs, partial downloads, and resume state remain in `~/rsna-data`. Credentials
remain in the existing Kaggle configuration outside both repositories.

Run from this repository:

```sh
# Original first-ten workflow (creates the separate download environment if needed).
./tools/download_first_10.command

# Resume the pinned ten-study excluded-training cohort.
~/rsna-data/.download-env/bin/python -u tools/download_excluded.py
```

The excluded downloader reads `~/rsna-data/excluded-review-10/selection.json`.
The ML project determines the selected IDs; this utility only downloads the pinned
selection. It scans the competition file catalog, verifies expected series and
file sizes, moves complete studies into `verified-studies/train_series`, and
imports them using this project's `.venv`. It must run separately from the web
server. The existing batch is complete; rerunning checks existing files and
imports them again without intentionally redownloading matching files.

`download_studies.py` is the original configurable `--count` / `--root` downloader.
`download_identified.py` is the legacy companion that downloads identified files
while the original catalog scan continues. It can wait indefinitely for that
scan; use it only with the original workflow, not the excluded-study batch.

The old script locations under `~/rsna-data` are compatibility symlinks to these
files, so existing launch commands continue to work. Do not put images, tokens,
or manifests in this repository. The Kaggle manifest-export utilities in the ML
repository are separate and have not been moved.
