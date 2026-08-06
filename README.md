# Amazon.fr 竞品价格监控系统

这个项目用于每天监控 Amazon.fr 上 Tentoki 及竞品的手机配件价格，并把结果发布成一个 GitHub Pages 看板。

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

工作流 `.github/workflows/weekly_wps_product_sync.yml` 每周一 UTC 01:30（北京时间 09:30）同步一次，比每日 UTC 02:20 的价格抓取提前 50 分钟。也可以在 GitHub Actions 中手动运行 `Weekly WPS Product List Sync`。

## 爬虫策略

- 每个商品请求之间随机等待 1-3 秒
- 使用固定 User-Agent
- 每次抓取前读取 Amazon.fr `robots.txt`，不允许访问的 URL 会跳过
- 优先读取 JSON-LD 和页面内嵌 JSON 的价格，再使用 DOM 兜底
- 评分和评论数优先读取 JSON-LD `aggregateRating`，缺失时使用页面元素兜底
- 保存 Amazon 展示的近 30 天销量标签原文；页面没有标签时字段为空，不推算销量
- 检测到 Clearance / Déstockage / Soldes 等清仓词时，不把页面中间态 ticket 价当作 MSRP；如历史中已有 MSRP，会继承历史 MSRP

注意：Amazon 可能出现验证码、地区价格差异或临时屏蔽。脚本会把异常写入 `status` 字段，避免误当成有效价格。

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
