import {renderRichText, renderPaperText} from './math.mjs';
const $ = (q, root = document) => root.querySelector(q);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tierNames = {oral:'Oral',spotlight:'Spotlight',highlight:'Highlight',award:'获奖',poster:'普通论文',unlabeled:'精选标签未启用'};
const trackNames = {main:'主研究轨道',position:'Position Track',evaluations_datasets:'Evaluations & Datasets',unverified:'轨道待核验'};
const main = $('#content'), sidebar = $('#sidebar');
let meta, currentPaper, revision = 0, searchTimer, pollTimer, metaUpdatedAt = 0;
const label = slug => meta?.categories.find(c => c.slug === slug);
const confLabel = id => meta?.conferences.find(c => c.id === id);
const api = async (url, options) => { const r = await fetch(url, options); if (!r.ok) {const e = await r.json().catch(() => ({}));throw Error(e.detail || `请求失败 (${r.status})`);} return r.json(); };
const badge = p => `${(p.distinctions || p.tiers || (['oral','spotlight','highlight'].includes(p.tier) ? [p.tier] : [])).map(t => `<span class="badge ${escape(t)}">${tierNames[t]}</span>`).join('')}${p.tier === 'poster' ? '<span class="badge poster">普通论文</span>' : ''}${(p.awards || []).map(a => `<span class="badge award">${escape(a.label)}</span>`).join('')}${p.track !== 'main' ? `<span class="badge">${escape(trackNames[p.track] || p.track)}</span>` : ''}`;

const paperPath = p => `/paper/${p.id}/`;
const date = value => value ? value.slice(0,10) : '尚未采集';
const external = (url, text) => /^https?:\/\//.test(url || '') ? `<a class="button" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(text)} ↗</a>` : '';
const tokenHeaders = () => {const token = sessionStorage.getItem('atlas-admin-token');return {'Content-Type':'application/json',...(token ? {'Authorization':`Bearer ${token}`} : {})};};

