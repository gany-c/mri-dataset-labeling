import csv
import hashlib
import hmac
import io
import json
import secrets
import time
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt
from .db import TARGETS, connect, init
from .imaging import render
from .reports import report_for

STATIC = Path(__file__).parent / 'static'
IMPORT_LOCK = threading.Lock()
SCAN_ROOT = Path(os.environ.get('KNEE_DICOM_ROOT', Path.home() / 'rsna-data')).expanduser()

@asynccontextmanager
async def lifespan(app):
    init()
    yield

app = FastAPI(title='Knee Review', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=STATIC), name='static')

@app.middleware('http')
async def local_protection(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return Response('Cross-origin writes are not permitted', status_code=403)
        if request.headers.get('x-knee-review') != '1':
            return Response('Application request header required', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    return response

def user(request: Request):
    token = request.cookies.get('review_session', '')
    with connect() as c:
        r = c.execute('SELECT reviewers.id,reviewers.name FROM sessions JOIN reviewers '
                      'ON reviewer=reviewers.id WHERE token=? AND expires>?',
                      (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    if not r:
        raise HTTPException(401, 'Please sign in')
    return dict(r)

class Credentials(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=8, max_length=200)
    create_account: bool = Field(default=False, alias='register')

def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()

@app.post('/api/login')
def login(body: Credentials, response: Response):
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(422, 'Enter your reviewer name')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        r = c.execute('SELECT * FROM reviewers WHERE name=?', (name,)).fetchone()
        if body.create_account:
            if r:
                raise HTTPException(409, 'Name already registered. Sign in instead.')
            salt = secrets.token_hex(16)
            cursor = c.execute('INSERT INTO reviewers(name,password) VALUES(?,?)',
                               (name, salt+':'+password_hash(body.password, salt)))
            rid = cursor.lastrowid
        else:
            if not r:
                raise HTTPException(401, 'Incorrect name or password')
            salt, expected = r['password'].split(':')
            if not hmac.compare_digest(expected, password_hash(body.password, salt)):
                raise HTTPException(401, 'Incorrect name or password')
            rid = r['id']
        token = secrets.token_urlsafe(32)
        c.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
        c.execute('INSERT INTO sessions VALUES(?,?,?)',
                  (hashlib.sha256(token.encode()).hexdigest(), rid, int(time.time())+86400))
    response.set_cookie('review_session', token, httponly=True, samesite='strict', max_age=86400)
    return {'name': name}

@app.post('/api/logout')
def logout(request: Request, response: Response):
    with connect() as c:
        c.execute('DELETE FROM sessions WHERE token=?',
                  (hashlib.sha256(request.cookies.get('review_session', '').encode()).hexdigest(),))
    response.delete_cookie('review_session')
    return {'ok': True}

@app.get('/api/me')
def me(reviewer=Depends(user)):
    return {'reviewer': reviewer['name'], 'targets': TARGETS, 'scan_root': str(SCAN_ROOT)}

@app.post('/api/import')
def import_scans(reviewer=Depends(user)):
    from .importer import import_directory
    if not IMPORT_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'An import is already running')
    try:
        return import_directory(SCAN_ROOT)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        IMPORT_LOCK.release()

@app.get('/')
def home():
    return FileResponse(STATIC / 'index.html')

@app.get('/api/studies')
def studies(reviewer=Depends(user)):
    with connect() as c:
        rows = c.execute('SELECT s.*, (SELECT count(*) FROM series WHERE study=s.uid) AS series_count,'
                         'r.status,r.labels FROM studies s LEFT JOIN reviews r ON r.study=s.uid '
                         'ORDER BY s.demo,s.uid').fetchall()
    return [dict(uid=r['uid'], title=r['title'], demo=bool(r['demo']), series_count=r['series_count'],
                 status=r['status'] or 'unstarted', answered=sum(v is not None for v in json.loads(r['labels']).values())
                 if r['labels'] else 0) for r in rows]

@app.get('/api/studies/{uid}')
def study(uid: str, reviewer=Depends(user)):
    with connect() as c:
        s = c.execute('SELECT * FROM studies WHERE uid=?', (uid,)).fetchone()
        if not s:
            raise HTTPException(404, 'Study not found')
        series = c.execute('SELECT * FROM series WHERE study=? ORDER BY plane,description,uid', (uid,)).fetchall()
        r = c.execute('SELECT reviews.*,reviewers.name AS editor FROM reviews JOIN reviewers ON reviewers.id=reviews.reviewer WHERE study=?', (uid,)).fetchone()
    return {**dict(s), 'report': report_for(uid) if not s['demo'] else '', 'series': [dict(uid=x['uid'], description=x['description'], plane=x['plane'],
            orientation=json.loads(x['orientation']), spacing=json.loads(x['spacing']),
            warnings=json.loads(x['warnings']), count=len(json.loads(x['slices']))) for x in series],
            'review': dict(labels=json.loads(r['labels']), notes=r['notes'], status=r['status'],
                           revision=r['revision'], updated=r['updated'], editor=r['editor']) if r else
                      dict(labels={t: None for t in TARGETS}, notes='', status='draft', revision=0, updated=None, editor=None)}

@app.get('/api/series/{uid}/slices/{index}')
def slice_image(uid: str, index: int, center: float | None=None, width: float | None=None, reviewer=Depends(user)):
    import math
    if (center is not None and not math.isfinite(center)) or (width is not None and (not math.isfinite(width) or width < 1)):
        raise HTTPException(422, 'Invalid window parameters')
    with connect() as c:
        s = c.execute('SELECT slices FROM series WHERE uid=?', (uid,)).fetchone()
    if not s:
        raise HTTPException(404, 'Series not found')
    items = json.loads(s['slices'])
    if not 0 <= index < len(items):
        raise HTTPException(404, 'Slice not found')
    path = Path(items[index]['path'])
    try:
        png, meta = render(str(path), path.stat().st_mtime_ns, center, width)
    except Exception as exc:
        raise HTTPException(422, f'Cannot display slice ({type(exc).__name__}). Check the DICOM file and installed decoder plugins.') from exc
    return Response(png, media_type='image/png', headers={'X-Image-Meta': json.dumps(meta)})

class Review(BaseModel):
    labels: dict[str, StrictInt | None]
    notes: str = Field(default='', max_length=10000)
    status: str
    revision: int = Field(ge=0)

@app.put('/api/studies/{uid}/review')
def save_review(uid: str, body: Review, reviewer=Depends(user)):
    if set(body.labels) != set(TARGETS) or any(v not in (0, 1, None) for v in body.labels.values()):
        raise HTTPException(422, 'Exactly twelve labels, each 0, 1, or null, are required')
    if body.status not in ('draft', 'complete'):
        raise HTTPException(422, 'Unknown review status')
    if body.status == 'complete' and any(v is None for v in body.labels.values()):
        raise HTTPException(422, 'Answer all twelve findings before completing; save a draft if unsure')
    updated = datetime.now(timezone.utc).isoformat()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM studies WHERE uid=?', (uid,)).fetchone():
            raise HTTPException(404, 'Study not found')
        old = c.execute('SELECT revision FROM reviews WHERE study=?', (uid,)).fetchone()
        revision = old['revision'] if old else 0
        if revision != body.revision:
            raise HTTPException(409, 'This review changed in another tab. Reload the study before saving.')
        values = (uid, reviewer['id'], json.dumps(body.labels), body.notes, body.status, revision+1, updated)
        c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?) ON CONFLICT(study) DO UPDATE SET reviewer=excluded.reviewer,'
                  'labels=excluded.labels,notes=excluded.notes,status=excluded.status,revision=excluded.revision,updated=excluded.updated', values)
        c.execute('INSERT INTO history(study,reviewer,labels,notes,status,revision,updated) VALUES(?,?,?,?,?,?,?)', values)
    return {'revision': revision+1, 'updated': updated, 'status': body.status}

def csv_response(rows, filename):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerows(rows)
    return Response(output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@app.get('/api/export')
def export(demo: bool=False, audit: bool=False, reviewer=Depends(user)):
    with connect() as c:
        studies = c.execute('SELECT uid FROM studies WHERE demo=? ORDER BY uid', (int(demo),)).fetchall()
        reviews = c.execute('SELECT reviews.*,reviewers.name AS editor FROM reviews JOIN reviewers ON reviewer=reviewers.id').fetchall()
    by_study = {r['study']: r for r in reviews}
    rows = [['StudyInstanceUID']+TARGETS]
    audit_rows = [['StudyInstanceUID', 'answered_targets', 'status', 'last_editor', 'updated_at', 'revision']]
    for s in studies:
        uid = s['uid']
        r = by_study.get(uid)
        labels = json.loads(r['labels']) if r else {}
        values = [labels.get(t) if labels.get(t) is not None else '' for t in TARGETS]
        rows.append([uid]+values)
        editor = r['editor'] if r else ''
        if editor.startswith(('=', '+', '-', '@')):
            editor = "'" + editor
        audit_rows.append([uid, sum(v != '' for v in values), r['status'] if r else 'unstarted',
                           editor, r['updated'] if r else '', r['revision'] if r else 0])
    return csv_response(audit_rows if audit else rows, 'review-status.csv' if audit else 'demo-labels.csv' if demo else 'labels.csv')

@app.get('/api/health')
def health():
    return {'status': 'ok'}
