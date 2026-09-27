"""Index local, deidentified DICOMs without copying or modifying them."""
import argparse
import json
import math
from pathlib import Path
import numpy as np
import pydicom
from .db import init, connect

def import_directory(root, demo=False):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('DICOM directory does not exist')
    groups, errors = {}, []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.name.startswith('.') or path.suffix.lower() not in ('.dcm', '.dicom', ''):
            continue
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            if int(getattr(ds, 'SamplesPerPixel', 1)) != 1:
                raise ValueError('Only grayscale MRI is supported')
            if int(getattr(ds, 'NumberOfFrames', 1)) != 1:
                raise ValueError('Enhanced/multiframe DICOM is not yet supported; export individual slices')
            uid, study = str(ds.SeriesInstanceUID), str(ds.StudyInstanceUID)
            if not getattr(ds, 'Rows', 0) or not getattr(ds, 'Columns', 0):
                raise ValueError('Not an image')
            orientation = list(map(float, getattr(ds, 'ImageOrientationPatient', [])))
            position = list(map(float, getattr(ds, 'ImagePositionPatient', [])))
            item = dict(path=str(path), sop=str(ds.SOPInstanceUID), orientation=orientation,
                        position=position, instance=int(getattr(ds, 'InstanceNumber', 0)))
            entry = groups.setdefault(uid, dict(study=study, description=str(getattr(ds, 'SeriesDescription', 'MRI series')),
                         spacing=list(map(float, getattr(ds, 'PixelSpacing', [1, 1]))), slices=[]))
            if entry['study'] != study:
                raise ValueError('Series UID reused across studies')
            entry['slices'].append(item)
        except Exception as exc:
            errors.append({'file': str(path), 'error': str(exc)})
    if not groups:
        raise ValueError(f'No supported DICOM series found. First errors: {errors[:3]}')
    if errors:
        raise ValueError(f'Import stopped: {len(errors)} files could not be read. No studies were changed. First errors: {errors[:3]}')
    init()
    with connect() as c:
        for uid, g in groups.items():
            items = g['slices']
            unique = {r['sop']: r for r in items}
            if len(unique) != len(items):
                raise ValueError(f'Duplicate SOPInstanceUID in {uid}; remove duplicate input files')
            ori = items[0]['orientation']
            valid = len(ori) == 6 and all(len(r['position']) == 3 and len(r['orientation']) == 6
                          and np.allclose(r['orientation'], ori, atol=1e-3) for r in items)
            warnings = []
            plane = 'Unknown plane'
            if valid:
                normal = np.cross(ori[:3], ori[3:])
                valid = np.isfinite(normal).all() and np.linalg.norm(normal) > .9
            if valid:
                items.sort(key=lambda r: (float(np.dot(r['position'], normal)), r['instance'], r['sop']))
                plane = ['Sagittal', 'Coronal', 'Axial'][int(np.argmax(np.abs(normal)))]
                if max(abs(normal)) < .95:
                    plane += ' (oblique)'
                positions = [float(np.dot(r['position'], normal)) for r in items]
                if len(positions) > 1 and any(abs(b-a) < .001 for a,b in zip(positions, positions[1:])):
                    warnings.append('Repeated slice positions: this series may contain multiple acquisitions.')
            else:
                items.sort(key=lambda r: (r['instance'], r['sop']))
                warnings.append('Geometry missing or inconsistent. Sorted by instance number; orientation labels unavailable.')
                ori = []
            prior = c.execute('SELECT demo FROM studies WHERE uid=?', (g['study'],)).fetchone()
            if prior is not None and bool(prior['demo']) != demo:
                raise ValueError('Cannot mix demo and real data for one study UID')
            c.execute('INSERT OR IGNORE INTO studies VALUES(?,?,?)',
                      (g['study'], 'Synthetic practice study' if demo else 'Knee MRI', int(demo)))
            previous = c.execute('SELECT slices FROM series WHERE uid=?', (uid,)).fetchone()
            if not previous and c.execute('SELECT 1 FROM reviews WHERE study=?', (g['study'],)).fetchone():
                raise ValueError('Cannot add series to an already reviewed study. Use a fresh catalog for changed study content.')
            if previous and json.loads(previous['slices']) != items:
                reviewed = c.execute('SELECT 1 FROM reviews WHERE study=? LIMIT 1', (g['study'],)).fetchone()
                if reviewed:
                    raise ValueError('Series content changed after review. Use a fresh catalog to avoid stale labels.')
            c.execute('INSERT INTO series VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET '
                      'description=excluded.description,plane=excluded.plane,orientation=excluded.orientation,'
                      'spacing=excluded.spacing,warnings=excluded.warnings,slices=excluded.slices',
                      (uid, g['study'], g['description'], plane, json.dumps(ori), json.dumps(g['spacing']),
                       json.dumps(warnings), json.dumps(items)))
    return {'studies': len({g['study'] for g in groups.values()}), 'series': len(groups),
            'slices': sum(len(g['slices']) for g in groups.values()), 'errors': errors}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    args = p.parse_args()
    result = import_directory(args.directory)
    print(json.dumps(result, indent=2))
    if result['errors']:
        raise SystemExit('Some files could not be imported. Resolve the errors before labeling these studies.')
