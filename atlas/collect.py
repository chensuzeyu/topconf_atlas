import json
import os
import re
import time
import unicodedata
import html
import threading
import concurrent.futures
from datetime import datetime, timezone
from collections import Counter, defaultdict
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from .storage import ROOT, DATA, connect, digest, dumps, now, write_json
from .taxonomy import classify
from .locking import locked

RANK = {'unlabeled': 0, 'poster': 1, 'oral': 3, 'spotlight': 2, 'highlight': 2, 'award': 4}
DISTINCTIONS = {'oral', 'spotlight', 'highlight'}


def conferences():
    return sorted(json.loads((ROOT / 'config/conferences.json').read_text(encoding='utf-8')),
                  key=lambda conf: (conf.get('decision_date') or '9999', conf['id']))


def title_key(title):
    return re.sub(r'\W+', '', unicodedata.normalize('NFKC', title).casefold())


def tier_of(row):
    # The distinction in the decision and the actual presentation are independent.
    # E.g. ICML oral events may still carry "Accept (spotlight)" decisions.
    if re.search(r'\b(reject|withdrawn|withdraw|desk reject)\b', str(row.get('decision') or ''), re.I):
        return None
    text = ' '.join(str(row.get(k) or '') for k in ('decision', 'eventtype', 'event_type'))
    tiers = [tier for tier in DISTINCTIONS if re.search(r'\b' + tier + r'\b', text, re.I)]
    return max(tiers, key=RANK.get) if tiers else None


class Fetcher:
    def __init__(self, conference, offline=False):
        self.directory = DATA / 'raw' / conference
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.directory / 'manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        self.offline = offline
        self.used = []
        self.mutex = threading.Lock()
        self.dirty = 0
        self.last_request = 0

    def flush(self):
        with self.mutex:
            write_json(self.manifest_path, self.manifest)
            self.dirty = 0

    def get(self, url, cached=False):
        item = self.manifest.get(url)
        fresh = item and (datetime.now(timezone.utc) - datetime.fromisoformat(item['retrieved_at'])).total_seconds() < 86400
        if self.offline or (cached and fresh):
            item = self.manifest.get(url)
            if not item:
                raise RuntimeError('No cached official source: ' + url)
            raw = (self.directory / item['file']).read_bytes()
        else:
            last = None
            for attempt in range(3):
                try:
                    proxy = os.environ.get('ATLAS_HTTP_PROXY')
                    with self.mutex:
                        pause = max(0, 0.1 - (time.monotonic() - self.last_request))
                        if pause:
                            time.sleep(pause)
                        self.last_request = time.monotonic()
                    response = requests.get(url, timeout=(15, 90),
                                            proxies={'https': proxy, 'http': proxy} if proxy else None,
                                            headers={'User-Agent': 'TopConfAtlas/1.0 (academic metadata archive)'})
                    response.raise_for_status()
                    raw = response.content
                    if re.search(rb'<title>\s*(One moment, please|Verifying your browser)', raw[:8000], re.I):
                        raise requests.RequestException('Official page returned a JavaScript verification page')
                    break
                except requests.RequestException as e:
                    last = e
                    if getattr(e, 'response', None) is not None and e.response.status_code in (401, 403, 404):
                        raise
                    time.sleep(1 + attempt)
            else:
                # Stable award announcements can use a separately sourced official web extraction.
                # Indexes never fall back silently: an unavailable index fails the refresh.
                archive_index = DATA / 'web_sources' / 'index.json'
                archives = json.loads(archive_index.read_text()) if archive_index.exists() else {}
                if url not in archives:
                    raise last
                archive = archives[url]
                raw = (DATA / 'web_sources' / archive['file']).read_bytes()
                sha = digest(raw.decode('utf-8'))
                filename = sha + '.json'
                (self.directory / filename).write_bytes(raw)
                self.manifest[url] = {'url': url, 'sha256': sha, 'file': filename,
                                      'retrieved_at': archive['retrieved_at'], 'bytes': len(raw),
                                      'retrieval_method': 'official-web-extraction',
                                      'fallback_reason': str(last)[:200]}
                write_json(self.manifest_path, self.manifest)
                self.used.append(self.manifest[url])
                return raw.decode('utf-8')
            sha = digest(raw.decode('utf-8'))
            suffix = '.json' if raw.lstrip().startswith((b'{', b'[')) else '.html'
            filename = sha + suffix
            (self.directory / filename).write_bytes(raw)
            with self.mutex:
                previous = self.manifest.get(url, {})
                history = list(previous.get('history', []))
                if previous and previous.get('sha256') != sha:
                    archived = {k:v for k,v in previous.items() if k!='history'}
                    if not any(item['sha256']==archived['sha256'] for item in history):
                        history.append(archived)
                self.manifest[url] = {'url': url, 'sha256': sha, 'file': filename, 'retrieved_at': now(), 'bytes': len(raw)}
                if history:
                    self.manifest[url]['history'] = history
                self.dirty += 1
                if not cached or self.dirty >= 10:
                    write_json(self.manifest_path, self.manifest)
                    self.dirty = 0
        with self.mutex:
            self.used.append(self.manifest[url])
        return raw.decode('utf-8')


