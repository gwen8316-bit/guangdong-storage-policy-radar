# 前端与自动发布

## 本次恢复核对

2026-09-29 恢复时 Git 工作区干净，没有 package.json、Astro 配置或 src 页面；已提交的是采集、分析和 356 份原始记录。90 份关键词命中记录已判断相关性：42 份直接相关、33 份间接相关、15 份无关。随后新增的数据层与页面在本次完整需求基础上继续修改，未覆盖原始数据。

最终只有首页、政策库和政策详情三种页面；移除了未按需求添加的采集状态页。保留已建立的哈希校验、筛选逻辑、详情及证据展示。

## 结构

2026-10-03 新增市场看板第 1 步：`src/pages/market/index.astro` 和 `src/lib/market.ts` 读取独立 `data/market/lithium-carbonate.json`。三指标卡、三趋势区中仅碳酸锂有真实日线，其余保留“数据待录入”；导航新增入口。使用 SVG 静态绘图及可展开的最近交易日表，手机布局单列。`market` Python 模块通过 AKShare 抓取 LC0，既有每日工作流独立更新市场候选；`scripts/prepare_publish.py` 组合成功快照，失败项保留旧数据。

跨网址去重由 `collector/dedup.py` 分组，在日常 `python -m analysis` 的分析前后重建映射。`src/lib/data.ts` 只展示保留记录，汇总全部来源机构与栏目；详情列出每个原网址及对应栏目。原始文件、相关性判断和解读均不改写。统计卡片、主题分布、列表和推荐统一使用去重后的政策。首页动态仍沿用原有规则，本次未增加解读状态筛选。

- `src/lib/data.ts`：构建时读取 JSON，核对输入哈希，日期口径与发布机构显示。
- `src/lib/filter.ts`：浏览器端组合筛选；仅搜索标题与摘要。
- `src/components/PolicyCard.astro`：首页与政策库共用卡片。
- `src/pages/index.astro`：统计、主题分布、10 条动态、关于项目。
- `src/pages/policies/index.astro`：筛选、搜索、排序、分页（每页 12 条）、URL 参数恢复。
- `src/pages/policies/[id].astro`：静态详情、核查提示、引用、附件、相关推荐。
- `scripts/update_site.py`：临时候选数据更新，50 次调用上限，失败时保留原始数据与支出账本。
- `.github/workflows/update-site.yml`：每天 UTC 00:00 更新、构建、部署；仅成功部署后保存候选数据。

## 验证

`npm test` 覆盖真实 JSON 关联、过期/缺失/无关解读隔离、组合筛选、日期范围与 URL 安全。
`python -m unittest discover -s tests -v` 包含原采集/分析测试、失败候选隔离和调用限额验证。
`npm run check` 检查 Astro/TypeScript；`npm run build` 生成完整静态站点。
`node scripts/verify_site.mjs` 检查内部路径和资源链接、9 个主题、AI 提示、状态页不存在。

## 已知剩余数据工作

历史回填缺口 109 个栏目条目；2 份正文抓取失败、1 个附件失败，另有部分图片/附件需人工核查。这些是既有数据问题，见 `reports/collection-validation.json`（本地生成，不提交）。本次聚焦三个页面、自动增量与上线，未将数据问题隐藏或伪造为抓取成功。

## 官方部署参考

[Astro GitHub Pages 部署与 base 路径](https://v6.docs.astro.build/en/guides/deploy/github/)；[GitHub Pages 自定义 Actions 工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。
