"""Create unmistakably synthetic practice images, separate from real exports."""
from pathlib import Path
import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
from .db import DATA
from .importer import import_directory

def create_demo(root=None):
    root = Path(root or DATA / 'practice-scans')
    y,x = np.mgrid[-1:1:256j,-1:1:256j]
    orientations = [[0,1,0,0,0,-1],[1,0,0,0,0,-1],[1,0,0,0,1,0]]
    descriptions = ['Sagittal PD · synthetic', 'Coronal T2 · synthetic', 'Axial T2 · synthetic']
    for study in range(1,4):
        study_uid=f'1.2.826.0.1.3680043.10.999.20260926.{study}'
        for series in range(3):
            series_uid=study_uid+f'.{series+1}'
            folder=root/study_uid/series_uid;folder.mkdir(parents=True,exist_ok=True)
            for index in range(24):
                path=folder/f'{index:03}.dcm'
                if path.exists():continue
                z=(index-11.5)/24
                # Geometric phantom, intentionally not a simulated diagnostic knee.
                a=np.zeros((256,256),np.float32)
                outer=(x/.77)**2+(y/.90)**2<1;a[outer]=170
                ring=(x/.72)**2+(y/.86)**2<1;a[ring]=75
                for cx,cy in [(-.28,-.18),(.28,-.18),(0,.48)]:
                    radius=.20*(1-.5*abs(z));d=np.sqrt((x-cx)**2+(y-cy)**2)
                    a[d<radius]=650+200*z;a[(d<radius)&(d>radius-.035)]=20
                a += (np.sin(x*42+index)*np.cos(y*30+series)+1)*15*outer
                a[122:128,40:215]=850  # obvious phantom reference bar
                meta=FileMetaDataset();meta.TransferSyntaxUID=ExplicitVRLittleEndian
                meta.MediaStorageSOPClassUID=MRImageStorage;meta.MediaStorageSOPInstanceUID=series_uid+f'.{index+1}'
                ds=FileDataset(str(path),{},file_meta=meta,preamble=b'\0'*128)
                ds.SOPClassUID=MRImageStorage;ds.SOPInstanceUID=meta.MediaStorageSOPInstanceUID
                ds.StudyInstanceUID=study_uid;ds.SeriesInstanceUID=series_uid;ds.Modality='MR'
                ds.PatientName='SYNTHETIC^PRACTICE';ds.PatientID='NOT-A-PATIENT'
                ds.SeriesDescription=descriptions[series];ds.InstanceNumber=index+1
                ds.ImageOrientationPatient=orientations[series]
                normal=np.cross(orientations[series][:3],orientations[series][3:])
                ds.ImagePositionPatient=list(normal*index*3);ds.PixelSpacing=[.7,.7];ds.SliceThickness=3
                ds.Rows=ds.Columns=256;ds.SamplesPerPixel=1;ds.PhotometricInterpretation='MONOCHROME2'
                ds.BitsAllocated=ds.BitsStored=16;ds.HighBit=15;ds.PixelRepresentation=0
                ds.PixelData=a.astype('<u2').tobytes();ds.save_as(path,enforce_file_format=True)
    return import_directory(root,demo=True)

if __name__=='__main__':print(create_demo())