def miniconf(conf, fetcher):
    base = 'https://' + conf['domain']
    stem = conf['name'].lower() + '-' + str(conf['year'])
    url = base + '/static/virtual/data/' + stem + '-orals-posters.json'
    abstracts = json.loads(fetcher.get(base + '/static/virtual/data/' + stem + '-abstracts.json'))
    rows = []
    visited = set()
    expected = None
    while url:
        if url in visited:
            raise RuntimeError('Pagination cycle')
        if urlparse(url).hostname != conf['domain']:
            raise RuntimeError('Untrusted pagination host')
        visited.add(url)
        page = json.loads(fetcher.get(url))
        expected = expected if expected is not None else page['count']
        if page['count'] != expected:
            raise RuntimeError('Official count changed during pagination; retry snapshot')
        rows.extend(page['results'])
        url = page.get('next')
        if url:
            url = url.replace('http://', 'https://', 1)
    if len(rows) != expected:
        raise RuntimeError(f'Incomplete event index: {len(rows)} / {expected}')
    unique = {}
    metadata_conflicts = []
    identity_fields = ('name', 'sourceurl', 'paper_url', 'decision', 'eventtype', 'related_events_ids')
    for row in rows:
        previous = unique.get(row['id'])
        if previous and any(previous.get(k) != row.get(k) for k in identity_fields):
            raise RuntimeError('Conflicting duplicate official event identity: ' + str(row['id']))
        if previous and previous != row:
            metadata_conflicts.append(row['id'])
        unique[row['id']] = row
    return list(unique.values()), abstracts, {'event_rows': len(rows), 'unique_event_rows': len(unique),
        'duplicate_event_rows': len(rows)-len(unique), 'duplicate_metadata_conflicts': sorted(set(metadata_conflicts)),
        'advertised_rows': expected, 'pagination_complete': True}


