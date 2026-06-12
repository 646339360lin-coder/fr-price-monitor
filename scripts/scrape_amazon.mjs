#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";

const SITE_CONFIG = {
  US: { domain: "amazon.com", currency: "USD", postalCode: "90001", cookie: "i18n-prefs=USD; lc-main=en_US", lang: "en-US,en;q=0.9" },
  UK: { domain: "amazon.co.uk", currency: "GBP", postalCode: "WC1E 7HU", cookie: "i18n-prefs=GBP; lc-acbuk=en_GB", lang: "en-GB,en;q=0.9" },
  DE: { domain: "amazon.de", currency: "EUR", postalCode: "10115", cookie: "i18n-prefs=EUR; lc-acbde=en_GB", lang: "en-GB,en;q=0.9" },
  FR: { domain: "amazon.fr", currency: "EUR", postalCode: "06200", cookie: "i18n-prefs=EUR; lc-acbfr=en_GB", lang: "en-GB,en;q=0.9" },
  IT: { domain: "amazon.it", currency: "EUR", postalCode: "50121", cookie: "i18n-prefs=EUR; lc-acbit=en_GB", lang: "en-GB,en;q=0.9" },
  ES: { domain: "amazon.es", currency: "EUR", postalCode: "08007", cookie: "i18n-prefs=EUR; lc-acbes=en_GB", lang: "en-GB,en;q=0.9" },
};

const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";

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

const argv = new Map(
  process.argv.slice(2).map((arg, index, args) => {
    if (!arg.startsWith("--")) return [arg, true];
    const [key, inlineValue] = arg.slice(2).split("=");
    return [key, inlineValue ?? args[index + 1] ?? true];
  })
);

const inputPath = String(argv.get("input") || "competitor_asin_seed.csv");
const outputDir = String(argv.get("output-dir") || "snapshots");
const latestPath = String(argv.get("latest") || "latest_snapshot.csv");
const delayMs = Number(argv.get("delay-ms") || 5000);
const dryRun = argv.has("dry-run");

if (argv.has("help")) {
  console.log(`Usage: node scripts/scrape_amazon.mjs [--input competitor_asin_seed.csv] [--output-dir snapshots] [--latest latest_snapshot.csv] [--delay-ms 5000] [--dry-run]`);
  process.exit(0);
}

function decode(value = "") {
  return String(value)
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&nbsp;/gi, " ")
    .replace(/&euro;/gi, "€")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">");
}

function stripHtml(value = "") {
  return decode(value)
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

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

function match(html, regex) {
  const result = html.match(regex);
  return result ? stripHtml(result[1]) : "";
}

function sectionById(html, id, length = 18000) {
  const index = html.indexOf(`id="${id}`);
  return index >= 0 ? html.slice(index, index + length) : "";
}

function firstNonEmpty(...values) {
  return values.find((value) => value && String(value).trim()) || "";
}

function splitSetCookie(value = "") {
  if (!value) return [];
  return value.split(/,(?=\s*[^=;,]+=[^;,]+)/g).map((cookie) => cookie.trim()).filter(Boolean);
}

class CookieJar {
  constructor(initialCookie = "") {
    this.cookies = new Map();
    initialCookie
      .split(";")
      .map((entry) => entry.trim())
      .filter(Boolean)
      .forEach((entry) => {
        const separator = entry.indexOf("=");
        if (separator > 0) this.cookies.set(entry.slice(0, separator), entry.slice(separator + 1));
      });
  }

  addFromResponse(response) {
    const setCookies = typeof response.headers.getSetCookie === "function" ? response.headers.getSetCookie() : splitSetCookie(response.headers.get("set-cookie"));
    setCookies.forEach((cookie) => {
      const [pair] = cookie.split(";");
      const separator = pair.indexOf("=");
      if (separator > 0) this.cookies.set(pair.slice(0, separator), pair.slice(separator + 1));
    });
  }

  header() {
    return [...this.cookies.entries()].map(([key, value]) => `${key}=${value}`).join("; ");
  }
}

function baseHeaders(config, jar, referer = `https://www.${config.domain}/`) {
  return {
    "User-Agent": USER_AGENT,
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": config.lang,
    Cookie: jar.header(),
    Referer: referer,
  };
}

async function fetchWithJar(url, config, jar, options = {}) {
  const response = await fetch(url, {
    redirect: options.redirect || "follow",
    method: options.method || "GET",
    body: options.body,
    headers: {
      ...baseHeaders(config, jar, options.referer),
      ...(options.headers || {}),
    },
  });
  jar.addFromResponse(response);
  return response;
}

function absoluteUrl(domain, url) {
  if (!url) return "";
  return url.startsWith("http") ? url : `https://www.${domain}${url.startsWith("/") ? "" : "/"}${url}`;
}

function extractLocationModal(html, domain) {
  const raw = html.match(/id="nav-global-location-data-modal-action"[^>]*data-a-modal="([^"]+)"/i)?.[1];
  if (!raw) return { url: "", csrf: "" };
  try {
    const modal = JSON.parse(decode(raw));
    return {
      url: absoluteUrl(domain, modal.url || ""),
      csrf: modal.ajaxHeaders?.["anti-csrftoken-a2z"] || "",
    };
  } catch {
    return { url: "", csrf: "" };
  }
}

