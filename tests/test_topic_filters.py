import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import tempfile
import json
from pathlib import Path
from atlas import server, storage


class TopicFilterTests(unittest.TestCase):
    def setUp(self):
        def paper(identifier, categories, tier='oral'):
            return {'id': identifier, 'conference': 'CVPR2026', 'title': identifier,
                    'abstract_en': 'robotics example', 'authors': [], 'categories': categories,
                    'tier': tier, 'track': 'main', 'awards': []}
        self.papers = [paper('single', ['robotics']),
                       paper('agent', ['robotics', 'llm_agent']),
                       paper('both', ['robotics', 'llm_agent', 'llm_reasoning']),
                       paper('reasoning', ['robotics', 'llm_reasoning'], 'highlight'),
                       paper('outside', ['llm_agent'])]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.mock = patch.object(storage, 'DATA', Path(self.temporary.name))
        self.mock.start()
        self.addCleanup(self.mock.stop)
        with storage.connect() as db:
            for paper in self.papers:
                paper.update(official_url='https://official.example',pdf_url='',evidence=[],
                             tiers=[paper['tier']],distinctions=[paper['tier']])
                db.execute('INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (paper['id'],paper['conference'],paper['title'],paper['tier'],paper['track'],paper['abstract_en'],
                            storage.digest(paper),storage.dumps(paper),1,storage.now(),storage.now()))
        self.client = TestClient(server.app)

    def test_counts_are_full_scope_and_not_pagination_or_selection(self):
        result = self.client.get('/api/papers?category=robotics&page_size=1').json()
        self.assertEqual(result['total'], 4)
        self.assertEqual(result['topic_facets']['exclusive_count'], 1)
        self.assertEqual({t['slug']: t['count'] for t in result['topic_facets']['tags']},
                         {'llm_agent': 2, 'llm_reasoning': 2})
        selected = self.client.get('/api/papers?category=robotics&tag=llm_agent&tag=llm_reasoning').json()
        self.assertEqual([p['id'] for p in selected['items']], ['both'])
        self.assertEqual(selected['topic_facets'], result['topic_facets'])

    def test_exclusive_and_other_filters(self):
        result = self.client.get('/api/papers?category=robotics&exclusive=true').json()
        self.assertEqual([p['id'] for p in result['items']], ['single'])
        result = self.client.get('/api/papers?category=robotics&tier=highlight&tag=llm_agent').json()
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['topic_facets']['exclusive_count'], 0)
        self.assertEqual({t['slug']: t['count'] for t in result['topic_facets']['tags']},
                         {'llm_agent': 0, 'llm_reasoning': 1})
        result = self.client.get('/api/papers?category=robotics&q=both').json()
        self.assertEqual(result['topic_facets']['total'], 1)
        self.assertEqual(result['topic_facets']['exclusive_count'], 0)

    def test_invalid_combination_and_duplicates(self):
        for query in ('tag=llm_agent', 'exclusive=true', 'category=robotics&tag=unknown',
                      'category=robotics&tag=robotics',
                      'category=robotics&exclusive=true&tag=llm_agent'):
            self.assertEqual(self.client.get('/api/papers?' + query).status_code, 422, query)
        result = self.client.get('/api/papers?category=robotics&tag=llm_agent&tag=llm_agent').json()
        self.assertEqual(result['total'], 2)


if __name__ == '__main__':
    unittest.main()
