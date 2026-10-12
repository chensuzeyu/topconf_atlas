import concurrent.futures
import json
import os
import secrets
import threading
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .collect import conferences, sync
from .enrich import enrich
from .storage import ROOT, DATA, all_papers, connect, dumps, enrichment_hash, export, hydrate, now
from .taxonomy import taxonomy
from .query import list_indexed, indexed_status, indexed_categories, TIERS

app = FastAPI(title='TopConf Atlas', version='2.0.0')
FRONT = ROOT / 'frontend'
app.mount('/assets', StaticFiles(directory=FRONT), name='assets')
_job_lock = threading.Lock()
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def latest_reports(db):
    result = {}
    for conf in conferences():
        rows = db.execute('SELECT report FROM runs WHERE conference=? ORDER BY started_at DESC,rowid DESC LIMIT 1', (conf['id'],)).fetchall()
        report = json.loads(rows[0][0]) if rows else {'status': 'not_collected', 'complete': False}
        sources=report.get('sources',[])
        report['source_snapshot_count']=len(sources)
        report['sources']=[s for s in sources if '/poster/' not in s['url'] and '/content/' not in s['url']]
        result[conf['id']] = report
    return result


def status():
    return indexed_status(conferences, latest_reports)


@app.get('/api/meta')
def meta():
    return {**status(), 'categories': indexed_categories()}


@app.get('/api/status')
def get_status():
    return status()


@app.get('/api/reports/{conference}')
def get_report(conference: str):
    if conference not in {c['id'] for c in conferences()}:
        raise HTTPException(404,'Unknown conference')
    with connect() as db:
        row=db.execute('SELECT report FROM runs WHERE conference=? ORDER BY started_at DESC,rowid DESC LIMIT 1',(conference,)).fetchone()
    if not row:raise HTTPException(404,'No collection report')
    return json.loads(row[0])


@app.get('/api/papers')
def list_papers(conference: str | None = None, category: str | None = None, tier: list[str] = Query(default=[]),
                track: str | None = None, q: str = Query('', max_length=300),
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                sort: str = 'title', review: str | None = None,
                tag: list[str] = Query(default=[]), exclusive: bool = False):
    if conference and conference not in {c['id'] for c in conferences()}:
        raise HTTPException(404, 'Unknown conference')
    if category and category not in {c['slug'] for c in taxonomy()}:
        raise HTTPException(404, 'Unknown category')
    tags = set(tag)
    valid_tags = {c['slug'] for c in taxonomy()}
    if tags - valid_tags:
        raise HTTPException(422, 'Unknown intersection tag')
    if (tags or exclusive) and not category:
        raise HTTPException(422, 'Tag filtering requires a topic page')
    if category in tags or (exclusive and tags):
        raise HTTPException(422, 'Exclusive current topic cannot be combined with other tags')
    if set(tier) - TIERS:
        raise HTTPException(422, 'Unknown distinction filter')
    if track and track not in {t for c in conferences() for t in c.get('tracks', {'main':'','position':''})}:
        raise HTTPException(422, 'Unknown paper track')
    if sort not in ('title', 'tier') or review not in (None, 'flagged', 'pending'):
        raise HTTPException(422, 'Unknown sorting or review filter')
    return list_indexed(conference, category, tier, track, q, page, page_size, sort, review, tags, exclusive)


@app.get('/api/papers/{paper_id}')
def get_paper(paper_id: str):
    with connect() as db:
        for _ in range(10):
            alias = db.execute('SELECT canonical FROM paper_aliases WHERE alias=?', (paper_id,)).fetchone()
            if not alias:
                break
            paper_id = alias[0]
        row = db.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Unknown paper')
        return hydrate(row, db)


def authorize(request):
    expected = os.environ.get('ATLAS_ADMIN_TOKEN')
    if expected:
        actual = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not secrets.compare_digest(actual, expected):
            raise HTTPException(401, 'Admin token required')
    elif request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Management is local-only; set ATLAS_ADMIN_TOKEN for remote access')
    origin = request.headers.get('Origin')
    if origin and urlparse(origin).netloc != request.headers.get('Host'):
        raise HTTPException(403, 'Cross-origin management request rejected')
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        raise HTTPException(403, 'Cross-site management request rejected')


