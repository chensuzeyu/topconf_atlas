"""Browser acceptance for complete proceedings and optional distinction filters."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('ATLAS_TEST_URL','http://127.0.0.1:18766')


def main():
    checks,errors=[],[]
    with sync_playwright() as player:
        browser=player.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def visit(path):
            page.goto(BASE+path)
            page.wait_for_selector('#content h1')
        def count(n):
            page.wait_for_function('(n)=>document.querySelector(".result-count")?.textContent.trim().endsWith("/ "+n)',arg=n)
        def total(query):return page.request.get(BASE+'/api/papers?'+query).json()['total']
        status=page.request.get(BASE+'/api/status').json()
        for conf in status['conferences']:
            visit('/'+conf['id']+'/');count(conf['count'])
            assert page.locator('#tier-filter').input_value()==''
            if conf['distinctions_enabled']:
                page.locator('#tier-filter').select_option('poster')
                count(conf['tiers']['poster'])
                assert page.locator('.badge.poster').count()==min(40,conf['tiers']['poster'])
                page.screenshot(path=str(ROOT/'docs/screenshots'/('ordinary-'+conf['id']+'.png')))
            else:
                assert page.locator('input[name="distinction"]').count()==0
                assert page.locator('#tier-filter option[value="oral"]').count()==0
                assert page.locator('.badge.oral,.badge.spotlight,.badge.highlight,.badge.poster').count()==0
                page.locator('#track-filter').select_option('unverified');count(conf['tracks']['unverified'])
                page.screenshot(path=str(ROOT/'docs/screenshots/neurips-unverified.png'))
        checks.append('five full conference lists; ordinary filters; NeurIPS distinctions disabled and unknown tracks explicit')
        visit('/ICML2026/')
        page.locator('input[name="distinction"][value="oral"]').check()
        count(total('conference=ICML2026&tier=oral'))
        page.locator('input[name="distinction"][value="spotlight"]').check()
        count(total('conference=ICML2026&tier=oral&tier=spotlight'))
        assert page.evaluate('new URLSearchParams(location.search).getAll("tier").length')==2
        page.reload();count(total('conference=ICML2026&tier=oral&tier=spotlight'))
        assert page.locator('input[name="distinction"]:checked').count()==2
        checks.append('OR union of distinctions, unique counts and URL restoration')
        visit('/topics/robotics/?tier=oral&tier=spotlight&tag=multimodal')
        page.wait_for_selector('#clear-tags')
        page.locator('#clear-tags').click()
        page.wait_for_function('!new URLSearchParams(location.search).has("tag")')
        assert page.locator('input[name="distinction"]:checked').count()==2
        count(total('category=robotics&tier=oral&tier=spotlight'))
        checks.append('clearing topic intersection preserves distinction filters')
        visit('/NeurIPS2026/')
        identifier=page.locator('.paper-row').first.get_attribute('data-paper-id')
        page.locator('.paper-title').first.click();page.wait_for_selector('.abstract-text')
        p=page.request.get(BASE+'/api/papers/'+identifier).json()
        assert p['acceptance_status']=='accepted' and not p['distinctions']
        assert p['abstract_en']
        if os.environ.get('ATLAS_REQUIRE_TRANSLATED','1')=='1':assert p['enrichment_status']=='ready' and p['abstract_zh']
        page.locator('[data-lang="en"]').click()
        assert len(page.locator('#abstract-body').inner_text())>40
        checks.append('NeurIPS full details, bilingual content and acceptance evidence')
        phone=browser.new_page(viewport={'width':390,'height':844})
        phone.goto(BASE+'/NeurIPS2026/');phone.wait_for_selector('.paper-row')
        assert phone.evaluate('document.documentElement.scrollWidth<=innerWidth')
        phone.screenshot(path=str(ROOT/'docs/screenshots/neurips-mobile.png'))
        checks.append('NeurIPS mobile layout')
        browser.close()
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'papers':status['total'],
            'checks':checks,'console_errors':errors,'passed':not errors}
    (ROOT/'docs/full-coverage-browser-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2));assert report['passed']


if __name__=='__main__':main()
