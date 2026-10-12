import hashlib
import json
from collections import Counter
from .storage import DATA, all_papers, connect, now, write_json
from .enrich import enrichment_hash, numeric_tokens
from .taxonomy import taxonomy
from .collect import conferences, RANK


def audit():
    issues, warnings = [], []
    papers = all_papers()
    valid = {c['slug'] for c in taxonomy()}
    with connect() as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            issues.append({'database': integrity})
    counts = []
    for c in conferences():
        ps = [p for p in papers if p['conference'] == c['id']]
        counts.append({'conference': c['id'], 'papers': len(ps), 'tiers': dict(Counter(p['tier'] for p in ps)),
                       'tracks': dict(Counter(p['track'] for p in ps)),
                       'translated': sum(p['enrichment_status'] == 'ready' for p in ps),
                       'abstracts': sum(bool(p.get('abstract_en')) for p in ps),
                       'track_verification_pending': sum(p['track']=='unverified' for p in ps),
                       'awards': sum(bool(p.get('awards')) for p in ps),
                       'cached_pdfs': sum(p.get('pdf_cached', False) for p in ps)})
        directory = DATA / 'raw' / c['id']
        manifest = json.loads((directory / 'manifest.json').read_text()) if (directory / 'manifest.json').exists() else {}
        for url, record in manifest.items():
            for snapshot in [record,*record.get('history',[])]:
                file = directory / snapshot['file']
                if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != snapshot['sha256']:
                    issues.append({'source': url, 'file':snapshot['file'], 'error': 'source snapshot hash mismatch'})
    for p in papers:
        if p['tier'] not in RANK or not p['evidence']:
            issues.append({'id': p['id'], 'error': 'missing official acceptance evidence'})
        if p.get('acceptance_status') != 'accepted':
            issues.append({'id':p['id'],'error':'acceptance not confirmed'})
        if p['conference'] == 'NeurIPS2026' and (p.get('distinctions') or p['tier'] != 'unlabeled'):
            issues.append({'id':p['id'],'error':'NeurIPS distinctions must remain disabled'})
        if not p['abstract_en'] or not p['categories'] or not set(p['categories']) <= valid:
            issues.append({'id': p['id'], 'error': 'missing abstract or invalid categories'})
        if p['enrichment_status'] != 'ready' or not all(p.get(k) for k in ('title_zh', 'summary_zh', 'abstract_zh')):
            issues.append({'id': p['id'], 'error': 'Chinese processing pending'})
        if p.get('quality_flags'):
            warnings.append({'id': p['id'], 'flags': p['quality_flags']})
        if p['track']=='unverified':
            warnings.append({'id':p['id'],'flags':['official_track_verification_pending']})
        if not p['pdf_url']:
            warnings.append({'id': p['id'], 'flags': ['missing_pdf_url']})
    identities = Counter((p['conference'],p.get('canonical_source_id') or p['id']) for p in papers)
    for identity,n in identities.items():
        if n>1:issues.append({'identity':list(identity),'error':'duplicate official paper identity','count':n})
    catalog = DATA / 'catalog.json'
    if catalog.exists():
        data = json.loads(catalog.read_text())
        if {p['id'] for p in data['papers']} != {p['id'] for p in papers}:
            issues.append({'error': 'catalog does not match the current active database'})
    else:
        issues.append({'error': 'catalog not exported'})
    result = {'checked_at': now(), 'database': integrity, 'total': len(papers), 'conferences': counts,
              'categories': len(valid), 'issues': issues, 'warnings': warnings, 'passed': not issues}
    write_json(DATA / 'reports' / 'integrity-latest.json', result)
    return result
