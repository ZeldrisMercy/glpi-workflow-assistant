"""Build an inspectable portfolio derivative without installing services."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
ROOT = Path(__file__).resolve().parents[1]
VERSION = '3.4.0~rc4-1'
BRIDGE_VERSION = '2.4.0'
EPOCH = 1790726400

def build(output):
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / 'package'
        shutil.copytree(ROOT / 'package', stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        control = stage / 'DEBIAN/control'
        rows = control.read_text().splitlines()
        control.write_text('\n'.join('Version: ' + VERSION if s.startswith('Version:') else s for s in rows) + '\n')
        docs = stage / 'usr/share/doc/glpi-assistant'
        docs.mkdir(parents=True)
        for p in [ROOT/'README.md', ROOT/'NOTICE.md', ROOT/'LEGAL_AND_OWNERSHIP.md', ROOT/'docs/installation.md', ROOT/'docs/known-limitations.md']:
            shutil.copy2(p, docs/p.name)
        for p in (stage/'DEBIAN').iterdir():
            if p.name != 'control':
                p.chmod(0o755)
                subprocess.run(['bash', '-n', str(p)], check=True)
        for p in (stage/'usr/bin').iterdir():
            p.chmod(0o755)
            if p.name != 'glpi-assistant-backup':
                subprocess.run(['bash', '-n', str(p)], check=True)
        runner = stage/'usr/lib/glpi-assistant/run-container.sh'
        runner.chmod(0o755)
        subprocess.run(['bash','-n',str(runner)], check=True)
        for p in sorted(stage.rglob('*')):
            os.utime(p,(EPOCH,EPOCH))
        os.utime(stage,(EPOCH,EPOCH))
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(output)], check=True,
                       env={**os.environ,'SOURCE_DATE_EPOCH':str(EPOCH)},stdout=subprocess.DEVNULL)
        assert subprocess.check_output(['dpkg-deb','-f',str(output),'Version'],text=True).strip()==VERSION
        return [{'path':str(p.relative_to(stage)), 'mode':oct(p.stat().st_mode & 0o777),
                 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(stage.rglob('*')) if p.is_file()]

def bridge(out):
    manifest = json.loads((ROOT/'extension/manifest.json').read_text())
    for chromium in (False, True):
        suffix = 'chromium.zip' if chromium else 'firefox-dev.xpi'
        cfg = json.loads(json.dumps(manifest))
        if chromium:
            cfg.pop('browser_specific_settings',None)
            cfg['background']={'service_worker':'chromium-worker.js'}
            cfg['minimum_chrome_version']='148'
        with zipfile.ZipFile(out/f'glpi-assistant-bridge_{BRIDGE_VERSION}_{suffix}','w',zipfile.ZIP_DEFLATED) as archive:
            entries={str(p.relative_to(ROOT/'extension')):p.read_bytes() for p in (ROOT/'extension').rglob('*') if p.is_file() and p.name!='manifest.json'}
            entries['manifest.json']=(json.dumps(cfg,indent=2)+'\n').encode()
            if chromium:entries['chromium-worker.js']=b"importScripts('browser-compat.js', 'background.js');\n"
            for name,data in sorted(entries.items()):
                info=zipfile.ZipInfo(name,(2026,9,30,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,data)

def main():
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    target=out/f'glpi-assistant_{VERSION}_all.deb'
    manifest=build(target)
    with tempfile.TemporaryDirectory() as td:
        second=Path(td)/'rebuild.deb';build(second)
        if target.read_bytes()!=second.read_bytes():raise RuntimeError('Package rebuild differs')
    (out/'package-manifest.json').write_text(json.dumps({'version':VERSION,'files':manifest,'rebuild_byte_identical':True},indent=2)+'\n')
    bridge(out)
    items=[p for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256SUMS']
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in items))
    print(json.dumps({'version':VERSION,'rebuild_byte_identical':True,'files':len(manifest),'installed':False}))

if __name__ == '__main__':main()
