"""Resumable download of the pinned excluded-study review batch."""
import csv, fcntl, json, os, shutil, sys, time, subprocess
from pathlib import Path, PurePosixPath
ROOT=Path.home()/'rsna-data'
import download_studies as d
BATCH=ROOT/'excluded-review-10'
def main():
    lock=(BATCH/'download.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ids=set(json.loads((BATCH/'selection.json').read_text())['study_ids'])
    assert len(ids)==10
    d.STAGING=BATCH/'staging';d.STAGING.mkdir(exist_ok=True)
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();api.authenticate()
    path=BATCH/'manifest.json'
    m=json.loads(path.read_text()) if path.exists() else dict(files=[],next_page=None,complete=False,pages=0)
    def status(stage,**kwargs):
        d.atomic_json(BATCH/'status.json',dict(status=stage,studies=10,catalog_pages=m['pages'],identified_slices=len(m['files']),updated_unix=time.time(),**kwargs))
    while not m['complete']:
        response=d.with_retries(lambda:api.competition_list_files(d.COMPETITION,page_token=m['next_page'],page_size=1000),'Catalog')
        known={x['name'] for x in m['files']}
        for x in response.files:
            parts=PurePosixPath(x.name).parts
            if len(parts)==4 and parts[0]=='train_series' and parts[1] in ids and x.name not in known:
                assert '..' not in parts
                m['files'].append(dict(name=x.name,bytes=x.total_bytes));known.add(x.name)
        token=response.next_page_token or None
        if token and token==m['next_page']:raise RuntimeError('Repeated catalog token')
        m.update(next_page=token,complete=not token,pages=m['pages']+1)
        d.atomic_json(path,m);status('catalog_scanning')
        if m['pages']%10==0 or m['complete']:print(f"Catalog pages: {m['pages']}; selected slices: {len(m['files'])}; complete: {m['complete']}",flush=True)
        time.sleep(1)
    with (ROOT/'.download-state/train_series.csv').open() as f:
        expected={(r['StudyInstanceUID'],r['SeriesInstanceUID']) for r in csv.DictReader(f) if r['StudyInstanceUID'] in ids}
    actual={(PurePosixPath(x['name']).parts[1],PurePosixPath(x['name']).parts[2]) for x in m['files']}
    assert actual==expected and {x[0] for x in actual}==ids,'Incomplete series coverage'
    assert shutil.disk_usage(ROOT).free>sum(x['bytes'] for x in m['files'])+1024**3,'Insufficient disk space'
    total=len(m['files']);done=0
    for uid in sorted(ids):
        items=[x for x in m['files'] if PurePosixPath(x['name']).parts[1]==uid]
        final=ROOT/'verified-studies/train_series'/uid
        for item in items:
            dest=(ROOT/'verified-studies'/item['name']) if final.exists() else (BATCH/'images'/item['name'])
            if not dest.exists() or dest.stat().st_size!=item['bytes']:
                d.download(api,item['name'],dest,item['bytes']);time.sleep(1)
            done+=1;status('downloading',downloaded_slices=done,total_slices=total)
            if done%10==0:print(f'Size-checked slices: {done}/{total}',flush=True)
        if not final.exists():os.rename(BATCH/'images/train_series'/uid,final)
        # Only complete study directories are exposed to the viewer.
        project=Path(__file__).resolve().parents[1]
        subprocess.run([str(project/'.venv/bin/python'),'-m','app.importer',str(final)],cwd=project,check=True)
        print(f'Complete study imported: {uid}',flush=True)
    status('complete',downloaded_slices=done,total_slices=total)
    print('COMPLETE: all 10 excluded studies downloaded and imported.',flush=True)
if __name__=='__main__':
    try:main()
    except Exception as e:
        d.atomic_json(BATCH/'error.json',dict(error=type(e).__name__,http_status=d.http_status(e),updated_unix=time.time()))
        print(f'STOPPED: {type(e).__name__}; HTTP {d.http_status(e)}. Rerun to resume.',flush=True)
        sys.exit(1)