function extractCsrf(html) {
  return firstNonEmpty(
    html.match(/CSRF_TOKEN\s*:\s*"([^"]+)"/i)?.[1],
    html.match(/name="anti-csrftoken-a2z"[^>]*content="([^"]+)"/i)?.[1],
    html.match(/id="cart-conflicts-anticsrf-token"[^>]*content="([^"]+)"/i)?.[1]
  );
}

function extractDeliveryLocation(html) {
  const line1 = match(html, /id="glow-ingress-line1"[^>]*>([\s\S]*?)<\/span>/i);
  const line2 = match(html, /id="glow-ingress-line2"[^>]*>([\s\S]*?)<\/span>/i);
  const shortLine = match(html, /id="contextualIngressPtLabel_deliveryShortLine"[^>]*>([\s\S]*?)<\/span>/i);
  return firstNonEmpty([line1, line2].filter(Boolean).join(" "), shortLine).trim();
}

function locationStatus(location, config, robot = false) {
  if (robot) return "robot_check";
  if (!config.postalCode) return "location_not_configured";
  if (!location) return "location_missing";
  const expected = config.postalCode.replace(/\s+/g, "").toUpperCase();
  const actual = location.replace(/\s+/g, "").toUpperCase();
  return actual.includes(expected) ? "location_ok" : "location_unverified";
}

async function applyPostalCode(domain, config, jar, productUrl, html) {
  if (!config.postalCode || /Robot Check|captcha|Enter the characters you see below/i.test(html)) return false;
  const modal = extractLocationModal(html, domain);
  let csrf = modal.csrf;

  if (modal.url) {
    const modalResponse = await fetchWithJar(modal.url, config, jar, {
      referer: productUrl,
      headers: {
        Accept: "text/html,*/*",
        "X-Requested-With": "XMLHttpRequest",
        ...(csrf ? { "anti-csrftoken-a2z": csrf } : {}),
      },
    });
    const modalHtml = await modalResponse.text();
    csrf = extractCsrf(modalHtml) || csrf;
  }

  const commonPayload = {
    locationType: "LOCATION_INPUT",
    zipCode: config.postalCode,
    storeContext: "generic",
    deviceType: "web",
    pageType: "Detail",
    actionSource: "glow",
  };
  const csrfHeader = csrf ? { "anti-csrftoken-a2z": csrf } : {};

  const oldForm = new URLSearchParams(commonPayload);
  const oldResponse = await fetchWithJar(`https://www.${domain}/gp/delivery/ajax/address-change.html`, config, jar, {
    method: "POST",
    redirect: "manual",
    referer: productUrl,
    body: oldForm,
    headers: {
      Accept: "application/json, text/javascript, */*; q=0.01",
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      "X-Requested-With": "XMLHttpRequest",
      ...csrfHeader,
    },
  });
  if (oldResponse.ok) return true;

  const newResponse = await fetchWithJar(`https://www.${domain}/portal-migration/hz/glow/address-change?actionSource=glow`, config, jar, {
    method: "POST",
    redirect: "manual",
    referer: productUrl,
    body: JSON.stringify(commonPayload),
    headers: {
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      ...csrfHeader,
    },
  });
  return newResponse.ok;
}

function normalizePrice(raw = "") {
  const clean = stripHtml(raw).replace(/&euro;/i, "€");
  const compact = clean.match(/[$£€]\s*\d+(?:[.,]\d+)?/)?.[0]?.replace(/\s+/g, "") || clean;
  const currency = compact.includes("$") ? "USD" : compact.includes("£") ? "GBP" : compact.includes("€") ? "EUR" : "";
  const value = compact.replace(/,/g, "").match(/\d+(?:\.\d+)?/)?.[0] || "";
  return { raw: compact, value, currency };
}

