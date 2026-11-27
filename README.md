# Amazon.fr 竞品价格监控系统

这个项目用于每天监控 Amazon.fr 上 Tentoki 及竞品的手机配件价格，并把结果发布成一个 GitHub Pages 看板。

其他独立运营项目：[手机壳选品助手](手机壳选品助手/README.md)（本机HTML、手动运行）。其资料、研究证据和报告在独立子目录管理。

## 当前监控范围

- 网站：Amazon.fr
- 品牌：Tentoki、TOCOL、NEW'C、JETech；Tauri、Torras、ivoler 已预留占位，补上 ASIN 后即可启用
- 重点型号：iPhone 13、iPhone 15、iPhone 17、iPhone 17 Pro、iPhone 17 Pro Max
- 品类：Verre Trempé、Films et protections d'écran pour téléphones portables、Coque、Coques et housses standards pour téléphones portables

## 文件说明

- `daily_price_refresh.py`：Python + Playwright 爬虫主程序
- `price_history_manager.py`：合并最新数据和历史数据
- `product_list.json`：监控商品 URL 清单
- `price_dashboard.html`：可视化看板，GitHub Pages 会把它作为首页发布
- `.github/workflows/daily_price_refresh.yml`：每天 UTC 02:20 自动运行，也支持手动运行
- `price_results_latest.json`：最新一次抓取结果，首次运行后生成
- `price_history.json`：历史价格记录，首次运行后生成

GitHub Actions 每次运行都会重新读取 `main` 分支上的最新 `product_list.json`，当前频率是每天一次，已经覆盖“每周读取清单”的需求。网页“原始数据登记表”中保存的浏览器草稿不会自动写回 GitHub；新增 ASIN 后需要下载 `product_list.json` 并提交到仓库，下一次每日任务就会自动使用新清单。

## 本地运行

先安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

测试配置，不真正抓取：

```bash
python daily_price_refresh.py --dry-run --allow-empty
```

正式抓取：

```bash
python daily_price_refresh.py
```

如果要抓取和法国前台一致的本地价，建议用持久浏览器资料夹，并在第一次打开时确认配送地址为 `75001`、语言为法语：

```bash
python daily_price_refresh.py --headful --user-data-dir .amazon-fr-profile --postcode 75001 --limit 1
```

第一次运行时如果 Amazon 没有自动切到 `75001`，在打开的浏览器里手动把配送地址改为 `75001`。后续运行复用同一个资料夹：

```bash
python daily_price_refresh.py --user-data-dir .amazon-fr-profile --postcode 75001
```

如果本机已有 Chromium/紫鸟浏览器开放了 DevTools 调试端口，并且前台地址已经是 `75001`，可以直接复用这个真实前台会话抓价。例子：

```bash
python daily_price_refresh.py --cdp-endpoint http://127.0.0.1:51679 --skip-location
```

这个方式更适合抽查价格是否和前台一致，因为它直接读取当前浏览器会话里的 Amazon.fr 页面状态。

打开本地看板：

```bash
python3 -m http.server 8080
```

浏览器访问：

```text
http://localhost:8080/price_dashboard.html
```

## 添加或修改监控商品

编辑 `product_list.json`。最简单的做法是复制一个现有商品块，改这几个字段：

```json
{
  "id": "B0XXXXXXXX",
  "asin": "B0XXXXXXXX",
  "url": "https://www.amazon.fr/dp/B0XXXXXXXX",
  "brand": "Torras",
  "category": "Coque",
  "model": "iPhone 17 Pro Max",
  "name": "Torras iPhone 17 Pro Max coque",
  "enabled": true
}
```

如果只是先占位，把 `enabled` 设为 `false`，脚本会跳过。

## 从 WPS 产品清单同步

项目内的 `wps_airscript_product_export.js` 用于读取 WPS 在线表格“TVL备货表格-20240914”中的“产品清单”工作表。脚本按表头名称识别字段：产品状态为“新品”或“正常在售”的记录写入 `products` 并按 ASIN 去重；其他状态写入 `non_active_products`，只显示在看板“非在售产品”页面，不参与 Amazon 抓价。