def neurips_full(conf, fetcher):
    """Reconcile the complete public paper export with the structured program and archived evidence."""
    rows, abstracts, coverage = miniconf(conf, fetcher)
    base = 'https://' + conf['domain']
    index_url = base + f'/static/virtual/data/neurips-{conf["year"]}-orals-posters.json'
    by_id = {}
    for record in fetcher.manifest.get(index_url, {}).get('history', []):
        archived = json.loads((fetcher.directory / record['file']).read_text())
        for row in archived['results']:
            by_id[row['id']] = row
        fetcher.used.append(record)
    by_id.update({r['id']:r for r in rows})
    paper_index_url = base + f'/virtual/{conf["year"]}/papers.html'
    soup = BeautifulSoup(fetcher.get(paper_index_url), 'html.parser')
    index = {int(re.search(r'/(\d+)$',a['href'])[1]):a.get_text(' ',strip=True)
             for a in soup.select('a[href]') if re.search(r'/virtual/'+str(conf['year'])+r'/(?:poster|oral)/\d+$',a['href'])}
    if not index:
        raise RuntimeError('Official NeurIPS paper index is empty')
    download_url = base + f'/Downloads/{conf["year"]}'
    export_key = download_url + '#posters-json'
    cached = fetcher.manifest.get(export_key)
    fresh = cached and (datetime.now(timezone.utc)-datetime.fromisoformat(cached['retrieved_at'])).total_seconds() < 86400
    if cached and (fetcher.offline or fresh):
        raw = (fetcher.directory / cached['file']).read_text()
    elif fetcher.offline:
        raise RuntimeError('No cached complete official poster export')
    else:
        session = requests.Session()
        proxy = os.environ.get('ATLAS_HTTP_PROXY')
        if proxy: session.proxies.update({'http':proxy,'https':proxy})
        form = session.get(download_url, timeout=(15,90))
        form.raise_for_status()
        token = BeautifulSoup(form.text,'html.parser').select_one('input[name=csrfmiddlewaretoken]')
        if not token: raise RuntimeError('Official download form changed')
        fields = {'format':'5','posters':'on','resource':'0','submitaction':'Download Data'}
        response = session.post(download_url, data={**fields,'csrfmiddlewaretoken':token['value']},
            headers={'Origin':base,'Referer':download_url}, timeout=(20,300))
        response.raise_for_status()
        raw = response.text
        sha = digest(raw)
        (fetcher.directory / (sha+'.json')).write_text(raw)
        history=list(cached.get('history',[])) if cached else []
        if cached and cached['sha256']!=sha and not any(r['sha256']==cached['sha256'] for r in history):
            history.append({k:v for k,v in cached.items() if k!='history'})
        cached = {'url':download_url,'method':'POST','request_fields':fields,'sha256':sha,
                  'file':sha+'.json','retrieved_at':now(),'bytes':len(response.content)}
        if history:cached['history']=history
        fetcher.manifest[export_key] = cached
        fetcher.flush()
    export = json.loads(raw)
    if not isinstance(export,list): raise RuntimeError('Official poster export must be an array')
    fetcher.used.append(cached)
    export_by_id = {}
    excluded = []
    for item in export:
        event_id = int(item['virtualsite_url'].rstrip('/').rsplit('/',1)[1])
        if event_id not in index:
            excluded.append({'event_id':event_id,'title':item['name'],'reason':'not in official conference paper index'})
            continue
        if title_key(item['name']) != title_key(index[event_id]):
            raise RuntimeError('Poster export title conflicts with official paper index: '+str(event_id))
        export_by_id[event_id] = item
    missing = sorted(set(index)-set(export_by_id))
    if missing: raise RuntimeError('Complete poster export does not cover official paper index: '+str(missing[:10]))
    journal_forums = {}
    journal_titles = {}
    for journal_url in conf.get('journal_index_urls',[]):
        journal = BeautifulSoup(fetcher.get(journal_url,cached=True),'html.parser')
        for heading in journal.select('h4,dt'):
            journal_titles[title_key(heading.get_text(' ',strip=True))]=journal_url
        for a in journal.select('a[href]'):
            parsed=urlparse(a['href'])
            if parsed.hostname=='openreview.net' and parsed.path=='/forum':
                journal_forums[a['href']]=journal_url
    supplement = [eid for eid in index if eid not in by_id]
    def detail(eid):
        item = export_by_id[eid]
        url = item['virtualsite_url']
        doc = BeautifulSoup(fetcher.get(url,cached=True),'html.parser')
        heading = doc.select_one('.event-title')
        if not heading or title_key(heading.get_text(' ',strip=True)) != title_key(item['name']):
            raise RuntimeError('Official detail title conflict: '+str(eid))
        links = [a['href'] for a in doc.select('.action-buttons a[href]')]
        forum = next((u for u in links if urlparse(u).hostname=='openreview.net' and urlparse(u).path=='/forum'), None)
        journal_source=journal_forums.get(forum) or journal_titles.get(title_key(item['name']))
        if not forum or journal_source:
            return eid, None, journal_source
        authors = []
        for part in re.split(r',\s*(?![^()]*\))', html.unescape(item.get('speakers/authors') or '')):
            name = part.split(' (',1)[0].strip()
            if name:authors.append({'fullname':name,'institution':None})
        return eid, {'id':eid,'name':item['name'],'eventtype':'Poster','decision':'Accepted: official conference paper index',
            'sourceurl':paper_index_url,'virtualsite_url':url,'paper_url':forum,'authors':authors,
            'evidence_kind':'official_paper_index','listing_url':paper_index_url,'track':'unverified',
            'eventmedia':[],'keywords':[],'related_events_ids':[]}, None
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get('ATLAS_FETCH_WORKERS','6'))) as pool:
        futures = {pool.submit(detail,eid):eid for eid in supplement}
        for f in concurrent.futures.as_completed(futures):
            try:
                eid,row,journal_url = f.result()
                if row:by_id[eid] = row
                else:excluded.append({'event_id':eid,'title':index[eid],
                    'reason':'canonical paper found in official journal index' if journal_url else 'no canonical conference OpenReview paper link',
                    'journal_source':journal_url})
            except Exception as e:failures.append({'event_id':futures[f],'error':str(e)[:300]})
    fetcher.flush()
    if failures: raise RuntimeError('Missing official paper details: '+str(failures[:3]))
    for eid,item in export_by_id.items():
        if item.get('abstract'):abstracts[str(eid)] = item['abstract'].strip()
    # Only the complete current index supplies active membership; older structured records supply track evidence.
    rows = [row for eid,row in by_id.items() if eid in index]
    coverage.update(official_paper_index_count=len(index),official_poster_export_count=len(export),
        export_complete=True,structured_supplements=len(supplement),excluded_nonproceedings=excluded,
        track_verification_pending=[r['id'] for r in rows if r.get('track')=='unverified'],
        track_metadata_complete=not any(r.get('track')=='unverified' for r in rows),
        unknown_track_policy='Retain official paper-index entries with canonical OpenReview links; mark track unverified; exclude known journal sources and entries without conference-paper links')
    return rows,abstracts,coverage


