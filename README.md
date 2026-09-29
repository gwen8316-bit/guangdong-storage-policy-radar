# 广东储能政策雷达

自动追踪国家及广东省储能相关政策，AI 辅助解读。个人政策研究与自动化求职展示项目：Python 采集与分析，JSON 存储，Astro 静态前端，GitHub Actions 自动更新，GitHub Pages 发布。

**网站：[广东储能政策雷达](https://gwen8316-bit.github.io/guangdong-storage-policy-radar/)**

## 页面

- 首页：数据更新时间、4 项统计、9 个主题的可点击条形图、最近 10 条已完成解读的相关政策、关于本项目。
- 政策库：默认显示直接/间接相关政策，支持标题与摘要搜索，以及相关程度、主题、影响对象、发布机构、影响方向、日期范围筛选；待核查政策仍展示。
- 政策详情：官方原文、发文字号、来源栏目、AI 摘要/要点/证据、附件、最多 5 条同主题政策。

适配手机；白底深蓝，利好/利空/中性同时使用文字与颜色标识。所有内部路径包含 GitHub Pages 项目前缀。

## 信源：3 个机构、10 个栏目

| 机构 | 栏目 |
| --- | --- |
| [国家能源局](https://www.nea.gov.cn/policy/zxwj.htm) | 最新文件、通知、公告、解读 |
| [国家能源局南方监管局](https://nfj.nea.gov.cn/) | 通知公示、政策法规、政策解读 |
| [广东省发展改革委（含省能源局）](https://drc.gd.gov.cn/) | 业务通知、业务公告、省能源局通知公告 |

具体 URL 在 `config/sources.json`。先按规范化 URL 保留采集记录，再按规范化标题与明确发布日期相同进行政策合并；优先保留有完整解读的记录，详情列出全部来源链接。没有明确发布日期时不猜测合并。原始文件与断点保留，合并映射在 `data/policy-groups.json`。机构缺少明确元数据时，页面依据原文域名及省能源局标题标识来源，不能视为对联合发文单位的完整认定。

## 分类与 AI 方法

9 个主题：规划与发展目标、分时电价与峰谷价差、电力现货市场、辅助服务、容量补偿与容量电价、需求响应与虚拟电厂、新能源配储与并网、补贴与示范项目、安全管理与标准。

5 类对象：工商业用户侧储能、独立储能、电源侧配储、电网侧储能、储能产业链。

先以标题和正文关键词初筛，再由 DeepSeek 基于正文和已解析附件判断直接相关/间接相关/无关。v3 要求储能是条款实际对象或有明确的收益/发展空间作用路径；通用能源管理、国际合作、一般安全生产、节能审查和行业节能降碳，不能仅因出现储能字样而收录。主题和对象标签逐项保存原文依据。后续解读生成一句话摘要、3 条要点、主题、适用对象、影响方向与原文引句。引用、数字、标签做结构校验；这不能替代人工判断。每份政策可有多个主题。

前端只读取当前输入哈希匹配且已判断相关的记录；`待核查`政策不隐藏。解读尚未通过校验的相关政策仍可在政策库查看原文，摘要标为未完成、影响标为待判断，不展示未校验的模型内容。原文更新后失效的 AI 结果不会继续作为当前解读展示。

## 运行

环境：Python 3.12+、Node.js 22.12+（部署固定 22.23.3）。

```sh
python -m pip install -r requirements-collector.txt
npm ci
python -m unittest discover -s tests -v
npm test
npm run check
npm run dev
```

本地打开 `http://localhost:4321/guangdong-storage-policy-radar/`。

```sh
npm run build
node scripts/verify_site.mjs
npm run preview
```

构建产物在 `dist/`，读取 `data/`；`POLICY_DATA_DIR` 可指定独立快照目录。前端不调用 AI、不读取密钥。

本地采集与分析（AI 步骤需要安全设置 `DEEPSEEK_API_KEY` 环境变量）：

```sh
python -m collector --mode incremental --batch-size 100
python -m analysis                       # 仅关键词与索引，无 API 调用
python -m analysis --all --max-calls 50   # 相关性与解读共用 50 次上限
```

历史回填可用 `python -m collector --mode backfill --since 2025-10-01 --batch-size 100` 续跑。不要删除断点文件。附加说明：[采集模块](docs/collector.md)、[分析模块](docs/analysis.md)、[前端与自动发布](docs/frontend.md)、[已验收 AI 样例](docs/ai-samples.md)。

## 自动运行与 GitHub Pages

工作流 **Update and deploy policy radar** 每天 **北京时间 08:00（UTC 00:00）** 执行增量抓取 → 筛选与 AI 解读 → 验证/构建 → 部署。单次最多 50 次 API 请求（含相关性、解读、格式纠正及失败），仍受每月 50 元预占预算保护；额度用尽的条目留待下一次处理。GitHub 调度可能延迟，并非准点 SLA。

手动更新：仓库 **Actions → Update and deploy policy radar → Run workflow**，选择 `main`，保留 `update_data=true`。只重新部署已存数据时设为 `false`。前端代码推送到 main 也会构建和部署，不自动调用 AI。

仓库 **Settings → Pages → Source = GitHub Actions**；已配置。**Settings → Secrets and variables → Actions** 中需有 `DEEPSEEK_API_KEY`；已配置（密钥仅在运行时注入，不写入代码）。

更新在临时候选目录进行。抓取/解读失败则不部署；构建或部署失败保留上一线上版本。只有成功部署的数据才复制回 `data/` 并提交；预算账本即使失败也保留；成功的 AI 调用另外缓存在 `data/state/update-analysis-cache.json`，下次仅在输入哈希匹配时复用，避免失败重跑重复付费。失败候选快照在 Actions artifacts 中保留 7 天。所有写数据的工作流共用并发组，避免覆盖。

## 统计口径与局限

2026-09-29 完成本次去重与分类复核：356 条原始记录合并为 352 份政策，4 组重复均保留全部来源链接。原 75 条相关记录（73 份政策）重判后为直接相关 22 份、间接相关 12 份；原摘要、要点及影响判断保留。使用 29 次 DeepSeek 请求后达到既有月预算上限，剩余校验失败项由助手依据原文补齐，并对标签作语义复核；这不是人工验收。复核前后及引句见 `data/reclassification-v3.json`、`data/classification-review-v3.json`。本月剩余 AI 处理需等待预算周期恢复；不会自动突破预算。

- 收录政策总数＝去重后的政策数；储能相关政策数＝当前可展示的直接/间接相关文件数。近 30 天按政策发布日期（缺失则列表日期）统计，包含本次构建当天、排除未来日期，并非首次入库时间。
- AI 生成，以原文为准；部分解读尚待人工核查。征求意见稿不能视为已生效政策；影响方向不构成投资建议。
- 当前历史回填未完整：2026-09-29 核对有 109 个栏目条目未入库（国家能源局公告 4、广东省能源局通知公告 105）；自动增量不等于补齐历史。
- 图片不做 OCR；DOC、XLS、压缩包及部分附件需人工核读。关键词仅匹配标题/正文，可能漏掉仅附件相关的文件；过长输入会截断并标待核查。
- 站点保存的是最近成功版本；官方站点变化、robots、网络、模型/API 或预算限制可能使更新暂停。调度长时间无仓库活动时可能被 GitHub 停用，可在 Actions 检查并重新启用。
- `python scripts/validate_collection.py` 目前会因上述历史缺口返回非零；不将其冒充为整库验收通过。
