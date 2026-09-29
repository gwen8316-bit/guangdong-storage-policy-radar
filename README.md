# 广东储能政策雷达

当前包含网络预检和政策抓取模块（发现、正文、附件、去重、JSON、日志），不包含相关性筛选、AI 或前端。

正式采集的运行方法、数据结构、增量/回填规则和已知限制见 [抓取模块说明](docs/collector.md)。

```powershell
python -m pip install -r requirements-collector.txt
python -m unittest discover -s tests -v
python -m collector --mode backfill --since 2025-10-01 --batch-size 100
python -m collector --mode incremental --batch-size 0
python scripts/validate_collection.py
```

回填可重复执行以续跑；GitHub 的 **Collect policy documents** 工作流支持手动选择模式。尚未开启定时运行。

下方保留第一步网络预检的运行说明。

本地与 GitHub Actions 各三轮测试已完成，见 [2026-09-29 验证报告](docs/connectivity-report-2026-09-29.md)。

## 本地运行

需要 Python 3.12 或更高版本。已在 `config/connectivity-sources.json` 配置三个信源的十个栏目。

```powershell
python -m pip install -r requirements-connectivity.txt
python scripts/check_connectivity.py --attempts 3
```

报告写入 `reports/connectivity.json`。该目录不提交 Git。

## GitHub Actions

将文件提交到 GitHub 仓库默认分支，在 Actions 中选择 `Source connectivity check`，
点击 Run workflow，选择轮数（默认三轮）。使用与本地相同的栏目配置。
运行完成后下载 `connectivity-report`。此工作流仅手动运行，不写仓库。

## 如何判断

- 每个网址默认请求三轮，每轮先检查 robots；请求起始时间至少间隔三秒。
- 报告包含 robots 和列表页各自的状态码、响应耗时、错误及文本片段。
- 耗时包括连接与响应体读取，不包括限速等待；单次请求超时为 30 秒。
- HTTP 200 不能直接视为成功；必须人工核对文本片段是否有目标栏目的政策标题、日期等内容。
- `list_content_candidate` 仅是可读文本和链接的启发式判断；以 `list_fields_ok`、`list_sample` 及人工核对为准。
- 每个栏目抽取一个详情页，另行检查 robots，记录正文片段及提取位置。附件不在本次测试范围内。
- 国家能源局的列表通过网页脚本引用的相邻 `ds_*.json` 提供；报告单独记录该请求。
- robots 禁止或无法可靠获取时跳过列表页；重定向记录目标但不自动跟随，避免绕过目标 robots 检查。
- 默认三轮只说明短时表现。应在不同时间手动重复运行，才能评价稳定性。
- 工作流成功仅表示报告已生成，不表示所有信源可访问。

报告不保存原始网页或附件，只保存必要的核查片段。短时测试成功不等于长期稳定。