def cvpr_listings(conf, fetcher):
    """Official distinction lists avoid a truncated static export and authenticated API."""
    base = 'https://' + conf['domain']
    rows, abstracts, counts = [], {}, {}
    for event, tier in [(f'Highlights{conf["year"]}', 'highlight'), ('Oral', 'oral')]:
        url = f'{base}/virtual/{conf["year"]}/events/{event}'
        soup = BeautifulSoup(fetcher.get(url), 'html.parser')
        cards = soup.select('.event-card[data-event-id]')
        if not cards:
            raise RuntimeError('Official distinction list is empty or markup changed: ' + url)
        for card in cards:
            a = card.select_one('.event-title a[href]')
            abstract = card.select_one('.abstract-text')
            authors = card.select_one('.event-speakers')
            if not a or not abstract:
                raise RuntimeError('Incomplete official event card')
            event_id = int(card['data-event-id'])
            rows.append({'id': event_id, 'name': a.get_text(' ', strip=True),
                         'eventtype': tier.title(), 'decision': 'Official ' + tier.title() + ' listing',
                         'sourceurl': 'https://openreview.net/group?id=' + conf['source_group'],
                         'virtualsite_url': a['href'], 'authors': [{'fullname': name.strip(), 'institution': None}
                             for name in authors.get_text(' ', strip=True).split('⋅')] if authors else [],
                         'listing_url': url, 'keywords': [], 'eventmedia': [], 'related_events_ids': []})
            abstracts[str(event_id)] = abstract.get_text(' ', strip=True)
        counts[tier] = len(cards)
    # One public proceedings index supplies canonical full text links without hundreds of page requests.
    index_url = f'https://openaccess.thecvf.com/{conf["name"]}{conf["year"]}?day=all'
    index = BeautifulSoup(fetcher.get(index_url), 'html.parser')
    links = {title_key(a.get_text(' ', strip=True)): urljoin(index_url, a['href'])
             for a in index.select('dt.ptitle a[href]')}
    anchors_by_url = {urljoin(index_url, a['href']): a for a in index.select('dt.ptitle a[href]')}
    if not links:
        raise RuntimeError('Public proceedings index markup changed')
    for row in rows:
        row['paper_url'] = links.get(title_key(row['name']), '')
        if row['paper_url']:
            row['paper_pdf_url'] = row['paper_url'].replace('/html/', '/papers/').replace('_paper.html', '_paper.pdf')
        else:
            # Title variants between the program and proceedings require an exact official detail lookup.
            detail_url = urljoin(base, row['virtualsite_url'])
            detail = BeautifulSoup(fetcher.get(detail_url), 'html.parser')
            actions = detail.select('.action-buttons a[href]')
            row['eventmedia'] = [{'name': 'Paper', 'uri': a['href']} for a in actions
                                 if any(host in a['href'] for host in ('openaccess.thecvf.com', 'openreview.net', 'arxiv.org'))]
            for a in actions:
                if 'openaccess.thecvf.com/content/' in a['href']:
                    row['paper_url'] = a['href']
                    row['paper_pdf_url'] = a['href'].replace('/html/', '/papers/').replace('_paper.html', '_paper.pdf')
                    break
    selected_links = {r.get('paper_url') for r in rows}
    # Proceedings inclusion is acceptance evidence, not a distinction or presentation label.
    for title, link in links.items():
        if link in selected_links:
            continue
        anchor = anchors_by_url[link]
        rows.append({'id': 'cvf-' + digest(link)[:20], 'name': anchor.get_text(' ', strip=True),
                     'eventtype': None, 'decision': 'Accepted: official proceedings',
                     'sourceurl': 'https://openreview.net/group?id=' + conf['source_group'],
                     'virtualsite_url': link, 'paper_url': link,
                     'paper_pdf_url': link.replace('/html/', '/papers/').replace('_paper.html', '_paper.pdf'),
                     'listing_url': index_url, 'evidence_kind': 'proceedings',
                     'authors': [], 'keywords': [], 'eventmedia': [], 'related_events_ids': []})
    return rows, abstracts, {'event_rows': len(rows), 'advertised_rows': None,
                            'pagination_complete': True, 'official_distinction_counts': counts,
                            'distinction_papers_outside_proceedings_index': [{'event_id':r['id'],'title':r['name'],'url':r.get('paper_url')} for r in rows if r.get('evidence_kind')!='proceedings' and r.get('paper_url') not in anchors_by_url],
                            'proceedings_index_count': len(links), 'missing_proceedings_links': sum(not r['paper_url'] for r in rows)}


