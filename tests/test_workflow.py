import csv
import io
import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydicom import dcmread
from PIL import Image
from app import db
from app.main import app
from app.demo import create_demo
from app.importer import import_directory
from app.imaging import render

HEAD = {'X-Knee-Review':'1'}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path/'store')
    create_demo(tmp_path/'scans')
    with TestClient(app) as c:
        r=c.post('/api/login',headers=HEAD,json={'name':'Doctor A','password':'test-password','register':True})
        assert r.status_code==200
        yield c

def first(c):
    uid=c.get('/api/studies').json()[0]['uid']
    return uid,c.get('/api/studies/'+uid).json()

def test_shared_record_conflict_and_csv(client):
    uid,s=first(client)
    labels={t:0 for t in db.TARGETS};labels['ACL']=1
    body={'labels':labels,'notes':'Review A','revision':0,'status':'complete'}
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==200
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==409
    assert client.post('/api/login',headers=HEAD,json={'name':'Doctor B','password':'test-password','register':True}).status_code==200
    shared=client.get('/api/studies/'+uid).json()['review']
    assert shared['labels']==labels and shared['editor']=='Doctor A'
    labels['MCL']=1
    body.update(labels=labels,revision=1)
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==200
    assert client.get('/api/studies/'+uid).json()['review']['editor']=='Doctor B'
    rows=list(csv.DictReader(io.StringIO(client.get('/api/export?demo=true').text)))
    assert len(rows)==3 and len(rows[0])==13
    assert rows[0]['ACL']=='1' and rows[0]['MCL']=='1'
    assert rows[1]['ACL']==''
    assert len(list(csv.DictReader(io.StringIO(client.get('/api/export').text))))==0
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM reviews').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM history').fetchone()[0]==2

def test_drafts_unknowns_and_type_validation(client):
    uid,s=first(client);body={'labels':s['review']['labels'],'notes':'','revision':0,'status':'complete'}
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==422
    body['status']='draft';body['labels']['ACL']=0
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==200
    rows=list(csv.DictReader(io.StringIO(client.get('/api/export?demo=true').text)))
    assert rows[0]['ACL']=='0' and rows[0]['MCL']==''
    body['revision']=1;body['labels']['MCL']=True
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==422
    del body['labels']['MCL']
    assert client.put(f'/api/studies/{uid}/review',headers=HEAD,json=body).status_code==422

def test_images_and_access(client):
    uid,s=first(client);series=s['series'][0]
    assert series['count']==24
    image=client.get(f"/api/series/{series['uid']}/slices/0")
    assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    assert Image.open(io.BytesIO(image.content)).size==(256,256)
    assert client.get(f"/api/series/{series['uid']}/slices/99").status_code==404
    assert client.get(f"/api/series/{series['uid']}/slices/0?width=-1").status_code==422
    assert client.post('/api/logout',headers={**HEAD,'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/logout').status_code==403
    assert client.post('/api/logout',headers=HEAD).status_code==200
    assert client.get('/api/export').status_code==401

def test_geometry_order_and_idempotent_import(client,tmp_path):
    with db.connect() as c:
        row=c.execute('SELECT * FROM series LIMIT 1').fetchone()
    items=json.loads(row['slices']);ori=json.loads(row['orientation']);normal=np.cross(ori[:3],ori[3:])
    positions=[np.dot(i['position'],normal) for i in items]
    assert positions==sorted(positions)
    result=import_directory(tmp_path/'scans',demo=True)
    assert result['studies']==3 and result['series']==9
    broken=tmp_path/'scans'/'broken.dcm';broken.write_bytes(b'broken')
    with pytest.raises(ValueError,match='Import stopped'):
        import_directory(tmp_path/'scans',demo=True)

def test_monochrome_inversion(client,tmp_path):
    with db.connect() as c:
        path=json.loads(c.execute('SELECT slices FROM series LIMIT 1').fetchone()[0])[0]['path']
    ds=dcmread(path);ds.PhotometricInterpretation='MONOCHROME1'
    invert=tmp_path/'invert.dcm';ds.save_as(invert,enforce_file_format=True)
    normal,_=render(path,1,center=400,width=800)
    inverted,_=render(str(invert),1,center=400,width=800)
    a=np.asarray(Image.open(io.BytesIO(normal))).astype(int)
    b=np.asarray(Image.open(io.BytesIO(inverted))).astype(int)
    assert np.max(abs(a+b-255))<=1