function route() {
  const parts = location.pathname.split('/').filter(Boolean);
  const params = new URLSearchParams(location.search);
  return {parts, params, conference: meta?.conferences.some(c => c.id === parts[0]) ? parts[0] : null,
          category: parts.length > 1 && parts[0] !== 'paper' ? parts[1] : null};
}
function toast(text) {$('#toast').textContent = text; $('#toast').hidden = false; setTimeout(() => $('#toast').hidden = true, 5000);}
function closeMenu() {sidebar.classList.remove('open'); $('#overlay').hidden = true; $('#menu-toggle').setAttribute('aria-expanded','false');}
function nav(url, scroll = true) {history.pushState({}, '', url); closeMenu(); render(); if (scroll) window.scrollTo(0,0);}
function refreshNav(conf) {
  $('#conference-nav').innerHTML = `<a data-nav href="/" class="${location.pathname === '/' ? 'active' : ''}">⌂ 首页</a>` +
    meta.conferences.map(c => `<a data-nav href="/${c.id}/" class="${conf === c.id ? 'active' : ''}">${c.icon} ${c.id}</a>`).join('') +
    '<span class="nav-scope">全部录用论文</span>';
}
function side(conf, category, papers = []) {
  const c = confLabel(conf), groups = [...new Set(meta.categories.map(t => t.group))];
  const activeCategory = category || currentPaper?.categories?.[0];
  sidebar.innerHTML = `<a data-nav href="${conf ? '/'+conf+'/' : '/'}" class="side-title">${c ? c.icon+' '+c.id : '▤ 顶会论文库'} <span style="float:right;color:var(--muted)">‹</span></a>` +
    (conf ? `<a class="category-link ${!category && !currentPaper ? 'active' : ''}" data-nav href="/${conf}/">全部论文 <span class="count">${c.count}</span></a>` : '') +
    groups.map(group => {
      const topics = meta.categories.filter(t => t.group === group && (conf ? t.by_conference[conf] : t.count));
      if (!topics.length) return '';
      const count = topics.reduce((sum,t) => sum + (conf ? t.by_conference[conf] || 0 : t.count),0);
      return `<details ${topics.some(t => t.slug === activeCategory) || !category ? 'open' : ''}><summary>${escape(group)} <span>${count}</span></summary>` +
        topics.map(t => `<a data-nav class="category-link ${t.slug === activeCategory ? 'active' : ''}" href="/${conf || 'topics'}/${t.slug}/">${t.icon} ${escape(t.name)} <span class="count">${conf ? t.by_conference[conf] || 0 : t.count}</span></a>` +
          (t.slug === activeCategory && papers.length ? `<div class="paper-nav">${papers.slice(0,15).map(p => `<a data-nav data-paper-id="${p.id}" href="${paperPath(p)}" class="${currentPaper?.id === p.id ? 'active' : ''}">${escape(p.title)}</a>`).join('')}</div>` : '')).join('') + '</details>';
    }).join('') +
    `<div class="side-conferences">${meta.conferences.filter(c => c.id !== conf).map(c => `<a data-nav href="/${c.id}/">${c.icon} ${c.id} <span class="count">(${c.count})</span></a>`).join('')}</div>` +
    '<p class="side-note">一篇论文可属于多个主题，主题计数会重叠。<br>会议按录用通知时间排列。</p>';
}
function title(text) {document.title = `${text} · TopConf Atlas`;}
function home() {
  title('顶会论文库'); side(null,null); refreshNav(null);
  main.innerHTML = `<h1>▤ 顶会论文库</h1><p class="home-lead">按会议与研究主题阅读 2026 年的全部录用论文。列表用一句话介绍工作，点进论文即可阅读完整中文摘要。</p>` +
    `<div class="conference-grid">${meta.conferences.map(c => `<a data-nav href="/${c.id}/" class="conference-card"><strong>${c.icon} ${c.id}</strong><span class="big-number">${c.count}<span style="font-size:12px;color:var(--muted)"> 篇</span></span><small>${Object.entries(c.tiers).map(([t,n]) => `${n} ${tierNames[t]}`).join(' · ')}</small><small>中文摘要 ${c.translated} / ${c.count}</small></a>`).join('')}</div>` +
    `<div class="notice">覆盖 ${meta.conferences.length} 个会议的官方录用论文，包含普通论文；Oral、Spotlight、Highlight 与获奖信息可选筛选。当前 ${meta.total.toLocaleString()} 篇，中文摘要 ${meta.translated.toLocaleString()} 篇；数据核验于 ${date(meta.snapshot_date)}。</div>` +
    `<h2>按研究主题浏览</h2><div class="topic-grid">${[...new Set(meta.categories.map(c => c.group))].map(group => `<section class="topic-group"><h3>${escape(group)}</h3>${meta.categories.filter(c => c.group === group && c.count).map(c => `<a data-nav class="topic-chip" href="/topics/${c.slug}/">${c.icon} ${escape(c.name)} <span style="color:var(--muted)">${c.count}</span></a>`).join('')}</section>`).join('')}</div>` +
    `<p class="detail-caption">ICLR 的精选标签目前仅核验到 Oral；普通论文已纳入完整名单。ICML 的 Position Track 单列，会议论文列表可筛选仅主研究轨道。</p>`;
}

