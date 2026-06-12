#!/usr/bin/env node
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const seedPath = path.join(root, "competitor_asin_seed.csv");
const portArgIndex = process.argv.indexOf("--port");
const port = Number(portArgIndex >= 0 ? process.argv[portArgIndex + 1] : process.env.PORT || 8080);

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

const HEADERS = [
  "asin",
  "site",
  "marketplace_domain",
  "url",
  "observer_postcode",
  "observer_location",
  "location_status",
  "brand",
  "product_line",
  "category",
  "title",
  "current_price",
  "currency",
  "list_price",
  "discount",
  "coupon_or_promo",
  "deal_badge",
  "availability",
  "rating",
  "review_count",
  "sold_by",
  "ships_from",
  "scrape_status",
  "fetched_at",
];

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".md": "text/plain; charset=utf-8",
};

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && inQuotes && next === '"') {
      value += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(value);
      value = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") index += 1;
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
  return records.map((record) => Object.fromEntries(headers.map((header, index) => [header, record[index] ?? ""])));
}

function csvEscape(value) {
  const raw = value == null ? "" : String(value);
  return /[",\n\r]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

function toCsv(rows) {
  return [HEADERS.join(","), ...rows.map((row) => HEADERS.map((header) => csvEscape(row[header])).join(","))].join("\n");
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

async function readSeedRows() {
  const text = await fs.readFile(seedPath, "utf8");
  return parseCsv(text);
}

async function writeSeedRows(rows) {
  await fs.writeFile(seedPath, `${toCsv(rows)}\n`);
}

function buildPendingRow(payload) {
  const site = String(payload.site || "").trim().toUpperCase();
  const asin = String(payload.asin || "").trim().toUpperCase();
  const domain = SITE_DOMAINS[site];
  if (!domain) throw new Error("unsupported_site");
  if (!/^[A-Z0-9]{10}$/.test(asin)) throw new Error("invalid_asin");

  return {
    asin,
    site,
    marketplace_domain: domain,
    url: `https://www.${domain}/dp/${asin}`,
    observer_postcode: SITE_POSTCODES[site] || "",
    observer_location: "",
    location_status: "location_not_captured",
    brand: String(payload.brand || "").trim(),
    product_line: String(payload.productLine || payload.product_line || "").trim(),
    category: String(payload.category || "").trim(),
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

async function addMonitorItem(req, res) {
  try {
    const payload = await readJson(req);
    const incoming = buildPendingRow(payload);
    const rows = await readSeedRows();
    const index = rows.findIndex((row) => row.site === incoming.site && row.asin === incoming.asin);
    if (index >= 0) {
      rows[index] = {
        ...rows[index],
        brand: incoming.brand || rows[index].brand,
        product_line: incoming.product_line || rows[index].product_line,
        category: incoming.category || rows[index].category,
        fetched_at: incoming.fetched_at,
      };
      await writeSeedRows(rows);
      json(res, 200, { ok: true, mode: "updated", row: rows[index] });
      return;
    }

    rows.push(incoming);
    await writeSeedRows(rows);
    json(res, 201, { ok: true, mode: "created", row: incoming });
  } catch (error) {
    json(res, 400, { ok: false, error: error.message });
  }
}

async function clearPendingItems(res) {
  const rows = await readSeedRows();
  const nextRows = rows.filter((row) => row.scrape_status !== "pending_manual");
  await writeSeedRows(nextRows);
  json(res, 200, { ok: true, removed: rows.length - nextRows.length });
}

async function serveStatic(req, res) {
  const url = new URL(req.url, `http://localhost:${port}`);
  const pathname = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
  const requestedPath = path.normalize(path.join(root, pathname));
  if (!requestedPath.startsWith(root)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  try {
    const data = await fs.readFile(requestedPath);
    res.writeHead(200, { "Content-Type": MIME_TYPES[path.extname(requestedPath)] || "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end("Not found");
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === "POST" && req.url === "/api/monitor-items") {
    await addMonitorItem(req, res);
    return;
  }
  if (req.method === "DELETE" && req.url === "/api/manual-items") {
    await clearPendingItems(res);
    return;
  }
  if (req.method === "GET" || req.method === "HEAD") {
    await serveStatic(req, res);
    return;
  }
  res.writeHead(405);
  res.end("Method not allowed");
});

server.listen(port, () => {
  console.log(`Amazon price monitor server: http://localhost:${port}/`);
});
