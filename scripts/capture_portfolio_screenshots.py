"""Capture the real RC3 UI with offline synthetic API fixtures; never contact GLPI."""
import json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'package/usr/lib/glpi-assistant/app'
OUT = ROOT/'docs/assets/screenshots'
sys.path.insert(0, str(APP))
from parser import parse_closure

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, captures = [], []
    with tempfile.TemporaryDirectory() as td:
        server = subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--app-dir',str(APP),'--host','127.0.0.1','--port','8765'],env={**os.environ,'GLPI_ASSISTANT_DATA':td},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=1); break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('Demo server failed to start')
            with sync_playwright() as p:
                options = {'headless':True,'args':['--no-sandbox','--disable-dev-shm-usage','--single-process','--no-zygote','--use-angle=swiftshader','--enable-unsafe-swiftshader']}
                if os.getenv('CHROMIUM_EXECUTABLE'): options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
                browser=p.chromium.launch(**options)
                page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
                page.on('pageerror',lambda e:errors.append(str(e)))
                now=time.time()
                ticket={'id':900001,'title':'Conferência de backup — exemplo sintético','description':'Validar a execução do backup de laboratório.','entity':{'id':1,'label':'Empresa Aurora (exemplo)'},'entity_id':1,'category':{'id':8,'label':'Infraestrutura / Backup'},'status':2,'priority':3,'requesters':[{'id':11,'label':'Alex Exemplo'}],'assigned_users':[{'id':9,'label':'Técnico de laboratório'}],'assigned_groups':[],'url':'https://glpi.example.invalid/front/ticket.form.php?id=900001'}
                row={**ticket,'entity':'Empresa Aurora (exemplo)','category':'Infraestrutura / Backup','contacts':[],'seen_at':now-3600,'last_own_update':now-3600,'stale_hours':1,'stale':False,'baseline':False,'initial':'pausada'}
                prefs={'enabled':False,'auto_initial':False,'interval':120,'stale_hours':24,'timezone':'America/Sao_Paulo','country_code':'55','contact_name':'Alex Exemplo','initial_reply_template':'{saudacao}, aqui é {tecnico}. Vou acompanhar o chamado #{chamado} — {assunto}.'}
                work={'items':[row],'last_sync':now,'settings':prefs,'errors':[]}
                parsed=parse_closure((ROOT/'demo/fixtures/formalization.txt').read_text())
                ops=[{'op':'create_task','task_id':t['id'],'modality':t['modalidade'],'level':t.get('nivel'),'actiontime':t['actiontime'],'evidences':t.get('evidences',[])} for t in parsed['tasks']]
                plan={'ticket':ticket,'parsed':parsed,'operations':ops,'current_user_id':9,'task_count':len(ops),'incoming_task_count':len(ops),'skipped_task_count':0,'evidence_count':0,'has_actionable_operations':True,'plan_id':'offline-demo-plan','required_evidence_ids':[]}
                def api(route):
                    path=route.request.url.split('/api/',1)[1].split('?',1)[0]
                    payload={'items':[]}
                    if path=='status': payload={'configured':True,'config':{'url':'https://glpi.example.invalid'},'version':'3.4.0-rc4','catalog':{},'current_user_id':9}
                    elif path=='workbench': payload=work
                    elif path=='workbench/settings': payload=prefs
                    elif path=='workbench/contact-profile': payload={'user_id':9,'name':'Alex Exemplo','source':'synthetic'}
                    elif path=='ticket/900001': payload=ticket
                    elif path=='ticket/900001/tasks': payload={'tasks':[]}
                    elif path=='parse': payload=parsed
                    elif path=='plan': payload=plan
                    elif path=='review/suggest': payload={'suggestions':[]}
                    elif path=='execute': payload={'ok':True,'expected_task_count':len(ops),'verified_task_count':len(ops),'results':[],'errors':[]}
                    elif path=='bridge/info': payload={'paired':False}
                    route.fulfill(json=payload)
                page.route('**/api/**',api)
                page.route('https://**/*',lambda r:r.abort())
                page.goto('http://127.0.0.1:8765',wait_until='networkidle')
                page.locator('#wbRows .wb-ticket-card').first.wait_for()
                def capture(name):
                    page.screenshot(path=str(OUT/(name+'.png')),full_page=False)
                    captures.append(name)
                capture('01-central')
                page.locator('#wbRows .wb-ticket-card summary').first.click()
                capture('02-ticket-card')
                page.locator('.wb-settings > summary').click()
                page.locator('#wbInitialTemplate').scroll_into_view_if_needed()
                capture('03-t01-paused')
                page.locator('.workspace-nav a[href="#operacao"]').click()
                page.locator('#ticketId').fill('900001');page.locator('#loadTicket').click()
                page.locator('#ticketSummary').get_by_text('#900001',exact=False).wait_for()
                page.locator('#closure').fill((ROOT/'demo/fixtures/formalization.txt').read_text())
                page.locator('#executeBtn').wait_for(state='visible')
                page.wait_for_function('!document.querySelector("#executeBtn").disabled')
                page.locator('#plan').scroll_into_view_if_needed()
                capture('04-dry-run')
                page.on('dialog',lambda dialog:dialog.accept())
                page.locator('#executeBtn').click()
                page.locator('#applySuccessDialog').wait_for(state='visible')
                capture('05-result-simulated')
                assert not errors, errors
                browser.close()
                (OUT/'capture-report.json').write_text(json.dumps({'mode':'offline synthetic API fixtures; real RC4 HTML/CSS/JS and parser','captures':captures,'page_errors':errors,'real_glpi_writes':0,'proactive_creation':'implemented; dedicated gallery capture pending'},indent=2)+'\n')
        finally:
            server.terminate();server.wait(timeout=10)
if __name__=='__main__': main()
