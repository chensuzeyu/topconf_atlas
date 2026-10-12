"""Indexed queries over effective paper metadata, preserving substring search and topic semantics."""
import json
from collections import Counter
from .storage import connect, refresh_query_index
from .taxonomy import taxonomy

TIERS = {'oral','spotlight','highlight','award','poster','unlabeled'}


def list_indexed(conference=None, category=None, tiers=(), track=None, q='', page=1,
                 page_size=50, sort='title', review=None, tags=(), exclusive=False):
    clauses, args = ['p.active=1'], []
    if conference:
        clauses.append('p.conference=?'); args.append(conference)
    if category:
        clauses.append('EXISTS(SELECT 1 FROM paper_topics t WHERE t.paper_id=p.id AND t.slug=?)'); args.append(category)
    if track:
        clauses.append('p.track=?'); args.append(track)
    if review == 'flagged': clauses.append('p.flagged=1')
    if review == 'pending': clauses.append('p.reviewed=0')
    if tiers:
        choices = []
        for tier in sorted(set(tiers)):
            if tier == 'award': choices.append('p.has_award=1')
            elif tier in ('poster','unlabeled'):
                choices.append('p.tier=?'); args.append(tier)
            else:
                choices.append('EXISTS(SELECT 1 FROM paper_distinctions d WHERE d.paper_id=p.id AND d.distinction=?)'); args.append(tier)
        clauses.append('('+' OR '.join(choices)+')')
    for term in q.casefold().split():
        clauses.append('instr(p.search_text,?)>0'); args.append(term)
    scope = ' AND '.join(clauses)
    facets = None
    with connect() as db:
        refresh_query_index(db)
        if category:
            base = db.execute('SELECT count(*) FROM paper_query p WHERE '+scope,args).fetchone()[0]
            exclusive_count = db.execute('SELECT count(*) FROM paper_query p WHERE '+scope+
                ' AND NOT EXISTS(SELECT 1 FROM paper_topics t WHERE t.paper_id=p.id AND t.slug!=?)',args+[category]).fetchone()[0]
            counts = dict(db.execute('WITH scope AS(SELECT p.id FROM paper_query p WHERE '+scope+') '
                'SELECT t.slug,count(*) FROM paper_topics t JOIN scope s ON s.id=t.paper_id GROUP BY t.slug',args).fetchall())
            facets = {'total':base,'exclusive_count':exclusive_count,
                'tags':[{**{k:t[k] for k in ('slug','name','icon','group')},'count':counts.get(t['slug'],0)}
                        for t in taxonomy() if t['slug']!=category and (counts.get(t['slug'],0) or t['slug'] in tags)]}
        if exclusive:
            clauses.append('NOT EXISTS(SELECT 1 FROM paper_topics t WHERE t.paper_id=p.id AND t.slug!=?)'); args.append(category)
        for tag in sorted(set(tags)):
            clauses.append('EXISTS(SELECT 1 FROM paper_topics t WHERE t.paper_id=p.id AND t.slug=?)'); args.append(tag)
        where = ' AND '.join(clauses)
        total = db.execute('SELECT count(*) FROM paper_query p WHERE '+where,args).fetchone()[0]
        order = ('CASE WHEN p.has_award=1 THEN 0 WHEN p.tier="oral" THEN 1 '
                 'WHEN p.tier IN ("spotlight","highlight") THEN 2 WHEN p.tier="poster" THEN 3 ELSE 4 END,' if sort=='tier' else '')
        rows = db.execute('SELECT p.payload FROM paper_query p WHERE '+where+' ORDER BY '+order+
                          'p.title_sort,p.id LIMIT ? OFFSET ?',args+[page_size,(page-1)*page_size]).fetchall()
    return {'items':[json.loads(r[0]) for r in rows],'total':total,'page':page,'page_size':page_size,
            'pages':(total+page_size-1)//page_size,'topic_facets':facets}


def indexed_status(conferences, latest_reports):
    with connect() as db:
        refresh_query_index(db)
        reports = latest_reports(db)
        summaries = {r['conference']:dict(r) for r in db.execute(
            'SELECT conference,count(*) AS count,sum(translated) AS translated,sum(flagged) AS quality_flags,'
            'sum(reviewed) AS reviewed,sum(has_award) AS awards,max(last_seen) AS snapshot_date '
            'FROM paper_query WHERE active=1 GROUP BY conference')}
        tiers,tracks,distinctions = {},{},{}
        for field,target in [('tier',tiers),('track',tracks)]:
            for r in db.execute(f'SELECT conference,{field},count(*) FROM paper_query WHERE active=1 GROUP BY conference,{field}'):
                target.setdefault(r[0],{})[r[1]]=r[2]
        for r in db.execute('SELECT p.conference,d.distinction,count(*) FROM paper_distinctions d '
                            'JOIN paper_query p ON p.id=d.paper_id WHERE p.active=1 GROUP BY p.conference,d.distinction'):
            distinctions.setdefault(r[0],{})[r[1]]=r[2]
        by_conf=[]
        for conf in conferences():
            summary=summaries.get(conf['id'],{})
            by_conf.append({**conf,**{k:summary.get(k,0) for k in ('count','translated','quality_flags','reviewed','awards')},
                'tiers':tiers.get(conf['id'],{}),'tracks':tracks.get(conf['id'],{}),
                'distinction_counts':distinctions.get(conf['id'],{}),'report':reports[conf['id']]})
        jobs=[dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY started_at DESC LIMIT 20')]
    return {'total':sum(c['count'] for c in by_conf),'translated':sum(c['translated'] for c in by_conf),
            'conferences':by_conf,'jobs':jobs,
            'snapshot_date':max((r['snapshot_date'] for r in summaries.values()),default=None)}


def indexed_categories():
    with connect() as db:
        refresh_query_index(db)
        counts={}
        for row in db.execute('SELECT t.slug,p.conference,count(*) FROM paper_topics t JOIN paper_query p '
                              'ON p.id=t.paper_id WHERE p.active=1 GROUP BY t.slug,p.conference'):
            counts.setdefault(row[0],{})[row[1]]=row[2]
    return [{**{k:v for k,v in t.items() if k!='patterns'},'count':sum(counts.get(t['slug'],{}).values()),
             'by_conference':counts.get(t['slug'],{})} for t in taxonomy()]
