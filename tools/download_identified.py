#!/usr/bin/env python3
"""Download selected files immediately while the separate catalog scan continues."""
import csv
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import time
import download_studies as d

def main():
    root=Path.home()/'rsna-data'
    meta=root/'.download-state'
    lock=(meta/'image-download.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ids={r['StudyInstanceUID'] for r in d.select_studies(meta/'train.csv',10)}
    key=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()[:16]
    manifest_path=meta/f'manifest-{key}.json'
    d.STAGING=root/'.download-work';d.STAGING.mkdir(exist_ok=True)
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();api.authenticate()
    expected=set()
    with (meta/'train_series.csv').open(newline='') as f:
        expected={(r['StudyInstanceUID'],r['SeriesInstanceUID']) for r in csv.DictReader(f) if r['StudyInstanceUID'] in ids}
    while True:
        manifest=json.loads(manifest_path.read_text());files=manifest['files']
        for item in files:
            parts=PurePosixPath(item['name']).parts
            if len(parts)!=4 or parts[0]!='train_series' or parts[1] not in ids or any(p in ('.','..') for p in parts):
                raise ValueError('Manifest contains a path outside selected studies')
        remaining=sum(x['bytes'] for x in files if not (root/x['name']).exists() or (root/x['name']).stat().st_size!=x['bytes'])
        if shutil.disk_usage(root).free<remaining+1024**3:raise ValueError('Insufficient free disk space')
        print(f'Identified slices: {len(files)}. Downloading now; catalog complete: {manifest["complete"]}',flush=True)
        done=0
        def progress(status):
            d.atomic_json(root/'image_download_status.json',{'status':status,'downloaded_slices':done,'identified_slices':len(files),'catalog_complete':manifest['complete'],'updated_unix':time.time()})
        for item in files:
            path=root/item['name']
            if not path.exists() or path.stat().st_size!=item['bytes']:
                d.download(api,item['name'],path,item['bytes'])
            done+=1
            progress('downloading')
            if done==1 or done%10==0 or done==len(files):print(f'Image slices downloaded and size-checked: {done}/{len(files)}',flush=True)
        if manifest['complete']:
            actual={(PurePosixPath(x['name']).parts[1],PurePosixPath(x['name']).parts[2]) for x in files}
            if actual!=expected or not expected:raise ValueError('Selected series coverage mismatch')
            d.atomic_json(root/'download_receipt.json',{'status':'complete','studies':len(ids),'series':len(actual),'slices':done,'bytes':sum(x['bytes'] for x in files),'competition':d.COMPETITION,'selection':'First ten train.csv studies without any official labels'})
            progress('complete');print('Complete. In Knee Review, click Scan data folder.',flush=True);return
        progress('identified_files_downloaded_awaiting_catalog')
        print('All currently identified images downloaded; waiting for catalog completeness verification.',flush=True)
        time.sleep(30)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Interrupted; downloaded files are preserved.',flush=True)
    except Exception as e:
        status=d.http_status(e)
        print(f'Image download stopped: HTTP {status}' if status else f'Image download stopped: {type(e).__name__}',flush=True)
        raise SystemExit(1)
