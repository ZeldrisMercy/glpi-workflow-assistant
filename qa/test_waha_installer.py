"""Exercise real installer control flow using isolated fake Docker/HTTP, no daemon."""
import json,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MOCK='''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['STATE']);d=json.loads(p.read_text());a=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(a)+'\\n')
def done(code=0):p.write_text(json.dumps(d));sys.exit(code)
if a[0]=='info':done()
if a[:2]==['container','inspect']:done(0 if a[2] in d else 1)
if a[0]=='inspect':
 n=d.get(a[-1]);
 if n is None:done(1)
 print(str(n.get('running',False)).lower() if 'Running' in a[2] else n.get('owner','waha'));done()
if a[0]=='pull':done(int(os.environ.get('PULL_FAIL','0')))
if a[0]=='rm':d.pop(a[-1],None);done()
if a[0]=='stop':d[a[-1]]['running']=False;done()
if a[0]=='rename':d[a[2]]=d.pop(a[1]);done()
if a[0]=='start':d[a[1]]['running']=True;done()
if a[0]=='run':d['glpi-assistant-waha']={'owner':'waha','running':True,'new':True};done()
done(2)
'''
def run(initial,health=0,pull=0):
 with tempfile.TemporaryDirectory() as td:
  t=Path(td);(t/'bin').mkdir();(t/'data').mkdir();(t/'waha').mkdir()
  (t/'state').write_text(json.dumps(initial));(t/'calls').touch()
  (t/'bin/docker').write_text(MOCK)
  (t/'bin/python3').write_text("#!/usr/bin/python3\nimport sys,os\ns=sys.stdin.read()\nsys.exit(int(os.environ.get('HEALTH_FAIL','0')) if 'urllib.request' in s else 0)\n")
  for p in (t/'bin').iterdir():p.chmod(0o755)
  s=(ROOT/'package/usr/bin/glpi-assistant-waha').read_text()
  # The production installer must run as root, while CI runners intentionally do
  # not.  This harness redirects every privileged path and replaces only the
  # root guard; all Docker, rollback, health-check and ownership logic remains
  # the real installer code.
  root_guard="[[ ${EUID} -eq 0 ]] || { echo 'Execute com sudo: sudo glpi-assistant-waha [devlikeapro/waha@sha256:DIGEST]'; exit 1; }"
  assert root_guard in s
  s=s.replace(root_guard, ": # root guard covered separately; sandboxed QA uses temporary paths")
  s=s.replace('/var/lib/glpi-assistant',str(t)).replace('/run/lock/glpi-assistant-waha.lock',str(t/'lock'))
  (t/'install').write_text(s)
  env={**os.environ,'PATH':str(t/'bin')+':'+os.environ['PATH'],'STATE':str(t/'state'),'CALLS':str(t/'calls'),'HEALTH_FAIL':str(health),'PULL_FAIL':str(pull)}
  r=subprocess.run(['bash',str(t/'install')],env=env,capture_output=True,text=True)
  return r.returncode,json.loads((t/'state').read_text()),[json.loads(x) for x in (t/'calls').read_text().splitlines()]
N='glpi-assistant-waha';P=N+'-previous';old={'owner':'waha','running':True,'old':True}
def test_fresh():
 code,state,calls=run({});assert code==0 and state[N]['new'];args=next(a for a in calls if a[0]=='run');assert '127.0.0.1:3000:3000' in args and '--cap-drop' in args and '@sha256:' in args[-1]
def test_upgrade():
 code,state,_=run({N:old,P:{'owner':'waha','running':False}});assert code==0 and state[P]['old'] and state[N]['new']
def test_rollback():
 code,state,_=run({N:old},health=1);assert code!=0 and state[N]==old and P not in state
def test_failed_fresh():
 code,state,_=run({},health=1);assert code!=0 and not state
def test_download_failure():
 code,state,calls=run({N:old},pull=1);assert code!=0 and state[N]==old and not any(a[0]=='stop' for a in calls)
def test_foreign_container():
 code,state,calls=run({N:{'owner':'other','running':True}});assert code!=0 and not any(a[0]=='run' for a in calls)
def test_running_predecessor():
 code,state,calls=run({N:old,P:old});assert code!=0 and not any(a[0]=='stop' for a in calls)
