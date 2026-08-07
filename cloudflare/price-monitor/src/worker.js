const ACCOUNT_KEY = "primary";
const DASHBOARD_HOST = "price.tentoki.online";
const INGEST_HOST = "price-ingest.tentoki.online";
const MARKETS = {
  UK: { label: "英国", site: "Amazon.co.uk", currency: "GBP" },
  DE: { label: "德国", site: "Amazon.de", currency: "EUR" },
  IT: { label: "意大利", site: "Amazon.it", currency: "EUR" },
  ES: { label: "西班牙", site: "Amazon.es", currency: "EUR" },
};

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
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
  if ((payload.account || ACCOUNT_KEY) !== ACCOUNT_KEY) {
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
    ).bind(ACCOUNT_KEY, market, now, JSON.stringify(catalog)),
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
    ).bind(ACCOUNT_KEY, market, generatedAt, now, JSON.stringify(latest)),
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
    ).bind(ACCOUNT_KEY, market, generatedAt, JSON.stringify(latest)),
    env.DB.prepare(
      `INSERT INTO market_runs
         (account_key, market, generated_at, total_count, success_count, stale_count)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_key, market) DO UPDATE SET
         generated_at = excluded.generated_at,
         total_count = excluded.total_count,
         success_count = excluded.success_count,
         stale_count = excluded.stale_count`
    ).bind(ACCOUNT_KEY, market, generatedAt, latest.length, successCount, staleCount),
  ];

  await env.DB.batch(statements);
  await env.DB.prepare(
    `DELETE FROM price_history
     WHERE account_key = ? AND market = ?
       AND scraped_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-180 days')`
  ).bind(ACCOUNT_KEY, market).run();

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
  const market = marketCode(url.searchParams.get("market"));
  if (!market) return json({ error: "Unsupported market" }, 400);
  const result = await env.DB.prepare(
    `SELECT record_json FROM latest_prices
     WHERE account_key = ? AND market = ? ORDER BY asin`
  ).bind(ACCOUNT_KEY, market).all();
  return json({
    generated_at: new Date().toISOString(),
    market,
    site: MARKETS[market].site,
    currency: MARKETS[market].currency,
    products: result.results.map((row) => safeJson(row.record_json)),
  });
}

async function marketList(request, env) {
  requireEmployee(request, env);
  const result = await env.DB.prepare(
    `SELECT market, generated_at, total_count, success_count, stale_count
     FROM market_runs WHERE account_key = ?`
  ).bind(ACCOUNT_KEY).all();
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
  requireEmployee(request, env);
  const result = await env.DB.prepare(
    `SELECT record_json FROM latest_prices
     WHERE account_key = ? AND market = ? ORDER BY asin`
  ).bind(ACCOUNT_KEY, market).all();
  const run = await env.DB.prepare(
    `SELECT generated_at FROM market_runs WHERE account_key = ? AND market = ?`
  ).bind(ACCOUNT_KEY, market).first();
  return json({
    generated_at: run?.generated_at || null,
    market,
    site: MARKETS[market].site,
    currency: MARKETS[market].currency,
    products: result.results.map((row) => safeJson(row.record_json)),
  });
}

async function priceHistory(request, env, market, url) {
  requireEmployee(request, env);
  const requestedAsins = String(url.searchParams.get("asins") || "")
    .split(",")
    .map((asin) => asin.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 3);
  let query =
    `SELECT record_json FROM price_history
     WHERE account_key = ? AND market = ?
       AND scraped_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-180 days')`;
  const bindings = [ACCOUNT_KEY, market];
  if (requestedAsins.length) {
    query += ` AND asin IN (${requestedAsins.map(() => "?").join(",")})`;
    bindings.push(...requestedAsins);
  }
  query += " ORDER BY scraped_at, asin";
  const result = await env.DB.prepare(query).bind(...bindings).all();
  return json({
    generated_at: new Date().toISOString(),
    market,
    site: MARKETS[market].site,
    currency: MARKETS[market].currency,
    products: result.results.map((row) => safeJson(row.record_json)),
  });
}

async function catalog(request, env, market) {
  requireEmployee(request, env);
  const result = await env.DB.prepare(
    `SELECT active, metadata_json FROM products
     WHERE account_key = ? AND market = ? ORDER BY active DESC, asin`
  ).bind(ACCOUNT_KEY, market).all();
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
    source: "WPS AirScript: TVL备货表格-20240914 / 产品清单",
    products,
    non_active_products: nonActiveProducts,
  });
}

async function getUserState(request, env, market) {
  const email = requireEmployee(request, env);
  const products = await env.DB.prepare(
    `SELECT asin, memo, memo_updated_at, focused FROM user_product_state
     WHERE email = ? AND account_key = ? AND market = ?`
  ).bind(email, ACCOUNT_KEY, market).all();
  const shell = await env.DB.prepare(
    `SELECT phone_brand, model, single_shell, three_in_one, breakthrough
     FROM shell_opportunity_state
     WHERE email = ? AND account_key = ? AND market = ?`
  ).bind(email, ACCOUNT_KEY, market).all();
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
  ).bind(email, ACCOUNT_KEY, market, asin).first();
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
  ).bind(email, ACCOUNT_KEY, market, asin, memo, memoUpdatedAt, focused ? 1 : 0, now).run();
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
    ACCOUNT_KEY,
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

async function handleApi(request, env, url) {
  if (url.pathname === "/api/ingest" && request.method === "POST") return ingest(request, env);
  if (url.pathname === "/api/ingest/seed" && request.method === "GET") {
    return seedHistory(request, env, url);
  }
  if (url.pathname === "/api/markets" && request.method === "GET") return marketList(request, env);

  const match = url.pathname.match(/^\/api\/market\/(UK|DE|IT|ES)\/(latest|history|catalog|state|shell-state)$/i);
  if (!match) return json({ error: "Not found" }, 404);
  const market = marketCode(match[1]);
  const resource = match[2].toLowerCase();
  if (resource === "latest" && request.method === "GET") return latestPrices(request, env, market);
  if (resource === "history" && request.method === "GET") return priceHistory(request, env, market, url);
  if (resource === "catalog" && request.method === "GET") return catalog(request, env, market);
  if (resource === "state" && request.method === "GET") return getUserState(request, env, market);
  if (resource === "state" && request.method === "PUT") return putUserState(request, env, market);
  if (resource === "shell-state" && request.method === "PUT") return putShellState(request, env, market);
  return json({ error: "Method not allowed" }, 405);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.hostname === INGEST_HOST) {
        const isIngestPath = url.pathname === "/api/ingest" || url.pathname === "/api/ingest/seed";
        return isIngestPath ? await handleApi(request, env, url) : json({ error: "Not found" }, 404);
      }
      if (url.hostname !== DASHBOARD_HOST && !["localhost", "127.0.0.1"].includes(url.hostname)) {
        return json({ error: "Not found" }, 404);
      }
      if (url.pathname.startsWith("/api/")) return await handleApi(request, env, url);
      return env.ASSETS.fetch(request);
    } catch (error) {
      if (error instanceof Response) return error;
      console.error(error);
      return json({ error: "Internal server error" }, 500);
    }
  },
};
