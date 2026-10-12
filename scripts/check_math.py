"""Audit every saved title/summary/abstract through the actual browser renderer."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('ATLAS_TEST_URL','http://127.0.0.1:18766')


def main():
    data=Path(os.environ.get('ATLAS_DATA_DIR',ROOT/'data'))
    papers=json.loads((data/'catalog.json').read_text())['papers']
    papers=[{k:p.get(k,'') for k in ('id','conference','title','title_zh','summary_zh','abstract_en','abstract_zh')} for p in papers]
    with sync_playwright() as player:
        browser=player.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(BASE)
        page.wait_for_selector('#content h1')
        renderer='''async serialized => {
          const papers=JSON.parse(serialized);
          const {renderRichText}=await import('/assets/math.mjs');
          const errors=[], leftovers=[], conferences={};
          for(const p of papers) {
            const c=conferences[p.conference] ||= {papers:0,fields:0,equations:0};c.papers++;
            for(const field of ['title','title_zh','summary_zh','abstract_en','abstract_zh']) {
              const node=document.createElement('div');renderRichText(node,p[field],p.id);c.fields++;
              c.equations+=node.querySelectorAll('.katex').length;
              for(const error of node.querySelectorAll('[data-math-error]'))
                errors.push({id:p.id,field,tex:error.textContent,error:error.dataset.mathError});
              const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);
              while(walker.nextNode()) {
                const text=walker.currentNode;
                if(!text.parentElement.closest('.math-inline,.math-display') && /\\\\[A-Za-z]+/.test(text.textContent))
                  leftovers.push({id:p.id,field,text:text.textContent});
              }
            }
          }
          const probe=document.createElement('div');
          renderRichText(probe,'<img src=x onerror=alert(1)> $\\\\href{javascript:alert(1)}{x}$');
          const safe=!probe.querySelector('img,script,a[href^="javascript:"]');
          return {conferences,errors,leftovers,safe};
        }'''
        result={'conferences':{},'errors':[],'leftovers':[],'safe':True}
        for start in range(0,len(papers),500):
            batch=page.evaluate(renderer,json.dumps(papers[start:start+500],ensure_ascii=False))
            result['errors'].extend(batch['errors']);result['leftovers'].extend(batch['leftovers'])
            result['safe'] = result['safe'] and batch['safe']
            for conf,counts in batch['conferences'].items():
                target=result['conferences'].setdefault(conf,{k:0 for k in counts})
                for key,value in counts.items():target[key]+=value
            print('Math fields checked:',min(start+500,len(papers)),'/',len(papers),flush=True)
        samples={
            'iclr':'iclr2026-ff40de6c7ac1aea2',
            'cvpr':'cvpr2026-664f9bb296d414b6',
            'icml':'icml2026-0669e06a3d45667e',
            'eccv':'eccv2026-c4e6f712d3632684',
        }
        for conf,pid in samples.items():
            page.goto(BASE+'/paper/'+pid+'/')
            page.wait_for_selector('.abstract-text')
            page.evaluate('document.fonts.ready')
            assert not page.locator('[data-math-error]').count()
            page.screenshot(path=str(ROOT/'docs/screenshots'/('math-'+conf+'-zh.png')))
            page.locator('[data-lang="en"]').click()
            page.evaluate('document.fonts.ready')
            assert not page.locator('[data-math-error]').count()
            page.screenshot(path=str(ROOT/'docs/screenshots'/('math-'+conf+'-en.png')))
        phone=browser.new_page(viewport={'width':390,'height':844})
        phone.goto(BASE+'/paper/icml2026-0669e06a3d45667e/')
        phone.wait_for_selector('.abstract-text')
        phone.evaluate('document.fonts.ready')
        assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
        phone.screenshot(path=str(ROOT/'docs/screenshots/math-mobile.png'))
        # A long displayed fraction must scroll inside its own box on mobile.
        assert phone.evaluate('''async () => {
          const {renderRichText}=await import('/assets/math.mjs');
          renderRichText(document.querySelector('#abstract-body'),'$$'+Array(25).fill('x_i^2').join('+')+'$$');
          return document.documentElement.scrollWidth <= innerWidth && !!document.querySelector('.katex-display');
        }''')
        failed_fonts=page.evaluate("[...document.fonts].filter(f=>f.family.startsWith('KaTeX') && f.status==='error').map(f=>f.family)")
        browser.close()
    baseline_file=ROOT/'.runtime/full-coverage/baseline.json'
    baseline=set(json.loads(baseline_file.read_text())) if baseline_file.exists() else set()
    baseline_issues=[e for e in result['errors']+result['leftovers'] if e['id'] in baseline]
    rendering_safe=result['safe'] and not errors and not failed_fonts
    complete=not result['errors'] and not result['leftovers']
    result.update(checked_at=datetime.now(timezone.utc).isoformat(),console_errors=errors,failed_fonts=failed_fonts,
                  all_formulas_rendered=complete,baseline_regressions=baseline_issues,
                  readable_fallbacks=len(result['errors']),source_markup_pending=len(result['leftovers']),
                  rendering_safe=rendering_safe,
                  passed=rendering_safe and not baseline_issues and (complete or os.environ.get('ATLAS_REQUIRE_PERFECT_MATH','0')=='0'))
    (ROOT/'docs/math-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('errors','leftovers')},ensure_ascii=False,indent=2))
    print('Math fallbacks:',len(result['errors']),'source markup:',len(result['leftovers']))
    assert result['passed'],result


if __name__=='__main__':
    main()
