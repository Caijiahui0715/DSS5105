# 人工排序表 V7（中文）

由 `evaluation/form_v7.py` 生成。题目和 V6 相同（15 题），候选来源分两类：

| 类别 | 题目 | 候选来源 | 用来检验 |
|---|---|---|---|
| 标准答案抽样 | A01、A08、A09、B01、G04 | `human_ranking/key.csv`（标准答案前 3 名 + 剩余最便宜的 1 个 + 随机 1 个） | 我们的排序规则和人的判断是否一致 |
| agent 前 3 名 | 其余 10 题 | `source/agent_profile20_20261105T032944Z.jsonl` 每题最后一轮 | agent 排出的顺序是否合理 |

分析时两类分开报告。V6 里这 5 题各有一个候选已下架（A08、A09、B01、G04）或按最新租金超预算（A01），所以换掉。52 个候选全部在冻结数据里，并且在标准答案里都是 confirmed。

所有房源信息来自 2026-11-02 冻结数据；通勤是到 NUS 商学院（公共交通，工作日 08:30）。

## 怎么建表单

1. 把 `images/` 里的 15 张 PNG 上传到 Google Drive 的同一个文件夹（不用上传 .html）。
2. 打开 <https://script.google.com>，新建项目，把 `build_form.gs` 的内容全部粘贴进去，替换掉默认代码。
3. 把第一行的 `FOLDER_ID` 换成那个文件夹的 ID（文件夹网址里 `/folders/` 后面那一串）。
4. 函数选 `buildForm`，点"运行"，按提示授权（只需要 Forms 和 Drive 权限）。
5. 运行完，在"执行日志"里能看到表单的编辑链接和填写链接。

每运行一次就新建一个表单。建好后在表单编辑页检查一遍，再发出去。

## 表单结构

- 第 1 页：说明 + 评审编号（必填）。
- 之后每题一页：用户需求（中文，附英文原文；G 类写两轮）、对比图、排名网格（行是候选，列是名次，每列只能选一个）、"这题无法判断"勾选、选填说明。

## 答案表 `key.csv`（不要给评审看）

| 列 | 含义 |
|---|---|
| Candidate source | `gold_sample` 或 `agent_top3` |
| Sampling source | 标准答案抽样时的来源：`gold_top3` / `cheapest_remaining` / `random_confirmed` |
| Agent rank | agent 给这个候选的名次（只有 agent 题有） |
| Gold rank among confirmed | 在标准答案全部 confirmed 里的名次 |
| Gold order of these candidates | 只看本题这几个候选，标准答案的顺序 |

导出表单回答后，每题用评审的名次和 `Gold order of these candidates`（以及 agent 题的 `Agent rank`）算 Kendall τ 或 Spearman 相关即可。
