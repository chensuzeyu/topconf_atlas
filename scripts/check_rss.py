"""RSS acceptance against the running service, including bilingual and mobile UI."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('ATLAS_TEST_URL', 'http://127.0.0.1:18766')


def main():
    checks, errors = [], []
    with sync_playwright() as player:
        browser = player.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        status = page.request.get(BASE + '/api/status').json()
        conf = next(c for c in status['conferences'] if c['id'] == 'RSS2026')
        assert conf['count'] == conf['translated'] == 210
        assert conf['awards'] == 3 and conf['tracks'] == {'main': 210}
        assert conf['report']['complete'] and conf['report']['metadata_complete']
        ids = []
        for n in range(1, 7):
            result = page.request.get(BASE + f'/api/papers?conference=RSS2026&page_size=40&page={n}').json()
            ids.extend(p['id'] for p in result['items'])
        assert len(ids) == len(set(ids)) == 210
        assert page.request.get(BASE + '/api/papers?conference=RSS2026&tier=oral').json()['total'] == 0
        checks.append('210 translated papers; unique pagination; 3 awards; no inferred Oral distinctions')
        page.goto(BASE + '/RSS2026/')
        page.wait_for_selector('.paper-row')
        assert page.locator('#conference-nav a.active').inner_text().endswith('RSS2026')
        assert page.locator('input[name="distinction"]').count() == 0
        page.screenshot(path=str(ROOT / 'docs/screenshots/rss-desktop.png'))
        facets = page.request.get(BASE + '/api/papers?conference=RSS2026').json()['topic_facets']
        counts = {t['slug']: t['count'] for t in facets['tags']}
        assert counts['robotics'] == 209 and counts['reinforcement_learning'] == 40
        assert page.locator('#topic-exclusive').count() == 0
        page.locator('#tag-robotics').check()
        page.wait_for_function('(n)=>document.querySelector(".result-count").textContent.trim().endsWith("/ "+n)', arg=counts['robotics'])
        page.locator('#tag-reinforcement_learning').check()
        intersection = page.request.get(BASE + '/api/papers?conference=RSS2026&tag=robotics&tag=reinforcement_learning').json()['total']
        page.wait_for_function('(n)=>document.querySelector(".result-count").textContent.trim().endsWith("/ "+n)', arg=intersection)
        page.reload()
        page.wait_for_selector('#tag-reinforcement_learning:checked')
        assert page.locator('#tag-robotics').is_checked()
        page.screenshot(path=str(ROOT / 'docs/screenshots/rss-topic-filters.png'))
        page.locator('#clear-tags').click()
        page.wait_for_function('document.querySelector(".result-count").textContent.trim().endsWith("/ 210")')
        assert 'tag=' not in page.url
        assert page.locator('.row-meta a[data-nav]').count() > 0
        checks.append('conference-wide topic counts, AND intersection, URL persistence, clearing and clickable paper tags')
        page.locator('#tier-filter').select_option('award')
        page.wait_for_function('document.querySelectorAll(".paper-row").length === 3')
        assert page.locator('.badge.award').count() == 3
        page.screenshot(path=str(ROOT / 'docs/screenshots/rss-awards.png'))
        page.locator('#tier-filter').select_option('')
        page.wait_for_function('document.querySelectorAll(".paper-row").length === 40')
        page.locator('#local-q').fill('FlashSAC')
        page.wait_for_function('document.querySelectorAll(".paper-row").length === 1')
        page.locator('.paper-title').click()
        page.wait_for_selector('#abstract-body')
        chinese = page.locator('#abstract-body').inner_text()
        assert len(chinese) > 100
        assert 'DOI：10.15607/RSS.2026.XXII.' in page.locator('#content').inner_text()
        page.locator('[data-lang="en"]').click()
        english = page.locator('#abstract-body').inner_text()
        assert len(english) > 100 and english != chinese
        page.locator('[data-lang="zh"]').click()
        assert page.locator('#abstract-body').inner_text() == chinese
        page.screenshot(path=str(ROOT / 'docs/screenshots/rss-detail.png'))
        checks.append('conference navigation, award filter, search, session/DOI and full bilingual detail')
        phone = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        phone.on('pageerror', lambda error: errors.append(str(error)))
        phone.goto(BASE + '/RSS2026/')
        phone.wait_for_selector('.paper-row')
        assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
        phone.screenshot(path=str(ROOT / 'docs/screenshots/rss-mobile.png'))
        checks.append('RSS mobile layout without horizontal overflow')
        browser.close()
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'papers': 210,
              'checks': checks, 'console_errors': errors, 'passed': not errors}
    (ROOT / 'docs/rss2026-browser-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert report['passed']


if __name__ == '__main__':
    main()
