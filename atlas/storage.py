import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('ATLAS_DATA_DIR', ROOT / 'data'))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else dumps(value)).encode()).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.' + secrets.token_hex(5) + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


class Database(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'atlas.sqlite3', timeout=30, factory=Database)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA foreign_keys=ON')
    old_triggers = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'dirty_%' AND sql LIKE '%INSERT OR IGNORE%'").fetchall()
    for trigger in old_triggers:
        db.execute('DROP TRIGGER '+trigger[0])
    db.executescript('''
    CREATE TABLE IF NOT EXISTS papers (
        id TEXT PRIMARY KEY, conference TEXT NOT NULL, title TEXT NOT NULL,
        tier TEXT NOT NULL, track TEXT NOT NULL, abstract_en TEXT NOT NULL,
        source_hash TEXT NOT NULL, payload TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS papers_conf ON papers(conference,active,tier);
    CREATE TABLE IF NOT EXISTS paper_aliases (
        alias TEXT PRIMARY KEY, canonical TEXT NOT NULL REFERENCES papers(id)
    );
    CREATE TABLE IF NOT EXISTS enrichments (
        paper_id TEXT NOT NULL REFERENCES papers(id), input_hash TEXT NOT NULL,
        payload TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(paper_id,input_hash)
    );
    CREATE TABLE IF NOT EXISTS overrides (
        paper_id TEXT PRIMARY KEY REFERENCES papers(id), payload TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY, conference TEXT NOT NULL, started_at TEXT NOT NULL,
        status TEXT NOT NULL, report TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY, paper_id TEXT, action TEXT NOT NULL,
        before_json TEXT, after_json TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS query_dirty (paper_id TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS paper_query (
        id TEXT PRIMARY KEY REFERENCES papers(id), conference TEXT NOT NULL,
        tier TEXT NOT NULL, track TEXT NOT NULL, active INTEGER NOT NULL,
        title_sort TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL,
        translated INTEGER NOT NULL, reviewed INTEGER NOT NULL, flagged INTEGER NOT NULL,
        has_award INTEGER NOT NULL, last_seen TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS query_conf ON paper_query(active,conference,track,tier,title_sort);
    CREATE TABLE IF NOT EXISTS paper_topics (
        paper_id TEXT NOT NULL REFERENCES papers(id), slug TEXT NOT NULL,
        PRIMARY KEY(paper_id,slug)
    );
    CREATE INDEX IF NOT EXISTS topics_slug ON paper_topics(slug,paper_id);
    CREATE TABLE IF NOT EXISTS paper_distinctions (
        paper_id TEXT NOT NULL REFERENCES papers(id), distinction TEXT NOT NULL,
        PRIMARY KEY(paper_id,distinction)
    );
    CREATE INDEX IF NOT EXISTS distinctions_label ON paper_distinctions(distinction,paper_id);
    CREATE TRIGGER IF NOT EXISTS dirty_paper_insert AFTER INSERT ON papers BEGIN
        INSERT INTO query_dirty SELECT NEW.id WHERE NOT EXISTS(SELECT 1 FROM query_dirty WHERE paper_id=NEW.id); END;
    CREATE TRIGGER IF NOT EXISTS dirty_paper_update AFTER UPDATE ON papers BEGIN
        INSERT INTO query_dirty SELECT NEW.id WHERE NOT EXISTS(SELECT 1 FROM query_dirty WHERE paper_id=NEW.id); END;
    CREATE TRIGGER IF NOT EXISTS dirty_enrichment_insert AFTER INSERT ON enrichments BEGIN
        INSERT INTO query_dirty SELECT NEW.paper_id WHERE NOT EXISTS(SELECT 1 FROM query_dirty WHERE paper_id=NEW.paper_id); END;
    CREATE TRIGGER IF NOT EXISTS dirty_enrichment_update AFTER UPDATE ON enrichments BEGIN
        INSERT INTO query_dirty SELECT NEW.paper_id WHERE NOT EXISTS(SELECT 1 FROM query_dirty WHERE paper_id=NEW.paper_id); END;
    CREATE TRIGGER IF NOT EXISTS dirty_override_insert AFTER INSERT ON overrides BEGIN
        INSERT INTO query_dirty SELECT NEW.paper_id WHERE NOT EXISTS(SELECT 1 FROM query_dirty WHERE paper_id=NEW.paper_id); END;
    CREATE TRIGGER IF NOT EXISTS dirty_override_update AFTER UPDATE ON overrides BEGIN
        INSERT INTO query_dirty SELECT NEW.paper_id WHERE NOT EXISTS(SELECT 1 FROM query_dirty WHERE paper_id=NEW.paper_id); END;
    ''')
    return db


@lru_cache(maxsize=4)
def _taxonomy_document(path, modified):
    return json.loads(Path(path).read_text())


def enrichment_hash(paper):
    path = ROOT / 'config/taxonomy.json'
    return digest({'title': paper['title'], 'abstract_en': paper['abstract_en'], 'prompt_version': 'zh-v1',
                   'taxonomy': _taxonomy_document(str(path), path.stat().st_mtime_ns)})


