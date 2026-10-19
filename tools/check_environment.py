"""Inspect local installation without downloading models or displaying secrets."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from importlib.metadata import version,PackageNotFoundError
from lab.video import availability
modules={}
for n in ('fastapi','pydantic','uvicorn','Pillow','numpy','mediapipe','opencv-python'):
    try:modules[n]=version(n)
    except PackageNotFoundError:modules[n]='not installed'
print(json.dumps({'python':sys.version,'packages':modules,'video':availability()},ensure_ascii=False,indent=2))