在 WPS 中创建脚本：

1. 打开“产品清单”工作表。
2. 打开“效率”或“脚本”入口，选择 AirScript / JS 脚本并新建文档共享脚本。
3. 把 `wps_airscript_product_export.js` 的完整内容粘贴进去。
4. 直接运行一次，确认返回结果包含 `products` 和 `stats`。
5. 在脚本菜单复制 Webhook 链接。

不要把 Script-Token 写进脚本。Webhook 创建后，在 GitHub 仓库 `Settings > Secrets and variables > Actions` 中保存 Webhook 和有效 Token，再由 GitHub Actions 每周调用脚本并更新 `product_list.json`。

GitHub Secrets 使用以下名称：

- `WPS_SCRIPT_WEBHOOK`
- `WPS_AIRSCRIPT_TOKEN`

TVL、SZTY 和 ASB 的 WPS 同步共用同一个个人 AirScript Token，三个工作流都只读取
`WPS_AIRSCRIPT_TOKEN`。各账号的 webhook 仍保持独立，避免同步到错误的产品清单。三个同步任务
也共用同一并发组，多个任务同时触发时会排队执行；任务开始时会重新检出最新 `main`，避免
排队期间产品清单更新后发生自动提交冲突。

工作流 `.github/workflows/weekly_wps_product_sync.yml` 每周一 UTC 01:30（北京时间 09:30）同步一次，比每日 UTC 02:20 的价格抓取提前 50 分钟。也可以在 GitHub Actions 中手动运行 `Weekly WPS Product List Sync`。

## 爬虫策略

- 每个商品请求之间随机等待 1-3 秒
- 使用固定 User-Agent
- 每次抓取前读取 Amazon.fr `robots.txt`，不允许访问的 URL 会跳过
- 当前售价依次尝试 JSON-LD、Amazon 核心价格区域 DOM、页面内嵌 JSON；命中后记录 `price_source`
- `msrp_price` 是“参考价候选值”，依次尝试 JSON-LD 的 `highPrice` / `priceSpecification.price`、DOM 的 `basisPrice`、页面内嵌 JSON 所有命中价格中的最大值；命中后记录 `msrp_source`
- 评分和评论数优先读取 JSON-LD `aggregateRating`，缺失时使用页面元素兜底
- 保存 Amazon 展示的近 30 天销量标签原文；页面没有标签时字段为空，不推算销量
- 检测到 Clearance / Déstockage / Soldes 等清仓词时，不把页面中间态 ticket 价当作 MSRP；如历史中已有 MSRP，会继承历史 MSRP

折扣仅在当前售价和 MSRP 都有效且 `MSRP > 当前售价` 时计算：

```text
discount_percent = (MSRP - 当前售价) / MSRP * 100
```

需要特别注意：当前 `msrp_price` 不等于“买家前台一定可见的划线价”。Amazon 页面可能在隐藏的 `.a-offscreen` 节点、未选中的变体或内嵌数据中保留参考价格；DOM 兜底读取第一个匹配节点，内嵌 JSON 兜底会取页面命中价格的最大值，当前实现尚未校验参考价节点是否可见、是否属于已选变体、是否带有 `Prix conseillé` 等买家可见标签。因此，运营判断促销时必须同时检查 `msrp_source` 并到相同邮编、语言和变体的前台复核，不能只依据看板 MSRP 和折扣列。

当本轮没有抓到当前售价时，系统会沿用历史中上一条有效价格并标记 `status=stale_price`、`price_source=history_carried_forward`；Clearance 商品只有在本轮没有 MSRP 时才可能标记 `msrp_source=history_inherited_for_clearance`。其他 `dom_fallback` 或 `json_ld` 来源都表示本轮页面提取，不代表价格一定在前台可见。

Amazon 还可能出现验证码、地区价格差异或临时屏蔽。脚本会把异常写入 `status` 字段，避免误当成有效价格。

