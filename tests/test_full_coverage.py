import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from atlas import storage, server
from atlas.collect import normalize, miniconf, neurips_full

CONF={'id':'NeurIPS2026','name':'NeurIPS','year':2026,'domain':'neurips.cc',
      'source_group':'NeurIPS.cc/2026/Conference','extra_groups':['NeurIPS.cc/2026/Evaluations_and_Datasets_Track'],
      'distinctions_enabled':False}


def row(eid,title='A paper',decision='Accept (poster)',group=None,forum=None):
    return {'id':eid,'name':title,'decision':decision,'eventtype':'Poster',
            'sourceurl':'https://openreview.net/group?id='+(group or CONF['source_group']),
            'paper_url':'https://openreview.net/forum?id='+(forum or f'TestPaper{eid:02}'),
            'virtualsite_url':f'/virtual/2026/poster/{eid}','authors':[{'fullname':'An Author'}],
            'related_events_ids':[]}


class CollectionCoverageTests(unittest.TestCase):
    def test_neurips_complete_export_reconciles_tracks_and_excludes_nonpapers(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            official='https://neurips.cc/virtual/2026/'
            export=[{'name':'A paper','virtualsite_url':official+'poster/1','abstract':'Full official abstract'},
                {'name':'New paper','virtualsite_url':official+'poster/2','abstract':'Another official abstract','speakers/authors':'Ada (Lab, University), Bob'},
                {'name':'Journal paper','virtualsite_url':official+'poster/3','abstract':'A journal abstract'},
                {'name':'Reproduction','virtualsite_url':official+'poster/9','abstract':'Not a proceedings paper'}]
            (directory/'export.json').write_text(json.dumps(export))
            fetch=Mock(directory=directory,offline=True,used=[],manifest={
                'https://neurips.cc/Downloads/2026#posters-json':{'file':'export.json','retrieved_at':'2026-01-01T00:00:00+00:00'}})
            pages={'https://neurips.cc/virtual/2026/papers.html':''.join(
                f'<a href="{official}poster/{i}">{title}</a>' for i,title in [(1,'A paper'),(2,'New paper'),(3,'Journal paper')]),
                official+'poster/2':'<h2 class="event-title">New paper</h2><div class="action-buttons"><a href="https://openreview.net/forum?id=TestPaper02">Paper</a></div>',
                official+'poster/3':'<h2 class="event-title">Journal paper</h2><div class="action-buttons"></div>'}
            fetch.get.side_effect=lambda url,**kwargs:pages[url]
            with patch('atlas.collect.miniconf',return_value=([row(1)],{}, {'pagination_complete':True})):
                rows,abstracts,coverage=neurips_full(CONF,fetch)
            self.assertEqual({r['id'] for r in rows},{1,2})
            self.assertEqual(abstracts['1'],'Full official abstract')
            self.assertEqual(coverage['track_verification_pending'],[2])
            self.assertFalse(coverage['track_metadata_complete'])
            self.assertEqual(rows[1]['authors'][0]['fullname'],'Ada')
            self.assertEqual(len(coverage['excluded_nonproceedings']),2)
            ps,_=normalize(CONF,rows,abstracts)
            self.assertEqual({p['track'] for p in ps},{'main','unverified'})
            journal_url='https://jmlr.org/tmlr/papers/'
            pages[journal_url]='<h4>New paper</h4><a href="https://openreview.net/forum?id=TestPaper02">openreview</a>'
            with patch('atlas.collect.miniconf',return_value=([row(1)],{}, {'pagination_complete':True})):
                journal_rows,_,journal_coverage=neurips_full({**CONF,'journal_index_urls':[journal_url]},fetch)
            self.assertEqual([r['id'] for r in journal_rows],[1])
            self.assertTrue(any(r.get('journal_source')==journal_url for r in journal_coverage['excluded_nonproceedings']))
            export.pop(1);(directory/'export.json').write_text(json.dumps(export))
            with patch('atlas.collect.miniconf',return_value=([row(1)],{}, {'pagination_complete':True})):
                with self.assertRaisesRegex(RuntimeError,'does not cover'):neurips_full(CONF,fetch)

    def test_plain_acceptance_and_disabled_distinctions(self):
        ps,quality=normalize(CONF,[row(1,decision='Accept (oral)'),row(2,title='Ordinary paper')],{'1':'An abstract','2':'An abstract'})
        self.assertEqual(len(ps),2)
        self.assertTrue(all(p['acceptance_status']=='accepted' and p['tier']=='unlabeled' and not p['distinctions'] for p in ps))
        self.assertEqual(ps[0]['evidence'][0]['decision'],'Accept (oral)')
        self.assertEqual(quality['tracks'],{'main':2})

    def test_track_whitelist_and_terminal_decisions(self):
        ps,quality=normalize(CONF,[row(1,group='NeurIPS.cc/2026/Evaluations_and_Datasets_Track'),
            row(2,group='NeurIPS.cc/2026/Workshop'),row(3,decision='Withdrawn (oral)'),row(4,decision='Reject')],{'1':'An abstract'})
        self.assertEqual(len(ps),1);self.assertEqual(ps[0]['track'],'evaluations_datasets')
        self.assertEqual(quality['excluded_sources']['rejected_or_withdrawn'],2)

    def test_forum_identity_merges_events_but_same_title_different_forum_survives(self):
        a=row(1,forum='CanonicalID');b=row(2,title='Corrected title',forum='CanonicalID');c=row(3)
        ps,_=normalize(CONF,[a,b,c],{'1':'Abstract','2':'Abstract','3':'Abstract'})
        self.assertEqual(len(ps),2);self.assertEqual(ps[0]['event_ids'],[1,2])
        self.assertEqual(len({p['id'] for p in ps}),2)

    def test_duplicate_event_rows_are_reported_and_identity_conflict_fails(self):
        a=row(1)
        fetch=Mock(get=Mock(side_effect=['{"1":"Abstract"}',json.dumps({'count':2,'results':[a,a],'next':None})]))
        rows,_,coverage=miniconf(CONF,fetch)
        self.assertEqual(len(rows),1);self.assertEqual(coverage['duplicate_event_rows'],1)
        b={**a,'name':'Conflicting title'}
        fetch=Mock(get=Mock(side_effect=['{}',json.dumps({'count':2,'results':[a,b],'next':None})]))
        with self.assertRaisesRegex(RuntimeError,'Conflicting duplicate'):miniconf(CONF,fetch)


class IndexedQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(storage,'DATA',Path(self.tmp.name));self.patch.start();self.addCleanup(self.patch.stop)
        self.client=TestClient(server.app)
        ps=[('oral','ICML2026',['oral','spotlight'],'oral',['robotics','multimodal'],[]),
            ('ordinary','ICML2026',[],'poster',['robotics'],[]),
            ('neurips','NeurIPS2026',[],'unlabeled',['robotics'],[]),
            ('award','CVPR2026',[],'poster',['robotics'],[{'label':'Best Paper'}])]
        with storage.connect() as db:
            for identifier,conference,distinctions,tier,categories,awards in ps:
                p={'id':identifier,'conference':conference,'title':identifier,'tier':tier,'tiers':distinctions,
                   'distinctions':distinctions,'categories':categories,'awards':awards,'track':'main',
                   'abstract_en':'A study with literal 95% and Unicode STRASSE.','authors':[],
                   'acceptance_status':'accepted','pdf_url':''}
                db.execute('INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (identifier,conference,identifier,tier,'main',p['abstract_en'],storage.digest(p),storage.dumps(p),1,storage.now(),storage.now()))

    def result(self,query):return self.client.get('/api/papers?'+query).json()

    def test_distinction_membership_or_union_and_ordinary_separation(self):
        self.assertEqual(self.result('tier=spotlight')['total'],1)
        self.assertEqual(self.result('tier=oral&tier=spotlight')['total'],1)
        self.assertEqual(self.result('tier=poster')['total'],2)
        self.assertEqual(self.result('conference=NeurIPS2026&tier=oral')['total'],0)
        self.assertEqual(self.result('tier=award')['items'][0]['id'],'award')
        self.assertEqual(self.result('sort=tier')['items'][0]['id'],'award')

    def test_literal_substring_search_and_unicode_casefold(self):
        self.assertEqual(self.result('q=95%25')['total'],4)
        self.assertEqual(self.result('q=Stra%C3%9Fe')['total'],4)
        self.assertEqual(self.result('q=%25')['total'],4)
        self.assertEqual(self.result('q=%27%20OR%201=1')['total'],0)

    def test_enrichment_and_override_refresh_effective_topics_and_search(self):
        self.result('category=robotics')
        with storage.connect() as db:
            p=json.loads(db.execute('SELECT payload FROM papers WHERE id="ordinary"').fetchone()[0])
            db.execute('INSERT INTO enrichments VALUES (?,?,?,?)',('ordinary',storage.enrichment_hash(p),
                storage.dumps({'title_zh':'新中文标题','summary_zh':'这个中文介绍可被查询。','abstract_zh':'完整译文',
                               'categories':['biology'],'review_status':'machine'}),storage.now()))
        self.assertEqual(self.result('q=新中文标题')['items'][0]['id'],'ordinary')
        self.assertEqual(self.result('category=robotics')['total'],3)
        self.assertEqual(self.result('category=biology')['total'],1)
        with storage.connect() as db:
            db.execute('INSERT INTO overrides VALUES (?,?,?)',('ordinary',storage.dumps(
                {'summary_zh':'人工校对后的句子','categories':['robotics','multimodal'],'review_status':'reviewed'}),storage.now()))
        self.assertEqual(self.result('category=robotics&tag=multimodal')['total'],2)
        self.assertEqual(self.result('q=人工校对')['total'],1)
        self.assertEqual(self.result('review=pending')['total'],3)
        with storage.connect() as db:db.execute('UPDATE papers SET active=0 WHERE id="ordinary"')
        self.assertEqual(self.result('q=人工校对')['total'],0)

    def test_validation(self):
        for query in ['tier=invalid','track=invalid','sort=invalid','review=invalid']:
            self.assertEqual(self.client.get('/api/papers?'+query).status_code,422)


if __name__=='__main__':unittest.main()
