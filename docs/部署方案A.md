# 方案 A 部署手册：GitHub Actions 定时 + GitHub Pages 前端托管（全部免费）

> 不用 Vercel、不用服务器——GitHub 一家搞定：定时跑管线、托管前端、自动更新数据。

## 架构

```
GitHub 仓库（公开，代码 + 前端 + 定时任务）
│
├── GitHub Actions（每周一 09:15 北京时间自动跑）
│     爬虫 → 汇总 → AI分析(glm-4-flash 免费) → 坐标补全(高德+讯飞搜索)
│     → 入库 TiDB → 导出 dashboard_data.json → commit 回仓库 → 周报邮件
│
├── GitHub Pages（托管 frontend/ 目录）
│     检测到新 commit → 自动重新部署 → https://<你的账号>.github.io/<仓库名>/
│
└── 浏览器访问：大屏每 5 分钟自动轮询刷新数据（前端已有此功能）
```

**为什么仓库必须公开**：GitHub Pages 免费版只能发布公开仓库（私有仓库需要付费套餐）。所以：
- ✅ 代码公开（爬虫/AI 逻辑无机密）
- ✅ **所有密钥已从代码移走**（settings.py 已清空默认值）→ 走 GitHub Secrets
- ⚠️ 本地 `.env` 已配置（已加入 .gitignore，不会被推送）

---

## 步骤一：创建 GitHub 仓库并推送代码

1. 打开 https://github.com/new ，创建仓库（如 `yantai-warning-platform`），**选择 Public**
2. 本地推代码：

```bash
cd d:\googledownload\wangluobu_vscode
git init
git add .
git status                # 确认 .env、venv、data/ 都没被加入（.gitignore 已配置）
git commit -m "init: 烟台工程预警平台（爬虫+AI+TiDB+前端）"
git branch -M main
git remote add origin https://github.com/<你的账号>/yantai-warning-platform.git
git push -u origin main
```

推送后到仓库页面确认：`.env` **没有**出现（有的话说明 .gitignore 失效，立即删除）。

## 步骤二：配置 GitHub Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| Secret 名称 | 值（来自你本地的 .env） |
|---|---|
| `TIDB_DATABASE_URL` | `mysql+pymysql://6F3sTxjda5A6hpJ.root:密码@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/yantai_projects?charset=utf8mb4&ssl_ca=config/tidb_ca.pem` |
| `ZHIPU_API_KEY` | 智谱 API Key（glm-4-flash 免费模型） |
| `XFYUN_API_KEY` | 讯飞星火 APIKey（坐标搜索补全） |
| `XFYUN_API_SECRET` | 讯飞星火 APISecret |
| `EMAIL_PASSWORD` | QQ 邮箱授权码（**可选**，不配则跳过周报邮件） |

> `TIDB_DATABASE_URL` 注意 `ssl_ca=config/tidb_ca.pem` 用**相对路径**（Actions 工作目录=仓库根，CA 证书已入库，非机密）。

## 步骤三：启用 GitHub Pages

仓库 → **Settings → Pages**：
- Source: **Deploy from a branch**
- Branch: `main`，文件夹：**`/frontend`**
- 保存。首次部署约 1 分钟。

## 步骤四：手动触发一次验证

仓库 → **Actions** → 左侧 "每周自动化管线" → **Run workflow**。

观察执行日志（约 1.5 小时，含爬虫 + 47 条 AI 分析限流等待）：
- ✅ 各步骤绿色
- 📊 最后"提交导出数据"提交了 `frontend/data/dashboard_data.json`
- 📧 周报邮件（若配置了 EMAIL_PASSWORD）

## 步骤五：访问

部署完成后访问 `https://<你的账号>.github.io/<仓库名>/`。

以后每周一 09:15 自动跑：数据入库 → JSON 更新 → Pages 自动重新部署 → 你打开页面就是最新数据（页面本身也会每 5 分钟自动检测刷新）。

---

## 常见问题

**Q: Actions 免费额度够吗？**
- 公开仓库 Actions **完全免费**，无时长限制。
- 每次运行约 1.5 小时，每周一次。

**Q: 想在别的时间跑？**
- 改 `.github/workflows/weekly_pipeline.yml` 里的 `cron`（UTC 时间，北京=UTC+8）。改完推上去即生效。

**Q: 想手动立刻跑一次？**
- 仓库 Actions 页 → 每周自动化管线 → Run workflow（`workflow_dispatch` 已启用）。

**Q: Pages 页面打不开 / 白屏？**
- 检查 Settings → Pages 是否显示部署成功（绿色 ✓）。
- 前端数据加载失败会显示空面板（不造假数据），属正常现象；确认 `https://<账号>.github.io/<仓库>/data/dashboard_data.json` 能直接打开（有 JSON）。

**Q: 代码里还有泄露的密钥吗？**
- `config/settings.py` 中 TiDB 密码、智谱 key、讯飞 key、邮箱授权码默认值均已清空，改由 `.env`（本地）和 GitHub Secrets（线上）提供。
- 仓库公开后可用 `grep -r "QoyA8\|22d8da\|lnhnfod" .` 自查。

**Q: 周报邮件在线上发不出去？**
- 确认 `EMAIL_PASSWORD` Secret 已配置为 QQ 邮箱授权码；未配置则 Actions 日志显示"跳过发送"，不影响数据流程。

**Q: 本地还能正常跑吗？**
- 能。本地 `.env` 已含全部密钥，`settings.py` 自动加载（`python-dotenv`）。
- 验证：`venv\Scripts\python -c "from config.settings import TIDB_DATABASE_URL; print(bool(TIDB_DATABASE_URL))"` 输出 `True`。
