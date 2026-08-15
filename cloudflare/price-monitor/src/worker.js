const MARKETS = {
  UK: { label: "英国", site: "Amazon.co.uk", currency: "GBP" },
  DE: { label: "德国", site: "Amazon.de", currency: "EUR" },
  IT: { label: "意大利", site: "Amazon.it", currency: "EUR" },
  ES: { label: "西班牙", site: "Amazon.es", currency: "EUR" },
  NL: { label: "荷兰", site: "Amazon.nl", currency: "EUR" },
};

function accountKey(env) {
  return String(env.ACCOUNT_KEY || "primary").trim().toLowerCase();
}

function dashboardHost(env) {
  return String(env.DASHBOARD_HOST || "price.tentoki.online").trim().toLowerCase();
}

function ingestHost(env) {
  return String(env.INGEST_HOST || "price-ingest.tentoki.online").trim().toLowerCase();
}

function catalogSource(env) {
  return String(
    env.CATALOG_SOURCE
      || (accountKey(env) === "szty"
        ? "WPS AirScript: SZTY备货表格-20260428 / 产品清单"
        : "WPS AirScript: TVL备货表格-20240914 / 产品清单")
  ).trim();
}

function json(data, status = 200, cacheControl = "no-store") {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": cacheControl,
      "x-content-type-options": "nosniff",
    },
  });
}

function readSession(env) {
  return typeof env.DB.withSession === "function"
    ? env.DB.withSession("first-unconstrained")
    : env.DB;
}

