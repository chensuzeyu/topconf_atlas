"""Optional browser acceptance checks against a running local server."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('ATLAS_TEST_URL', 'http://127.0.0.1:18766')
SHOTS = ROOT / 'docs/screenshots'
SHOTS.mkdir(parents=True, exist_ok=True)


def main():
    errors, checks = [], []
    with sync_playwright() as player:
        browser = player.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1440, 'height':1000}, device_scale_factor=1)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        def visit(route):
            page.goto(BASE + route)
            page.wait_for_selector('#content h1')
            page.evaluate('document.fonts.ready')
        visit('/')
        status = page.request.get(BASE + '/api/status').json()
        if os.environ.get('ATLAS_REQUIRE_TRANSLATED', '1') == '1':
            assert status['total'] == status['translated'], status
        page.screenshot(path=str(SHOTS / 'home-desktop.png'))
        visit('/CVPR2026/3d_vision/')
        page.screenshot(path=str(SHOTS / 'category-desktop.png'))
        page.locator('#local-q').fill('3D-LATTE')
        page.wait_for_function("document.querySelectorAll('.paper-row').length === 1")
        assert page.locator('#local-q').evaluate('(el)=>document.activeElement===el')
        checks.append('category search and focus retention')
        page.locator('.paper-title').click()
        page.wait_for_selector('.abstract-text')
        chinese = page.locator('#abstract-body').inner_text()
        assert len(chinese) > 100
        page.locator('[data-lang="en"]').click()
        assert page.locator('#abstract-body').inner_text() != chinese
        page.locator('[data-lang="zh"]').click()
        assert page.locator('#abstract-body').inner_text() == chinese
        page.screenshot(path=str(SHOTS / 'detail-desktop.png'))
        checks.append('detail and full bilingual abstract tabs')
        for conference, tier in [('ICLR2026','oral'),('CVPR2026','highlight'),('ICML2026','spotlight'),('ECCV2026','spotlight')]:
            visit('/' + conference + '/')
            page.locator('#tier-filter').select_option(tier)
            expected = page.request.get(BASE+'/api/papers?conference='+conference+'&tier='+tier).json()['total']
            page.wait_for_function('(count)=>document.querySelector(".result-count")?.textContent.trim().endsWith("/ "+count)', arg=expected)
        checks.append('four conference distinction filters')
        visit('/ICML2026/')
        page.locator('#track-filter').select_option('position')
        expected = next(c for c in status['conferences'] if c['id']=='ICML2026')['tracks']['position']
        page.wait_for_function('(count)=>document.querySelector(".result-count")?.textContent.trim().endsWith("/ "+count)', arg=expected)
        checks.append('ICML position track filter')
        visit('/ECCV2026/llm_agent/')
        page.screenshot(path=str(SHOTS / 'eccv-agent-desktop.png'))
        visit('/manage/')
        assert int(page.locator('.admin-stats').inner_text().split(' · ')[1].split()[0]) >= status['translated']
        page.screenshot(path=str(SHOTS / 'manage-desktop.png'))
        checks.append('management Chinese processing counts')
        mobile = browser.new_context(viewport={'width':390,'height':844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        phone = mobile.new_page()
        phone.on('pageerror', lambda error: errors.append(str(error)))
        phone.goto(BASE + '/ECCV2026/llm_agent/')
        phone.wait_for_selector('.paper-row')
        phone.evaluate('document.fonts.ready')
        assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
        phone.locator('#menu-toggle').click()
        assert phone.locator('#sidebar').evaluate('(el)=>el.classList.contains("open")')
        phone.locator('#overlay').click(position={'x':370,'y':300})
        assert not phone.locator('#sidebar').evaluate('(el)=>el.classList.contains("open")')
        phone.screenshot(path=str(SHOTS / 'category-mobile.png'))
        checks.append('mobile sidebar and no horizontal overflow')
        page.locator('#theme-toggle').click()
        assert page.evaluate('document.documentElement.dataset.theme') == 'dark'
        checks.append('dark mode')
        browser.close()
    report = {'checked_at':datetime.now(timezone.utc).isoformat(), 'passed':not errors,
              'papers':status['total'], 'translated':status['translated'],
              'complete_chinese_coverage':status['translated']==status['total'],
              'checks':checks, 'console_errors':errors}
    (ROOT / 'docs/browser-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert not errors, errors


if __name__ == '__main__':
    main()
