#!/usr/bin/env python3
"""Download complete, officially unlabeled RSNA studies, in train.csv order."""
import argparse
import csv
import hashlib
import fcntl
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from requests.exceptions import ConnectionError, Timeout, ChunkedEncodingError
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import time
import zipfile

COMPETITION = 'rsna-knee-abnormality-detection'
LABELS = ['ACL','MCL','Medial Meniscus','Lateral Meniscus','Medial OA','Lateral OA','PF OA','Effusion','Synovitis',"Baker's",'Contusion','Fracture']

def http_status(error):
    response = getattr(error, 'response', None)
    return getattr(response, 'status_code', None)

def retry_delay(error, attempt):
    response = getattr(error, 'response', None)
    value = response.headers.get('Retry-After') if response is not None else None
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    return min(120, 2 ** (attempt + 1)) + random.uniform(0, 1)

def with_retries(operation, description, attempts=10):
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            status = http_status(error)
            transient = status in (408, 429, 500, 502, 503, 504) or isinstance(error, (ConnectionError, Timeout, ChunkedEncodingError))
            if not transient or attempt == attempts - 1:
                raise
            delay = retry_delay(error, attempt)
            reason = f'HTTP {status}' if status else type(error).__name__
            print(f'{description}: {reason}; retry {attempt + 1}/{attempts - 1} in {delay:.1f}s.', flush=True)
            time.sleep(delay)


def select_studies(path, count):
    with path.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if not rows or not set(LABELS + ['StudyInstanceUID']).issubset(rows[0]):
        raise ValueError('Unexpected train.csv schema')
    selected = [r for r in rows if all(r[k].strip().lower() in ('','nan') for k in LABELS)][:count]
    if len(selected) != count:
        raise ValueError('Not enough studies without official labels')
    return selected

def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)

def download(api, remote, destination, size=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Staging outside train_series prevents interrupted downloads entering the viewer.
    for attempt in range(3):
        try:
            with tempfile.TemporaryDirectory(dir=STAGING) as work:
                with_retries(lambda: api.competition_download_file(COMPETITION, remote, path=work, force=True, quiet=True), 'File download')
                candidates = list(Path(work).rglob('*'))
                files = [p for p in candidates if p.is_file() and not p.name.endswith('.kaggle-partial')]
                direct = [p for p in files if p.name == PurePosixPath(remote).name]
                if direct:
                    source = direct[0]
                else:
                    archives = [p for p in files if p.suffix == '.zip']
                    if len(archives) != 1:
                        raise ValueError('Unexpected download contents')
                    with zipfile.ZipFile(archives[0]) as z:
                        members = [n for n in z.namelist() if not n.endswith('/') and PurePosixPath(n).name == PurePosixPath(remote).name]
                        if len(members) != 1: raise ValueError('Unexpected ZIP members')
                        source = Path(work)/'extracted'
                        with z.open(members[0]) as src, source.open('wb') as dst: shutil.copyfileobj(src,dst)
                if size is not None and source.stat().st_size != size:
                    raise ValueError('Downloaded file size does not match Kaggle manifest')
                source.replace(destination)
            return
        except Exception as error:
            if http_status(error) is not None or attempt == 2: raise
            time.sleep(2**attempt)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--catalog-only', action='store_true')
    parser.add_argument('--root', type=Path, default=Path.home()/'rsna-data')
    args=parser.parse_args()
    if args.count < 1: parser.error('--count must be positive')
    root=args.root.expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    global STAGING
    # Kept out of source data folder; viewer ignores this hidden working directory.
    STAGING=root/'.download-work';STAGING.mkdir(exist_ok=True)
    meta=root/'.download-state';meta.mkdir(exist_ok=True)
    lock=(meta/'download.lock').open('w')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('Another downloader is already running')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();api.authenticate()
    for name in ('train.csv','train_series.csv'):
        if not (meta/name).exists(): download(api,name,meta/name)
    selected=select_studies(meta/'train.csv',args.count)
    ids={r['StudyInstanceUID'] for r in selected}
    with (root/'selected_studies.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['StudyInstanceUID']);w.writerows([r['StudyInstanceUID']] for r in selected)
    key=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()[:16]
    manifest_path=meta/f'manifest-{key}.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {'files':[], 'next_page':None, 'complete':False}
    pages=0
    print(f'Resuming saved catalog; {len(manifest["files"])} selected slices already identified.',flush=True)
    while not manifest['complete']:
        response=with_retries(lambda: api.competition_list_files(COMPETITION,page_token=manifest['next_page'],page_size=200), 'Catalog request')
        known={x['name'] for x in manifest['files']}
        for item in response.files:
            parts=PurePosixPath(item.name).parts
            if len(parts)==4 and parts[0]=='train_series' and parts[1] in ids:
                if any(p in ('..','.') for p in parts): raise ValueError('Unsafe remote path')
                if item.name not in known:
                    manifest['files'].append({'name':item.name,'bytes':item.total_bytes});known.add(item.name)
        manifest['next_page']=response.next_page_token or None
        manifest['complete']=not manifest['next_page']
        manifest['pages_scanned']=manifest.get('pages_scanned',0)+1
        atomic_json(manifest_path,manifest);pages+=1
        print(f'Catalog pages this run: {pages}; selected slices found: {len(manifest["files"])}',flush=True)
    if args.catalog_only:
        print("Catalog verification complete.",flush=True)
        return
    expected=set()
    with (meta/'train_series.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            if row['StudyInstanceUID'] in ids: expected.add((row['StudyInstanceUID'],row['SeriesInstanceUID']))
    actual={(PurePosixPath(x['name']).parts[1],PurePosixPath(x['name']).parts[2]) for x in manifest['files']}
    if not expected or expected != actual: raise ValueError('File catalog does not cover every expected selected series')
    files=manifest['files'];total=sum(x['bytes'] for x in files)
    remaining=sum(x['bytes'] for x in files if not (root/x['name']).exists() or (root/x['name']).stat().st_size != x['bytes'])
    if shutil.disk_usage(root).free < remaining + 1024**3: raise ValueError('Insufficient free disk space')
    print(f'Downloading {len(ids)} studies, {len(files)} slices, {total/1024**3:.2f} GiB total.',flush=True)
    for i,item in enumerate(files,1):
        path=root/item['name']
        if not path.exists() or path.stat().st_size != item['bytes']: download(api,item['name'],path,item['bytes'])
        if i%25==0 or i==len(files): print(f'Slices complete: {i}/{len(files)}',flush=True)
    atomic_json(root/'download_receipt.json',{'status':'complete','competition':COMPETITION,'studies':len(ids),'series':len(actual),'slices':len(files),'bytes':total,'selection':'First rows of train.csv with all 12 official labels missing'})
    try: STAGING.rmdir()
    except OSError: pass
    print('Complete. In Knee Review, click Scan data folder.',flush=True)

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('Interrupted. Run again to resume.',file=sys.stderr);sys.exit(130)
    except Exception as e:
        status=http_status(e)
        reason=f'HTTP {status}' if status else type(e).__name__
        detail=str(e) if isinstance(e,(ValueError,RuntimeError)) and status is None else ''
        print(f'Download stopped ({reason}). {detail} Progress is saved; rerun to resume.',file=sys.stderr)
        sys.exit(1)
