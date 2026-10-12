"""Browser acceptance checks for exclusive and intersecting topic filters."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('ATLAS_TEST_URL', 'http://127.0.0.1:18766')


def main():
    errors, checks = [], []
    with sync_playwright() as player:
        browser = player.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda error: errors.append(str(error)))
        def api(query):
            return page.request.get(BASE + '/api/papers?' + query).json()
        def wait_total(total):
            page.wait_for_function('(n)=>document.querySelector(".result-count")?.textContent.trim().endsWith("/ "+n)', arg=total)
        def wait_selection(tags, exclusive=False):
            page.wait_for_function('''({tags,exclusive})=>{
                const form=document.querySelector('#filters');
                if(!form) return false;
                const actual=[...form.querySelectorAll('input[name="tag"]:checked')].map(e=>e.value).sort();
                return JSON.stringify(actual)===JSON.stringify(tags.slice().sort()) &&
                    form.querySelector('#topic-exclusive').checked===exclusive &&
                    actual.every(s=>form.querySelector('[id="tag-'+s+'"]').closest('label').classList.contains('selected'));
            }''', arg={'tags': tags, 'exclusive': exclusive})
        page.goto(BASE + '/topics/robotics/')
        page.wait_for_selector('.topic-filters')
        all_result = api('category=robotics&page_size=200')
        papers = list(all_result['items'])
        for number in range(2, all_result['pages']+1):
            papers.extend(api('category=robotics&page_size=200&page='+str(number))['items'])
        assert len(papers) == all_result['total']
        expected_single = sum(set(p['categories']) == {'robotics'} for p in papers)
        assert all_result['topic_facets']['exclusive_count'] == expected_single
        for facet in all_result['topic_facets']['tags']:
            expected = sum(facet['slug'] in p['categories'] for p in papers)
            assert expected == facet['count']
            assert page.locator('#tag-' + facet['slug']).locator('..').locator('.tag-count').inner_text() == str(expected)
        checks.append('all cross-topic counts and exclusive count agree with full catalog')
        page.get_by_role('button', name='下一页 →').click()
        page.wait_for_function('location.search.includes("page=2")')
        page.locator('#tag-multimodal').check()
        expected = sum('multimodal' in p['categories'] for p in papers)
        wait_total(expected)
        wait_selection(['multimodal'])
        assert 'page=' not in page.url
        page.locator('#tag-optimization').check()
        expected_pair = sum({'multimodal', 'optimization'} <= set(p['categories']) for p in papers)
        wait_total(expected_pair)
        wait_selection(['multimodal', 'optimization'])
        ids = page.locator('.paper-row').evaluate_all('(els)=>els.map(e=>e.dataset.paperId)')
        assert set(ids) <= {p['id'] for p in papers if {'multimodal','optimization'} <= set(p['categories'])}
        assert len(ids) == min(40, expected_pair)
        checks.append('AND intersection and pagination reset')
        page.reload()
        page.wait_for_selector('.topic-filters')
        wait_total(expected_pair)
        wait_selection(['multimodal', 'optimization'])
        checks.append('URL preserves repeated tags after refresh')
        page.locator('#topic-exclusive').check()
        wait_total(expected_single)
        wait_selection([], True)
        assert 'tag=' not in page.url
        page.locator('#tag-multimodal').check()
        wait_total(expected)
        wait_selection(['multimodal'])
        assert 'exclusive=' not in page.url
        checks.append('mutual exclusion switches correctly in both directions')
        page.locator('#tier-filter').select_option('oral')
        wait_total(api('category=robotics&tag=multimodal&tier=oral')['total'])
        page.locator('#clear-tags').click()
        wait_total(api('category=robotics&tier=oral')['total'])
        wait_selection([])
        assert 'tier=oral' in page.url
        page.goto(BASE + '/CVPR2026/robotics/')
        page.wait_for_selector('.topic-filters')
        r = api('category=robotics&conference=CVPR2026')
        wait_total(r['total'])
        assert page.locator('#topic-exclusive').locator('..').locator('.tag-count').inner_text() == str(r['topic_facets']['exclusive_count'])
        checks.append('conference scope, tier filtering, and clear-tags preserving other filters')
        page.goto(BASE + '/topics/robotics/?tag=multimodal&tag=optimization')
        page.wait_for_selector('.topic-filters')
        page.evaluate('document.fonts.ready')
        page.screenshot(path=str(ROOT / 'docs/screenshots/topic-filters-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(ROOT / 'docs/screenshots/topic-filters-mobile.png'), full_page=True)
        page.locator('#topic-exclusive').check()
        wait_total(expected_single)
        wait_selection([], True)
        checks.append('mobile width and checkbox interaction')
        browser.close()
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'base_url': BASE,
              'topic': 'robotics', 'total': len(papers), 'exclusive_count': expected_single,
              'multimodal_optimization_count': expected_pair, 'checks': checks,
              'console_errors': errors, 'passed': not errors}
    (ROOT / 'docs/topic-filter-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    assert not errors, errors
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
