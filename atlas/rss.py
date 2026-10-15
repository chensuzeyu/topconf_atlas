"""RSS official accepted list reconciled with the complete proceedings volume."""
import concurrent.futures
import os
import re
import unicodedata
from collections import Counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def key(text):
    return re.sub(r'\W+', '', unicodedata.normalize('NFKC', text).casefold())


def rss_proceedings(conf, fetcher):
    accepted_url, index_url = conf['accepted_index_url'], conf['proceedings_index_url']
    soup = BeautifulSoup(fetcher.get(accepted_url), 'html.parser')
    accepted, program_ids = {}, set()
    for tr in soup.select('#myTable tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 4:
            continue
        anchor = cells[2].select_one('a[href]')
        if not anchor:
            raise RuntimeError('RSS accepted paper lacks a detail link')
        title = anchor.get_text(' ', strip=True)
        program_id = int(cells[0].get_text(strip=True))
        if key(title) in accepted or program_id in program_ids:
            raise RuntimeError('RSS duplicate accepted identity')
        program_ids.add(program_id)
        # The hidden author div repeats names and sometimes contains a longer list.
        author_cell = BeautifulSoup(str(cells[3]), 'html.parser')
        hidden = author_cell.select_one('.content')
        authors = (hidden or author_cell).get_text(' ', strip=True)
        accepted[key(title)] = {'program_id': program_id, 'title': title,
            'session': cells[1].get_text(' ', strip=True), 'authors_text': authors,
            'url': urljoin(accepted_url, anchor['href'])}
    soup = BeautifulSoup(fetcher.get(index_url), 'html.parser')
    links = {}
    for anchor in soup.select('a[href]'):
        url = urljoin(index_url, anchor['href'])
        if (urlparse(url).netloc == urlparse(index_url).netloc and
                re.fullmatch(re.escape(urlparse(index_url).path) + r'p\d+\.html', urlparse(url).path)):
            title = anchor.get_text(' ', strip=True)
            if url in links and links[url] != title:
                raise RuntimeError('RSS conflicting proceedings identity')
            links[url] = title
    if not accepted or not links or len(accepted) != len(links):
        raise RuntimeError(f'RSS incomplete membership indexes: {len(accepted)} accepted / {len(links)} proceedings')
    if Counter(key(t) for t in links.values()) != Counter(accepted.keys()):
        raise RuntimeError('RSS accepted/proceedings title conflict; review official identities')

    def detail(item):
        url, index_title = item
        soup = BeautifulSoup(fetcher.get(url, cached=True), 'html.parser')
        def meta(name):
            element = soup.select_one(f'meta[name="{name}"]')
            return element.get('content', '').strip() if element else ''
        title = meta('citation_title')
        if not title or key(title) != key(index_title):
            raise RuntimeError('RSS detail/index title conflict: ' + url)
        program = accepted[key(title)]
        authors = [e['content'].strip() for e in soup.select('meta[name="citation_author"]') if e.get('content', '').strip()]
        label = soup.find('b', string=lambda t: t and t.strip() == 'Abstract:')
        block = label.find_parent('p').find_next_sibling('p') if label and label.find_parent('p') else None
        abstract = block.get_text(' ', strip=True) if block else ''
        bib = soup.select_one('pre')
        doi = re.search(r'DOI\s*=\s*\{([^}]+)', bib.get_text() if bib else '')
        expected_doi = f'10.15607/RSS.{conf["year"]}.{conf["volume_roman"]}.'
        pdf = soup.select_one('.content a[href$=".pdf"]')
        pdf_url = urljoin(url, pdf['href']) if pdf else ''
        if (len(abstract) < 40 or not authors or not doi or not doi[1].startswith(expected_doi)
                or not pdf_url or urlparse(pdf_url).netloc != urlparse(index_url).netloc
                or not meta('citation_publication_date').startswith(str(conf['year']))):
            raise RuntimeError('RSS incomplete or invalid official detail: ' + url)
        row = {'id': urlparse(url).path, 'name': title, 'decision': 'Accepted: official accepted list and proceedings',
            'sourceurl': index_url, 'listing_url': accepted_url, 'virtualsite_url': program['url'],
            'evidence_kind': 'proceedings', 'paper_url': url, 'paper_pdf_url': pdf_url,
            'authors': [{'fullname': name, 'institution': None} for name in authors],
            'track': 'main', 'session': program['session'], 'program_id': program['program_id'],
            'doi': doi[1], 'abstract_source_url': url, 'authors_source_url': url,
            'program_authors_text': program['authors_text'],
            'proceedings_match_method': 'unique_exact_normalized_official_title'}
        return row, abstract

    rows, abstracts = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, max(1, int(os.environ.get('ATLAS_FETCH_WORKERS', '4'))))) as pool:
        for row, abstract in pool.map(detail, links.items()):
            rows.append(row)
            abstracts[str(row['id'])] = abstract
    dois = [r['doi'] for r in rows]
    if len(set(dois)) != len(dois):
        raise RuntimeError('RSS conflicting duplicate DOI')
    return rows, abstracts, {'event_rows': len(rows), 'unique_event_rows': len(rows),
        'advertised_rows': len(accepted), 'accepted_index_count': len(accepted),
        'proceedings_index_count': len(links), 'proceedings_matches': len(rows),
        'pagination_complete': True, 'membership_reconciled': True,
        'session_counts': dict(Counter(r['session'] for r in rows)),
        'author_source_differences': [{'program_id': r['program_id'], 'program_authors': r['program_authors_text'],
            'proceedings_authors': [a['fullname'] for a in r['authors']]} for r in rows
            if key(r['program_authors_text']) != key(', '.join(a['fullname'] for a in r['authors']))]}
