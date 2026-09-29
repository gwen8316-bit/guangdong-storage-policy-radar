# 关键词筛选与三个 AI 样例

运行 `python -m analysis` 仅更新全库关键词索引，不调用 API；
`python -m analysis --sample` 只处理 config/analysis.json 指定的三份政策；`python -m analysis --all` 处理全部关键词命中政策。
安装环境：`python -m pip install -r requirements-collector.txt`。
验证：`python -m unittest discover -s tests -p test_analysis.py -v`。

## 密钥与 Actions

1. 在 https://platform.deepseek.com/api_keys 登录、创建 API key，并确认账户有可用余额。
2. 仓库 Settings → Secrets and variables → Actions → New repository secret，名称 DEEPSEEK_API_KEY。
3. Actions → Analyze policies → Run workflow → scope 选择 all（全量）或 sample（三份样例）。无需将密钥写入代码或聊天。
4. 结果自动保存并提交 data/analysis/<政策ID>.json；无关文件保留政策原始记录。
   本地运行需事先通过安全方式设置 DEEPSEEK_API_KEY 环境变量。

## 数据与限制

- data/analysis-index.json：关键词、相关性、状态、visible；无关和未完成的记录不展示。
- data/analysis/<ID>.json：原文链接、输入哈希、相关性及理由、summary/key_points/topics/targets/impact，
  impact 含 direction/reason；evidence 为对应三条要点的原文引句。统一标注“AI 生成，以原文为准”。
- 相关性发送标题、正文前 2000 字和全部附件解析文本合并后的前 2000 字。明确涉及储能考核、补偿、价格、准入或规划的条款判直接相关。解读发送正文与已解析附件，最多 12000 字；
  超限截取、正文不全或附件不完整均标“待核查”。这会漏掉仅附件里出现关键词的政策，遵循本版标题/正文规则。
- 要点优先具体规定与要求，不写背景形势；对象只含明确适用范围，不含参照执行；主题最多三项，按相关程度排序。
- 成功相关性判断立即缓存，成功解读不重复请求；内容、附件或规则版本改变会使结果失效（本次为 2026-09-29-v2）。
  解读字段/引用校验失败最多纠正一次；API 失败不自动重试，保留错误供人工查看。
- 每次最多 300 次调用；每次请求前在 data/state/ai-budget.json 预占 0.2 元，每月最多预占 50 元。
  这是保守限额，不是实际账单；失败和中断也计入，实际 token usage 单独保存。
  按 2026-09-29 官方 Flash 峰时价（输入 $0.3/百万 token，输出 $1.2/百万 token），输入不超过 50000 UTF-8 字节、输出不超过1600 token，以保守换算10元/美元计算，单次上界约0.17元，预占0.2元；历史样例的每次1元预占不下调。不管理其他应用共用密钥的支出。
  改模型或价格变化后需复核预占额。官方定价：https://api-docs.deepseek.com/quick_start/pricing/。
- 结构、标签、数字存在性和引句校验不能证明语义完全准确；样例已获用户验收，本版按新规则重新生成样例并开放批量处理。
- 两个工作流共享 concurrency 组，避免采集和解读同时写仓库；无定时任务、无前端。

样例分别为国家能源局《新型储能电站建设工程质量监督大纲》政策解读、
南方区域“两个细则”部分条款修订征求意见、广东省新型储能电站建设运行管理办法。
南方样例的正文主要为附件链接，解读会纳入两份已经解析的 PDF。

## 统计口径

`data/analysis-summary.json` 保存相关性数量、待核查数量和各主题数量；待核查可与三种相关性重叠，主题也可多选。`data/analysis-last-run.json` 记录当次实际请求次数（含失败/格式纠正，不含缓存跳过），月度历史详见预算账本。
