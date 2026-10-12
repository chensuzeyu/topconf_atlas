#!/usr/bin/env python3
"""Manage only this project's local preview; never touch a listener owned by another project."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
STATE = RUNTIME / 'service.json'


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def owned(pid):
    try:
        return str(ROOT).encode() in (Path('/proc') / str(pid) / 'environ').read_bytes() and b'atlas' in (Path('/proc') / str(pid) / 'cmdline').read_bytes()
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    running = bool(state.get('pid') and alive(state['pid']) and owned(state['pid']))
    if args.action == 'status':
        print(json.dumps({**state, 'running': running}, ensure_ascii=False))
        return
    if args.action == 'stop':
        if running:
            os.kill(state['pid'], signal.SIGTERM)
            print('Stopped TopConf Atlas', state['pid'])
        STATE.unlink(missing_ok=True)
        return
    if running:
        print('Already running:', state['url'])
        return
    RUNTIME.mkdir(exist_ok=True)
    port = int(os.environ.get('ATLAS_PORT', '18766'))
    url = f'http://127.0.0.1:{port}'
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise SystemExit(f'Port {port} is in use; choose another ATLAS_PORT. Existing service was left untouched.')
    env = dict(os.environ, PYTHONPATH=str(ROOT), ATLAS_HOST='127.0.0.1', ATLAS_PORT=str(port))
    log = (RUNTIME / 'server.log').open('ab')
    proc = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-m', 'atlas', 'serve'], cwd=ROOT,
                            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    for _ in range(30):
        if proc.poll() is not None:
            raise SystemExit('Server failed to start; inspect .runtime/server.log (a port conflict may exist)')
        try:
            with urlopen(url + '/api/status', timeout=2) as response:
                if response.status == 200:
                    STATE.write_text(json.dumps({'pid':proc.pid,'url':url,'port':port,'log':str(RUNTIME / 'server.log')}))
                    print('TopConf Atlas:', url)
                    return
        except OSError:
            time.sleep(0.3)
    os.kill(proc.pid, signal.SIGTERM)
    raise SystemExit('Server did not become ready')


if __name__ == '__main__':
    main()
