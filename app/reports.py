"""Read original report text by exact study UID; never infer findings from it."""
import csv
import os
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=2)
def _read_reports(path, modified):
    with Path(path).open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not {'StudyInstanceUID', 'Report'}.issubset(reader.fieldnames or []):
            return {}
        reports = {}
        for row in reader:
            uid = row['StudyInstanceUID']
            if uid in reports:
                raise ValueError('Duplicate study in report CSV')
            reports[uid] = row.get('Report') or ''
        return reports

def report_for(uid):
    explicit = os.environ.get('KNEE_REPORT_CSV')
    candidates = [Path(explicit).expanduser()] if explicit else [
        Path.home()/'rsna-data/.download-state/train.csv',
        Path.home()/'rsna-data/train.csv']
    for path in candidates:
        if path.is_file():
            return _read_reports(str(path), path.stat().st_mtime_ns).get(uid, '')
    return ''
