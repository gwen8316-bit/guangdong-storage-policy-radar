# 政策抓取模块（第二步）

本模块范围：发现、详情、附件、去重、存储和运行记录。相关性筛选与 AI 由 analysis 模块负责；Astro 网站和定时工作流见 frontend.md。因此行政许可、项目名单等也可能出现在原始采集库；后续筛选层决定研究库收录范围。

## 运行

Python 3.12+，在仓库根目录执行：

```powershell
python -m pip install -r requirements-collector.txt
python -m unittest discover -s tests -v
python -m collector --mode backfill --since 2025-10-01 --batch-size 100
```

再次执行同一个回填命令即可续跑；`--batch-size 0` 处理全部待处理详情。每个页面的发现进度、每份已保存文件的处理进度都原子写入 JSON。程序被中断时，已经保存的内容仍然保留。不要删除 `data/state/backfill.json`，否则会重新发现列表。

```powershell
python -m collector --mode incremental --batch-size 0
python scripts/validate_collection.py
```

本机若 `python` 不在 PATH，可使用已验证的自带解释器：

```powershell
$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m collector --mode backfill --since 2025-10-01 --batch-size 100
```

其他参数：

- `--columns nea_latest,gd_notices`：仅选择这些栏目。
- `--config config/sources.json`：指定信源配置。
- `--data-dir data`：指定独立数据目录；验收故障注入使用独立目录。
- `--discover-only`：只发现链接和保存回填进度。
- `--workers 3`：线程数，所有线程仍共享每域名至少三秒的请求间隔。
- `--recheck-days 7 --recheck-limit 20`：增量运行额外轮换复查较旧文件，发现首页以下的正文或附件变化。

增量运行先检查列表头部，遇到连续十条已成功保存且已属于该栏目的文件后停止翻页。普通 HTML 列表会完成当前页；国家能源局一次返回 JSON 列表，按日期排列后在已知条目阈值处停止处理。未完成的增量任务保存在 `incremental-pending.json`，下次继续。

## Actions

在 GitHub 的 **Actions → Collect policy documents → Run workflow** 中选择：

- `mode`：`incremental` 或 `backfill`。
- `batch_size`：默认 100，0 表示处理全部待处理文件。
- `since`：默认 `2025-10-01`；已有回填检查点时不能直接换成其他日期。

此独立采集工作流只有 `workflow_dispatch`，没有 `schedule`；每天 08:00 的更新由 Update and deploy policy radar 工作流统一调度。同一时间最多一个采集工作流运行。完成或异常退出后，尽可能提交 `data/` 中已保存的数据和检查点，并上传日志、摘要。若遇到推送冲突，工作流会失败并保留可下载报告，不覆盖远端历史。

本地与 Actions 不应同时采集后推送同一仓库；本地数据目录另有操作系统文件锁，防止同目录的两个进程同时写入。

## 数据目录

```text
data/
  policies/<sha256-of-normalized-url>.json
  index.json
  state/backfill.json
  state/incremental-pending.json
  status/columns.json
  status/latest-run.json
  runs/<run-id>.json
  logs/<run-id>.jsonl
```

每条政策独立存储，`index.json` 是精简索引。文件写入使用同目录临时文件和原子替换。请求日志不含认证信息；原始附件只存在于内存或系统临时目录中，解析后清除。

## 政策 JSON，schema_version = 1

| 字段 | 类型 / 含义 |
|---|---|
| `id` | 规范化 URL 的完整 SHA-256，稳定唯一 |
| `url` / `final_url` | 主键 URL / 实际请求最终 URL |
| `title` | 详情标题，缺少详情标题时保留列表标题 |
| `doc_number` / `issuer` | 发文字号 / 发文机关；缺乏明确依据时 null |
| `source_id` / `column_id` | 首次归属，作为兼容性主字段 |
| `source_ids` / `column_ids` | 全部归属 ID 数组 |
| `columns` | 全部栏目来源，含 source_id、column_id、list_url、list_date、list_date_raw、list_title |
| `list_date` | 主来源的列表日期；其他栏目的列表日期保存在 columns |
| `publish_date` / `written_date` | 发布日期 / 成文日期；ISO 日期或 null |
| `date_metadata` | 原始日期元数据，供核查，不能直接等同发布日期 |
| `field_evidence` | 日期、文号、发文机关的原文依据或选择器 |
| `content_text` | 正文纯文本，保留段落和表格内容 |
| `content_status` | complete / image_only / partial / failed，描述页面正文，不表示附件全部解析成功 |
| `body_selector` | 实际正文提取位置 |
| `attachments` | 附件及正文图片列表 |
| `first_seen_at` / `last_checked_at` | UTC 首次抓取时间 / 最近详情检查时间 |
| `content_hash` | 正文纯文本的 SHA-256 |
| `attachments_hash` | 附件 URL、原件哈希、解析状态、文本构成的摘要 |
| `versions` | 变更时间、旧正文哈希、旧附件摘要；不保存旧原件 |
| `last_fetch_error` / `collection_issues` | 最近抓取问题；成功旧正文不因一次失败被清空 |