function topicFilters(t, facets, params) {
  if (!facets) return '';
  const tags = new Set(params.getAll('tag')), exclusive = ['true','1'].includes(params.get('exclusive'));
  const chip = (id, name, value, text, count, checked) => `<label class="tag-filter ${checked ? 'selected' : ''}"><input id="${id}" type="checkbox" name="${name}" value="${escape(value)}" ${checked ? 'checked' : ''}><span>${escape(text)}</span><span class="tag-count">${count}</span></label>`;
  return `<fieldset class="topic-filters"><legend>${t ? '交叉标签筛选' : '研究主题标签（多选）'}</legend><p class="tag-help">${t ? '当前主题始终包含在筛选中。多选其它标签时，论文须同时包含所有选中标签；“仅当前主题”与其它标签互斥。' : '按研究主题分类与筛选，多选时论文须同时包含所有选中标签；不选时显示全部论文。'}</p><div class="tag-filter-options">` +
    (t ? chip('topic-exclusive','exclusive','true',`${t.icon} 仅${t.name}`,facets.exclusive_count,exclusive) : '') +
    facets.tags.map(f => chip(`tag-${f.slug}`,'tag',f.slug,`${f.icon} ${f.name}`,f.count,tags.has(f.slug))).join('') +
    `</div><div class="tag-filter-footer"><span>数字为${t ? '当前主题内与各标签交叉' : '当前范围内各标签'}的篇数（随会议、搜索和级别等筛选更新，多标签计数可重叠）。未选标签时显示全部 ${facets.total} 篇。</span><button type="button" class="button" id="clear-tags">清除标签选择</button></div></fieldset>`;
}

