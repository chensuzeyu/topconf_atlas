import './vendor/katex/katex.min.js';

// Presentation only: the archived source and editable text stay unchanged.
const COMMANDS = 'textbf textit texttt textsc textul emph underline textrm text mathcal mathbb mathbf mathsf mathrm boldsymbol operatorname frac sqrt times sim approx pi alpha beta gamma delta epsilon varepsilon sigma Sigma rho tau mu eta theta varphi ell log ln exp max sup inf in infty to rightarrow leftarrow mid left right tilde widetilde Omega Theta Delta Pi star ast top langle rangle cdot binom dots le leq ge geq lesssim gg ll begin end url href cite citep citet NC AC TC alg method mask eg ourshortname MOE ourmethod methodname tracker modelname algshort ourbenchmark ourname MethodName dataset ouralg Walrus bench Ours ourset perfit cutting benchname'.split(' ');
const DOUBLE_COMMAND = new RegExp(String.raw`(?<!\\)\\\\(?=(?:${COMMANDS.join('|')})\b)`, 'g');
const FORMATS = {textbf:'strong', textit:'em', emph:'em', texttt:'code', textsc:'smallcaps', underline:'underline', textul:'underline', textrm:'span', text:'span'};
const MATH_COMMANDS = new Set(COMMANDS.filter(name => !FORMATS[name] && !['url','href','cite','citep','citet','eg'].includes(name)));
const MACROS = {'\\NC':'\\mathsf{NC}', '\\AC':'\\mathsf{AC}', '\\TC':'\\mathsf{TC}'};
export const ALIASES = {
  'iclr2026-3c7fde53bdb5996e': {alg:'InfoTok'},
  'iclr2026-b22813abf7f09692': {method:'MemAgent'},
  'iclr2026-12331806f03c2759': {mask:'mask'},
  'cvpr2026-9e05b7667180212f': {algshort:'3PT'},
  'cvpr2026-41ec525d2b7e35d6': {ourbenchmark:'R4D-Bench'},
  'cvpr2026-1a3a0d4ad1ea4426': {modelname:'AeroGS'},
  'cvpr2026-27148cb53283d1c3': {ourmethod:'XL-VLA'},
  'cvpr2026-664f9bb296d414b6': {methodname:'RR-DU'},
  'cvpr2026-9ee7cf1a7775c812': {tracker:'SVLTrack'},
  'cvpr2026-68321373d20b7129': {ourname:'Gated KalmaNet',ourshortname:'GKA'},
  'cvpr2026-f8c80c74343465b1': {method:'One-to-More'},
  'cvpr2026-029009644c9d59be': {MethodName:'PoseD-Flow'},
  'cvpr2026-f3cf17e24fca1a32': {MOE:'PromptMoE'},
  'cvpr2026-fe10f547b512a3e5': {dataset:'VideoNet'},
  'icml2026-06038897d8180b32': {ourset:'FLIP2'},
  'icml2026-00e9964da00d0e07': {perfit:'PerFit',cutting:'cutting'},
  'icml2026-4c913b559e4e399f': {method:'TESS'},
  'icml2026-447e2cef4c1ce917': {method:'PLANTAIN'},
  'icml2026-2df97d2fcf6e902d': {method:'SCALE'},
  'icml2026-c3226b59d8651f98': {ouralg:'ThunderAgent'},
  'icml2026-1aa8c9aac09d00b1': {Ours:'UDM-GRPO'},
  'icml2026-5850d950949cd368': {benchname:'VisionWebDev'},
  'icml2026-4aace155a93bff5d': {Walrus:'Walrus'},
  'icml2026-acf3876ac240ca7c': {bench:'SandboxEscapeBench'}
};

