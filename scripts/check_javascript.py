"""Check shipped JavaScript and execute the Node/DOM regression suites."""
from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    syntax = []
    for folder in ('extension', 'package/usr/lib/glpi-assistant/app/static', 'security-3.4'):
        for path in sorted((ROOT / folder).rglob('*')):
            if path.suffix in ('.js', '.mjs'):
                subprocess.run(['node', '--check', str(path)], check=True, cwd=ROOT)
                syntax.append(str(path.relative_to(ROOT)))

    jsdom_path = subprocess.check_output(
        ['node', '-p', "require.resolve('jsdom')"], cwd=ROOT, text=True
    ).strip()
    env = {**os.environ, 'JSDOM_PATH': jsdom_path}

    tests = []
    candidates = [
        *sorted((ROOT / 'tests').glob('*.js')),
        *sorted((ROOT / 'tests').glob('*.mjs')),
        *sorted((ROOT / 'qa').glob('*.cjs')),
    ]
    for path in candidates:
        command = ['node', str(path)]
        if path.name == 'test_waha_restricted.mjs':
            command.append(str(ROOT / 'security-3.4/modified-source/src/core/assistant-restricted.ts'))
        subprocess.run(command, check=True, cwd=ROOT, env=env)
        tests.append(str(path.relative_to(ROOT)))

    print(json.dumps({
        'syntax_files': len(syntax),
        'regression_files': len(tests),
        'tests': tests,
    }))


if __name__ == '__main__':
    main()