function extractPrice(html) {
  const core = firstNonEmpty(
    sectionById(html, "corePriceDisplay_desktop_feature_div", 26000),
    sectionById(html, "corePrice_feature_div", 16000),
    sectionById(html, "apex_offerDisplay_desktop", 30000)
  );
  return normalizePrice(
    firstNonEmpty(
      match(core, /id="apex-pricetopay-accessibility-label"[^>]*>([\s\S]*?)<\/span>/i),
      match(core, /class="[^"]*priceToPay[^"]*"[\s\S]*?<span class="a-offscreen">([\s\S]*?)<\/span>/i),
      match(core, /class="a-price[^"]*apex-pricetopay-value[^"]*"[\s\S]*?<span class="a-offscreen">([\s\S]*?)<\/span>/i),
      match(core, /<span class="a-offscreen">([\s\S]*?)<\/span>/i)
    )
  );
}

function extractListPrice(html, currentRaw) {
  const core = firstNonEmpty(
    sectionById(html, "corePriceDisplay_desktop_feature_div", 26000),
    sectionById(html, "corePrice_feature_div", 16000),
    sectionById(html, "apex_offerDisplay_desktop", 30000)
  );
  const basis = firstNonEmpty(
    match(core, /class="[^"]*basisPrice[^"]*"[\s\S]*?<span class="a-offscreen">([\s\S]*?)<\/span>/i),
    match(core, /class="[^"]*a-text-price[^"]*"[\s\S]*?<span class="a-offscreen">([\s\S]*?)<\/span>/i)
  );
  const price = normalizePrice(basis);
  return price.raw && price.raw !== currentRaw ? price : { raw: "", value: "", currency: "" };
}

function extractDiscount(html) {
  const core = firstNonEmpty(
    sectionById(html, "corePriceDisplay_desktop_feature_div", 26000),
    sectionById(html, "corePrice_feature_div", 16000),
    sectionById(html, "apex_offerDisplay_desktop", 30000)
  );
  return firstNonEmpty(
    match(core, /class="[^"]*savingsPercentage[^"]*"[^>]*>([\s\S]*?)<\/span>/i),
    match(core, /with\s+(\d+\s+percent savings)/i)
  ).replace(/^with\s+/i, "-").replace(/\s+percent savings/i, "%");
}

function extractCoupon(html) {
  const snippets = ["couponFeature_feature_div", "promoPriceBlockMessage_feature_div", "vpcButton_feature_div"]
    .map((id) => sectionById(html, id, 10000))
    .join(" ");
  const text = stripHtml(snippets);
  return (
    text.match(/Save\s+\d+%\s+on\s+any\s+\d+(?:\s+or\s+more)?/i)?.[0] ||
    text.match(/save\s+\d+%\s+Shop items/i)?.[0] ||
    match(html, /id="couponText"[^>]*>([\s\S]*?)<\/label>/i)
  );
}

function extractDeal(html) {
  const core = firstNonEmpty(sectionById(html, "corePriceDisplay_desktop_feature_div", 26000), sectionById(html, "apex_offerDisplay_desktop", 30000));
  return firstNonEmpty(
    match(core, /<span[^>]*>([^<]*(?:Limited time deal|Lightning Deal|Deal of the Day|Prime Day Deal|Savings & Sales)[^<]*)<\/span>/i),
    match(core, /class="[^"]*(?:dealBadge|badge)[^"]*"[^>]*>([\s\S]*?(?:Deal|Sale|Offer)[\s\S]*?)<\/span>/i)
  );
}