def paper_links(rows, base):
    urls = []
    for row in sorted(rows, key=lambda r: r.get('eventtype') != 'Poster'):
        for field in ('paper_url', 'paper_pdf_url'):
            if row.get(field):
                urls.append(urljoin(base, row[field]))
        for media in row.get('eventmedia') or []:
            if media.get('uri') and (media.get('name') in ('OpenReview', 'Paper', 'Paper PDF', 'Code', 'Project')
                                     or any(d in media['uri'] for d in ('openreview.net', 'arxiv.org', 'github.com'))):
                urls.append(urljoin(base, media['uri']))
    # Imported oral events sometimes contain synthetic forum URLs. Prefer canonical media links.
    forums = [u for u in urls if 'openreview.net/forum?' in u and
              re.fullmatch(r'[A-Za-z0-9_]{8,20}', parse_qs(urlparse(u).query).get('id', [''])[0])]
    landing = next(iter(forums), '') or next((u for u in urls if '/html/' in u or '/abs/' in u), '')
    pdf = next((u for u in urls if urlparse(u).path.lower().endswith('.pdf')), '')
    if not pdf and forums:
        pdf = forums[0].replace('/forum?', '/pdf?')
    if not landing:
        landing = pdf
    return {'paper_url': landing, 'pdf_url': pdf,
            'code_url': next((u for u in urls if 'github.com/' in u), ''), 'all_urls': sorted(set(urls))}


def award_records(conf, fetcher):
    records = {}
    for spec in conf.get('award_sources', []):
        soup = BeautifulSoup(fetcher.get(spec['url']), 'html.parser')
        text = title_key(soup.get_text(' ', strip=True))
        for item in spec['papers']:
            if title_key(item['title']) not in text:
                raise RuntimeError('Configured award absent from official announcement: ' + item['title'])
            records[title_key(item['title'])] = {**item, 'source_url': spec['url']}
    return records