def hydrate(row, db, enrichments=None, overrides=None):
    paper = json.loads(row['payload'])
    paper.update(active=bool(row['active']), first_seen=row['first_seen'], last_seen=row['last_seen'])
    h = enrichment_hash(paper)
    e = ((enrichments.get((paper['id'], h))) if enrichments is not None else
         db.execute('SELECT payload FROM enrichments WHERE paper_id=? AND input_hash=?', (paper['id'], h)).fetchone())
    if e:
        paper.update(json.loads(e[0]))
        paper['enrichment_status'] = 'ready'
    else:
        paper.update(title_zh='', abstract_zh='', summary_zh='', enrichment_status='pending')
    override = (overrides.get(paper['id']) if overrides is not None else
                db.execute('SELECT payload,updated_at FROM overrides WHERE paper_id=?', (paper['id'],)).fetchone())
    if override:
        edited = json.loads(override[0])
        paper.update(edited)
        if edited.get('review_input_hash') and edited['review_input_hash'] != h:
            paper['quality_flags'] = list(set(paper.get('quality_flags', [])) | {'source_changed_after_review'})
            paper['review_status'] = 'needs_review'
        paper['reviewed_at'] = override[1]
    paper['pdf_cached'] = (DATA / 'pdf' / paper['conference'] / (paper['id'] + '.pdf')).exists()
    return paper


def hydrate_many(rows, db):
    result = []
    for start in range(0, len(rows), 400):
        batch = rows[start:start+400]
        ids = [r['id'] for r in batch]
        marks = ','.join('?' for _ in ids)
        enrichments = {(r['paper_id'],r['input_hash']): (r['payload'],) for r in
                       db.execute(f'SELECT paper_id,input_hash,payload FROM enrichments WHERE paper_id IN ({marks})', ids)}
        overrides = {r['paper_id']: (r['payload'],r['updated_at']) for r in
                     db.execute(f'SELECT * FROM overrides WHERE paper_id IN ({marks})', ids)}
        result.extend(hydrate(r, db, enrichments, overrides) for r in batch)
    return result


LIST_FIELDS = ['id','conference','title','title_zh','tier','tiers','distinctions','distinction_status',
               'acceptance_status','presentation_types','awards','track','categories','summary_zh',
               'authors','enrichment_status','review_status','quality_flags']


def refresh_query_index(db):
    """Maintain effective, searchable list metadata; full abstracts are hydrated only for details."""
    db.execute('INSERT OR IGNORE INTO query_dirty SELECT id FROM papers WHERE id NOT IN (SELECT id FROM paper_query)')
    rows = db.execute('SELECT p.* FROM papers p JOIN query_dirty d ON d.paper_id=p.id').fetchall()
    if not rows:
        return
    for p in hydrate_many(rows, db):
        if 'distinctions' not in p:
            p['distinctions'] = [t for t in p.get('tiers', [p['tier']]) if t in ('oral','spotlight','highlight')]
        slim = {k:p.get(k) for k in LIST_FIELDS}
        search = ' '.join(str(p.get(k) or '') for k in ('title','title_zh','abstract_en','abstract_zh','summary_zh'))
        search += ' ' + ' '.join(a.get('fullname','') for a in p.get('authors',[]))
        db.execute('INSERT OR REPLACE INTO paper_query VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (p['id'],p['conference'],p['tier'],p['track'],int(p['active']),p['title'].casefold(),
                    search.casefold(),dumps(slim),int(p['enrichment_status']=='ready'),
                    int(p.get('review_status')=='reviewed'),int(bool(p.get('quality_flags'))),
                    int(bool(p.get('awards'))),p['last_seen']))
        db.execute('DELETE FROM paper_topics WHERE paper_id=?',(p['id'],))
        db.executemany('INSERT INTO paper_topics VALUES (?,?)',[(p['id'],s) for s in set(p['categories'])])
        db.execute('DELETE FROM paper_distinctions WHERE paper_id=?',(p['id'],))
        db.executemany('INSERT INTO paper_distinctions VALUES (?,?)',[(p['id'],s) for s in set(p['distinctions'])])
        db.execute('DELETE FROM query_dirty WHERE paper_id=?',(p['id'],))


def all_papers(db=None, conference=None, include_inactive=False):
    own = db is None
    db = db or connect()
    sql = 'SELECT * FROM papers WHERE 1=1'
    args = []
    if not include_inactive:
        sql += ' AND active=1'
    if conference:
        sql += ' AND conference=?'
        args.append(conference)
    result = hydrate_many(db.execute(sql + ' ORDER BY conference,title', args).fetchall(), db)
    if own:
        db.close()
    return result


def export():
    with connect() as db:
        papers = all_papers(db, include_inactive=True)
        for p in papers:
            write_json(DATA / 'papers' / p['conference'] / (p['id'] + '.json'), p)
        active = [p for p in papers if p['active']]
        write_json(DATA / 'catalog.json', {'generated_at': now(), 'count': len(active), 'papers': active})
        write_json(DATA / 'archive.json', {'generated_at': now(), 'papers': papers})
    return len(active)
