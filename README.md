# Knee Review

Local MRI study labeling workspace. Each study has **one shared record** containing twelve findings. Named reviewer accounts identify the last editor; simultaneous stale edits are rejected rather than silently overwriting another review. Every saved version is retained in SQLite history.

## Start on this Mac

Double-click `start.command`, or run:

```sh
cd ~/git-projects/mri-dataset-labeling
./start.command
```

Open http://127.0.0.1:8765. On first use, enter a reviewer name and password (at least eight characters), select **I'm a new reviewer**, and enter the workspace. Each reviewer can create an account. Accounts and labels stay on this Mac. Stop the terminal server with Ctrl+C.

Dependencies are already installed in `.venv`. For a fresh installation, use Python 3.13:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.demo
./start.command
```

## Add studies

Download and extract DICOM files into `~/rsna-data`, then click **Scan data folder**. For example:

```
~/rsna-data/train_series/<StudyInstanceUID>/<SeriesInstanceUID>/*.dcm
```

The importer scans recursively, groups by DICOM identifiers, and leaves source images untouched. CSV reports and generated labels are not imported. Do not move source files after indexing. Unreadable headers abort the import; a reviewed study cannot silently acquire a changed slice list. The importer does not verify whether a download contains every expected series: finish downloads before indexing.

Set `KNEE_DICOM_ROOT` before starting to use another source folder. Set `KNEE_REVIEW_DATA` to change the database/practice-data directory (default `data/` in this project).

## Review and export

1. Select a study and switch among its acquired series.
2. Scroll or use the slice slider/arrows. Adjust window, level, zoom, inversion, or drag to pan. Orientation markers come from DICOM metadata; warnings identify uncertain geometry. This viewer displays acquired 2D slices, not reconstructed planes.
3. Mark each finding **Yes** or **No**. Clear an answer with ×; an unanswered finding remains blank, never defaults to No.
4. Click **Save draft**, or **Complete review** after answering all twelve. Saving is explicit; Ctrl/Cmd+S saves a draft. Notes and editor attribution are retained locally.
5. Click **Export labels** to download `labels.csv`. It has exactly one row per indexed real study, including unstarted studies and saved drafts. Columns are `StudyInstanceUID` and the twelve competition findings; values are 1, 0, or blank. Use the companion status export to identify complete records. Unsaved edits are excluded.

If another reviewer changes the same record, saving an older revision fails. Preserve any notes you need, reopen the study, and reconcile your edits with the latest saved answers.

Practice scans are synthetic geometric images, prominently marked and separated from real studies. Practice exports use `demo-labels.csv`; they never enter the real labels export. Practice scans have no diagnostic ground truth.

## Storage and implementation

FastAPI backend, plain JavaScript/canvas frontend, SQLite labels/history, and pydicom with pylibjpeg decoding. No external frontend assets or image uploads. JPEG lossless and JPEG 2000 decoder dependencies are included. Single-frame grayscale DICOM is supported; multi-frame/color images are rejected. Pixel decoding errors are displayed rather than replaced with fabricated images.

Back up `data/` while the app is stopped, alongside the original DICOM folder. Git ignores scans, credentials/database, virtualenv, and generated data. `data/reviews.sqlite3` holds accounts, shared labels, notes, revisions, and edit history.

The current server binds only to localhost. The future Render/S3 phase should add invitation-based access, HTTPS/secure cookies, persistent database storage, private S3 objects and authorized image delivery. Deployment and cloud storage are not configured yet.

## Validation

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests cover shared edits, stale-revision conflicts, exact CSV schema and demo isolation, partial labels, authentication/write protection, DICOM ordering, atomic failed imports, and image rendering/inversion. Browser checks cover login, practice images, slice navigation and saving. Real downloaded MRI studies have not yet been available for validation.

## Original reports

Each real study has a collapsible **Original radiology report** panel. Text is matched by exact StudyInstanceUID and displayed in its original language without translation or label extraction. The app reads `~/rsna-data/.download-state/train.csv`, falling back to `~/rsna-data/train.csv`. Set `KNEE_REPORT_CSV` to choose another CSV. Reports remain separate from reviewer notes and exported labels.