def normalize(conf, rows, abstracts, awards=None):
    awards = awards or {}
    allowed = {conf['source_group'], *conf.get('extra_groups', [])}
    groups = defaultdict(list)
    excluded = Counter()
    eligible = {}
    for row in rows:
        group = parse_qs(urlparse(row.get('sourceurl') or '').query).get('id', [''])[0]
        official_index = (row.get('evidence_kind') == 'official_paper_index' and
                          row.get('sourceurl') == 'https://' + conf['domain'] + f'/virtual/{conf["year"]}/papers.html')
        if group not in allowed and not official_index:
            excluded[row.get('sourceurl') or 'unknown source'] += 1
            continue
        decision = str(row.get('decision') or '')
        if re.search(r'\b(reject|withdrawn|withdraw|desk reject)\b', decision, re.I):
            excluded['rejected_or_withdrawn'] += 1
            continue
        if not (re.search(r'\baccept(?:ed)?\b', decision, re.I) or tier_of(row)
                or row.get('evidence_kind') == 'proceedings'):
            excluded['acceptance_not_confirmed'] += 1
            continue
        eligible[row['id']] = row
    # Union paired oral/poster events even if their titles differ after a correction.
    parent = {event_id: event_id for event_id in eligible}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        parent[find(a)] = find(b)
    names, identities = {}, {}
    for event_id, row in eligible.items():
        key = title_key(row['name'])
        identity = paper_links([row], 'https://' + conf['domain'])['paper_url']
        if identity and identity in identities:
            union(event_id, identities[identity])
        if identity:
            identities[identity] = event_id
        if key in names and (not identity or not names[key][1] or identity == names[key][1]):
            union(event_id, names[key][0])
        names[key] = (event_id, identity)
        for related in row.get('related_events_ids') or []:
            if related in eligible:
                union(event_id, related)
    for event_id, row in eligible.items():
        groups[find(event_id)].append(row)
    selected = []
    for events in groups.values():
        raw_tiers = {t for r in events for t in DISTINCTIONS
                     if re.search(r'\b' + t + r'\b', ' '.join(str(r.get(k) or '') for k in ('decision','eventtype','event_type')), re.I)}
        tiers = raw_tiers if conf.get('distinctions_enabled', True) else set()
        award = next((awards[title_key(r['name'])] for r in events if title_key(r['name']) in awards), None)
        tier = max(tiers, key=RANK.get) if tiers else ('poster' if conf.get('distinctions_enabled', True) else 'unlabeled')
        # Prefer the canonical poster record for abstract, author and forum metadata.
        ordered = sorted(events, key=lambda r: (r.get('eventtype') != 'Poster', not bool(abstracts.get(str(r['id'])))))
        main = ordered[0]
        key = title_key(main['name'])
        abstract = next((abstracts.get(str(r['id']), '') for r in ordered if abstracts.get(str(r['id']))), '')
        source_group = parse_qs(urlparse(main.get('sourceurl') or '').query).get('id', [''])[0]
        track = main.get('track') or ('position' if source_group.endswith('/Position_Paper_Track') else
                 'evaluations_datasets' if source_group.endswith('/Evaluations_and_Datasets_Track') else 'main')
        paper = {'id': conf['id'].lower() + '-' + digest(key)[:16], 'conference': conf['id'],
                 'title': main['name'].strip(), 'tier': tier, 'tiers': sorted(tiers, key=RANK.get, reverse=True),
                 'acceptance_status': 'accepted', 'distinctions': sorted(tiers, key=RANK.get, reverse=True),
                 'distinction_status': 'verified' if tiers else ('not_enabled' if not conf.get('distinctions_enabled', True) else 'no_confirmed_distinction'),
                 'presentation_types': sorted({r['eventtype'] for r in events if r.get('eventtype')}),
                 'track': track, 'abstract_en': abstract.strip(), 'authors': main.get('authors') or [],
                 'topic': main.get('topic') or '', 'keywords': main.get('keywords') or [],
                 'categories': classify(main['name'], abstract, main.get('topic'), main.get('keywords')),
                 'classification_method': 'rules-v1',
                 'awards': [award] if award else [],
                 'official_url': urljoin('https://' + conf['domain'], main.get('virtualsite_url') or ''),
                 'event_ids': sorted((r['id'] for r in events), key=str),
                 'evidence': [{'event_id': r['id'], 'decision': r.get('decision'), 'eventtype': r.get('eventtype'),
                               'source_url': r.get('listing_url') or urljoin('https://' + conf['domain'], r.get('virtualsite_url') or ''),
                               'source_group': r.get('sourceurl'), 'kind': r.get('evidence_kind', 'conference_program')} for r in events]}
        paper.update(paper_links(ordered, 'https://' + conf['domain']))
        paper['canonical_source_id'] = paper['paper_url'] or str(main['id'])
        # A shared title alone must never collide two different official papers.
        paper['id'] = conf['id'].lower() + '-' + digest(paper['canonical_source_id'])[:16]
        paper['source_hash'] = digest({k: paper[k] for k in ('title', 'abstract_en', 'tier', 'authors', 'evidence')})
        selected.append(paper)
    return selected, {'excluded_sources': dict(excluded), 'eligible_tracks_unique_papers': len(groups),
                      'deduplicated_selected_papers': len(selected),
                      'tiers': dict(Counter(p['tier'] for p in selected)),
                      'tracks': dict(Counter(p['track'] for p in selected)),
                      'missing_abstracts': [p['id'] for p in selected if not p['abstract_en']],
                      'missing_pdf_links': [p['id'] for p in selected if not p['pdf_url']]}


def complete_abstracts(conf, papers, fetcher):
    missing = [p for p in papers if not p['abstract_en']]
    failures, completed = [], 0
    def fill(p):
        url = p['paper_url'] if conf.get('adapter') == 'cvpr-listings' else p['official_url']
        soup = BeautifulSoup(fetcher.get(url, cached=True), 'html.parser')
        element = soup.select_one('#abstract') if conf.get('adapter') == 'cvpr-listings' else soup.select_one('.abstract-text')
        abstract = element.get_text(' ', strip=True) if element else ''
        if not abstract or len(abstract) < 40:
            raise RuntimeError('Official detail has no complete abstract: ' + url)
        p['abstract_en'] = abstract
        p['abstract_source_url'] = url
        if not p['authors']:
            block = soup.select_one('#authors')
            names = block.select_one('b') if block else None
            if names:
                p['authors'] = [{'fullname': n.strip(), 'institution': None} for n in names.get_text(' ', strip=True).split(',') if n.strip()]
        p['categories'] = classify(p['title'], abstract, p['topic'], p['keywords'])
        p['source_hash'] = digest({k: p[k] for k in ('title','abstract_en','tier','authors','evidence')})
        return p['id']
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get('ATLAS_FETCH_WORKERS', '6'))) as pool:
        futures = {pool.submit(fill, p): p for p in missing}
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
                completed += 1
            except Exception as e:
                failures.append({'id': futures[future]['id'], 'error': str(e)[:300]})
            if (completed+len(failures)) % 100 == 0:
                print(conf['id'], 'detail abstracts', completed, '/', len(missing), 'errors', len(failures), flush=True)
    fetcher.flush()
    return {'abstracts_from_official_details': completed, 'abstract_detail_failures': failures,
            'abstracts_complete': not failures and all(p['abstract_en'] for p in papers)}


