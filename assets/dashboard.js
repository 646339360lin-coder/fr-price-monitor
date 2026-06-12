const DATA_SOURCES = ["latest_snapshot.csv", "competitor_asin_seed.csv"];
const SITE_ORDER = ["US", "UK", "DE", "FR", "IT", "ES"];
const MANUAL_STORAGE_KEY = "amazonPriceMonitor.manualRows.v1";
const SITE_DOMAINS = {
  US: "amazon.com",
  UK: "amazon.co.uk",
  DE: "amazon.de",
  FR: "amazon.fr",
  IT: "amazon.it",
  ES: "amazon.es",
};
const SITE_POSTCODES = {
  US: "90001",
  UK: "WC1E 7HU",
  DE: "10115",
  FR: "06200",
  IT: "50121",
  ES: "08007",
};

const state = {
  baseRows: [],
  manualRows: [],
  rows: [],
  activeSites: new Set(SITE_ORDER),
  brand: "",
  productLine: "",
  status: "",
  search: "",
  source: "",
};

const els = {
  statusStrip: document.querySelector("#statusStrip"),
  searchInput: document.querySelector("#searchInput"),
  brandFilter: document.querySelector("#brandFilter"),
  productLineFilter: document.querySelector("#productLineFilter"),
  statusFilter: document.querySelector("#statusFilter"),
  siteFilter: document.querySelector("#siteFilter"),
  addAsinForm: document.querySelector("#addAsinForm"),
  newSite: document.querySelector("#newSite"),
  newAsin: document.querySelector("#newAsin"),
  newBrand: document.querySelector("#newBrand"),
  newProductLine: document.querySelector("#newProductLine"),
  newCategory: document.querySelector("#newCategory"),
  clearManualRows: document.querySelector("#clearManualRows"),
  addAsinMessage: document.querySelector("#addAsinMessage"),
  metrics: document.querySelector("#metrics"),
  alertsList: document.querySelector("#alertsList"),
  alertCount: document.querySelector("#alertCount"),
  productMatrix: document.querySelector("#productMatrix"),
  matrixCount: document.querySelector("#matrixCount"),
  detailRows: document.querySelector("#detailRows"),
  rowCount: document.querySelector("#rowCount"),
  refreshData: document.querySelector("#refreshData"),
  exportCsv: document.querySelector("#exportCsv"),
};

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (char === '"' && inQuotes && next === '"') {
      value += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(value);
      value = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(value);
      if (row.some((cell) => cell !== "")) rows.push(row);
      row = [];
      value = "";
    } else {
      value += char;
    }
  }

  if (value || row.length) {
    row.push(value);
    rows.push(row);
  }

  const [headers, ...records] = rows;
  return records.map((record) =>
    Object.fromEntries(headers.map((header, index) => [header, record[index] ?? ""]))
  );
}