标题、日期等元数据补全不算正文变化。正文或附件解析内容变化会记录版本。正常复查仅更新 `last_checked_at`，不会制造内容版本。

`content_status`：正文区域识别成功且有可提取文字时为 complete；主体只有图片为 image_only；正文混有需核读图片或仅有简短内容为 partial；无法获取或无法识别正文为 failed。纯文本完整性是结构检查，不能证明附件或图表内容已全部转换为文字。

附件对象包含：

```text
name, url, final_url, format, kind, size_bytes, sha256,
status, needs_manual_review, text, error, content_type
```

`kind` 为 attachment 或 inline_image。`status` 为 parsed、partial、needs_manual_review、failed。PDF 额外记录页数；识别到不符扩展名的二进制容器时记录 detected_format。无法成功下载时大小和校验值可以为 null，并保留具体错误。

- PDF 保留页码；混合扫描页标记 partial，纯扫描页标记 needs_manual_review。
- DOCX 提取段落和表格，图片不做 OCR。
- XLSX 按工作表和行提取，公式保留公式文本，不在后台计算。
- DOC、XLS、图片、压缩包等仅保留原件信息和校验值，需人工核读。
- 单响应上限 80 MiB；单附件解析限时 90 秒；PDF 最多 600 页；Office 展开体积最多 300 MiB、XLSX 最多 200 万单元格。触及限制会明确标记，不能当作完整提取。

## 发现和合规

国家能源局从网页实际 datasource 节点定位公开 JSON；南方监管局按其零基页码翻页；广东省发改委读取页面真实“下一页”链接。每页保留全部满足回溯日期的条目，避免置顶旧文导致提前停止。整页均早于起点才停止 HTML 翻页。

广东意见征集互动页从页面公开的 `question_data.article` JSON 中读取正文和明确的 published_at，再使用页面脚本公开调用的附件元信息/下载接口。只执行 GET，不登录、不提交意见、不调用统计写入接口。

部分附件扩展名与实际容器不符，或链接返回 HTML：保留原始链接和校验值，明确标记需人工核读。少数 XLSX 的富文本样式不被 openpyxl 接受时，会从有效的工作表 XML 中提取原始单元格值并标记 partial，避免把样式兼容问题当成整份文件没有内容。

请求包含项目名和仓库地址，每个域名请求起始间隔至少三秒，超时 30 秒，瞬时网络错误、408、429、5xx 最多重试三次（总计四次），指数退避并尊重 Retry-After。404、403 等明确拒绝不反复请求。

每次运行首次访问域名时检查 robots，长任务每 30 分钟刷新；404/410 视为无规则，403、获取失败、异常 HTML 和未处理的 robots 重定向均停止对应路径。页面重定向后的目标也重新检查 robots。[Protego](https://github.com/scrapy/protego) 处理通配符、Allow 优先级和 Crawl-delay。遇到禁止不绕过。

## 摘要与健康状态

每次运行记录开始/结束时间，每栏目记录 discovered、checked、new、updated、unchanged、failed、errors、pending_this_run、backfill_remaining。全局 new/updated 按唯一文件计数；栏目计数按归属计数，所以栏目数之和可能大于唯一文件数。

附件失败的文件仍会保存，且其栏目 failed 加一；errors 列出每个附件错误。needs_manual_review 是受支持的降级结果，不是网络失败。`status/columns.json` 保存 last_success_at、consecutive_failures 和最近原因；尚有待处理批次时为 pending，实际错误为 degraded。

进程硬中断时运行摘要可能只有 started_at、没有 ended_at；这表示未完成运行，应续跑，不应当成成功。首次回填完成后仍应看是否存在 failed 或 collection_issues，不能仅以发现链接数判断回填质量。

## 测试

`tests/fixtures/manifest.json` 记录真实网页样本来源与抓取时间。国家能源局 JSON 测试用预检时取得的真实条目摘录；字段裁剪在样本中注明。测试覆盖列表、分页、置顶、日期、正文、附件链接、去重、版本、失败保护、robots 和断点续跑。

`scripts/validate_collection.py` 检查主键、去重、哈希、日期依据、栏目覆盖和疑似导航文字；以固定随机种子 20260929 抽十条供人工核对，不把自动校验当成人工原文核查。
