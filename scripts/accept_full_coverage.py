"""Run final acceptance after Chinese enrichment finishes; never dispatch model calls."""
import json
import os
import subprocess
from pathlib import Path
from atlas.storage import ROOT, all_papers, export, now, write_json
from atlas.audit import audit


def main():
    papers=all_papers()
    pending=[p['id'] for p in papers if p['enrichment_status']!='ready']
    assert not pending, f'{len(pending)} papers still need Chinese processing'
    assert len(papers)==27794
    print('Exporting full catalog',flush=True)
    export()
    result=audit()
    assert result['passed'], json.dumps(result['issues'][:10],ensure_ascii=False)
    checks=[]
    python=str(ROOT/'.venv/bin/python')
    commands=[
        ('baseline',[python,'scripts/check_baseline.py']),
        ('units',[python,'-m','unittest','discover','-s','tests','-v']),
        ('browser',[python,'scripts/check_browser.py']),
        ('full_coverage_browser',[python,'scripts/check_full_coverage.py']),
        ('topics',[python,'scripts/check_topic_filters.py']),
        ('math',[python,'scripts/check_math.py']),
        ('math_units',[str(ROOT/'.venv/lib/python3.11/site-packages/playwright/driver/node'),'tests/math.test.mjs'])]
    for name,command in commands:
        path=ROOT/'.runtime/full-coverage'/('final-'+name+'.log')
        print('Checking',name,flush=True)
        with path.open('w') as log:
            run=subprocess.run(command,cwd=ROOT,env=dict(os.environ),stdout=log,stderr=subprocess.STDOUT)
        checks.append({'name':name,'passed':run.returncode==0,'log':str(path)})
        assert run.returncode==0,f'{name} failed; inspect {path}'
    write_json(ROOT/'docs/full-coverage-acceptance.json',{
        'checked_at':now(),'papers':len(papers),'translated':len(papers),
        'checks':checks,'passed':True})
    print('Final full-coverage acceptance passed',flush=True)


if __name__=='__main__':main()