## 英德法意西统一员工看板

英国、德国、法国、意大利和西班牙使用同一份 WPS 产品清单，并通过以下链路运行：

1. `.github/workflows/weekly_wps_product_sync.yml` 每天 UTC 01:30 从 WPS 同步一次 `product_list.json`。
2. `.github/workflows/daily_eu_market_price_refresh.yml` 在 GitHub Actions 中按站点错峰启动 Playwright。
3. `multi_market_price_refresh.py` 分别设置当地语言、币种和配送邮编后抓取 Amazon 页面。
4. `cloudflare_price_sync.py` 把本次结果和最新产品清单上传到 Cloudflare D1；五站价格 JSON 不提交到公开 Git 仓库。
5. `competitor_market_refresh.py` 读取当前站点已登记的竞品 ASIN，使用相同的语言、邮编和币种抓取页面，并把每日页面截图保存到私有 R2。
6. `https://price.tentoki.online` 从 D1 读取数据，并通过顶部按钮切换英国、德国、法国、意大利和西班牙。

原法国 GitHub Pages 工作流仅保留手动刷新和静态回退，不再每天重复抓取。

五站共用看板的筛选区提供“下载当前筛选 Excel”，导出顶部筛选、商品明细列筛选及成功/历史价状态筛选后实际显示的商品；商品明细和重点关注页面仍分别保留全部数据与重点关注专用导出。

五站自动运行时间（UTC）：

- 法国：02:20
- 英国：03:30
- 德国：04:40
- 意大利：05:50
- 西班牙：07:00

也可以在 GitHub Actions 中手动运行 `Daily Amazon UK DE FR IT ES Price Refresh`，选择单个站点或 `ALL`。仓库需要配置 Actions Secret `PRICE_MONITOR_INGEST_TOKEN`；该值同时保存为 Cloudflare Worker 的 `INGEST_TOKEN`，不能写入代码或提交记录。

Cloudflare 目录说明：

- `cloudflare/price-monitor/src/worker.js`：D1 API、竞品登记、员工状态与私有截图读取接口
- `cloudflare/price-monitor/public/index.html`：五站统一看板
- `cloudflare/price-monitor/migrations/`：D1 数据表
- `cloudflare/price-monitor/wrangler.jsonc`：Worker、D1、R2 与自定义域名配置

`price.tentoki.online` 应由 Cloudflare Access 保护，只允许已登记的员工邮箱访问。`price-ingest.tentoki.online` 只供 GitHub Actions 上传数据，Worker 会拒绝该域名上的看板和价格查询接口。

竞品跟踪按站点独立管理。在对应站点页面选择“对标类型”（选项来自自己的在售产品类型）并录入竞品 ASIN；下一次该站点定时任务会抓取价格、评分、评论、促销等字段并保存完整页面截图。截图不公开，员工可在看板中悬停预览、点击查看或下载。每张完整页面截图会自动压缩到约 1 MB 以内，上传接口也会拒绝超限文件；R2 生命周期和每日清理任务均按 60 天保留。

## SZTY 荷兰站看板

SZTY 使用独立的 WPS 清单、GitHub Actions Secrets、Cloudflare Worker 账户键和员工域名，不会覆盖 TVL 数据：

- 产品清单：`product_list_szty.json`
- 看板：`https://szty.price.tentoki.online`
- 内部上传域名：`https://szty-price-ingest.tentoki.online`
- 每日抓价：UTC 16:20，即北京时间次日 00:20
- 每周清单同步：每周日 UTC 16:00，即北京时间周一 00:00
- 观察位置：Amazon.nl 默认 Amsterdam `1079 CK`

SZTY 同步会把 WPS“产品清单”中所有唯一且有效的 ASIN 纳入价格抓取，不按产品状态排除；没有 ASIN 的资料行只保留在非在售资料中。第一版只抓 SZTY 自有产品，不启用竞品跟踪。

GitHub Actions 使用以下 Secrets：