function csvEscape(value) {
  const raw = value == null ? "" : String(value);
  return /[",\n\r]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

function toCsv(rows) {
  const headers = state.rows.length ? Object.keys(state.rows[0]).filter((header) => header !== "source_type") : [];
  return [headers.join(","), ...rows.map((row) => headers.map((header) => csvEscape(row[header])).join(","))].join("\n");
}

function statusKind(row) {
  if (row.scrape_status === "pending_manual") return "pending";
  if (isLocationIssue(row)) return "issue";
  if (!row.scrape_status || row.scrape_status.startsWith("error") || row.scrape_status === "robot_check") return "issue";
  if (row.scrape_status.includes("unavailable")) return "issue";
  if (row.scrape_status.includes("retry")) return "retry";
  return "ok";
}

function isLocationIssue(row) {
  return Boolean(row.location_status && row.location_status !== "location_ok" && row.location_status !== "location_not_configured" && row.scrape_status !== "pending_manual");
}

function statusLabel(row) {
  return isLocationIssue(row) ? row.location_status : row.scrape_status || "missing";
}

function priceText(row) {
  if (!row.current_price) return "N/A";
  const symbol = row.currency === "USD" ? "$" : row.currency === "GBP" ? "£" : row.currency === "EUR" ? "€" : "";
  return `${symbol}${Number(row.current_price).toFixed(2)}`;
}

function manualRows() {
  try {
    const parsed = JSON.parse(localStorage.getItem(MANUAL_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveManualRows(rows) {
  localStorage.setItem(MANUAL_STORAGE_KEY, JSON.stringify(rows));
}

function mergeRows(baseRows, manualRowsToMerge) {
  const byKey = new Map();
  baseRows.forEach((row) => byKey.set(`${row.site}:${row.asin}`, { ...row, source_type: "csv" }));

  manualRowsToMerge.forEach((manual) => {
    const key = `${manual.site}:${manual.asin}`;
    if (byKey.has(key)) {
      const existing = byKey.get(key);
      byKey.set(key, {
        ...existing,
        brand: manual.brand || existing.brand,
        product_line: manual.product_line || existing.product_line,
        category: manual.category || existing.category,
        title: manual.title || existing.title,
        source_type: "csv+manual",
      });
      return;
    }
    byKey.set(key, { ...manual, source_type: "manual" });
  });

  return [...byKey.values()];
}

function rebuildRows() {
  state.manualRows = manualRows();
  state.rows = mergeRows(state.baseRows, state.manualRows);
}

function hasPromo(row) {
  return Boolean(row.discount || row.coupon_or_promo || row.deal_badge);
}

function isStockIssue(row) {
  return row.availability && !/in stock|only \d+ left/i.test(row.availability);
}

function filteredRows() {
  const query = state.search.trim().toLowerCase();
  return state.rows.filter((row) => {
    const haystack = [row.asin, row.site, row.brand, row.product_line, row.title, row.sold_by, row.availability].join(" ").toLowerCase();
    if (!state.activeSites.has(row.site)) return false;
    if (state.brand && row.brand !== state.brand) return false;
    if (state.productLine && row.product_line !== state.productLine) return false;
    if (state.status && statusKind(row) !== state.status) return false;
    if (query && !haystack.includes(query)) return false;
    return true;
  });
}

function groupBy(rows, key) {
  return rows.reduce((acc, row) => {
    const groupKey = row[key] || "未分类";
    acc[groupKey] ||= [];
    acc[groupKey].push(row);
    return acc;
  }, {});
}

function unique(rows, key) {
  return [...new Set(rows.map((row) => row[key]).filter(Boolean))].sort();
}

async function loadData() {
  els.statusStrip.textContent = "正在读取数据...";
  for (const source of DATA_SOURCES) {
    try {
      const response = await fetch(source, { cache: "no-store" });
      if (!response.ok) continue;
      const text = await response.text();
      state.baseRows = parseCsv(text);
      state.source = source;
      rebuildRows();
      setupFilters();
      render();
      return;
    } catch (error) {
      // Try the next configured source.
    }
  }
  els.statusStrip.innerHTML = `<span class="empty">没有找到 CSV 数据。请确认 competitor_asin_seed.csv 存在，并通过本地服务器打开页面。</span>`;
}

function setupFilters() {
  const brands = unique(state.rows, "brand");
  els.brandFilter.innerHTML = `<option value="">全部品牌</option>${brands
    .map((brand) => `<option value="${brand}">${brand}</option>`)
    .join("")}`;
  els.brandFilter.value = state.brand;

  const productLines = unique(state.rows, "product_line");
  els.productLineFilter.innerHTML = `<option value="">全部产品线</option>${productLines
    .map((line) => `<option value="${line}">${line}</option>`)
    .join("")}`;
  els.productLineFilter.value = state.productLine;

  els.siteFilter.innerHTML = SITE_ORDER.map(
    (site) => `<button class="chip ${state.activeSites.has(site) ? "active" : ""}" type="button" data-site="${site}">${site}</button>`
  ).join("");
}

function renderMetrics(rows) {
  const asinCount = unique(rows, "asin").length;
  const lineCount = unique(rows, "product_line").length;
  const promoCount = rows.filter(hasPromo).length;
  const pendingCount = rows.filter((row) => statusKind(row) === "pending").length;
  const issueCount = rows.filter((row) => statusKind(row) === "issue").length;
  const retryCount = rows.filter((row) => statusKind(row) === "retry").length;
  const sellerCount = unique(rows, "sold_by").length;
  const locationIssueCount = rows.filter(isLocationIssue).length;

  const metrics = [
    ["ASIN", asinCount],
    ["站点记录", rows.length],
    ["产品线", lineCount],
    ["促销/折扣", promoCount],
    ["待抓取", pendingCount],
  ];

  els.metrics.innerHTML = metrics
    .map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");

  els.statusStrip.innerHTML = `<span>数据源：${state.source} · 手动新增：${state.manualRows.length} 行</span><span>重试成功：${retryCount} 行 · 异常/缺失：${issueCount} 行 · 地址未验证：${locationIssueCount} 行 · 卖家数：${sellerCount || "-"}</span>`;
}

function buildAlerts(rows) {
  const alerts = [];
  rows.forEach((row) => {
    if (statusKind(row) === "issue") {
      alerts.push({ kind: "danger", title: `${row.site} ${row.asin}`, body: `抓取状态：${row.scrape_status || "missing"}` });
    }
    if (statusKind(row) === "pending") {
      alerts.push({ kind: "warn", title: `${row.site} ${row.asin}`, body: "页面内新增，等待下一次抓取脚本补齐价格和库存。" });
    }
    if (isLocationIssue(row)) {
      alerts.push({
        kind: "warn",
        title: `${row.site} ${row.asin}`,
        body: `观察邮编 ${row.observer_postcode || SITE_POSTCODES[row.site] || "-"} 未验证，页面地址：${row.observer_location || row.location_status}`,
      });
    }
    if (isStockIssue(row)) {
      alerts.push({ kind: "danger", title: `${row.site} ${row.asin}`, body: `库存状态：${row.availability}` });
    }
    if (row.discount) {
      alerts.push({ kind: "good", title: `${row.site} ${row.asin}`, body: `价格折扣：${row.discount}，当前价 ${priceText(row)}` });
    }
    if (row.coupon_or_promo) {
      alerts.push({ kind: "good", title: `${row.site} ${row.asin}`, body: `促销：${row.coupon_or_promo}` });
    }
  });
  return alerts;
}

function renderAlerts(rows) {
  const alerts = buildAlerts(rows).slice(0, 12);
  els.alertCount.textContent = `${alerts.length} 条`;
  if (!alerts.length) {
    els.alertsList.innerHTML = `<div class="empty">当前筛选下没有促销、库存或抓取异常。</div>`;
    return;
  }

  els.alertsList.innerHTML = alerts
    .map(
      (alert) => `
        <article class="alert-item ${alert.kind}">
          <div class="alert-title"><span>${alert.title}</span></div>
          <div class="alert-body">${alert.body}</div>
        </article>
      `
    )
    .join("");
}

function renderMatrix(rows) {
  const siteGroups = groupBy(rows, "site");
  const sites = SITE_ORDER.filter((site) => siteGroups[site]?.length);
  els.matrixCount.textContent = `${sites.length} 个站点 · ${rows.length} 行`;

  if (!sites.length) {
    els.productMatrix.innerHTML = `<div class="empty">没有符合筛选条件的商品。</div>`;
    return;
  }

  els.productMatrix.innerHTML = sites
    .map((site) => {
      const siteRows = siteGroups[site].sort(
        (a, b) =>
          (a.product_line || "").localeCompare(b.product_line || "") ||
          (a.brand || "").localeCompare(b.brand || "") ||
          (a.asin || "").localeCompare(b.asin || "")
      );
      const lineGroups = groupBy(siteRows, "product_line");
      const lines = Object.keys(lineGroups).sort();
      return `
        <div class="site-group">
          <div class="site-group-header">
            <strong>${site}</strong>
            <span>${siteRows.length} 个监控项</span>
          </div>
          ${lines
            .map(
              (line) => `
                <div class="line-group">
                  <div class="line-heading">
                    <span>${line}</span>
                    <span>${lineGroups[line].length} 个 ASIN</span>
                  </div>
                  ${lineGroups[line].map(renderProductRow).join("")}
                </div>
              `
            )
            .join("")}
        </div>
      `;
    })
    .join("");
}

function renderProductRow(row) {
  const kind = statusKind(row);
  const promo = [row.discount, row.coupon_or_promo, row.deal_badge].filter(Boolean).join(" · ");
  const observerPostcode = row.observer_postcode || SITE_POSTCODES[row.site] || "-";
  const observerLocation = row.observer_location || row.location_status || "地址待验证";
  return `
    <article class="product-card single">
      <div class="product-row-grid">
        <div class="product-row-title">
          <strong><a href="${row.url}" target="_blank" rel="noreferrer">${row.asin}</a> · ${row.brand || "Unknown"}</strong>
          <span>${row.title || "页面内新增，等待抓取补齐标题"}</span>
        </div>
        <div>
          <span class="site-label">价格</span>
          <span class="price">${priceText(row)}</span>
          ${row.list_price ? `<span class="cell-meta">List ${row.list_price}</span>` : ""}
        </div>
        <div>
          <span class="site-label">促销</span>
          ${promo ? `<span class="promo">${promo}</span>` : `<span class="muted">无记录</span>`}
        </div>
        <div>
          <span class="site-label">库存 / 评分</span>
          <div class="cell-meta">${row.availability || "待抓取"}<br />★ ${row.rating || "-"} · ${row.review_count || "-"} reviews</div>
        </div>
        <div>
          <span class="status-pill ${kind}">${statusLabel(row)}</span>
          <div class="cell-meta">${row.sold_by || "卖家待抓取"}<br />观察 ${observerPostcode} · ${observerLocation}</div>
        </div>
      </div>
    </article>
  `;
}

function renderTable(rows) {
  els.rowCount.textContent = `${rows.length} 行`;
  els.detailRows.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td><a href="${row.url}" target="_blank" rel="noreferrer">${row.asin}</a></td>
          <td>${row.site}</td>
          <td>${row.brand || ""}</td>
          <td>${priceText(row)}</td>
          <td>${row.discount || ""}</td>
          <td>${row.coupon_or_promo || ""}</td>
          <td>${row.availability || ""}</td>
          <td>${row.rating || ""}</td>
          <td>${row.review_count || ""}</td>
          <td>${row.sold_by || ""}</td>
          <td>${row.ships_from || ""}<br /><span class="cell-meta">观察 ${row.observer_postcode || SITE_POSTCODES[row.site] || "-"} · ${row.observer_location || row.location_status || "地址待验证"}</span></td>
          <td><span class="status-pill ${statusKind(row)}">${statusLabel(row)}</span></td>
        </tr>
      `
    )
    .join("");
}

function render() {
  const rows = filteredRows();
  renderMetrics(rows);
  renderAlerts(rows);
  renderMatrix(rows);
  renderTable(rows);
}

function buildManualRow({ site, asin, brand, productLine, category }) {
  const domain = SITE_DOMAINS[site];
  return {
    asin,
    site,
    marketplace_domain: domain,
    url: `https://www.${domain}/dp/${asin}`,
    observer_postcode: SITE_POSTCODES[site] || "",
    observer_location: "",
    location_status: "location_not_captured",
    brand,
    product_line: productLine,
    category,
    title: "",
    current_price: "",
    currency: site === "US" ? "USD" : site === "UK" ? "GBP" : "EUR",
    list_price: "",
    discount: "",
    coupon_or_promo: "",
    deal_badge: "",
    availability: "",
    rating: "",
    review_count: "",
    sold_by: "",
    ships_from: "",
    scrape_status: "pending_manual",
    fetched_at: new Date().toISOString(),
  };
}

function showFormMessage(message, type = "") {
  els.addAsinMessage.textContent = message;
  els.addAsinMessage.className = `form-message ${type}`;
}

async function addManualRow(event) {
  event.preventDefault();
  const site = els.newSite.value;
  const asin = els.newAsin.value.trim().toUpperCase();
  const brand = els.newBrand.value.trim();
  const productLine = els.newProductLine.value.trim();
  const category = els.newCategory.value.trim();

  if (!/^[A-Z0-9]{10}$/.test(asin)) {
    showFormMessage("ASIN 必须是 10 位字母数字。", "error");
    return;
  }

  try {
    const response = await fetch("/api/monitor-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site, asin, brand, productLine, category }),
    });
    if (response.ok) {
      const result = await response.json();
      await loadData();
      showFormMessage(result.mode === "updated" ? `已更新 ${site} ${asin} 并写入 CSV。` : `已加入 ${site} ${asin} 并写入 CSV。`, "success");
      els.addAsinForm.reset();
      els.newSite.value = site;
      return;
    }
  } catch {
    // Static server fallback: store in browser localStorage.
  }

  const row = buildManualRow({ site, asin, brand, productLine, category });
  const rows = manualRows();
  const index = rows.findIndex((item) => item.site === site && item.asin === asin);
  if (index >= 0) {
    rows[index] = {
      ...rows[index],
      ...row,
      brand: brand || rows[index].brand,
      product_line: productLine || rows[index].product_line,
      category: category || rows[index].category,
    };
    showFormMessage(`已更新 ${site} ${asin} 的本地监控信息。`, "success");
  } else {
    rows.push(row);
    showFormMessage(`已加入 ${site} ${asin}。等待下一次抓取补齐价格。`, "success");
  }

  saveManualRows(rows);
  rebuildRows();
  setupFilters();
  render();
  els.addAsinForm.reset();
  els.newSite.value = site;
}

async function clearManualRows() {
  try {
    const response = await fetch("/api/manual-items", { method: "DELETE" });
    if (response.ok) {
      saveManualRows([]);
      await loadData();
      const result = await response.json();
      showFormMessage(`已清空 ${result.removed} 个 CSV 待抓取项。`, "success");
      return;
    }
  } catch {
    // Static server fallback: clear browser localStorage only.
  }

  saveManualRows([]);
  rebuildRows();
  setupFilters();
  render();
  showFormMessage("已清空页面内手动新增的监控项。", "success");
}

els.searchInput.addEventListener("input", (event) => {
  state.search = event.target.value;
  render();
});

els.brandFilter.addEventListener("change", (event) => {
  state.brand = event.target.value;
  render();
});

els.productLineFilter.addEventListener("change", (event) => {
  state.productLine = event.target.value;
  render();
});

els.statusFilter.addEventListener("change", (event) => {
  state.status = event.target.value;
  render();
});

els.siteFilter.addEventListener("click", (event) => {
  const button = event.target.closest("[data-site]");
  if (!button) return;
  const site = button.dataset.site;
  if (state.activeSites.has(site)) {
    state.activeSites.delete(site);
    button.classList.remove("active");
  } else {
    state.activeSites.add(site);
    button.classList.add("active");
  }
  render();
});

els.addAsinForm.addEventListener("submit", addManualRow);
els.clearManualRows.addEventListener("click", clearManualRows);
els.refreshData.addEventListener("click", loadData);

els.exportCsv.addEventListener("click", () => {
  const blob = new Blob([toCsv(filteredRows())], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `amazon-price-monitor-view-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
});

loadData();