function withCacheControl(response, value, cacheStatus) {
  const headers = new Headers(response.headers);
  headers.set("cache-control", value);
  if (cacheStatus) headers.set("x-price-monitor-cache", cacheStatus);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

async function cachedEmployeeResponse(request, env, ctx, ttlSeconds, producer) {
  requireEmployee(request, env);
  const cache = caches.default;
  const cacheKey = new Request(request.url, { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) {
    return withCacheControl(cached, `private, max-age=${ttlSeconds}`, "HIT");
  }

  const response = await producer();
  if (!response.ok) return response;
  const edgeResponse = withCacheControl(response.clone(), `public, max-age=${ttlSeconds}`);
  ctx.waitUntil(cache.put(cacheKey, edgeResponse));
  return withCacheControl(response, `private, max-age=${ttlSeconds}`, "MISS");
}

function marketCode(value) {
  const code = String(value || "").toUpperCase();
  return Object.hasOwn(MARKETS, code) ? code : null;
}

function authenticatedEmail(request) {
  return String(request.headers.get("cf-access-authenticated-user-email") || "")
    .trim()
    .toLowerCase();
}

function requireEmployee(request, env) {
  const email = authenticatedEmail(request);
  if (!email) throw new Response("Cloudflare Access authentication required", { status: 401 });
  const allowed = String(env.ALLOWED_EMAILS || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  if (allowed.length && !allowed.includes(email)) {
    throw new Response("Forbidden", { status: 403 });
  }
  return email;
}

function requireIngestToken(request, env) {
  const authorization = request.headers.get("authorization") || "";
  if (!env.INGEST_TOKEN || authorization !== `Bearer ${env.INGEST_TOKEN}`) {
    throw new Response("Unauthorized", { status: 401 });
  }
}

function safeJson(value, fallback = {}) {
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

async function ingest(request, env) {
  requireIngestToken(request, env);
  const payload = await request.json();
  const market = marketCode(payload.market || payload.latest?.market);
  if (!market) return json({ error: "Unsupported market" }, 400);
  if ((payload.account || accountKey(env)) !== accountKey(env)) {
    return json({ error: "Unsupported account" }, 400);
  }

  const latest = Array.isArray(payload.latest?.products) ? payload.latest.products : [];
  const active = Array.isArray(payload.catalog?.products) ? payload.catalog.products : [];
  const inactive = Array.isArray(payload.catalog?.non_active_products)
    ? payload.catalog.non_active_products
    : [];
  if (!latest.length || !active.length) {
    return json({ error: "latest.products and catalog.products are required" }, 400);
  }

  const now = new Date().toISOString();
  const catalog = [
    ...active.map((item) => ({ ...item, _active: 1 })),
    ...inactive.map((item) => ({ ...item, _active: 0 })),
  ];
  const generatedAt = payload.latest.generated_at || now;
  const successCount = latest.filter((item) => item.status === "ok").length;
  const staleCount = latest.filter((item) => item.status === "stale_price").length;

  const statements = [
    env.DB.prepare(
      `INSERT INTO products (account_key, market, asin, active, metadata_json, updated_at)
       SELECT ?, ?, UPPER(json_extract(value, '$.asin')),
              CAST(json_extract(value, '$._active') AS INTEGER), value, ?
       FROM json_each(?)
       WHERE json_extract(value, '$.asin') IS NOT NULL
       ON CONFLICT(account_key, market, asin) DO UPDATE SET
         active = excluded.active,
         metadata_json = excluded.metadata_json,
         updated_at = excluded.updated_at`
    ).bind(accountKey(env), market, now, JSON.stringify(catalog)),
    env.DB.prepare(
      `INSERT INTO latest_prices
         (account_key, market, asin, scraped_at, status, current_price, msrp_price, record_json, updated_at)
       SELECT ?, ?, UPPER(json_extract(value, '$.asin')),
              COALESCE(json_extract(value, '$.scraped_at'), ?),
              json_extract(value, '$.status'),
              json_extract(value, '$.current_price'),
              json_extract(value, '$.msrp_price'), value, ?
       FROM json_each(?)
       WHERE json_extract(value, '$.asin') IS NOT NULL
       ON CONFLICT(account_key, market, asin) DO UPDATE SET
         scraped_at = excluded.scraped_at,
         status = excluded.status,
         current_price = excluded.current_price,
         msrp_price = excluded.msrp_price,
         record_json = excluded.record_json,
         updated_at = excluded.updated_at`
    ).bind(accountKey(env), market, generatedAt, now, JSON.stringify(latest)),
    env.DB.prepare(
      `INSERT OR IGNORE INTO price_history
         (account_key, market, asin, scraped_at, current_price, msrp_price,
          promotion_status, status, record_json)
       SELECT ?, ?, UPPER(json_extract(value, '$.asin')),
              COALESCE(json_extract(value, '$.scraped_at'), ?),
              json_extract(value, '$.current_price'),
              json_extract(value, '$.msrp_price'),
              json_extract(value, '$.promotion_status'),
              json_extract(value, '$.status'), value
       FROM json_each(?)
       WHERE json_extract(value, '$.asin') IS NOT NULL`
    ).bind(accountKey(env), market, generatedAt, JSON.stringify(latest)),
    env.DB.prepare(
      `INSERT INTO market_runs
         (account_key, market, generated_at, total_count, success_count, stale_count)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_key, market) DO UPDATE SET
         generated_at = excluded.generated_at,
         total_count = excluded.total_count,
         success_count = excluded.success_count,
         stale_count = excluded.stale_count`
    ).bind(accountKey(env), market, generatedAt, latest.length, successCount, staleCount),
  ];

  await env.DB.batch(statements);
  await env.DB.prepare(
    `DELETE FROM price_history
     WHERE account_key = ? AND market = ?
       AND scraped_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-180 days')`
  ).bind(accountKey(env), market).run();

  return json({
    ok: true,
    market,
    generated_at: generatedAt,
    catalog_count: catalog.length,
    latest_count: latest.length,
    success_count: successCount,
    stale_count: staleCount,
  });
}

async function seedHistory(request, env, url) {
  requireIngestToken(request, env);
  const requestedAccount = String(url.searchParams.get("account") || accountKey(env)).toLowerCase();
  if (requestedAccount !== accountKey(env)) return json({ error: "Unsupported account" }, 400);
  const market = marketCode(url.searchParams.get("market"));
  if (!market) return json({ error: "Unsupported market" }, 400);
  const result = await env.DB.prepare(
    `SELECT record_json FROM latest_prices
     WHERE account_key = ? AND market = ? ORDER BY asin`
  ).bind(accountKey(env), market).all();
  return json({
    generated_at: new Date().toISOString(),
    market,
    site: MARKETS[market].site,
    currency: MARKETS[market].currency,
    products: result.results.map((row) => safeJson(row.record_json)),
  });
}

async function marketList(request, env) {
  const db = readSession(env);
  const result = await db.prepare(
    `SELECT market, generated_at, total_count, success_count, stale_count
     FROM market_runs WHERE account_key = ?`
  ).bind(accountKey(env)).all();
  const runs = Object.fromEntries(result.results.map((row) => [row.market, row]));
  return json({
    markets: Object.entries(MARKETS).map(([code, config]) => ({
      code,
      ...config,
      run: runs[code] || null,
    })),
  });
}

async function latestPrices(request, env, market) {
  const db = readSession(env);
  const result = await db.prepare(
    `SELECT record_json FROM latest_prices
     WHERE account_key = ? AND market = ? ORDER BY asin`
  ).bind(accountKey(env), market).all();
  const run = await db.prepare(
    `SELECT generated_at FROM market_runs WHERE account_key = ? AND market = ?`
  ).bind(accountKey(env), market).first();
  return json({
    generated_at: run?.generated_at || null,
    market,
    site: MARKETS[market].site,
    currency: MARKETS[market].currency,
    products: result.results.map((row) => safeJson(row.record_json)),
  });
}

async function priceHistory(request, env, market, url) {
  const requestedAsins = String(url.searchParams.get("asins") || "")
    .split(",")
    .map((asin) => asin.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 5);
  const weekly = url.searchParams.get("scope") === "weekly";
  if (!requestedAsins.length && !weekly) {
    return json({ error: "Provide up to 5 ASINs or use scope=weekly" }, 400);
  }
  const historyDays = weekly ? 7 : 180;
  let query =
    `SELECT record_json FROM price_history
     WHERE account_key = ? AND market = ?
       AND scraped_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)`;
  const bindings = [accountKey(env), market, `-${historyDays} days`];
  if (requestedAsins.length) {
    query += ` AND asin IN (${requestedAsins.map(() => "?").join(",")})`;
    bindings.push(...requestedAsins);
  }
  query += " ORDER BY scraped_at, asin";
  const result = await readSession(env).prepare(query).bind(...bindings).all();
  return json({
    generated_at: new Date().toISOString(),
    market,
    site: MARKETS[market].site,
    currency: MARKETS[market].currency,
    products: result.results.map((row) => safeJson(row.record_json)),
  });
}

async function catalog(request, env, market, url) {
  const inactiveOnly = url.searchParams.get("scope") === "inactive";
  const activeClause = inactiveOnly ? " AND active = 0" : "";
  const result = await readSession(env).prepare(
    `SELECT active, metadata_json FROM products
     WHERE account_key = ? AND market = ?${activeClause} ORDER BY active DESC, asin`
  ).bind(accountKey(env), market).all();
  const products = [];
  const nonActiveProducts = [];
  for (const row of result.results) {
    const item = safeJson(row.metadata_json);
    delete item._active;
    (row.active ? products : nonActiveProducts).push(item);
  }
  return json({
    market,
    site: MARKETS[market].site,
    source: catalogSource(env),
    products,
    non_active_products: nonActiveProducts,
  });
}

async function getUserState(request, env, market) {
  const email = requireEmployee(request, env);
  const products = await env.DB.prepare(
    `SELECT asin, memo, memo_updated_at, focused FROM user_product_state
     WHERE email = ? AND account_key = ? AND market = ?`
  ).bind(email, accountKey(env), market).all();
  const shell = await env.DB.prepare(
    `SELECT phone_brand, model, single_shell, three_in_one, breakthrough
     FROM shell_opportunity_state
     WHERE email = ? AND account_key = ? AND market = ?`
  ).bind(email, accountKey(env), market).all();
  return json({ email, market, products: products.results, shell: shell.results });
}

async function putUserState(request, env, market) {
  const email = requireEmployee(request, env);
  const payload = await request.json();
  const asin = String(payload.asin || "").trim().toUpperCase();
  if (!/^[A-Z0-9]{10}$/.test(asin)) return json({ error: "Invalid ASIN" }, 400);
  const existing = await env.DB.prepare(
    `SELECT memo, memo_updated_at, focused FROM user_product_state
     WHERE email = ? AND account_key = ? AND market = ? AND asin = ?`
  ).bind(email, accountKey(env), market, asin).first();
  const memo = Object.hasOwn(payload, "memo") ? String(payload.memo || "") : existing?.memo || "";
  const focused = Object.hasOwn(payload, "focused")
    ? Boolean(payload.focused)
    : Boolean(existing?.focused);
  const memoUpdatedAt = Object.hasOwn(payload, "memo")
    ? new Date().toISOString().slice(0, 10)
    : existing?.memo_updated_at || null;
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO user_product_state
       (email, account_key, market, asin, memo, memo_updated_at, focused, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(email, account_key, market, asin) DO UPDATE SET
       memo = excluded.memo,
       memo_updated_at = excluded.memo_updated_at,
       focused = excluded.focused,
       updated_at = excluded.updated_at`
  ).bind(email, accountKey(env), market, asin, memo, memoUpdatedAt, focused ? 1 : 0, now).run();
  return json({ ok: true, asin, memo, memo_updated_at: memoUpdatedAt, focused });
}

async function putShellState(request, env, market) {
  const email = requireEmployee(request, env);
  const payload = await request.json();
  const phoneBrand = String(payload.phone_brand || "").trim();
  const model = String(payload.model || "").trim();
  if (!phoneBrand || !model) return json({ error: "phone_brand and model are required" }, 400);
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO shell_opportunity_state
       (email, account_key, market, phone_brand, model, single_shell, three_in_one,
        breakthrough, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(email, account_key, market, phone_brand, model) DO UPDATE SET
       single_shell = excluded.single_shell,
       three_in_one = excluded.three_in_one,
       breakthrough = excluded.breakthrough,
       updated_at = excluded.updated_at`
  ).bind(
    email,
    accountKey(env),
    market,
    phoneBrand,
    model,
    payload.single_shell ? 1 : 0,
    payload.three_in_one ? 1 : 0,
    payload.breakthrough ? 1 : 0,
    now
  ).run();
  return json({ ok: true });
}

function validAsin(value) {
  const asin = String(value || "").trim().toUpperCase();
  return /^[A-Z0-9]{10}$/.test(asin) ? asin : null;
}

async function employeeCompetitors(request, env, market) {
  requireEmployee(request, env);
  const result = await readSession(env).prepare(
    `WITH latest AS (
       SELECT *, ROW_NUMBER() OVER (
         PARTITION BY account_key, market, asin ORDER BY scraped_at DESC, id DESC
       ) AS row_number
       FROM competitor_snapshots
       WHERE account_key = ? AND market = ?
     )
     SELECT cp.asin, cp.benchmark_type, cp.active, cp.created_at, cp.updated_at,
            latest.id AS snapshot_id, latest.scraped_at, latest.status,
            latest.record_json, latest.screenshot_key
     FROM competitor_products cp
     LEFT JOIN latest
       ON latest.account_key = cp.account_key AND latest.market = cp.market
      AND latest.asin = cp.asin AND latest.row_number = 1
     WHERE cp.account_key = ? AND cp.market = ?
     ORDER BY cp.active DESC, cp.benchmark_type, cp.asin`
  ).bind(accountKey(env), market, accountKey(env), market).all();
  const products = result.results.map((row) => {
    const record = safeJson(row.record_json, {}) || {};
    const snapshotPath = row.snapshot_id
      ? `/api/market/${market}/competitor-screenshot/${row.snapshot_id}`
      : null;
    return {
      ...record,
      asin: row.asin,
      category: row.benchmark_type,
      benchmark_type: row.benchmark_type,
      active: Boolean(row.active),
      registry_created_at: row.created_at,
      registry_updated_at: row.updated_at,
      scraped_at: row.scraped_at || record.scraped_at || null,
      status: row.status || record.status || "等待首次抓取",
      screenshot_url: row.screenshot_key ? snapshotPath : null,
      screenshot_download_url: row.screenshot_key ? `${snapshotPath}?download=1` : null,
    };
  });
  return json({ market, products });
}

async function addEmployeeCompetitor(request, env, market) {
  const email = requireEmployee(request, env);
  const payload = await request.json();
  const asin = validAsin(payload.asin);
  const benchmarkType = String(payload.benchmark_type || "").trim();
  if (!asin) return json({ error: "Invalid ASIN" }, 400);
  if (!benchmarkType) return json({ error: "benchmark_type is required" }, 400);
  const ownType = await env.DB.prepare(
    `SELECT 1 FROM products
     WHERE account_key = ? AND market = ? AND active = 1
       AND (json_extract(metadata_json, '$.category') = ?
         OR json_extract(metadata_json, '$.type') = ?)
     LIMIT 1`
  ).bind(accountKey(env), market, benchmarkType, benchmarkType).first();
  if (!ownType) return json({ error: "benchmark_type must match an active own-product type" }, 400);
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO competitor_products
       (account_key, market, asin, benchmark_type, active, created_by, created_at, updated_at)
     VALUES (?, ?, ?, ?, 1, ?, ?, ?)
     ON CONFLICT(account_key, market, asin) DO UPDATE SET
       benchmark_type = excluded.benchmark_type,
       active = 1,
       updated_at = excluded.updated_at`
  ).bind(accountKey(env), market, asin, benchmarkType, email, now, now).run();
  return json({ ok: true, market, asin, benchmark_type: benchmarkType, active: true });
}

async function updateEmployeeCompetitor(request, env, market, asinValue) {
  requireEmployee(request, env);
  const asin = validAsin(asinValue);
  if (!asin) return json({ error: "Invalid ASIN" }, 400);
  const payload = await request.json();
  if (!Object.hasOwn(payload, "active")) return json({ error: "active is required" }, 400);
  const result = await env.DB.prepare(
    `UPDATE competitor_products SET active = ?, updated_at = ?
     WHERE account_key = ? AND market = ? AND asin = ?`
  ).bind(payload.active ? 1 : 0, new Date().toISOString(), accountKey(env), market, asin).run();
  if (!result.meta.changes) return json({ error: "Competitor not found" }, 404);
  return json({ ok: true, market, asin, active: Boolean(payload.active) });
}

async function competitorScreenshot(request, env, market, snapshotId, url) {
  requireEmployee(request, env);
  const id = Number(snapshotId);
  if (!Number.isInteger(id) || id <= 0) return json({ error: "Invalid snapshot" }, 400);
  const row = await readSession(env).prepare(
    `SELECT asin, screenshot_key, screenshot_content_type
     FROM competitor_snapshots
     WHERE id = ? AND account_key = ? AND market = ?`
  ).bind(id, accountKey(env), market).first();
  if (!row?.screenshot_key) return json({ error: "Screenshot not found" }, 404);
  const object = await env.SCREENSHOTS.get(row.screenshot_key);
  if (!object) return json({ error: "Screenshot object not found" }, 404);
  const download = url.searchParams.get("download") === "1";
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("content-type", row.screenshot_content_type || "image/jpeg");
  headers.set("cache-control", "private, max-age=86400");
  headers.set("x-content-type-options", "nosniff");
  headers.set(
    "content-disposition",
    `${download ? "attachment" : "inline"}; filename="${row.asin}-${id}.jpg"`
  );
  return new Response(object.body, { headers });
}

async function ingestCompetitorList(request, env, url) {
  requireIngestToken(request, env);
  const market = marketCode(url.searchParams.get("market"));
  if (!market) return json({ error: "Unsupported market" }, 400);
  const result = await env.DB.prepare(
    `SELECT asin, benchmark_type FROM competitor_products
     WHERE account_key = ? AND market = ? AND active = 1
     ORDER BY benchmark_type, asin`
  ).bind(accountKey(env), market).all();
  return json({ market, products: result.results });
}

async function ingestCompetitorResult(request, env) {
  requireIngestToken(request, env);
  const payload = await request.json();
  const market = marketCode(payload.market);
  const record = payload.record && typeof payload.record === "object" ? payload.record : null;
  const asin = validAsin(record?.asin);
  if (!market || !asin || !record) return json({ error: "market and record.asin are required" }, 400);
  const registered = await env.DB.prepare(
    `SELECT benchmark_type FROM competitor_products
     WHERE account_key = ? AND market = ? AND asin = ? AND active = 1`
  ).bind(accountKey(env), market, asin).first();
  if (!registered) return json({ error: "Active competitor not found" }, 404);

  const screenshotBase64 = String(payload.screenshot_base64 || "");
  if (!screenshotBase64 || screenshotBase64.length > 1_500_000) {
    return json({ error: "A screenshot of approximately 1 MB or less is required" }, 400);
  }
  let screenshot;
  try {
    const binary = atob(screenshotBase64);
    screenshot = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    return json({ error: "Invalid screenshot encoding" }, 400);
  }
  if (screenshot.byteLength > 1_100_000) {
    return json({ error: "Screenshot exceeds the 1 MB storage limit" }, 413);
  }
  const scrapedAt = String(record.scraped_at || new Date().toISOString());
  const date = scrapedAt.slice(0, 10);
  const stamp = scrapedAt.replace(/[^0-9]/g, "").slice(0, 14) || Date.now();
  const screenshotKey = `competitors/${accountKey(env)}/${market}/${asin}/${date}/${stamp}.jpg`;
  const contentType = payload.screenshot_content_type === "image/png" ? "image/png" : "image/jpeg";
  await env.SCREENSHOTS.put(screenshotKey, screenshot, {
    httpMetadata: { contentType },
    customMetadata: { account: accountKey(env), market, asin, scrapedAt },
  });
  try {
    await env.DB.prepare(
      `INSERT INTO competitor_snapshots
         (account_key, market, asin, scraped_at, status, current_price, msrp_price,
          record_json, screenshot_key, screenshot_content_type, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_key, market, asin, scraped_at) DO UPDATE SET
         status = excluded.status,
         current_price = excluded.current_price,
         msrp_price = excluded.msrp_price,
         record_json = excluded.record_json,
         screenshot_key = excluded.screenshot_key,
         screenshot_content_type = excluded.screenshot_content_type`
    ).bind(
      accountKey(env), market, asin, scrapedAt, record.status || null,
      record.current_price ?? null, record.msrp_price ?? null,
      JSON.stringify({ ...record, category: registered.benchmark_type }),
      screenshotKey, contentType, new Date().toISOString()
    ).run();
  } catch (error) {
    await env.SCREENSHOTS.delete(screenshotKey);
    throw error;
  }
  return json({ ok: true, market, asin, scraped_at: scrapedAt });
}

async function cleanupCompetitorSnapshots(request, env, url) {
  requireIngestToken(request, env);
  const market = marketCode(url.searchParams.get("market"));
  if (!market) return json({ error: "Unsupported market" }, 400);
  const expired = await env.DB.prepare(
    `SELECT id, screenshot_key FROM competitor_snapshots
     WHERE account_key = ? AND market = ?
       AND scraped_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-60 days')`
  ).bind(accountKey(env), market).all();
  const keys = expired.results.map((row) => row.screenshot_key).filter(Boolean);
  for (let index = 0; index < keys.length; index += 1000) {
    await env.SCREENSHOTS.delete(keys.slice(index, index + 1000));
  }
  await env.DB.prepare(
    `DELETE FROM competitor_snapshots
     WHERE account_key = ? AND market = ?
       AND scraped_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-60 days')`
  ).bind(accountKey(env), market).run();
  return json({ ok: true, market, deleted: expired.results.length, retention_days: 60 });
}

async function handleApi(request, env, url, ctx) {
  if (url.pathname === "/api/ingest" && request.method === "POST") return ingest(request, env);
  if (url.pathname === "/api/ingest/seed" && request.method === "GET") {
    return seedHistory(request, env, url);
  }
  if (url.pathname === "/api/ingest/competitors" && request.method === "GET") {
    return ingestCompetitorList(request, env, url);
  }
  if (url.pathname === "/api/ingest/competitor-result" && request.method === "POST") {
    return ingestCompetitorResult(request, env);
  }
  if (url.pathname === "/api/ingest/competitors/cleanup" && request.method === "POST") {
    return cleanupCompetitorSnapshots(request, env, url);
  }
  if (url.pathname === "/api/markets" && request.method === "GET") {
    return cachedEmployeeResponse(request, env, ctx, 60, () => marketList(request, env));
  }

  const competitorScreenshotMatch = url.pathname.match(
    /^\/api\/market\/(UK|DE|IT|ES|NL)\/competitor-screenshot\/(\d+)$/i
  );
  if (competitorScreenshotMatch && request.method === "GET") {
    return competitorScreenshot(
      request,
      env,
      marketCode(competitorScreenshotMatch[1]),
      competitorScreenshotMatch[2],
      url
    );
  }
  const competitorItemMatch = url.pathname.match(
    /^\/api\/market\/(UK|DE|IT|ES|NL)\/competitors\/([A-Z0-9]{10})$/i
  );
  if (competitorItemMatch && request.method === "PATCH") {
    return updateEmployeeCompetitor(
      request, env, marketCode(competitorItemMatch[1]), competitorItemMatch[2]
    );
  }
  const competitorListMatch = url.pathname.match(
    /^\/api\/market\/(UK|DE|IT|ES|NL)\/competitors$/i
  );
  if (competitorListMatch) {
    const market = marketCode(competitorListMatch[1]);
    if (request.method === "GET") return employeeCompetitors(request, env, market);
    if (request.method === "POST") return addEmployeeCompetitor(request, env, market);
    return json({ error: "Method not allowed" }, 405);
  }

  const match = url.pathname.match(/^\/api\/market\/(UK|DE|IT|ES|NL)\/(latest|history|catalog|state|shell-state)$/i);
  if (!match) return json({ error: "Not found" }, 404);
  const market = marketCode(match[1]);
  const resource = match[2].toLowerCase();
  if (resource === "latest" && request.method === "GET") {
    return cachedEmployeeResponse(request, env, ctx, 60, () => latestPrices(request, env, market));
  }
  if (resource === "history" && request.method === "GET") {
    return cachedEmployeeResponse(request, env, ctx, 120, () => priceHistory(request, env, market, url));
  }
  if (resource === "catalog" && request.method === "GET") {
    return cachedEmployeeResponse(request, env, ctx, 300, () => catalog(request, env, market, url));
  }
  if (resource === "state" && request.method === "GET") return getUserState(request, env, market);
  if (resource === "state" && request.method === "PUT") return putUserState(request, env, market);
  if (resource === "shell-state" && request.method === "PUT") return putShellState(request, env, market);
  return json({ error: "Method not allowed" }, 405);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if (url.hostname === ingestHost(env)) {
        const isIngestPath = url.pathname === "/api/ingest"
          || url.pathname === "/api/ingest/seed"
          || url.pathname.startsWith("/api/ingest/competitor");
        return isIngestPath ? await handleApi(request, env, url, ctx) : json({ error: "Not found" }, 404);
      }
      if (url.hostname !== dashboardHost(env) && !["localhost", "127.0.0.1"].includes(url.hostname)) {
        return json({ error: "Not found" }, 404);
      }
      if (url.pathname.startsWith("/api/")) return await handleApi(request, env, url, ctx);
      return env.ASSETS.fetch(request);
    } catch (error) {
      if (error instanceof Response) return error;
      console.error(error);
      return json({ error: "Internal server error" }, 500);
    }
  },
};
