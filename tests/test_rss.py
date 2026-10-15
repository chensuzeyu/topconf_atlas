import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from atlas import collect, storage
from atlas.collect import normalize, paper_links
from atlas.rss import rss_proceedings


CONF = {'id': 'RSS2026', 'name': 'RSS', 'year': 2026, 'domain': 'roboticsconference.org',
        'adapter': 'rss-proceedings', 'volume_roman': 'XXII', 'distinctions_enabled': False,
        'accepted_index_url': 'https://roboticsconference.org/2026/program/papers/',
        'proceedings_index_url': 'https://www.roboticsproceedings.org/rss22/'}
TITLE = 'A robot policy'
DETAIL = '''<meta name="citation_title" content="A robot policy">
<meta name="citation_author" content="Ada Example">
<meta name="citation_publication_date" content="2026/07/13">
<div class="content"><p><b>Abstract:</b></p><p>A complete official abstract describing a robust robot policy and its experimental evaluation.</p>
<a href="p001.pdf">PDF</a><pre>DOI = {10.15607/RSS.2026.XXII.001}</pre></div>'''


def sources(title=TITLE, detail=DETAIL):
    accepted = f'''<table id="myTable"><tr><td>99</td><td>Manipulation 1</td>
        <td><a href="/2026/program/papers/99/">{title}</a></td>
        <td>Ada Example<div class="content" style="display:none">Ada Example</div></td></tr></table>'''
    index = f'<a href="p001.html">{title}</a><a href="p001.pdf">PDF</a>'
    pages = {CONF['accepted_index_url']: accepted, CONF['proceedings_index_url']: index,
             CONF['proceedings_index_url'] + 'p001.html': detail}
    return Mock(get=lambda url, **kwargs: pages[url])


class RSSTests(unittest.TestCase):
    def test_membership_stable_identity_and_independent_program_number(self):
        rows, abstracts, coverage = rss_proceedings(CONF, sources())
        papers, quality = normalize(CONF, rows, abstracts)
        p = papers[0]
        self.assertEqual(coverage['accepted_index_count'], 1)
        self.assertTrue(coverage['membership_reconciled'])
        self.assertEqual(quality['missing_abstracts'], [])
        self.assertEqual(p['program_id'], 99)
        self.assertEqual(p['session'], 'Manipulation 1')
        self.assertEqual(p['authors'], [{'fullname': 'Ada Example', 'institution': None}])
        self.assertEqual(p['tier'], 'unlabeled')
        self.assertEqual(p['distinctions'], [])
        self.assertTrue(p['paper_url'].endswith('/p001.html'))
        self.assertTrue(p['pdf_url'].endswith('/p001.pdf'))
        self.assertEqual(p['canonical_source_id'], p['paper_url'])
        self.assertEqual({e['source_url'] for e in p['evidence']},
                         {CONF['accepted_index_url'], p['paper_url']})
        new_title = 'A corrected robot policy'
        rows2, abstracts2, _ = rss_proceedings(CONF, sources(new_title, DETAIL.replace(TITLE, new_title)))
        papers2, _ = normalize(CONF, rows2, abstracts2)
        self.assertEqual(p['id'], papers2[0]['id'])

    def test_missing_abstract_or_wrong_volume_rejected(self):
        for detail in [DETAIL.replace('<b>Abstract:</b>', '<b>Unavailable:</b>'),
                       DETAIL.replace('RSS.2026.XXII', 'RSS.2025.XXI')]:
            with self.subTest(detail=detail), self.assertRaisesRegex(RuntimeError, 'incomplete or invalid'):
                rss_proceedings(CONF, sources(detail=detail))

    def test_mismatched_membership_or_detail_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'title conflict'):
            rss_proceedings(CONF, sources(detail=DETAIL.replace(TITLE, 'Different official paper')))
        fetcher = sources()
        original = fetcher.get
        fetcher.get = lambda url, **kw: ('<a href="p001.html">Other paper</a>'
                                         if url == CONF['proceedings_index_url'] else original(url, **kw))
        with self.assertRaisesRegex(RuntimeError, 'title conflict'):
            rss_proceedings(CONF, fetcher)

    def test_untrusted_evidence_is_excluded(self):
        rows, abstracts, _ = rss_proceedings(CONF, sources())
        rows[0]['sourceurl'] = 'https://unofficial.example/'
        papers, _ = normalize(CONF, rows, abstracts)
        self.assertEqual(papers, [])

    def test_html_link_does_not_displace_openreview_identity(self):
        links = paper_links([{'paper_url': 'https://openreview.net/forum?id=AbCdEfGhIj',
            'eventmedia': [{'name': 'Paper', 'uri': CONF['proceedings_index_url'] + 'p001.html'}]}], '')
        self.assertEqual(links['paper_url'], 'https://openreview.net/forum?id=AbCdEfGhIj')
        links = paper_links([{'paper_url': 'https://official.example/paper.pdf',
            'eventmedia': [{'name': 'Project', 'uri': 'https://project.example/index.html'}]}], '')
        self.assertEqual(links['paper_url'], 'https://official.example/paper.pdf')

    def test_sync_noop_and_failed_refresh_preserve_previous_papers(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = sources()
            fixture.used = []
            with patch.object(storage, 'DATA', Path(temporary)), patch.object(collect, 'DATA', Path(temporary)), \
                    patch.object(collect, 'conferences', return_value=[{**CONF, 'enabled': True}]), \
                    patch.object(collect, 'Fetcher', return_value=fixture):
                first = collect.sync()[0]
                self.assertEqual(first['status'], 'success')
                self.assertTrue(first['complete'])
                before = storage.all_papers()[0]
                second = collect.sync()[0]
                self.assertEqual((second['added'], second['changed'], second['removed']), (0, 0, 0))
                fixture.get = Mock(side_effect=RuntimeError('Official detail unavailable'))
                self.assertEqual(collect.sync()[0]['status'], 'failed')
                after = storage.all_papers()[0]
                self.assertEqual((before['id'], before['source_hash']), (after['id'], after['source_hash']))
                with patch.object(collect, 'conferences', return_value=[{**CONF, 'enabled': True, 'adapter': 'typo'}]):
                    result = collect.sync()[0]
                    self.assertIn('Unknown conference adapter', result['error'])


if __name__ == '__main__':
    unittest.main()
