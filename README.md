# TopConf Atlas：顶会论文库

本项目位于 `/Knowin/sim/chensuzeyu/research/topconf_atlas`，包含可运行的前端、FastAPI 后端、SQLite 数据库、官方来源快照，以及可续跑的分类和中文处理管线。

浏览结构参考 [Paper-Notes](https://github.com/zhaoyang97/Paper-Notes) 和 [papernotes.org 的分类页](https://papernotes.org/ECCV2026/llm_agent/)：深色会议导航、左侧分类树、右侧论文标题与一句话中文介绍。论文内页只显示完整摘要的中文翻译与英文原文，不额外生成长篇解读。移动端可折叠分类栏。

## 当前范围

以原五会 2026-10-11、RSS 2026-10-15 取得的官方公开资料为依据，收录六个会议的全部可核验录用论文，含普通 Poster / 非精选论文。**Oral、Spotlight、Highlight 是可选筛选维度，不是收录条件**；展示形式、录用依据、精选标签和获奖信息分别保存。当前去重后共有 **28,004 篇**。

| 会议 | 全部论文 | 普通 / 未启用标签 | Oral | Spotlight | Highlight |
| --- | ---: | ---: | ---: | ---: | ---: |
| ICLR2026 | 5,353 | 5,129 | 224 | 未见独立标记 | — |
| CVPR2026 | 4,047 | 3,331 | 141 | — | 575 |
| ICML2026 | 6,554 | 5,980 | 168 | 406 | — |
| RSS2026 | 210 | 210 | 不作为精选标签 | 不启用 | 不启用 |
| ECCV2026 | 2,834 | 2,671 | 28 | 135 | — |
| NeurIPS2026 | 9,006 | 9,006 | 本轮禁用 | 本轮禁用 | 本轮禁用 |

表内精选列按主展示级别统计，同一论文可能另有官方 decision 标签；筛选按全部已确认标签匹配，多选取并集，论文不重复。普通论文表示没有已确认精选标签，不代表推断官方展示形式一定是 Poster。NeurIPS 本轮禁用精选标签，原始来源中的展示信息仍保存用于核验。RSS 的会议报告安排不作为精选 Oral 标签；210 篇论文覆盖 21 个官方 session，3 篇获奖论文可独立筛选。46 个主题支持多标签分类与交叉筛选。

ICML 包含 6,341 篇主研究轨道、213 篇 Position Track。NeurIPS 已核验轨道为主研究 7,151 篇、Evaluations & Datasets 915 篇、Position 136 篇；另有 **804 篇轨道待核验**，官方论文名单、完整摘要和 canonical OpenReview 链接可核验，但公开导出缺少轨道字段。不能把它们猜成主研究轨道。Workshop、Blog、已确认期刊展示与复现活动不混入正式论文库。

[CVPR 官方论文集索引](https://openaccess.thecvf.com/CVPR2026?day=all)有 4,042 篇；另外 5 篇原有精选论文仍出现在官方 Oral / Highlight 名单中，因此保留，共 4,047 篇。这 5 篇的官方提供 CVF 地址目前返回 404，论文与 PDF 链接可用性不等于名单覆盖率；差异记录在采集报告中。没有通过标题相似度猜测合并。

[NeurIPS 官方论文索引](https://neurips.cc/virtual/2026/papers.html)列出 9,094 个展示条目；[完整公开导出](https://neurips.cc/Downloads/2026)有 9,110 行，含 16 行不在论文索引中的复现活动。对账后排除 88 篇期刊展示，得到 9,006 篇。结构化 static JSON 存在重复行和不同快照遗漏；适配器结合当前完整索引、公开导出、存档结构化轨道证据与官方论文详情，避免把其截断子集误报为全覆盖。补充记录还与 [TMLR 官方论文索引](https://jmlr.org/tmlr/papers/)及 [JMLR 当年索引](https://jmlr.org/papers/v27/)核对，以排除有 OpenReview 链接的期刊展示。

原有 **1,677 篇的 ID、翻译输入和历史中文结果保持不变**；核验见 `docs/baseline-preservation.json`。全部原始来源、采集时间、内容 SHA-256、名单差异与处理进度见管理页面、`/api/reports/{会议}` 和 `data/reports/`。中文处理独立统计，机器翻译不标为人工已校对。

## 启动与访问

已安装独立虚拟环境，不需要 Node.js 或前端构建服务。

```bash
cd /Knowin/sim/chensuzeyu/research/topconf_atlas
./scripts/atlas.sh serve
```

地址为 **http://127.0.0.1:18766**。管理页面：http://127.0.0.1:18766/manage/ 。已有服务占用了 8765 / 8766，本项目使用独立端口。

持久启动、查看状态和停止本项目服务：

```bash
.venv/bin/python scripts/service.py start
.venv/bin/python scripts/service.py status
.venv/bin/python scripts/service.py stop
```

`service.py` 只管理本项目自己的进程，端口被其他项目占用时会退出。日志在 `.runtime/server.log`。若通过 SSH 访问此服务器，在自己的电脑上建立转发：

```bash
ssh -N -L 18766:127.0.0.1:18766 <你的服务器 SSH Host>
```

然后在电脑浏览器打开上述地址。修改端口可设置 `ATLAS_PORT`。默认只绑定本机；远程管理写入需要设置 `ATLAS_ADMIN_TOKEN`，并在管理页面输入同一个令牌。不要直接把无认证的本地管理接口公开到互联网。

## 更新与日常管理

```bash
./scripts/atlas.sh sync                         # 更新六会全部录用论文
./scripts/atlas.sh sync --conference ECCV2026  # 更新单个会议
./scripts/atlas.sh sync --offline              # 用原始快照复现筛选和去重
./scripts/atlas.sh enrich                      # 仅处理新增或原文已变化的论文
./scripts/atlas.sh enrich --repair             # 同时重试有机器质检标记的译文
./scripts/atlas.sh export                      # 导出当前完整 JSON 目录
./scripts/atlas.sh status
./scripts/atlas.sh recheck                     # 不调用模型，重新检查已有译文
./scripts/atlas.sh audit                       # 源文件哈希、录用依据、去重、分类、中文覆盖检查
```

默认中文处理每批 3 篇、4 个 HTTP 工作线程，可用 `--workers` 与 `--batch-size` 调整。 每次请求（含失败重试）的 usage 与实际返回服务档位独立保存至 `data/reports/model-usage-*`，即使内容校验失败也保存已有 usage。可设置 `ATLAS_LLM_TOKEN_BUDGET` 限制后续请求派发，并用 `ATLAS_LLM_USAGE_DIR` 指定跨续跑共享的预算目录；并发请求按每篇 5,000 token 预留，每批最多 30,000 token；未知用量或中断请求按请求当时的预留量保守计入，历史估算不追溯改小；连接超时或异常链明确显示 TLS 握手失败、请求尚未发出时单独记为 not_sent，不计为模型用量。各工作线程复用自己的 HTTP 会话并在操作结束时关闭。此上限控制派发，不等同于账户账单的硬性扣费上限。连续 8 次模型连接失败后，本次处理停止派发后续请求；已经派发的请求仍会结束并记录用量，避免连接故障时重试整个论文库。翻译成功即逐篇提交，网络故障或中断后再次运行会跳过已成功的相同输入。页面管理按钮对应相同操作，后台运行并显示结果。未设置定时任务；需要自动更新时，可在服务器自己的调度系统调用上述命令。

人工校对入口在论文内页。“中文标题、一句话介绍、完整中文摘要、主题分类”可以修改。修订独立存储，采集不会覆盖；若原摘要变化，会保留人工译文并提示重新校对。审计历史保存在 `audit` 表中。手工修订原文后再运行 `enrich` 时，新的机器结果也不会覆盖人工修订。

## 论文正文 PDF

完整元数据、英文摘要、中文摘要和论文链接均保存在本地。PDF 可在论文页面按需缓存，或批量下载：

```bash
./scripts/atlas.sh pdf --conference CVPR2026
./scripts/atlas.sh pdf --workers 3               # 全部符合标准的论文
./scripts/atlas.sh pdf --conference ICLR2026 --limit 1
```

每个 PDF 独立记录来源、最终地址、下载时间、字节数与 SHA-256。检查 HTTP 200、`%PDF-` 文件头、EOF 标记和长度，拒绝错误 HTML 或不完整的 HTTP 206 响应。失败会保留可续跑清单，已验证的文件会跳过。默认单文件上限 250 MiB。

OpenReview 可能对服务器请求返回验证页面；这种情况下会明确记录失败，不会伪装为成功或尝试绕过验证。ICLR 和 ICML 已匹配全部入库论文的官方 proceedings / PMLR PDF 地址，并保留 OpenReview 地址；正文可用性和元数据覆盖率分别报告。

## 存储与复现

```text
config/
  conferences.json       会议顺序、年份、采集适配器、官方轨道、奖项证据
  taxonomy.json          46 个研究主题及分组、slug、初始规则
atlas/
  collect.py             官方采集、分页完整性、事件关联去重、增量更新
  rss.py                 RSS 接收名单与论文集对账、摘要与 DOI 提取
  enrich.py              完整摘要翻译、一句话介绍、模型多标签分类与数值检查
  storage.py             数据库、原文哈希、机器处理版本、人工覆盖、JSON 导出
  query.py               有效元数据查询索引、分页、主题与精选标签组合筛选
  server.py              论文查询、管理任务、校对、PDF 和导出 API
  pdf.py                 PDF 下载与完整性校验
  audit.py               全库交付检查
frontend/                无构建步骤的网页与本地字体
data/
  atlas.sqlite3          运行数据库，含处理结果、人工修订、审计历史、旧 ID 别名
  raw/<会议>/            原始官方索引与摘要；按内容哈希归档
  papers/<会议>/         单篇完整 JSON（历史失效记录带 active=false）
  catalog.json           只包含当前有效论文的完整导出
  archive.json           包含合并/失效论文的历史导出
  translations/          每次模型输入哈希、输出、模型与 token 使用记录
  reports/               覆盖率、更新差异、失败清单、质检
  web_sources/           官方奖项公告的文献事实提取快照
  pdf/<会议>/            按需下载的 PDF 与校验元数据
docs/screenshots/        参考页面与本项目页面的验收截图
tests/                   管线与 API 测试
```

`data/raw/` 保存当前与历史官方快照；同一 URL 的历史版本列在 manifest 的 history 中，可离线复现。正式收录范围由可核验录用 / 论文集成员资格决定，精选标签只控制筛选。旧记录保留供审计，正常列表不会重复展示。

数据库保留原始摘要和完整译文，列表查询使用由数据库触发器更新的有效元数据投影。标题、作者、中英文摘要与中文介绍仍按大小写无关的文字包含关系搜索；分页仅传输列表所需字段。机器处理、人工校对和名单更新会使对应索引失效并自动重建，不需要手工清缓存。

备份时保存整个 `data/` 和 `config/`；运行中如只备份数据库，使用 SQLite backup，避免仅复制 WAL 模式下的主文件：

```bash
.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
Path('data/backups').mkdir(exist_ok=True)
with sqlite3.connect('data/atlas.sqlite3') as source, sqlite3.connect('data/backups/atlas.sqlite3') as destination:
    source.backup(destination)
PY
```

恢复时停止本项目服务，再恢复数据目录。JSON 导出方便分析和迁移；保留 SQLite 数据库才能完整保留人工修订历史与任务记录。

## 采集适配器与后续扩展

当前 ICLR / ICML / ECCV 使用完整 Miniconf 分页，CVPR 使用 `cvpr-listings` 将精选名单与 CVF 全部论文集合并，NeurIPS 使用 `neurips-full` 对账公开下载与论文索引。配置中的 `scope: accepted` 表示全量录用范围；`distinctions_enabled: false` 控制 NeurIPS 本轮不展示精选标签。轨道由 `source_group` / `extra_groups` 明确允许，缺失轨道标记 `unverified`。

RSS 使用 `rss-proceedings` 适配器，将 [官方接收名单](https://roboticsconference.org/2026/program/papers/)与 [RSS XXII 论文集](https://www.roboticsproceedings.org/rss22/)逐篇对账。详情页的 citation 元数据提供完整作者，HTML 提供完整摘要、DOI 与 HTTPS PDF 链接；接收名单的隐藏作者列表避免重复读取。身份使用稳定的 proceedings URL，保留独立 program ID、session 和来源证据，不假设两站编号相同。标题冲突、缺失摘要、DOI 冲突或两份索引不一致时拒绝更新并保留原库；已有快照支持离线重放。官方三项获奖结果独立配置、核验与展示，不把 finalist 当作获奖论文。

```bash
./scripts/atlas.sh sync --conference RSS2026
./scripts/atlas.sh sync --conference RSS2026 --offline
./scripts/atlas.sh enrich --conference RSS2026
./scripts/atlas.sh pdf --conference RSS2026 --limit 1
```

RSS 接入的隔离验证、旧数据保持与交付记录见 `docs/rss2026-*.json`；接入前 SQLite 和配置备份保存在 `data/backups/rss2026-before-integration/`。

新增会议需要核验官方 source group、文件名、分页、录用判断、轨道与论文身份；必要时新增适配器。标题里的 “oral / spotlight” 不构成精选证据。分页不完整、摘要缺失、官方身份冲突或异常缩水会使刷新失败并保留之前数据；不能把网络验证页面当作空名单提交。采集使用限速并发，`ATLAS_FETCH_WORKERS` 默认 6，可调整；详情页短期缓存与按内容哈希归档使补齐过程可续跑，`sync --offline` 只读取已有官方快照。

NeurIPS 的公开下载使用普通 CSRF 表单 POST，保存非敏感请求字段和响应哈希，24 小时内可重用；过期在线同步会重新取表单。未访问认证接口，未绕过访问限制。名单覆盖、轨道完整性、摘要完整性、中文处理和 PDF 可用性分别报告。

ICML 的 PMLR Volume 306 用官方 OpenReview ID 匹配，不依赖修改前后的标题相似度。ECCV 的 Mind-to-Face 官方摘要 JSON 缺少末句最后一个词，已根据官方 PDF 第 1 页恢复；修复内容、原摘要哈希和正文哈希独立保存于 `config/abstract-corrections-eccv2026.json`，后续原文变化时会要求重新核对，避免沿用过期修复。

CVPR 2026 的 static JSON 只含前 200 条，后续 API 要求认证，因此使用官方完整 Highlight / Oral 分类页面和 CVF 全量 proceedings 索引。少量标题变体通过官方论文详情页补齐链接。两份官方博客奖项公告直接请求会返回 JavaScript 验证页，已通过可访问的官方网页文本提取获奖文献事实，保存独立来源与采集时间；正文名单始终使用官方会议数据。扩展其他会议时需要配置和核验它们自己的 award_sources，不能假定历年奖项命名和结构相同。

## 中文处理模型

当前使用本机已有的 Codex 登录会话，读取其配置中的模型名称。没有启动子代理、执行模型工具，也没有把登录令牌复制进项目或写进日志。

```bash
export ATLAS_LLM_PROVIDER=codex-session
export ATLAS_CODEX_DIR=/Knowin/sim/chensuzeyu/.codex
./scripts/atlas.sh enrich
```

也支持标准 OpenAI Responses API：

```bash
export ATLAS_LLM_PROVIDER=openai
export OPENAI_API_KEY='<在你的环境中设置，不写入仓库>'
export ATLAS_LLM_MODEL='<你的可用模型>'
./scripts/atlas.sh enrich
```

依据 [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) 使用严格 JSON Schema，逐批检查 ID、中文文本、摘要长度和分类值。Codex 会话端点不是稳定的公共 API 合约；适配器已隔离，移植或长期无人值守运行优先使用标准 API。会话过期会明确失败，已有数据不受影响。网络代理可设置 `ATLAS_HTTP_PROXY`（采集）及标准 `HTTPS_PROXY`（模型/PDF），不需要修改服务器全局网络配置。

机器翻译和分类标为 machine；只有通过网页保存的人工校对才标为 reviewed。数值质检会识别单位换算，例如 `1.3 million` 与 `130 万`，以及 `3D` 与“三维”；不能自动证明全文语义完全正确，因此保留人工校对入口及原文对照。

## 安装与测试

Python 3.11+：

```bash
python3 -m venv .venv
PYTHONPATH='' .venv/bin/pip install -r requirements.lock
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
./scripts/atlas.sh audit
```

`requirements.lock` 为本次已验证环境的版本快照；基础运行依赖见 `requirements.txt`。浏览器检查使用 Playwright；需要另行 `playwright install chromium`。前端字体保存在本地，SIL OFL 许可证位于 `frontend/fonts/`，不依赖外部字体 CDN。

## 验证与页面截图

管线测试：`PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v`。浏览器验收：启动本项目服务后运行 `PYTHONPATH=. .venv/bin/python scripts/check_browser.py`（需开发依赖与 Playwright Chromium）。报告在 `docs/browser-checks.json`，桌面和移动端截图在 `docs/screenshots/`。数据完整性报告由 `./scripts/atlas.sh audit` 生成至 `data/reports/integrity-latest.json`。

## 公式与论文格式

标题、侧栏目录、列表介绍和中英文摘要使用本地 KaTeX 0.19.0 及其数学字体；运行时不访问第三方 CDN。支持 `$…$`、`$$…$$`、`\(...\)`、`\[...\]` 和常见公式环境，处理来源的重复转义、公式外的乘号/百分号、中文文本强调及已核验的作者宏。原始摘要、复制内容和编辑表单保留原文写法；规范化仅用于页面显示。作者宏按论文隔离，定义依据见 `docs/math-macro-sources.json`。渲染选项参照 [KaTeX 官方文档](https://katex.org/docs/options)。

ECCV 的 Zero-shot Depth from Defocus 官方摘要索引误包含首页图注与损坏的指标字符，已根据官方 PDF 第 1 页剔除图注，保留完整摘要；修复有原摘要哈希和正文 SHA-256，旧版本仍保留。

全库公式验收会分批检查全部字段，区分成功排版、可读源公式回退和残留源格式；源公式缺少作者宏时不会猜测定义。`ATLAS_REQUIRE_PERFECT_MATH=1` 可要求所有公式与源格式问题均解决才通过；默认要求安全渲染、页面可读、无浏览器异常且原有论文无回归。详细待核验项保存在报告中。

全库公式验收：`PYTHONPATH=. .venv/bin/python scripts/check_math.py`，检查全部论文的中英文标题、中英文摘要和列表介绍，以及桌面/手机端与语言切换。报告在 `docs/math-checks.json`，截图在 `docs/screenshots/math-*.png`。可选 Node 回归检查：`node tests/math.test.mjs`。未来新增不支持的命令会保留可阅读的源公式并进入检查报告，避免整篇内容渲染失败。

### 主题页交叉标签筛选

会议总列表 `/{conference}/` 也直接展示“研究主题标签（多选）”，无需先进入左侧主题页；多选按 AND 取交集，选择随 URL 保存，清除标签保留搜索、级别和轨道条件。论文行的主题标签可点击进入对应会议的主题页。RSS 的 210 篇论文均已分类，当前覆盖 27 个有效研究主题；“精选标签未启用”仅指会议精选级别，不影响研究主题标签。

跨会议 `/topics/{slug}/` 和会议内 `/{conference}/{slug}/` 均支持标签多选。页面主题是固定条件；额外标签取交集（AND），例如机器人页选择“多模态 VLM”和“优化与训练”，只显示同时属于这三个主题的论文。“仅机器人与具身智能”只匹配标签集合恰好为 `robotics` 的论文，与其它标签互斥；切换时自动清除冲突选择。没有勾选时显示该主题下全部论文。

标签数量统计分页前的当前主题范围，会议、关键词、级别、轨道和校对条件均参与计数，额外标签选择不改变这些基础交叉数量。各标签数量可能重叠；列表总数显示当前多选交集的实际篇数。数量为零的单一主题项仍显示，已选择的其它标签即使变为零也保留，便于取消。清除标签选择保留搜索和级别等条件，筛选变化会回到第一页。

API 使用 `/api/papers?category=robotics&tag=multimodal&tag=optimization`；独占使用 `exclusive=true`。响应 `topic_facets` 含 `total`、`exclusive_count` 和交叉标签 `tags`。缺少页面主题、未知标签或互斥条件组合返回 422。选择保存在 URL，刷新与分享可恢复。

验证：`PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v`；浏览器验收：`PYTHONPATH='' .venv/bin/python scripts/check_topic_filters.py`，报告在 `docs/topic-filter-checks.json`。

### 精选标签与全量范围

默认显示全部论文。选择 Oral / Spotlight / Highlight 可缩小范围，多选取并集（OR）；主题交叉标签仍取交集（AND）。普通论文单独可筛选，获奖信息独立。NeurIPS 页面不显示精选标签控件或精选徽章，可按主研究、E&D、Position、轨道待核验筛选。

API 兼容单值 `tier=oral`，并支持 `tier=oral&tier=spotlight`。`tier=poster` 匹配未确认精选标签的原四会论文；`tier=unlabeled` 匹配未启用精选标签的会议。`tier=award` 匹配获奖论文。标签数量可能重叠，总数始终按唯一论文统计。

2026-10-11 扩容时，五个会议共 **27,794 篇已全部完成中文处理**，正式服务为 `http://127.0.0.1:18766`。扩容交付与用量记录在 `docs/full-coverage-delivery.json`，完整验收在 `docs/full-coverage-acceptance.json`。实施前 SQLite 与代码备份位于 `.runtime/full-coverage/`，原数据目录完整保留在 `.runtime/full-coverage/data-before-switch/`，可在停止服务后恢复作回滚。临时模型代理已停止，其凭证配置已删除。

2026-10-15 已接入 RSS2026：210 篇全部完成中文标题、完整摘要翻译、一句话介绍和分类；当前六会合计 **28,004 篇**。RSS 专项交付与验收见 `docs/rss2026-delivery.json`、`docs/rss2026-browser-checks.json` 和 `docs/rss2026-quality-checks.json`。

## Git 与 GitHub 管理

源码仓库采用 `main` 主分支。`origin` 预配置为 `git@github.com:chensuzeyu/topconf_atlas.git`；配置远程地址不代表 GitHub 仓库已经创建。建议先使用私有仓库，确认文档、截图与数据发布范围后再考虑公开。没有设置独立本地备份仓库。

| 内容 | Git 管理方式 | 原因 |
| --- | --- | --- |
| `atlas/`、`scripts/`、`tests/` | 追踪 | 实现、操作入口与回归测试 |
| `config/`、`requirements*.txt`、`requirements.lock` | 追踪 | 采集规则、人工原文修复、分类体系与依赖版本 |
| `frontend/`，含字体、KaTeX 与许可证 | 追踪 | 无构建步骤，克隆后需要这些运行资源 |
| `README.md`、`docs/` 下的人工维护文档、公式来源证据与原始设计参考图 | 追踪 | 保存说明、公式修复依据与设计输入 |
| `docs/*.json`（除 `math-macro-sources.json`）、`docs/screenshots/*`（除 `reference.png`） | 忽略 | 验收、交付和性能报告及浏览器截图属于运行生成产物，保留在本地和数据备份中 |
| `data/web_sources/` 下现有三个奖项证据 JSON | 明确白名单追踪 | 文件很小，保存采集器依赖的官方奖项事实；新增文件需单独评估并更新白名单 |
| SQLite、`data/raw/`、`data/papers/`、`data/translations/`、`data/reports/`、两个完整 JSON 导出 | 忽略 | 持续变化的研究数据，体积大、历史膨胀快 |
| `data/pdf/`、`data/backups/`、`data/locks/` | 忽略 | 下载文件、数据备份与进程状态 |
| `.venv/`、`.runtime/`、`probe/`、缓存、日志 | 忽略 | 本机环境、临时探索与运行产物 |
| `.env*`、认证文件和私钥 | 忽略 | 凭证只保留在环境或本机；不含秘密的 `.env.example` 可提交 |

验收报告和页面截图仍写入上述 `docs/` 路径，可运行对应 `scripts/check_*.py` 检查脚本重新生成；交付报告和完整离线证据随本地数据另行保存。已有追踪的生成文件已取消追踪，本地文件不删除，历史提交中的版本仍可查询。

GitHub 远程只保存上述追踪文件，不包含当前论文库、机器翻译结果、人工校对历史、完整离线采集快照或生成的验收产物。克隆后可安装依赖并在线执行 `sync`；恢复现有完整论文库仍需要单独的数据副本。`sync --offline` 需要 `data/raw/`，不会仅凭源码仓库成功。数据保存方法见“存储与复现”；本次 Git 配置没有新增数据备份任务。

现有 `catalog.json` 和 `archive.json` 各约 186 MB，超过 GitHub 普通 Git 的 100 MiB 单文件限制。当前不启用 Git LFS；如以后需要发布数据集，可考虑独立的数据存储或版本化发布附件，避免日常运行数据进入源码历史。参见 [GitHub 大文件说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。

本机仓库级配置参考 `volcengine-codex-bridge`：提交身份为 `chensuzeyu <chensuzeyu@qq.com>`（取自参考仓库最近一次提交），SSH 使用 `ssh -F /Knowin/sim/chensuzeyu/.ssh/config`，经 `ssh.github.com:443` 连接。另设置 `pull.ff=only`、`push.default=simple`、`fetch.prune=true` 和 `core.autocrlf=false`。这些配置保存在本机 `.git/config`，不会改变全局 Git 配置，也不会随克隆传播；换机器时配置自己的提交身份与 GitHub 认证即可。`.gitattributes` 统一源文件 LF 换行，并标明图片、字体为二进制。

首次连接 GitHub：在 [GitHub 新建仓库页面](https://github.com/new) 创建 `chensuzeyu/topconf_atlas`，建议选择 Private，**不要勾选生成 README、License 或 .gitignore**。本地已经有这些项目文件和初始历史。创建空仓库后执行：

```bash
cd /Knowin/sim/chensuzeyu/research/topconf_atlas
git ls-remote origin
git push -u origin main
```

本机目前没有 GitHub CLI 或 API 令牌；SSH 认证已验证可用，但只凭 SSH 密钥无法通过 Git 命令创建 GitHub 仓库。创建与推送流程参见 [GitHub 导入本地仓库说明](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

日常修改先检查提交范围，再推送：

```bash
git status --short
git diff
git add atlas scripts tests config frontend README.md docs .gitignore .gitattributes
git diff --cached --stat
git diff --cached
git commit -m "Describe the change"
git push
```

跨机器修改前执行 `git pull --ff-only`；多人协作或较大改动使用 `git switch -c feature/<name>`，推送分支后通过 GitHub Pull Request 合并。`pull --ff-only` 遇到分叉会停止，应先查看双方历史并选择合并或变基。不要为了提交数据而使用 `git add -f data/`；`.gitignore` 不会阻止强制添加文件，也不会自动移除已追踪文件。