def augment_proceedings(conf, papers, fetcher):
    url = conf.get('proceedings_index_url')
    if not url:
        return {}
    soup = BeautifulSoup(fetcher.get(url), 'html.parser')
    forum_links = {}
    if conf.get('proceedings_adapter') == 'pmlr':
        links = {}
        for entry in soup.select('.paper'):
            title = entry.select_one('.title')
            anchors = entry.select('.links a[href]')
            landing = next((urljoin(url, a['href']) for a in anchors if a.get_text(strip=True) == 'abs'), None)
            pdf = next((urljoin(url, a['href']) for a in anchors if a.get_text(strip=True) == 'Download PDF'), None)
            if title and landing and pdf:
                links[title_key(title.get_text(' ', strip=True))] = (landing, pdf)
                for a in anchors:
                    parsed = urlparse(a['href'])
                    if parsed.hostname == 'openreview.net' and parsed.path == '/forum':
                        forum = parse_qs(parsed.query).get('id', [None])[0]
                        if forum:
                            forum_links[forum] = (landing, pdf)
    else:
        links = {}
        for a in soup.select('a[href*="-Abstract-"]'):
            landing = urljoin(url, a['href'])
            pdf = landing.replace('/hash/', '/file/').replace('-Abstract-', '-Paper-').replace('.html', '.pdf')
            links[title_key(a.get_text(' ', strip=True))] = (landing, pdf)
    if not links:
        raise RuntimeError('Official proceedings index markup changed')
    count = 0
    for p in papers:
        forum = parse_qs(urlparse(p.get('paper_url') or '').query).get('id', [None])[0]
        match = forum_links.get(forum) or links.get(title_key(p['title']))
        if match:
            landing, pdf = match
            previous = p['pdf_url']
            p['proceedings_url'] = landing
            p['proceedings_match_method'] = 'official_openreview_id' if forum in forum_links else 'normalized_title'
            p['pdf_url'] = pdf
            p['pdf_urls'] = list(dict.fromkeys([p['pdf_url'], previous]))
            count += 1
    return {'proceedings_matches': count, 'proceedings_unmatched': len(papers) - count}


def apply_abstract_corrections(conf, papers):
    """Apply explicitly reviewed official-source repairs, guarded by the original hash."""
    filename = conf.get('abstract_corrections_file')
    if not filename:
        return {}
    corrections = json.loads((ROOT / filename).read_text(encoding='utf-8'))
    count = 0
    for correction in corrections:
        matches = [p for p in papers if set(p['event_ids']) & set(correction['event_ids'])]
        if len(matches) != 1:
            raise RuntimeError('Reviewed abstract correction no longer matches one official paper')
        p = matches[0]
        if p['abstract_en'] != correction['abstract_en'] and digest(p['abstract_en']) != correction['original_abstract_sha256']:
            raise RuntimeError('Official abstract changed; review the existing source correction: ' + p['title'])
        p['abstract_en'] = correction['abstract_en']
        p['abstract_source_correction'] = {k:v for k,v in correction.items() if k != 'abstract_en'}
        p['source_hash'] = digest({k:p[k] for k in ('title','abstract_en','tier','authors','evidence')})
        count += 1
    return {'reviewed_abstract_source_repairs': count}