function escaped(text, index) {
  let slashes = 0;
  while (index > 0 && text[--index] === '\\') slashes++;
  return slashes % 2 === 1;
}
function group(text, start) {
  if (text[start] !== '{') return null;
  let depth = 1;
  for (let i = start + 1; i < text.length; i++) {
    if (escaped(text, i)) continue;
    if (text[i] === '{') depth++;
    if (text[i] === '}' && --depth === 0) return {text:text.slice(start+1,i), end:i+1};
  }
  return null;
}
function closeDelimiter(text, from, delimiter) {
  let depth = 0;
  for (let i = from; i < text.length; i++) {
    if (!escaped(text,i)) {
      if (depth === 0 && text.startsWith(delimiter,i)) return i;
      if (text[i] === '{') depth++;
      if (text[i] === '}') depth = Math.max(0,depth-1);
    }
  }
  return -1;
}
function normalize(text) {
  return String(text ?? '').replace(/(?<!\\)\\\\(?=[()[\]])/g, '\\').replace(DOUBLE_COMMAND, '\\')
    .replace(/\\\$(?=\\(?:approx|sim)\$)/g, '$');
}

export function mathOptions(paperId, displayMode=false) {
  const macros={...MACROS};
  for (const [name,value] of Object.entries(ALIASES[paperId] || {})) macros['\\'+name]='\\text{'+value+'}';
  return {displayMode,throwOnError:true,trust:false,strict:'ignore',maxExpand:1000,macros};
}

export function normalizeEquation(tex) {
  // Some CVPR records combine dollar delimiters with a stray \) closer.
  return tex.replace(/\\([()[\]])/g, '$1');
}