async function listing(r, version) {
  const c = confLabel(r.conference), t = label(r.category), isSearch = r.parts[0] === 'search';
  if (r.category && !t) throw Error('没有找到这个论文类别');
  const heading = t ? `${t.icon} ${t.name}` : isSearch ? '⌕ 搜索论文' : `${c.icon} ${c.id}`;
  title(t ? `${t.name}${c ? ' · '+c.id : ''}` : isSearch ? '搜索' : c.id);
  const query = new URLSearchParams(r.params);
  if (r.conference) query.set('conference',r.conference);
  if (r.category) query.set('category',r.category);
  query.set('page_size','40');
  const result = await api('/api/papers?'+query);
  if (version !== revision) return;
  refreshNav(c?.id);side(c?.id,r.category,result.items);
  const cross = t ? meta.conferences.filter(x => x.id !== r.conference && t.by_conference[x.id]).map(x => `<a data-nav href="/${x.id}/${t.slug}/">${x.icon} ${x.id} (${t.by_conference[x.id]})</a>`).join(' · ') : '';
  const refocus = document.activeElement?.id === 'local-q', caret = refocus ? document.activeElement.selectionStart : 0;
  const focusId = document.activeElement?.closest('#filters') ? document.activeElement.id : null;
  main.innerHTML = `<div class="breadcrumbs"><a data-nav href="/">首页</a> / ${c ? `<a data-nav href="/${c.id}/">${c.id}</a>` : '跨会议'}${t ? ' / '+escape(t.name) : ''}</div><h1>${escape(heading)}</h1>` +
    `<p class="intro"><strong>${c ? c.icon+' '+c.id : '全部会议'}</strong> · ${result.total} 篇论文</p>` +
    (cross ? `<p class="cross-links">同领域跨会议浏览：${cross}</p>` : '') +
    (c?.id === 'NeurIPS2026' ? '<div class="notice">覆盖官方论文名单，本轮暂不展示精选标签；轨道资料尚未完整公开的条目标为“轨道待核验”。</div>' : '') +
    (c?.id === 'RSS2026' ? '<div class="notice">研究主题可在下方多选筛选，也可从左侧进入主题分类。会议报告安排不作为精选 Oral 标签；获奖论文可独立筛选。</div>' : '') +
    (c?.id === 'ICLR2026' ? '<div class="notice">已收录全部主研究轨道论文。当前官方索引提供 Oral / Poster，独立 Spotlight 名单仍待核验。</div>' : '') +
    `<form class="toolbar" id="filters"><label class="sr-only" for="local-q">在当前列表搜索</label><input id="local-q" name="q" placeholder="在当前列表搜索…" value="${escape(r.params.get('q') || '')}">` +
    `<label class="sr-only" for="tier-filter">论文筛选</label><select id="tier-filter" name="tier"><option value="">全部论文</option>${(c?.distinctions_enabled === false ? ['unlabeled','award'] : ['oral','spotlight','highlight','poster','award']).map(v => `<option value="${v}" ${r.params.getAll('tier').includes(v) ? 'selected' : ''}>${tierNames[v]}</option>`).join('')}</select>` +
    `<label class="sr-only" for="track-filter">论文轨道</label><select id="track-filter" name="track"><option value="">全部轨道</option>${Object.entries(c?.tracks || trackNames).map(([v,name]) => `<option value="${v}" ${r.params.get('track') === v ? 'selected' : ''}>${escape(name)}</option>`).join('')}</select>` +
    `<label class="sr-only" for="sort-filter">排序</label><select id="sort-filter" name="sort"><option value="title">标题顺序</option><option value="tier" ${r.params.get('sort') === 'tier' ? 'selected' : ''}>精选优先</option></select><span class="result-count" role="status">${result.total ? (result.page-1)*40+1 : 0}–${Math.min(result.page*40,result.total)} / ${result.total}</span>${c?.distinctions_enabled === false ? '' : `<fieldset class="distinction-filters"><legend>精选标签（多选取并集）</legend>${['oral','spotlight','highlight'].map(v=>`<label><input type="checkbox" name="distinction" value="${v}" ${r.params.getAll('tier').includes(v)?'checked':''}>${tierNames[v]}</label>`).join('')}</fieldset>`}${topicFilters(t,result.topic_facets,r.params)}</form>` +
    `<div class="paper-list">${result.items.length ? result.items.map(p => `<article class="paper-row" data-paper-id="${p.id}"><a class="paper-title" data-nav href="${paperPath(p)}">${escape(p.title)}</a><div class="row-meta">${badge(p)}${!c ? `<span>${p.conference}</span>` : ''}<span>${p.categories.map(s => `<a data-nav href="/${p.conference}/${s}/">${escape(label(s)?.name || s)}</a>`).join(' · ')}</span>${p.quality_flags?.length ? '<span title="翻译中的数字需要复核">待校对</span>' : ''}</div><p class="paper-summary">${escape(p.summary_zh || '中文介绍处理中，可点击标题阅读原始英文摘要。')}</p></article>`).join('') : '<div class="empty"><h2>没有匹配的论文</h2><p>试试其他关键词，或清除级别与轨道筛选。</p><button class="button" data-action="clear-filters">清除筛选</button></div>'}</div>` +
    (result.pages > 1 ? `<div class="pagination"><button class="button" data-page="${result.page-1}" ${result.page <= 1 ? 'disabled' : ''}>← 上一页</button><span>第 ${result.page} / ${result.pages} 页</span><button class="button" data-page="${result.page+1}" ${result.page >= result.pages ? 'disabled' : ''}>下一页 →</button></div>` : '');
  const filter = $('#filters');
  filter.addEventListener('submit', e => {e.preventDefault();applyFilters();});
  filter.addEventListener('change', e => {
    if(e.target.id === 'tier-filter') filter.querySelectorAll('input[name="distinction"]').forEach(input => input.checked = false);
    if(e.target.name === 'distinction' && !filter.querySelector('input[name="distinction"]:checked')) $('#tier-filter').value = '';
    if(e.target.checked && e.target.name === 'exclusive') filter.querySelectorAll('input[name="tag"]').forEach(input => input.checked = false);
    if(e.target.checked && e.target.name === 'tag' && $('#topic-exclusive')) $('#topic-exclusive').checked = false;
    applyFilters();
  });
  $('#clear-tags')?.addEventListener('click', () => {
    filter.querySelectorAll('input[name="tag"],input[name="exclusive"]').forEach(input => input.checked = false);
    applyFilters();
  });
  $('#local-q').addEventListener('input', () => {clearTimeout(searchTimer);searchTimer=setTimeout(applyFilters,500);});
  if(refocus){$('#local-q').focus();$('#local-q').setSelectionRange(caret,caret);}
  else if(focusId) document.getElementById(focusId)?.focus();
}
function applyFilters() {
  clearTimeout(searchTimer);
  const form = $('#filters');if (!form) return;
  const data = new FormData(form);
  const selected = data.getAll('distinction');
  data.delete('distinction');
  if (selected.length) {data.delete('tier');selected.forEach(t=>data.append('tier',t));}
  const query = new URLSearchParams(data);
  for (const [k,v] of [...query]) if (!v) query.delete(k);
  history.replaceState({}, '', location.pathname + (query.size ? '?'+query : ''));
  render();
}