@locked('sync')
def sync(conference=None, offline=False):
    reports = []
    for conf in conferences():
        if not conf.get('enabled') or (conference and conf['id'] != conference):
            continue
        run_id = conf['id'] + '-' + now().replace(':', '') + '-' + os.urandom(3).hex()
        report = {'conference': conf['id'], 'checked_at': now(), 'source_scope': 'all accepted papers in configured official proceedings tracks',
                  'status': 'collecting', 'complete': False}
        fetcher = Fetcher(conf['id'], offline)
        try:
            adapter = cvpr_listings if conf.get('adapter') == 'cvpr-listings' else neurips_full if conf.get('adapter') == 'neurips-full' else miniconf
            rows, abstracts, coverage = adapter(conf, fetcher)
            awards = award_records(conf, fetcher)
            papers, quality = normalize(conf, rows, abstracts, awards)
            report.update(complete_abstracts(conf, papers, fetcher))
            quality['missing_abstracts'] = [p['id'] for p in papers if not p['abstract_en']]
            report.update(apply_abstract_corrections(conf, papers))
            report.update(augment_proceedings(conf, papers, fetcher))
            found_awards = {title_key(a['title']) for p in papers for a in p['awards']}
            if set(awards) - found_awards:
                raise RuntimeError('Award papers absent from eligible official index: ' + str(sorted(set(awards) - found_awards)))
            report['award_papers'] = len(found_awards)
            report.update(coverage, **quality, sources=fetcher.used)
            report['metadata_complete'] = coverage.get('pagination_complete', False)
            if not papers:
                raise RuntimeError('No public qualifying papers; preserve previous database and retry later')
            if quality['missing_abstracts']:
                raise RuntimeError('Qualifying papers have missing abstracts; refuse to publish an incomplete refresh')
            with connect() as db:
                existing_ids = defaultdict(set)
                just_merged = set()
                aliases = {r['alias']: r['canonical'] for r in db.execute('SELECT * FROM paper_aliases')}
                for stored in db.execute('SELECT id,payload FROM papers WHERE conference=?', (conf['id'],)):
                    identity = stored['id']
                    for _ in range(10):
                        if identity not in aliases:
                            break
                        identity = aliases[identity]
                    for event_id in json.loads(stored['payload']).get('event_ids', []):
                        existing_ids[event_id].add(identity)
                for p in papers:
                    matched = set().union(*(existing_ids[e] for e in p['event_ids']))
                    if len(matched) == 1:
                        p['id'] = next(iter(matched))
                    elif len(matched) > 1:
                        # Paired event IDs in the official program prove this is one paper.
                        # Keep the canonical poster identity, retain old records and bookmark aliases.
                        canonical = p['id'] if p['id'] in matched else sorted(matched)[0]
                        for old_id in matched - {canonical}:
                            just_merged.add(old_id)
                            db.execute('INSERT OR REPLACE INTO paper_aliases VALUES (?,?)', (old_id, canonical))
                            db.execute('''INSERT OR IGNORE INTO enrichments(paper_id,input_hash,payload,created_at)
                                          SELECT ?,input_hash,payload,created_at FROM enrichments WHERE paper_id=?''', (canonical, old_id))
                            old_override = db.execute('SELECT payload,updated_at FROM overrides WHERE paper_id=?', (old_id,)).fetchone()
                            canonical_override = db.execute('SELECT payload FROM overrides WHERE paper_id=?', (canonical,)).fetchone()
                            if old_override and not canonical_override:
                                db.execute('INSERT INTO overrides VALUES (?,?,?)', (canonical, old_override[0], old_override[1]))
                            elif old_override and canonical_override and old_override[0] != canonical_override[0]:
                                edited = json.loads(canonical_override[0])
                                edited['quality_flags'] = sorted(set(edited.get('quality_flags', [])) | {'merged_manual_versions_review'})
                                edited['review_status'] = 'needs_review'
                                db.execute('UPDATE overrides SET payload=? WHERE paper_id=?', (dumps(edited), canonical))
                            db.execute('INSERT INTO audit(paper_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?)',
                                       (canonical, 'merge_official_paired_events', dumps({'old_id': old_id}), dumps({'canonical': canonical, 'events': p['event_ids']}), now()))
                        p['id'] = canonical
                previous = {r['id']: r['source_hash'] for r in db.execute('SELECT id,source_hash FROM papers WHERE conference=? AND active=1', (conf['id'],))}
                ids = {p['id'] for p in papers}
                # A large deletion requires explicit CLI review of the snapshot, never silent loss.
                if previous and len(ids) < (len(previous) - len(just_merged)) * 0.8:
                    raise RuntimeError('Snapshot shrank by over 20%; check source before accepting')
                db.execute('UPDATE papers SET active=0 WHERE conference=?', (conf['id'],))
                for p in papers:
                    db.execute('''INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(id) DO UPDATE SET title=excluded.title,tier=excluded.tier,track=excluded.track,
                      abstract_en=excluded.abstract_en,source_hash=excluded.source_hash,payload=excluded.payload,
                      active=1,last_seen=excluded.last_seen''',
                      (p['id'], p['conference'], p['title'], p['tier'], p['track'], p['abstract_en'], p['source_hash'], dumps(p), 1, report['checked_at'], report['checked_at']))
                report.update(added=len(ids - previous.keys()), removed=len(previous.keys() - ids - just_merged),
                              merged=len(just_merged),
                              changed=sum(p['id'] in previous and p['source_hash'] != previous[p['id']] for p in papers),
                              status='success', complete=True)
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (run_id, conf['id'], report['checked_at'], 'success', dumps(report)))
        except Exception as e:
            report.update(status='failed', error=str(e)[:500], sources=fetcher.used)
            with connect() as db:
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (run_id, conf['id'], report['checked_at'], 'failed', dumps(report)))
        fetcher.flush()
        write_json(DATA / 'reports' / (run_id + '.json'), report)
        reports.append(report)
        print(conf['id'], report['status'], report.get('tiers', {}), report.get('error', ''), flush=True)
    return reports