class EditPaper(BaseModel):
    title_zh: str = Field(max_length=1000)
    summary_zh: str = Field(min_length=1, max_length=2000)
    abstract_zh: str = Field(min_length=1, max_length=30000)
    categories: list[str] = Field(min_length=1, max_length=8)
    review_status: str = 'reviewed'
    quality_flags: list[str] = Field(default_factory=list)


@app.patch('/api/admin/papers/{paper_id}')
def edit_paper(paper_id: str, edit: EditPaper, request: Request):
    authorize(request)
    if not set(edit.categories) <= {t['slug'] for t in taxonomy()}:
        raise HTTPException(422, 'Invalid category')
    if edit.review_status not in ('reviewed', 'machine'):
        raise HTTPException(422, 'Invalid review status')
    payload = edit.model_dump()
    with connect() as db:
        row = db.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Unknown paper')
        payload['review_input_hash'] = enrichment_hash(json.loads(row['payload']))
        previous = db.execute('SELECT payload FROM overrides WHERE paper_id=?', (paper_id,)).fetchone()
        db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?)', (paper_id, dumps(payload), now()))
        db.execute('INSERT INTO audit(paper_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?)',
                   (paper_id, 'manual_edit', previous[0] if previous else None, dumps(payload), now()))
    export()
    return get_paper(paper_id)


class JobSpec(BaseModel):
    kind: str
    conference: str | None = None


@app.post('/api/admin/jobs', status_code=202)
def create_job(spec: JobSpec, request: Request):
    authorize(request)
    if spec.kind not in ('sync', 'enrich', 'export'):
        raise HTTPException(422, 'Unknown job type')
    if spec.conference and spec.conference not in {c['id'] for c in conferences()}:
        raise HTTPException(422, 'Unknown conference')
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, 'Another managed job is running')
    job_id = secrets.token_hex(12)
    with connect() as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)', (job_id, spec.kind, 'running', now(), None, dumps(spec.model_dump())))
    def run():
        state, result = 'success', {}
        try:
            if spec.kind == 'sync':
                result = sync(spec.conference)
                if any(r['status'] != 'success' for r in result):
                    state = 'failed'
            elif spec.kind == 'enrich':
                result = enrich(spec.conference)
                if result['errors']:
                    state = 'failed'
            export()
        except Exception as e:
            state, result = 'failed', {'error': str(e)[:500]}
        finally:
            with connect() as db:
                db.execute('UPDATE jobs SET status=?,finished_at=?,payload=? WHERE id=?', (state, now(), dumps(result), job_id))
            _job_lock.release()
    _executor.submit(run)
    return {'id': job_id, 'status': 'running'}


@app.get('/api/admin/audit/{paper_id}')
def audit(paper_id: str, request: Request):
    authorize(request)
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM audit WHERE paper_id=? ORDER BY id DESC', (paper_id,))]


@app.get('/api/export')
def download_catalog():
    if not (DATA / 'catalog.json').exists():
        export()
    return FileResponse(DATA / 'catalog.json', filename='topconf-atlas-catalog.json')


@app.post('/api/admin/papers/{paper_id}/cache-pdf')
def save_pdf(paper_id: str, request: Request):
    authorize(request)
    from .pdf import cache_pdf
    paper = get_paper(paper_id)
    try:
        result = cache_pdf(paper)
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    return result


@app.get('/api/pdf/{paper_id}')
def local_pdf(paper_id: str):
    paper = get_paper(paper_id)
    path = DATA / 'pdf' / paper['conference'] / (paper['id'] + '.pdf')
    if not path.exists():
        raise HTTPException(404, 'PDF is not cached yet')
    return FileResponse(path, media_type='application/pdf', filename=paper['id'] + '.pdf')


@app.get('/{route:path}')
def frontend(route: str):
    if route.startswith('api/'):
        raise HTTPException(404)
    return FileResponse(FRONT / 'index.html')
