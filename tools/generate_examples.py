"""Regenerate original synthetic fixtures and sample exports. No network / AI."""
import os,tempfile,sys,zipfile,io
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.demo import new_project
from lab.reference import synthetic_reference
from lab.motion import solve_project
from lab.renderer import bake
from lab import storage

def main():
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        previous=os.environ.get('RIG_LAB_DATA_DIR');os.environ['RIG_LAB_DATA_DIR']=tmp
        try:
            p=new_project(demo=True)
            p.motion.kind='attack'
            data=bake(p,solve_project(p),256)
            (root/'examples/attack-demo.zip').write_bytes(data)
            with zipfile.ZipFile(io.BytesIO(data)) as z:(root/'examples/attack-preview.gif').write_bytes(z.read('preview.gif'))
            p.motion.kind='walk'
            data=bake(p,solve_project(p),256)
            with zipfile.ZipFile(io.BytesIO(data)) as z:(root/'examples/walk-preview.gif').write_bytes(z.read('preview.gif'))
            (root/'examples/reference-attack.json').write_text(synthetic_reference().model_dump_json(indent=2),encoding='utf-8')
            im=storage.image(p.id,p.reference_image);im.save(root/'examples/guard-reference.png')
        finally:
            if previous is None:os.environ.pop('RIG_LAB_DATA_DIR',None)
            else:os.environ['RIG_LAB_DATA_DIR']=previous
if __name__=='__main__':main()