- `SZTY_WPS_SCRIPT_WEBHOOK`
- `WPS_AIRSCRIPT_TOKEN`（与 TVL、ASB 共用）
- `SZTY_PRICE_MONITOR_INGEST_TOKEN`

对应工作流：

- `.github/workflows/weekly_szty_wps_product_sync.yml`
- `.github/workflows/daily_szty_nl_price_refresh.yml`

每日抓价默认每个 GitHub Runner 处理 50 个 ASIN，降低单个 Runner 被 Amazon.nl 限制后影响整批数据的范围。手动恢复时可在 Actions 页面填写 `offset`、`limit` 和 `batch_size`，只重跑指定区间；例如 `offset=675`、`limit=49`、`batch_size=10` 表示把第 676 至 724 个 ASIN 拆成 5 个小批次。

Cloudflare 部署配置位于 `cloudflare/price-monitor/wrangler.szty.jsonc`。D1 表通过 `account_key=szty` 与 TVL 的 `account_key=primary` 隔离，不需要新增数据库表。

## ASB 荷兰站看板

ASB 使用独立的 WPS 清单、GitHub Actions Secrets、Cloudflare Worker 和员工域名：

- 产品清单：`product_list_asb.json`
- AirScript：`wps_airscript_asb_product_export.js`
- 看板：`https://asb.price.tentoki.online`
- 内部上传域名：`https://asb-price-ingest.tentoki.online`
- 每日抓价：UTC 19:00，即北京时间次日 03:00
- 每周清单同步：每周日 UTC 18:40，即北京时间周一 02:40
- 观察位置：Amazon.nl 默认 Amsterdam `1079 CK`

ASB 与 XND 共用一份 WPS 文件，但 ASB 欧洲产品使用 `ASB` iSKU 前缀。同步工作流只保留 `iSKU` 以 `ASB` 开头且具有有效 ASIN 的记录，避免将 XND 北美产品混入欧洲看板。所有产品状态均纳入监控。

GitHub Actions 使用以下 Secrets：

- `ASB_WPS_SCRIPT_WEBHOOK`
- `WPS_AIRSCRIPT_TOKEN`（与 TVL、SZTY 共用）
- `ASB_PRICE_MONITOR_INGEST_TOKEN`

对应工作流：

- `.github/workflows/weekly_asb_wps_product_sync.yml`
- `.github/workflows/daily_asb_nl_price_refresh.yml`

Cloudflare 部署配置位于 `cloudflare/price-monitor/wrangler.asb.jsonc`。D1 和 R2 与其他账号复用物理资源，通过 `account_key=asb` 隔离数据。

## 从零创建 GitHub 仓库

1. 注册或登录 GitHub。
2. 打开 [https://github.com/new](https://github.com/new)。
3. Repository name 填一个名字，例如 `amazon-fr-price-monitor`。
4. 选择 `Public`。免费 GitHub Pages 对公开仓库最简单。
5. 不要勾选 README、.gitignore 或 license，因为本地已经有文件。
6. 点击 `Create repository`。

然后在当前文件夹执行下面命令，把项目上传到 GitHub。把 `YOUR_USER` 和仓库名换成你自己的：

```bash
git init
git add .
git commit -m "Initial Amazon.fr price monitor"
git branch -M main
git remote add origin https://github.com/YOUR_USER/amazon-fr-price-monitor.git
git push -u origin main
```

## 启用 GitHub Pages

1. 进入 GitHub 仓库页面。
2. 打开 `Settings`。
3. 左侧选择 `Pages`。
4. Source 选择 `GitHub Actions`。
5. 打开仓库顶部的 `Actions`。
6. 选择 `Daily Amazon.fr Price Refresh`。
7. 点击 `Run workflow` 手动跑一次。

运行成功后，Pages 链接通常是：

```text
https://YOUR_USER.github.io/amazon-fr-price-monitor/
```

之后 GitHub Actions 会每天 UTC 02:20 自动抓取一次，并更新 JSON 数据和看板。
