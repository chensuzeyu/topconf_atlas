import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from atlas import collect, storage, enrich, server, pdf
from atlas.collect import normalize, tier_of, miniconf

CONF = {'id': 'TEST2026', 'name': 'TEST', 'year': 2026, 'domain': 'official.example',
        'source_group': 'TEST.cc/2026/Conference', 'adapter': 'miniconf', 'enabled': True,
        'extra_groups': ['TEST.cc/2026/Position_Paper_Track']}


def row(event_id=1, title='A robust web agent', kind='Poster', decision='Accept (Spotlight)', group=None, related=None):
    return {'id': event_id, 'name': title, 'eventtype': kind, 'decision': decision,
            'sourceurl': 'https://openreview.net/group?id=' + (group or CONF['source_group']),
            'virtualsite_url': '/virtual/2026/poster/' + str(event_id),
            'paper_url': 'https://openreview.net/forum?id=' + ('AbCdEfGhIj' if event_id == 1 else f'TestPaper{event_id:02}'),
            'authors': [{'fullname': 'Test Author', 'institution': 'Example University'}],
            'keywords': [], 'eventmedia': [], 'related_events_ids': related or []}


class NormalizationTests(unittest.TestCase):
    def test_distinction_not_inferred_from_title(self):
        self.assertIsNone(tier_of(row(title='Spotlight on AI', decision='Accept (Poster)')))
        self.assertIsNone(tier_of(row(decision='Withdrawn (Oral)', kind='Oral')))
        self.assertEqual(tier_of(row(decision='Accept (spotlight)', kind='Oral')), 'oral')

    def test_pair_merge_title_change_and_track_exclusion(self):
        records = [row(1, decision='Accept (Poster)', related=[2]),
                   row(2, title='A robust web agent: corrected title', kind='Oral', decision=None, related=[1]),
                   row(3, group='TEST.cc/2026/Workshop', kind='Oral'),
                   row(4, title='Ordinary poster', decision='Accept (Poster)')]
        ps, report = normalize(CONF, records, {'1': 'We propose a robust web agent. Accuracy is 90%.'})
        self.assertEqual(len(ps), 2)
        self.assertEqual(ps[1]['tier'], 'poster')
        self.assertEqual(ps[0]['event_ids'], [1, 2])
        self.assertEqual(ps[0]['tier'], 'oral')
        self.assertEqual(ps[0]['title'], 'A robust web agent')
        self.assertIn('llm_agent', ps[0]['categories'])
        self.assertEqual(len(report['excluded_sources']), 1)

    def test_synthetic_forum_does_not_replace_real_forum(self):
        r = row(kind='Oral')
        r['paper_url'] = 'https://openreview.net/forum?id=2026-Oral--42-deadbeef'
        r['eventmedia'] = [{'name': 'OpenReview', 'uri': 'https://openreview.net/forum?id=RealPaperID'}]
        ps, _ = normalize(CONF, [r], {'1': 'We propose an agent.'})
        self.assertEqual(ps[0]['pdf_url'], 'https://openreview.net/pdf?id=RealPaperID')

    def test_pmlr_uses_official_forum_identity_when_titles_change(self):
        conf = {**CONF, 'proceedings_index_url':'https://proceedings.mlr.press/v306/', 'proceedings_adapter':'pmlr'}
        html = '<div class="paper"><p class="title">Corrected title</p><p class="links"><a href="paper.html">abs</a><a href="https://raw.githubusercontent.com/mlresearch/v306/main/assets/p/p.pdf">Download PDF</a><a href="https://openreview.net/forum?id=AbCdEfGhIj">OpenReview</a></p></div>'
        paper = {'title':'Old title', 'paper_url':'https://openreview.net/forum?id=AbCdEfGhIj', 'pdf_url':'https://openreview.net/pdf?id=AbCdEfGhIj'}
        report = collect.augment_proceedings(conf, [paper], Mock(get=Mock(return_value=html)))
        self.assertEqual(report['proceedings_matches'], 1)
        self.assertEqual(paper['proceedings_match_method'], 'official_openreview_id')
        self.assertEqual(paper['title'], 'Old title')
        self.assertIn('raw.githubusercontent.com', paper['pdf_url'])

    def test_award_can_include_ordinary_poster(self):
        r = row(decision='Accept (Poster)')
        awards = {collect.title_key(r['name']): {'title': r['name'], 'label': 'Best Paper', 'source_url': 'https://official.example/awards'}}
        ps, _ = normalize(CONF, [r], {'1': 'We propose an agent.'}, awards)
        self.assertEqual(ps[0]['tier'], 'poster')
        self.assertEqual(ps[0]['awards'][0]['label'], 'Best Paper')

    def test_pagination_complete_and_incomplete(self):
        class Fetcher:
            def get(self, url):
                if 'abstracts.json' in url:
                    return '{}'
                if 'page2' in url:
                    return json.dumps({'count': 2, 'results': [row(2)], 'next': None})
                return json.dumps({'count': 2, 'results': [row(1)], 'next': 'https://official.example/page2'})
        rows, _, coverage = miniconf(CONF, Fetcher())
        self.assertEqual(len(rows), 2)
        self.assertTrue(coverage['pagination_complete'])
        class Incomplete(Fetcher):
            def get(self, url):
                if 'abstracts.json' in url:
                    return '{}'
                return json.dumps({'count': 5, 'results': [row(1)], 'next': None})
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            miniconf(CONF, Incomplete())

    def test_reviewed_source_repair_refuses_changed_abstract(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = 'An official abstract is truncated'
            correction = {'event_ids':[1], 'original_abstract_sha256':storage.digest(original),
                          'abstract_en':original + ' here.'}
            Path(temporary, 'repair.json').write_text(json.dumps([correction]))
            paper = {'event_ids':[1], 'title':'Paper', 'abstract_en':original, 'tier':'oral', 'authors':[], 'evidence':[]}
            with patch.object(collect, 'ROOT', Path(temporary)):
                conf = {**CONF, 'abstract_corrections_file':'repair.json'}
                self.assertEqual(collect.apply_abstract_corrections(conf, [paper])['reviewed_abstract_source_repairs'], 1)
                self.assertEqual(paper['abstract_en'], correction['abstract_en'])
                paper['abstract_en'] = 'New official version'
                with self.assertRaisesRegex(RuntimeError, 'Official abstract changed'):
                    collect.apply_abstract_corrections(conf, [paper])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.root = Path(self.tmp.name)
        for module in (storage, collect, enrich, server, pdf):
            self.stack.enter_context(patch.object(module, 'DATA', self.root))
        self.stack.enter_context(patch.object(collect, 'conferences', return_value=[CONF]))
        self.stack.enter_context(patch.object(server, 'conferences', return_value=[CONF]))
        self.stack.enter_context(patch.object(collect, 'Fetcher', return_value=Mock(used=[])))

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def sync(self, records=None, abstract='We propose a robust web agent. Accuracy is 90%.'):
        records = records or [row()]
        with patch.object(collect, 'miniconf', return_value=(records, {'1': abstract}, {'pagination_complete': True})):
            return collect.sync()[0]

    def test_official_pair_merge_retains_old_links_and_is_idempotent(self):
        from fastapi.testclient import TestClient
        rows = [row(1), row(2, title='A robust web agent (revised)', kind='Oral')]
        abstracts = {'1':'We propose an agent.', '2':'We propose an agent.'}
        with patch.object(collect, 'miniconf', return_value=(rows, abstracts, {})):
            self.assertEqual(collect.sync()[0]['deduplicated_selected_papers'], 2)
        old_ids = {p['id'] for p in storage.all_papers()}
        rows[0]['related_events_ids'] = [2]
        with patch.object(collect, 'miniconf', return_value=(rows, abstracts, {})):
            self.assertEqual(collect.sync()[0]['deduplicated_selected_papers'], 1)
        client = TestClient(server.app)
        canonical = storage.all_papers()[0]['id']
        for old_id in old_ids:
            self.assertEqual(client.get('/api/papers/'+old_id).json()['id'], canonical)
        with patch.object(collect, 'miniconf', return_value=(rows, abstracts, {})):
            self.assertEqual(collect.sync()[0]['changed'], 0)
        with storage.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM audit').fetchone()[0], 1)

    def test_idempotence_and_failed_refresh_preserves_data(self):
        self.assertEqual(self.sync()['added'], 1)
        self.assertEqual(self.sync()['added'], 0)
        with patch.object(collect, 'miniconf', side_effect=RuntimeError('Incomplete source')):
            self.assertEqual(collect.sync()[0]['status'], 'failed')
        ps = storage.all_papers()
        self.assertEqual(len(ps), 1)
        self.assertTrue(ps[0]['active'])

    def test_rename_keeps_identity_and_translation_is_invalidated(self):
        self.sync()
        p = storage.all_papers()[0]
        with storage.connect() as db:
            db.execute('INSERT INTO enrichments VALUES (?,?,?,?)',
                       (p['id'], storage.enrichment_hash(p), json.dumps({'abstract_zh':'译文','summary_zh':'摘要','title_zh':'标题'}), storage.now()))
            db.execute('INSERT INTO overrides VALUES (?,?,?)', (p['id'], json.dumps({'abstract_zh':'人工译文','review_status':'reviewed','review_input_hash':storage.enrichment_hash(p)}), storage.now()))
        self.sync([row(title='A corrected robust web agent')], 'We propose a robust web agent. Accuracy is 95%.')
        updated = storage.all_papers()[0]
        self.assertEqual(p['id'], updated['id'])
        self.assertEqual(updated['abstract_zh'], '人工译文')
        self.assertEqual(updated['enrichment_status'], 'pending')
        self.assertEqual(updated['review_status'], 'needs_review')
        self.assertIn('source_changed_after_review', updated['quality_flags'])

    def test_api_query_edit_and_csrf(self):
        from fastapi.testclient import TestClient
        self.sync()
        client = TestClient(server.app)
        response = client.get('/api/papers?conference=TEST2026&category=llm_agent&q=robust')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 1)
        self.assertEqual(client.get('/api/papers?category=invalid').status_code, 404)
        self.assertEqual(client.get('/api/papers?page=0').status_code, 422)
        p = storage.all_papers()[0]
        body = {'title_zh':'论文标题','abstract_zh':'完整中文摘要','summary_zh':'这是人工校对的一句话介绍。','categories':['llm_agent']}
        self.assertEqual(client.patch('/api/admin/papers/'+p['id'], json=body, headers={'Origin':'https://malicious.example'}).status_code, 403)
        self.assertEqual(client.patch('/api/admin/papers/'+p['id'], json=body).status_code, 200)
        self.sync()
        self.assertEqual(storage.all_papers()[0]['summary_zh'], body['summary_zh'])
        self.assertEqual(client.get('/api/admin/audit/'+p['id']).json()[0]['action'], 'manual_edit')
        self.assertEqual(client.get('/api/no-such-route').status_code, 404)

    def test_pdf_rejects_html_and_partial_responses(self):
        self.sync()
        p = storage.all_papers()[0]
        response = Mock(status_code=200, headers={}, url=p['pdf_url'])
        response.iter_content.return_value = iter([b'<html>not a paper</html>'])
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        with patch.object(pdf.requests, 'get', return_value=response), patch.object(pdf.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                pdf.cache_pdf(p)
        self.assertFalse(list(self.root.rglob('*.pdf')))
        response.status_code = 206
        with patch.object(pdf.requests, 'get', return_value=response), patch.object(pdf.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, '206'):
                pdf.cache_pdf(p)


class TranslationTests(unittest.TestCase):
    def test_numbers_attached_to_extracted_words_units_and_dimensions(self):
        self.assertEqual(enrich.numeric_tokens('with99.5%'), {'99.5'})
        self.assertEqual(enrich.numeric_tokens('1.3 million clips; 2.3 million images'),
                         enrich.numeric_tokens('130 万片段；230 万图像'))
        self.assertEqual(enrich.numeric_tokens('2D and 3D geometry'), enrich.numeric_tokens('二维和三维几何'))
        self.assertFalse(enrich.numeric_tokens('di_x001B_usion'))
        self.assertEqual(enrich.numeric_tokens('two trillion tokens and five-thousand images'),
                         enrich.numeric_tokens('2 万亿 token 和 5000 张图像'))
        self.assertEqual(enrich.numeric_tokens('148Khuman preference pairs'), {'148000'})
        self.assertEqual(enrich.numeric_tokens('twelve datasets and fifteen models'), enrich.numeric_tokens('十二个数据集与十五个模型'))
        self.assertEqual(enrich.numeric_tokens('reconstructs3D; 2-D projection; con(cid:28)figuration'), set())
        self.assertEqual(enrich.numeric_tokens('0.71 MoGe; 8.1mDFF'), {'0.71','8.1'})
        self.assertEqual(enrich.numeric_tokens('ten billion'), enrich.numeric_tokens('一百亿'))
        self.assertEqual(enrich.numeric_tokens('72.5 million'), enrich.numeric_tokens('72.5 百万'))

    def test_full_translation_validation_and_number_flags(self):
        p = {'id':'p1','title':'Paper','abstract_en':'We propose an agent that achieves 90% accuracy.'}
        output = {'papers':[{'id':'p1','title_zh':'中文标题','abstract_zh':'我们提出一种智能体，可实现很高的准确率。',
                           'summary_zh':'本文通过检索与自检机制改进智能体的任务规划，并在受控实验中评估该方法的准确率。', 'categories':['llm_agent']}]}
        items = enrich.validate_output([p], output)
        self.assertIn('numeric_translation_review', items[0]['quality_flags'])
        p['title'] = 'VGGT-Ω'
        output['papers'][0]['title_zh'] = 'VGGT-Ω'
        self.assertEqual(enrich.validate_output([p], output)[0]['title_zh'], 'VGGT-Ω')
        for name in ('Avey-B','Sapiens2'):
            p['title']=name;output['papers'][0]['title_zh']=name
            self.assertEqual(enrich.validate_output([p],output)[0]['title_zh'],name)
        p['title']='An English Title';output['papers'][0]['title_zh']='An English Title'
        with self.assertRaisesRegex(ValueError,'Missing Chinese text'):enrich.validate_output([p],output)
        output['papers'][0]['id']='wrong'
        with self.assertRaises(ValueError):
            enrich.validate_output([p], output)


if __name__ == '__main__':
    unittest.main()
