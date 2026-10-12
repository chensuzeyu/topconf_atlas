"""Switch the validated expansion into service, keeping the old data directory for rollback."""
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.runtime/full-coverage'
STAGE=RUNTIME/'data'
CURRENT=ROOT/'data'
BACKUP=RUNTIME/'data-before-switch'
PYTHON=ROOT/'.venv/bin/python'


def running(pid):
    try:
        return bool((Path('/proc')/str(pid)/'cmdline').read_bytes())
    except FileNotFoundError:
        return False


def main():
    acceptance=json.loads((ROOT/'docs/full-coverage-acceptance.json').read_text())
    integrity=json.loads((STAGE/'reports/integrity-latest.json').read_text())
    assert acceptance['passed'] and integrity['passed']
    assert acceptance['papers']==acceptance['translated']==integrity['total']
    assert not BACKUP.exists(),'Existing switch backup must be reviewed before another switch'
    with sqlite3.connect(CURRENT/'atlas.sqlite3') as live:
        assert not live.execute('SELECT 1 FROM jobs WHERE status="running"').fetchone(),'Live management job is still running'
    live.close()
    state=json.loads((ROOT/'.runtime/service.json').read_text())
    original_pid=state['pid']
    stage_pids=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            args=(proc/'cmdline').read_bytes();env=(proc/'environ').read_bytes()
            if b'\0-m\0atlas\0serve' in args and (proc/'cwd').resolve()==ROOT and (b'ATLAS_DATA_DIR='+str(STAGE).encode()+b'\0') in env:
                stage_pids.append(int(proc.name))
        except (OSError,PermissionError):pass
    subprocess.run([str(PYTHON),'scripts/service.py','stop'],cwd=ROOT,check=True)
    for pid in stage_pids:os.kill(pid,signal.SIGTERM)
    for _ in range(50):
        if not any(running(pid) for pid in [original_pid,*stage_pids]):break
        time.sleep(.2)
    else:raise RuntimeError('Server did not stop; data directories left in place')
    # Preserve any reviews and PDF caches saved in the original service during the migration.
    with sqlite3.connect(CURRENT/'atlas.sqlite3') as live,sqlite3.connect(STAGE/'atlas.sqlite3') as stage:
        for row in live.execute('SELECT * FROM overrides'):
            assert stage.execute('SELECT 1 FROM papers WHERE id=?',(row[0],)).fetchone(),'Reviewed paper missing in staged catalog'
            stage.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?)',row)
        for row in live.execute('SELECT paper_id,action,before_json,after_json,created_at FROM audit'):
            if not stage.execute('SELECT 1 FROM audit WHERE paper_id IS ? AND action=? AND created_at=?', (row[0],row[1],row[4])).fetchone():
                stage.execute('INSERT INTO audit(paper_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?)',row)
        stage.commit();stage.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        live.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    stage.close();live.close()
    if (CURRENT/'pdf').exists():shutil.copytree(CURRENT/'pdf',STAGE/'pdf',dirs_exist_ok=True)
    CURRENT.rename(BACKUP)
    STAGE.rename(CURRENT)
    try:
        env=dict(os.environ,PYTHONPATH=str(ROOT));env.pop('ATLAS_DATA_DIR',None)
        subprocess.run([str(PYTHON),'scripts/service.py','start'],cwd=ROOT,env=env,check=True)
    except Exception:
        # The validated new data remains available for investigation and retry.
        subprocess.run([str(PYTHON),'scripts/service.py','stop'],cwd=ROOT,check=False)
        CURRENT.rename(STAGE);BACKUP.rename(CURRENT)
        subprocess.run([str(PYTHON),'scripts/service.py','start'],cwd=ROOT,env=env,check=True)
        raise
    migration=json.loads((RUNTIME/'migration.json').read_text());migration.update(state='switched',backup=str(BACKUP))
    (RUNTIME/'migration.json').write_text(json.dumps(migration,ensure_ascii=False,indent=2))
    print('Validated full coverage is now serving; rollback data:',BACKUP)


if __name__=='__main__':main()
