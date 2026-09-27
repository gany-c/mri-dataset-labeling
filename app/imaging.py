import io
from functools import lru_cache
import numpy as np
import pydicom
from PIL import Image
from pydicom.pixels import apply_modality_lut

@lru_cache(maxsize=24)
def pixels(path, mtime):
    ds = pydicom.dcmread(path)
    array = np.asarray(apply_modality_lut(ds.pixel_array, ds), dtype=np.float32)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError('Unsupported or invalid pixel array')
    valid = array
    if hasattr(ds, 'PixelPaddingValue'):
        raw = ds.pixel_array
        valid = array[raw != ds.PixelPaddingValue]
    if not valid.size:
        valid = array
    lo, hi = np.percentile(valid, [.5, 99.5])
    return array, float(lo), float(hi), str(getattr(ds, 'PhotometricInterpretation', 'MONOCHROME2'))

def render(path, mtime, center=None, width=None):
    a, lo, hi, photo = pixels(path, mtime)
    w = max(hi-lo, 1) if width is None else width
    c = (hi+lo)/2 if center is None else center
    gray = np.clip((a-(c-w/2))/w, 0, 1)
    if photo == 'MONOCHROME1':
        gray = 1-gray
    image = Image.fromarray(np.rint(gray*255).astype('uint8'))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue(), {'center': (hi+lo)/2, 'width': max(hi-lo, 1),
                           'rows': a.shape[0], 'columns': a.shape[1]}