async function detail(id, version) {
  const p = await api('/api/papers/'+encodeURIComponent(id));if (version !== revision) return;
  currentPaper = p;title(p.title);
  const c = confLabel(p.conference), t = label(p.categories[0]);
  side(c.id,t?.slug,[p]);refreshNav(c.id);
  main.innerHTML = `<div class="breadcrumbs"><a data-nav href="/">首页</a> / <a data-nav href="/${c.id}/">${c.id}</a> / ${t ? `<a data-nav href="/${c.id}/${t.slug}/">${escape(t.name)}</a> / ` : ''}论文摘要</div>` +
    `<h1 class="detail-title">${escape(p.title)}</h1><p class="title-zh">${escape(p.title_zh)}</p><div class="row-meta">${badge(p)}<span>${p.review_status === 'reviewed' ? '人工已校对' : '机器翻译，未人工校对'}</span></div>` +
    `${p.session ? `<p class="detail-caption">官方 Session：${escape(p.session)}${p.doi ? ' · DOI：'+escape(p.doi) : ''}</p>` : ''}<p class="detail-authors">${p.authors.map(a => escape(a.fullname)).join(' · ')}</p><div>${p.categories.map(slug => {const t=label(slug);return `<a class="topic-chip" data-nav href="/${c.id}/${slug}/">${t?.icon || ''} ${escape(t?.name || slug)}</a>`;}).join('')}</div>` +
    `<div class="detail-actions">${external(p.paper_url,'论文原文')}${external(p.pdf_url,'PDF')}${p.pdf_cached ? `<a class="button" href="/api/pdf/${p.id}" target="_blank" rel="noopener">本地 PDF</a>` : p.pdf_url ? '<button class="button" data-action="cache-pdf">保存 PDF 到本地</button>' : ''}${external(p.official_url,'官方页面')}${external(p.code_url,'代码')}<button class="button" data-action="copy-abstract">复制中文摘要</button><button class="button" data-action="edit">校对摘要与分类</button></div>` +
    (p.quality_flags?.length ? `<div class="notice">${p.quality_flags.includes('source_changed_after_review') ? '原始摘要在人工校对后发生变化，已保留人工译文并标记需要重新校对。' : '中文译文中部分数值格式与原文不一致，已标记待校对；可切换英文摘要核对。'}</div>` : '') +
    `<section><div class="abstract-header"><h2>摘要</h2><div class="abstract-tabs" role="tablist" aria-label="摘要语言"><button class="active" role="tab" aria-selected="true" data-lang="zh">中文译文</button><button role="tab" aria-selected="false" data-lang="en">英文原文</button></div></div><div class="abstract-text" id="abstract-body">${escape(p.abstract_zh || '中文翻译处理中。请切换英文原文阅读完整摘要。')}</div><p class="detail-caption">${p.translation_meta ? `摘要完整翻译 · ${escape(p.translation_meta.model)} · ${date(p.translation_meta.generated_at)}` : '保留完整英文原始摘要'}${p.reviewed_at ? ' · 人工校对于 '+date(p.reviewed_at) : ''}</p></section><div id="editor-slot"></div>` +
    (p.abstract_source_correction ? `<p class="detail-caption">会议网页的摘要有提取问题，已根据${external(p.abstract_source_correction.source_url,'官方论文正文')}第 ${p.abstract_source_correction.page} 页核对修正。</p>` : '') +
    `<details class="source-details"><summary>来源与收录依据</summary><p>最后核验：${date(p.last_seen)} · 首次收录：${date(p.first_seen)}。官方录用依据、展示形式、精选标签和获奖信息分别保存。</p><div class="table-scroll"><table><thead><tr><th>官方记录</th><th>录用决定</th><th>展示形式</th><th>录用依据</th></tr></thead><tbody>${p.evidence.map(e => `<tr><td>${e.event_id}</td><td>${escape(e.decision || '未单独给出')}</td><td>${escape(e.eventtype || '未单独给出')}</td><td><a href="${escape(e.source_url)}" target="_blank" rel="noopener">官方记录 ↗</a></td></tr>`).join('')}</tbody></table></div><p>原始记录哈希：<span class="code-value">${p.source_hash}</span></p><p>分类方式：${escape(p.classification_method)}；中文介绍仅基于摘要，不代表全文评述。</p></details>`;
}
function editor() {
  const p=currentPaper;
  $('#editor-slot').innerHTML = `<form id="edit-form" class="editor"><h2>校对中文摘要与分类</h2><label for="edit-title">中文标题</label><input id="edit-title" name="title_zh" value="${escape(p.title_zh)}"><label for="edit-summary">列表的一句话介绍</label><textarea id="edit-summary" name="summary_zh" rows="3" required>${escape(p.summary_zh)}</textarea><label for="edit-abstract">完整中文摘要</label><textarea id="edit-abstract" name="abstract_zh" rows="12" required>${escape(p.abstract_zh)}</textarea><label>研究主题（至少选择一个）</label><div class="category-options">${meta.categories.map(t => `<label><input type="checkbox" name="categories" value="${t.slug}" ${p.categories.includes(t.slug) ? 'checked' : ''}>${escape(t.name)}</label>`).join('')}</div><p class="detail-caption">保存后标记为人工已校对。人工修订独立保留，会议名单更新不会覆盖它。</p><button class="button primary" type="submit">保存校对</button> <button class="button" type="button" data-action="cancel-edit">取消</button></form>`;
  $('#edit-form').addEventListener('submit', async e => {
    e.preventDefault();const form=e.currentTarget, data=new FormData(form);
    const body={title_zh:data.get('title_zh'),summary_zh:data.get('summary_zh'),abstract_zh:data.get('abstract_zh'),categories:data.getAll('categories'),review_status:'reviewed',quality_flags:[]};
    if (!body.categories.length) return toast('请选择至少一个主题');
    $('button[type=submit]',form).disabled=true;
    try {await api('/api/admin/papers/'+p.id,{method:'PATCH',headers:tokenHeaders(),body:JSON.stringify(body)});meta=await api('/api/meta');toast('校对已保存');render();} catch(err){toast(err.message);$('button[type=submit]',form).disabled=false;}
  });
  $('#editor-slot').scrollIntoView({behavior:'smooth',block:'start'});
}
async function manage(version) {
  const s=await api('/api/status');if(version!==revision)return;
  title('管理与更新');side(null,null);refreshNav(null);
  main.innerHTML=`<h1>管理与更新</h1><p class="home-lead">更新官方名单，继续处理新论文的中文摘要，检查来源覆盖率与待校对内容。</p><div class="admin-controls"><label class="sr-only" for="job-conf">更新范围</label><select id="job-conf"><option value="">全部会议</option>${s.conferences.map(c=>`<option value="${c.id}">${c.id}</option>`).join('')}</select><button class="button" data-job="sync">更新官方名单</button><button class="button" data-job="enrich">继续中文处理</button><button class="button" data-job="export">重新导出</button><a class="button" href="/api/export" download>下载完整元数据</a><button class="button" data-action="admin-token">设置管理令牌</button></div><div class="admin-stats">${s.total} 篇论文 · ${s.translated} 篇已完成中文处理 · 最近核验 ${date(s.snapshot_date)}</div><div class="table-scroll"><table><thead><tr><th>会议</th><th>论文与标签</th><th>中文摘要</th><th>名单覆盖</th><th>校对状态</th></tr></thead><tbody>${s.conferences.map(c=>`<tr><td><a data-nav href="/${c.id}/">${c.icon} ${c.id}</a></td><td>${Object.entries(c.tiers).map(([t,n])=>`${n} ${tierNames[t]}`).join('<br>')}</td><td>${c.translated} / ${c.count}<br><small>摘要 ${c.report.abstracts_complete ? c.count : '待补齐'} / ${c.count}</small></td><td><span class="status-dot ${c.report.status==='failed'?'failed':''}"></span>${c.report.complete?'完整名单已核验':'需要核验'}<br><small>${date(c.report.checked_at)}</small></td><td>${c.reviewed} 已校对<br>${c.quality_flags} 数值待复核</td></tr>`).join('')}</tbody></table></div>` +
    `<h2>来源核验</h2>${s.conferences.map(c=>`<details class="source-details"><summary>${c.id} · ${c.report.deduplicated_selected_papers || 0} 篇去重论文</summary><p>${c.report.event_rows || 0} 条官方日程记录；${c.report.source_snapshot_count || 0} 份来源快照；${escape(JSON.stringify(c.tracks))}。</p><a href="/api/reports/${c.id}" target="_blank" rel="noopener">完整来源核验报告 ↗</a>${c.report.error?`<div class="notice">更新失败：${escape(c.report.error)}。保留此前成功数据。</div>`:''}<p>${c.id==='ICLR2026'?'官方索引尚未标记独立 Spotlight，仅确认 Oral。':''}</p>${c.report.track_verification_pending?.length ? `<p>另有 ${c.report.track_verification_pending.length} 条记录的轨道元数据待核验，已保留官方名单与论文链接。</p>` : ''}${c.report.sources?.filter(src=>!src.url.includes('/poster/')&&!src.url.includes('/content/')).map(src=>`<p><a href="${escape(src.url)}" target="_blank" rel="noopener">${escape(src.url)}</a><br><span class="code-value">SHA-256 ${src.sha256}</span><br>采集时间 ${escape(src.retrieved_at)}</p>`).join('') || ''}</details>`).join('')}` +
    `<h2>更新任务</h2>${s.jobs.length?`<div class="table-scroll"><table><thead><tr><th>任务</th><th>状态</th><th>开始时间</th><th>结束时间</th></tr></thead><tbody>${s.jobs.map(j=>`<tr><td>${escape(j.kind)}</td><td>${escape(j.status)}</td><td>${escape(j.started_at)}</td><td>${escape(j.finished_at || '进行中')}</td></tr>`).join('')}</tbody></table></div>`:'<p class="detail-caption">尚未从网页发起更新。命令行采集记录已保存在来源核验中。</p>'}`;
  if(s.jobs.some(j=>j.status==='running'))pollTimer=setTimeout(()=>render(),7000);
}