export function tokenizeRichText(input, aliases = {}) {
  const text = normalize(input), tokens = [];
  let plain = '', i = 0;
  const flush = () => {if (plain) {tokens.push({kind:'text',text:plain});plain='';}};
  while (i < text.length) {
    let delimiter = null;
    if (!escaped(text,i)) {
      for (const [left,right,display] of [['$$','$$',true],['\\[','\\]',true],['\\(','\\)',false],['$','$',false]]) {
        if (text.startsWith(left,i)) {delimiter={left,right,display};break;}
      }
    }
    if (delimiter) {
      const end = closeDelimiter(text,i+delimiter.left.length,delimiter.right);
      if (end >= 0) {
        const tex = text.slice(i+delimiter.left.length,end);
        // Currency in prose is not a mathematical expression.
        const currencyProse=delimiter.left==='$' && !tex.includes('\\') &&
          (/[A-Za-z]{3,}\s+[A-Za-z]{3,}/.test(tex) || /\b(and|or|USD|dollars|per|each|for)\b/.test(tex));
        if (tex.trim() && !currencyProse) {
          const nameFormat=/^\\texttt\{\\textbf\{([^{}]+)\}\}$/.exec(tex.trim());
          flush();
          if (nameFormat) tokens.push({kind:'code',children:[{kind:'strong',children:tokenizeRichText(nameFormat[1],aliases)}]});
          else tokens.push({kind:'math',tex,display:delimiter.display});
          i=end+delimiter.right.length;continue;
        }
      }
    }
    if (text[i]==='{') {
      const wrapped=group(text,i);
      if(wrapped && /^\s*\\[A-Za-z]/.test(wrapped.text)) {
        flush();tokens.push({kind:'span',children:tokenizeRichText(wrapped.text,aliases)});i=wrapped.end;continue;
      }
    }
    const command = text[i] === '\\' ? /^\\([A-Za-z]+)\*?/.exec(text.slice(i)) : null;
    if (command) {
      const name = command[1], after = i+command[0].length;
      let argumentStart=after;
      while (/\s/.test(text[argumentStart] || '') && argumentStart<text.length) argumentStart++;
      const argument=group(text,argumentStart);
      if (name === 'begin' && argument) {
        const env=argument.text, endMarker='\\end{'+env+'}', end=text.indexOf(endMarker,argument.end);
        if (end>=0) {
          let tex=text.slice(i,end+endMarker.length);
          if (/^(equation|equation\*)$/.test(env)) tex=text.slice(argument.end,end);
          if (/^(align|align\*)$/.test(env)) tex='\\begin{aligned}'+text.slice(argument.end,end)+'\\end{aligned}';
          flush();tokens.push({kind:'math',tex,display:true});i=end+endMarker.length;continue;
        }
      }
      if (FORMATS[name] && argument) {
        flush();tokens.push({kind:FORMATS[name],children:tokenizeRichText(argument.text,aliases)});i=argument.end;continue;
      }
      if (['url','href'].includes(name) && argument) {
        const label=name==='href'?group(text,argument.end):null;
        flush();tokens.push({kind:'link',url:argument.text,children:tokenizeRichText(label?.text ?? argument.text,aliases)});i=label?.end ?? argument.end;continue;
      }
      if (['cite','citep','citet'].includes(name) && argument) {
        plain+='('+argument.text+')';i=argument.end;continue;
      }
      if (name==='eg') {plain+='e.g.';i=after;continue;}
      if (aliases[name]) {plain+=aliases[name];i=after;if(text.slice(i,i+2)==='{}')i+=2;if(text[i]==='~'){plain+=' ';i++;}continue;}
      if (MATH_COMMANDS.has(name)) {
        let end=argument?.end ?? after;
        if (['frac','binom'].includes(name) && argument) end=group(text,end)?.end ?? end;
        // Preserve subscripts/superscripts attached to a bare TeX symbol.
        while (text[end]==='_' || text[end]==='^') {
          end++;const power=group(text,end);end=power?.end ?? Math.min(text.length,end+1);
        }
        flush();tokens.push({kind:'math',tex:text.slice(i,end),display:false});i=end;continue;
      }
    }
    if (text[i]==='\\' && /[%&#_$]/.test(text[i+1] || '')) {plain+=text[i+1];i+=2;continue;}
    const accent=text[i]==='\\' ? /^\\(['`"^~])([A-Za-z])/.exec(text.slice(i)) : null;
    if(accent){plain+=(accent[2]+{"'":'\u0301','`':'\u0300','"':'\u0308','^':'\u0302','~':'\u0303'}[accent[1]]).normalize('NFC');i+=accent[0].length;continue;}
    // Mathematical alphanumeric characters from PDF extraction need a math font.
    const point=text.codePointAt(i);
    if (point>=0x1d400 && point<=0x1d7ff) {
      const symbol=String.fromCodePoint(point);flush();tokens.push({kind:'math',tex:symbol,display:false});i+=symbol.length;continue;
    }
    plain+=text[i++];
  }
  flush();return tokens;
}

export function renderRichText(element, text, paperId) {
  const aliases=ALIASES[paperId] || {};
  const render = (tokens,parent) => {
    for (const token of tokens) {
      if (token.kind==='text') {parent.append(document.createTextNode(token.text));continue;}
      if (token.kind==='math') {
        const node=document.createElement('span');node.className=token.display?'math-display':'math-inline';
        try {
          globalThis.katex.render(normalizeEquation(token.tex),node,mathOptions(paperId,token.display));
        } catch(error) {
          node.classList.add('math-error');node.textContent=token.tex;node.title='公式源格式需要校对：'+error.message;node.dataset.mathError=error.message;
        }
        parent.append(node);continue;
      }
      const node=document.createElement(token.kind==='link'?'a':['strong','em','code'].includes(token.kind)?token.kind:'span');
      if(token.kind==='link' && /^https?:\/\//i.test(token.url)) {node.href=token.url;node.target='_blank';node.rel='noopener noreferrer';}
      if(token.kind==='smallcaps')node.style.fontVariant='small-caps';
      if(token.kind==='underline')node.style.textDecoration='underline';
      render(token.children,node);parent.append(node);
    }
  };
  const fragment=document.createDocumentFragment();render(tokenizeRichText(text,aliases),fragment);element.replaceChildren(fragment);
}

export function renderPaperText(root, paperId) {
  const selector='.paper-title, .paper-summary, .paper-nav a, .detail-title, .title-zh, .abstract-text';
  for (const element of root.querySelectorAll(selector)) {
    renderRichText(element,element.textContent,element.closest('[data-paper-id]')?.dataset.paperId || paperId);
  }
}
