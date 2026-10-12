import json
import re
from .storage import ROOT
from functools import lru_cache


@lru_cache(maxsize=4)
def _read_taxonomy(path, modified):
    return json.loads(path.read_text(encoding='utf-8'))


def taxonomy():
    path = ROOT / 'config/taxonomy.json'
    return _read_taxonomy(path, path.stat().st_mtime_ns)


def classify(title, abstract, topic='', keywords=None):
    """Auditable fallback. Model labels supersede these, never presented as human reviewed."""
    text = (title + ' ' + abstract + ' ' + (topic or '') + ' ' + ' '.join(keywords or [])).lower()
    ranked = []
    for item in taxonomy():
        score = sum(len(re.findall(pattern, text)) for pattern in item['patterns'])
        title_score = sum(len(re.findall(pattern, title.lower())) for pattern in item['patterns'])
        if score:
            ranked.append((score + title_score * 4, item['slug']))
    ranked.sort(reverse=True)
    return [slug for _, slug in ranked[:3]] or ['other']