async function render() {
  const version=++revision;clearTimeout(pollTimer);currentPaper=null;
  if(!meta || Date.now()-metaUpdatedAt>15000){meta=await api('/api/meta');metaUpdatedAt=Date.now();}
  const r=route();$('#search-input').value=r.parts[0]==='search'?r.params.get('q')||'':'';
  try{
    if(!r.parts.length)home();
    else if(r.parts[0]==='paper'&&r.parts[1])await detail(r.parts[1],version);
    else if(r.parts[0]==='manage')await manage(version);
    else if(r.conference||r.parts[0]==='topics'||r.parts[0]==='search')await listing(r,version);
    else throw Error('没有找到这个页面');
    if(version===revision){renderPaperText(main,currentPaper?.id);renderPaperText(sidebar,currentPaper?.id);}
  }catch(e){if(version===revision){main.innerHTML=`<div class="empty"><h2>${escape(e.message)}</h2><p>请检查地址或确认本地服务正在运行。</p><a class="button" data-nav href="/">返回首页</a></div>`;}}
}
document.addEventListener('click',async e=>{
  const anchor=e.target.closest('a[data-nav]');
  if(anchor&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&e.button===0){e.preventDefault();nav(anchor.getAttribute('href'));return;}
  const button=e.target.closest('button');if(!button)return;
  if(button.dataset.page){const params=new URLSearchParams(location.search);params.set('page',button.dataset.page);nav(location.pathname+'?'+params);}
  if(button.dataset.lang){document.querySelectorAll('[data-lang]').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});renderRichText($('#abstract-body'),button.dataset.lang==='en'?currentPaper.abstract_en:currentPaper.abstract_zh||'中文翻译处理中。',currentPaper.id);}
  if(button.dataset.action==='copy-abstract'){try{await navigator.clipboard.writeText(currentPaper.abstract_zh||'');toast('已复制中文摘要');}catch{toast('浏览器未允许复制，请直接选择摘要文本。');}}
  if(button.dataset.action==='cache-pdf'){button.disabled=true;button.textContent='正在保存 PDF…';try{await api('/api/admin/papers/'+currentPaper.id+'/cache-pdf',{method:'POST',headers:tokenHeaders()});toast('PDF 已保存到本地');render();}catch(err){toast(err.message);button.disabled=false;button.textContent='保存 PDF 到本地';}}
  if(button.dataset.action==='edit')editor();
  if(button.dataset.action==='cancel-edit')$('#editor-slot').innerHTML='';
  if(button.dataset.action==='clear-filters')nav(location.pathname);
  if(button.dataset.action==='admin-token'){const t=window.prompt('远程管理使用的令牌（本机访问可以留空）：');if(t!==null){if(t)sessionStorage.setItem('atlas-admin-token',t);else sessionStorage.removeItem('atlas-admin-token');toast('管理令牌已保存在当前浏览器会话');}}
  if(button.dataset.job){button.disabled=true;try{const job=await api('/api/admin/jobs',{method:'POST',headers:tokenHeaders(),body:JSON.stringify({kind:button.dataset.job,conference:$('#job-conf').value||null})});toast('任务已启动，可在下方查看状态');render();}catch(err){toast(err.message);button.disabled=false;}}
});
$('#global-search').addEventListener('click',()=>$('#search-input').focus());
$('#global-search').addEventListener('submit',e=>{e.preventDefault();const q=$('#search-input').value.trim();nav('/search/?q='+encodeURIComponent(q));});
$('#menu-toggle').addEventListener('click',()=>{const open=sidebar.classList.toggle('open');$('#overlay').hidden=!open;$('#menu-toggle').setAttribute('aria-expanded',String(open));});
$('#overlay').addEventListener('click',closeMenu);
$('#theme-toggle').addEventListener('click',()=>{const dark=document.documentElement.dataset.theme!=='dark';document.documentElement.dataset.theme=dark?'dark':'light';localStorage.setItem('atlas-theme',dark?'dark':'light');$('#theme-toggle').setAttribute('aria-label',dark?'切换浅色模式':'切换深色模式');});
document.documentElement.dataset.theme=localStorage.getItem('atlas-theme')||'light';
document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();$('#search-input').focus();}if(e.key==='Escape')closeMenu();});
window.addEventListener('popstate',()=>{closeMenu();render();});
render().catch(e=>main.innerHTML=`<div class="empty"><h2>论文库暂时无法读取</h2><p>${escape(e.message)}</p><button class="button" onclick="location.reload()">重新加载</button></div>`);