function extractBrand(html, title, fallback = "") {
  const byline = match(html, /id="bylineInfo"[^>]*>([\s\S]*?)<\/a>/i)
    .replace(/^Visit the\s+/i, "")
    .replace(/\s+Store$/i, "")
    .replace(/^Brand:\s*/i, "")
    .trim();
  if (byline && !/^Amazon\./i.test(byline)) return byline;
  return fallback || title.match(/^([A-Za-z0-9'’&.-]+)/)?.[1] || "";
}

function extractOfferFeature(html, label) {
  const index = html.search(new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  if (index < 0) return "";
  const snippet = html.slice(index, index + 2500);
  return firstNonEmpty(
    match(snippet, /offer-display-feature-text[^>]*>[\s\S]*?<a[^>]*>([\s\S]*?)<\/a>/i),
    match(snippet, /offer-display-feature-text[^>]*>[\s\S]*?<div[^>]*>([\s\S]*?)<\/div>/i)
  );
}

function extractRating(html) {
  const raw = firstNonEmpty(
    match(html, /id="acrPopover"[^>]*title="([^"]+)"/i),
    match(html, /<span class="a-icon-alt">([\s\S]*?out of 5 stars[\s\S]*?)<\/span>/i)
  );
  return raw.match(/\d+(?:[.,]\d+)?/)?.[0]?.replace(",", ".") || "";
}

function extractReviews(html) {
  const raw = firstNonEmpty(
    match(html, /id="acrCustomerReviewText"[^>]*aria-label="([^"]+)"/i),
    match(html, /id="acrCustomerReviewText"[^>]*>([\s\S]*?)<\/span>/i)
  );
  return raw.match(/[\d,.]+/)?.[0]?.replace(/[,.](?=\d{3}\b)/g, "").replace(/,/g, "") || "";
}

function inferCategory(title) {
  return /screen protector|protector pantalla|protector de pantalla|schutzfolie|tempered glass|vetro temperato/i.test(title) ? "Screen Protector" : "";
}

function inferProductLine(title) {
  const mentions = [...new Set(title.match(/iPhone\s*(?:17|17 Pro|16 Pro)/gi) || [])];
  return mentions.join(" / ");
}

async function scrape(row) {
  const config = SITE_CONFIG[row.site];
  if (!config) return { ...row, scrape_status: "unsupported_site", fetched_at: new Date().toISOString() };

  const url = `https://www.${config.domain}/dp/${row.asin}?th=1&psc=1`;
  const jar = new CookieJar(config.cookie);
  let response = await fetchWithJar(url, config, jar);
  let html = await response.text();
  await applyPostalCode(config.domain, config, jar, url, html);
  response = await fetchWithJar(url, config, jar);
  html = await response.text();
  const robot = /Robot Check|captcha|Enter the characters you see below/i.test(html);
  const observerLocation = robot ? "" : extractDeliveryLocation(html);
  const observerLocationStatus = locationStatus(observerLocation, config, robot);
  const title = match(html, /id="productTitle"[^>]*>([\s\S]*?)<\/span>/i);
  const price = robot ? { value: "", raw: "", currency: config.currency } : extractPrice(html);
  const listPrice = robot ? { value: "", raw: "" } : extractListPrice(html, price.raw);

  return {
    ...row,
    marketplace_domain: config.domain,
    url: `https://www.${config.domain}/dp/${row.asin}`,
    observer_postcode: config.postalCode,
    observer_location: observerLocation,
    location_status: observerLocationStatus,
    brand: robot ? row.brand : extractBrand(html, title, row.brand),
    product_line: robot ? row.product_line : inferProductLine(title) || row.product_line,
    category: robot ? row.category : inferCategory(title) || row.category,
    title: robot ? row.title : title || row.title,
    current_price: price.value,
    currency: price.currency || config.currency,
    list_price: listPrice.value,
    discount: robot ? "" : extractDiscount(html),
    coupon_or_promo: robot ? "" : extractCoupon(html),
    deal_badge: robot ? "" : extractDeal(html),
    availability: robot ? "" : match(html, /id="availability"[\s\S]*?<span[^>]*>([\s\S]*?)<\/span>/i),
    rating: robot ? "" : extractRating(html),
    review_count: robot ? "" : extractReviews(html),
    sold_by: robot ? "" : extractOfferFeature(html, "Sold by"),
    ships_from: robot ? "" : firstNonEmpty(extractOfferFeature(html, "Ships from"), extractOfferFeature(html, "Dispatches from")),
    scrape_status: robot ? "robot_check" : response.ok ? "ok" : `http_${response.status}`,
    fetched_at: new Date().toISOString(),
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const inputRows = parseCsv(await fs.readFile(inputPath, "utf8"));
const targets = inputRows.map((row) => ({
  ...row,
  asin: row.asin,
  site: row.site,
  brand: row.brand,
  category: row.category,
  product_line: row.product_line,
}));

if (dryRun) {
  console.log(`Would scrape ${targets.length} rows from ${inputPath} with ${delayMs}ms delay.`);
  process.exit(0);
}

const results = [];
for (const target of targets) {
  try {
    const result = await scrape(target);
    results.push(result);
    console.log(`${result.site} ${result.asin} ${result.scrape_status} ${result.currency} ${result.current_price || "-"}`);
  } catch (error) {
    results.push({ ...target, scrape_status: `error:${error.message}`, fetched_at: new Date().toISOString() });
    console.log(`${target.site} ${target.asin} error:${error.message}`);
  }
  await sleep(delayMs);
}

await fs.mkdir(outputDir, { recursive: true });
const stamp = new Date().toISOString().slice(0, 10);
const snapshotPath = path.join(outputDir, `${stamp}.csv`);
const csv = toCsv(results);
await fs.writeFile(snapshotPath, csv);
await fs.writeFile(latestPath, csv);
console.log(`Wrote ${snapshotPath} and ${latestPath}`);
