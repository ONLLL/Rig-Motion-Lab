"""Real localhost HTTP smoke, separate from Playwright's document bridge."""
import io,json,zipfile
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
results=[]
def check(name,ok):
    assert ok,name
    results.append({'check':name,'passed':True})
with httpx.Client(base_url='http://127.0.0.1:8020',headers={'X-Rig-Request':'1'},trust_env=False,timeout=30) as c:
    check('health HTTP 200',c.get('/api/health').status_code==200)
    check('real HTML and JavaScript served',c.get('/').status_code==200 and c.get('/static/app.js').status_code==200)
    r=c.post('/api/projects',data={'name':'HTTP smoke fixture','demo':'true'});p=r.json();pid=p['id']
    check('create isolated fixture',r.status_code==200 and len(p['parts'])==14)
    clip=c.post(f'/api/projects/{pid}/solve').json()
    check('full solved pose JSON and draw matrices',len(clip['frames'])==24 and bool(clip['frames'][0]['draws']))
    check('no default contact slip',clip['diagnostics']['max_stance_step_slip']<1e-8)
    r=c.post(f'/api/projects/{pid}/export',json={'expected_revision':p['revision'],'size':128})
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:check('real exported PNG ZIP',z.testzip() is None and 'frames/000.png' in z.namelist())
    check('refuses cross-origin write',c.post('/api/projects',data={'demo':'true'},headers={'Origin':'https://evil.example'}).status_code==403)
    r=c.get(f'/api/projects/{pid}/download')
    q=c.post('/api/import-project',files={'file':('saved.zip',r.content,'application/zip')}).json()
    check('download/open roundtrip independent project id',q['id']!=pid and len(q['parts'])==14)
    q.pop('asset_prefix');r=c.put(f'/api/projects/{pid}',json={'expected_revision':1,'project':q})
    check('cannot change a different project id',r.status_code==422)
(ROOT/'docs/http-results.json').write_text(json.dumps({'method':'Actual TCP HTTP to local uvicorn','results':results,'passed':len(results)},indent=2),encoding='utf-8')
print(len(results),'HTTP checks passed')
