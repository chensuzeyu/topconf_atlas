import concurrent.futures
import hashlib
import json
import os
import time

import requests

from .storage import DATA, all_papers, digest, now, write_json


def cache_pdf(paper, refresh=False):
    path = DATA / 'pdf' / paper['conference'] / (paper['id'] + '.pdf')
    metadata = path.with_suffix('.json')
    if path.exists() and metadata.exists() and not refresh:
        saved = json.loads(metadata.read_text())
        if saved.get('source_url') == paper['pdf_url'] and saved.get('sha256') == hashlib.sha256(path.read_bytes()).hexdigest():
            return saved
    if not paper.get('pdf_url'):
        raise RuntimeError('No confirmed full-text PDF URL for this paper')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.' + os.urandom(4).hex() + '.part')
    last = None
    for attempt in range(3):
        try:
            with requests.get(paper['pdf_url'], stream=True, timeout=(15, 120)) as response:
                # Never cache a challenge HTML page or an unsolicited partial response.
                if response.status_code != 200:
                    raise RuntimeError(f'PDF source HTTP {response.status_code}')
                size, sha = 0, hashlib.sha256()
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(131072):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > 250 * 1024 * 1024:
                            raise RuntimeError('PDF exceeds the 250 MiB per-file limit')
                        sha.update(chunk)
                        output.write(chunk)
                with temporary.open('rb') as source:
                    if source.read(5) != b'%PDF-':
                        raise RuntimeError('Source returned non-PDF content')
                    source.seek(max(0, size - 4096))
                    if b'%%EOF' not in source.read():
                        raise RuntimeError('PDF appears truncated (missing EOF marker)')
                length = response.headers.get('Content-Length')
                if length and not response.headers.get('Content-Encoding') and int(length) != size:
                    raise RuntimeError('PDF length mismatch')
                temporary.replace(path)
                result = {'paper_id': paper['id'], 'source_url': paper['pdf_url'], 'final_url': response.url,
                          'downloaded_at': now(), 'bytes': size, 'sha256': sha.hexdigest(),
                          'file': str(path.relative_to(DATA))}
                write_json(metadata, result)
                return result
        except Exception as e:
            last = e
            temporary.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(attempt + 1)
    raise last


def download(conference=None, workers=3, limit=None, refresh=False):
    papers = all_papers(conference=conference)
    if limit:
        papers = papers[:limit]
    def process(p):
        try:
            return {'id': p['id'], 'status': 'cached', **cache_pdf(p, refresh)}
        except Exception as e:
            return {'id': p['id'], 'status': 'failed', 'error': str(e)[:300]}
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for result in executor.map(process, papers):
            results.append(result)
            if len(results) % 25 == 0 or result['status'] == 'failed':
                print('PDF', len(results), '/', len(papers), result['status'], result.get('error', ''), flush=True)
    report = {'finished_at': now(), 'requested': len(papers), 'cached': sum(r['status'] == 'cached' for r in results), 'results': results}
    write_json(DATA / 'reports' / ('pdf-' + now().replace(':', '') + '.json'), report)
    return report
