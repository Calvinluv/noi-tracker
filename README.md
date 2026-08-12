# 香港指数期货 NOI 每日追踪

自动抓取 etnet 經濟通的三大指数期货（HSI/HHI/HTI）未平仓净数（NOI），生成对比报告并推送微信。

## 运行机制

| 任务 | 时间 (HKT) | 对比逻辑 | 产出 |
|---|---|---|---|
| 🌙 早盘对比 | 工作日 08:30 | 今早 vs 昨晚 | `noi_morning_YYYYMMDD.html` |
| 🌇 晚间日报 | 工作日 21:35 | 今晚 vs 今早 | `noi_daily_YYYYMMDD.html` |

数据通过 git commit 回存仓库，HTML 报告通过 GitHub Pages 展示。

## 部署步骤

### 1. 创建 GitHub 仓库

```bash
# 初始化并推送
git init
git add .
git commit -m "init: NOI tracker"
git remote add origin https://github.com/<你的用户名>/noi-tracker.git
git branch -M main
git push -u origin main
```

### 2. 配置微信推送 Secret

进入仓库 **Settings → Secrets and variables → Actions → New repository secret**：

- Name: `SERVERCHAN_KEY`
- Value: 你的 Server酱 SendKey（如 `SCT394553T4v6ho8Nwab8gG1u9pQjpC6HK`）

### 3. 开启 GitHub Pages

进入仓库 **Settings → Pages**：
- Source: **Deploy from a branch**
- Branch: `main` / `docs` 目录
- 点击 Save

等待 1-2 分钟后，访问 `https://<你的用户名>.github.io/noi-tracker/` 即可查看最新报告。

### 4. 验证运行

进入仓库 **Actions** 页面：
- 选择 "NOI 晚间日报" workflow
- 点击 **Run workflow** 手动触发一次
- 查看运行日志确认无误

之后每个工作日 08:30 和 21:35 HKT 会自动运行。

## 项目结构

```
noi-tracker/
├── .github/workflows/
│   ├── noi_morning.yml      # 早盘 workflow (08:30 HKT)
│   └── noi_evening.yml       # 晚间 workflow (21:35 HKT)
├── scripts/
│   ├── noi_common.py         # 公共模块（抓取/解析/对比/HTML/推送）
│   ├── noi_morning.py        # 早盘入口
│   └── noi_evening.py        # 晚间入口
├── data/
│   ├── noi_history.json      # 昨晚数据（晚间任务写入）
│   └── noi_morning_latest.json  # 今早数据（早盘任务写入）
├── docs/                     # GitHub Pages 根目录
│   ├── index.html            # 最新报告入口（自动跳转）
│   └── noi_daily_*.html      # 历史报告
├── requirements.txt
└── README.md
```

## 时区说明

GitHub Actions cron 使用 UTC。HKT = UTC+8。
- 早盘 08:30 HKT → cron `30 0 * * 1-5` (UTC 00:30)
- 晚间 21:35 HKT → cron `35 13 * * 1-5` (UTC 13:35)

> ⚠️ GitHub Actions cron 可能延迟 5-15 分钟，可接受。

## 移仓换月

脚本自动从 etnet 首页识别当前即月合约月份。当即月合约到期后，自动切换到下月+下下月合约，不会拿不同月份的数据做对比。

## 异常波动预警

当品种合计 NOI 变化超过 ±3% 时：
1. 自动抓取对应现货指数成交额
2. 判断阳线/阴线 + 是否放量
3. 给出市场解读
4. 额外推送一条微信预警
