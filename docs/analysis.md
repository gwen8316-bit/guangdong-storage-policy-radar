# 关键词筛选与三个 AI 样例

本阶段不运行全量 AI。运行 `python -m analysis` 仅更新全库关键词索引，不调用 API；
`python -m analysis --sample` 只处理 config/analysis.json 指定的三份政策。
安装环境：`python -m pip install -r requirements-collector.txt`。
验证：`python -m unittest discover -s tests -p test_analysis.py -v`。

## 密钥与 Actions

1. 在 https://platform.deepseek.com/api_keys 登录、创建 API key，并确认账户有可用余额。
2. 仓库 Settings → Secrets and variables → Actions → New repository secret，名称 DEEPSEEK_API_KEY。
3. Actions → Analyze three policy samples → Run workflow。无需将密钥写入代码或聊天。
4. 结果自动保存并提交 data/analysis/<政策ID>.json；无关文件保留政策原始记录。
   本地运行需事先通过安全方式设置 DEEPSEEK_API_KEY 环境变量。

## 数据与限制

- data/analysis-index.json：关键词、相关性、状态、visible；无关和未完成的记录不展示。
- data/analysis/<ID>.json：原文链接、输入哈希、相关性及理由、summary/key_points/topics/targets/impact，
  impact 含 direction/reason；evidence 为对应三条要点的原文引句。统一标注“AI 生成，以原文为准”。
- 相关性只发送标题和正文前 2000 字。解读发送正文与已解析附件，最多 12000 字；
  超限截取、正文不全或附件不完整均标“待核查”。这会漏掉仅附件里出现关键词的政策，遵循本版标题/正文规则。
  正文很短且主要内容在附件时，也标“待核查”，提醒相关性判断尚未读取附件。
- 成功相关性判断立即缓存，成功解读不重复请求；内容或附件哈希改变会使结果失效。
  格式错误、引用校验失败和 API 失败不自动重试，保留错误供人工查看。
- 每次最多 6 次调用；每次请求前在 data/state/ai-budget.json 预占 1 元，每月最多预占 50 元。
  这是保守限额，不是实际账单；失败和中断也计入，实际 token usage 单独保存。
  当前 Flash 官方峰时价格和输入/输出上限下预占额高于单次成本；不管理其他应用共用密钥的支出。
  改模型或价格变化后需复核预占额。官方定价：https://api-docs.deepseek.com/quick_start/pricing/。
- 结构、标签、数字存在性和引句校验不能证明语义完全准确；三个样例须由研究员验收后再开放批量处理。
- 两个工作流共享 concurrency 组，避免采集和解读同时写仓库；无定时任务、无前端。

样例分别为国家能源局《新型储能电站建设工程质量监督大纲》政策解读、
南方区域“两个细则”部分条款修订征求意见、广东省新型储能电站建设运行管理办法。
南方样例的正文主要为附件链接，解读会纳入两份已经解析的 PDF。
