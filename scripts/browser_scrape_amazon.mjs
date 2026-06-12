#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

const SITE_CONFIG = {
  US: { domain: "amazon.com", currency: "USD", postalCode: "90001", lang: "en-US,en;q=0.9", localeCookieName: "lc-main", localeCookie: "en_US" },
  UK: { domain: "amazon.co.uk", currency: "GBP", postalCode: "WC1E 7HU", lang: "en-GB,en;q=0.9", localeCookieName: "lc-acbuk", localeCookie: "en_GB" },
  DE: { domain: "amazon.de", currency: "EUR", postalCode: "10115", lang: "de-DE,de;q=0.9,en;q=0.8", localeCookieName: "lc-acbde", localeCookie: "de_DE" },
  FR: { domain: "amazon.fr", currency: "EUR", postalCode: "06200", lang: "fr-FR,fr;q=0.9,en;q=0.8", localeCookieName: "lc-acbfr", localeCookie: "fr_FR" },
  IT: { domain: "amazon.it", currency: "EUR", postalCode: "50121", lang: "it-IT,it;q=0.9,en;q=0.8", localeCookieName: "lc-acbit", localeCookie: "it_IT" },
  ES: { domain: "amazon.es", currency: "EUR", postalCode: "08007", lang: "es-ES,es;q=0.9,en;q=0.8", localeCookieName: "lc-acbes", localeCookie: "es_ES" },
};

const TARGET_PRODUCT_LINES = new Set(["清水壳-3in1", "清水壳-单壳", "一代除尘仓"]);
const CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
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
const userDataDir = String(argv.get("profile") || ".amazon-browser-profile");
const samplePerGroup = Number(argv.get("sample-per-group") || 1);
const maxRows = Number(argv.get("max-rows") || 0);
const delayMs = Number(argv.get("delay-ms") || 3000);
const headless = argv.get("headless") === "true";
const updateInput = !argv.has("no-update-input");

if (argv.has("help")) {
  console.log(`Usage: node scripts/browser_scrape_amazon.mjs [--input competitor_asin_seed.csv] [--sample-per-group 1] [--max-rows 0] [--delay-ms 3000] [--headless true] [--no-update-input]`);
  process.exit(0);
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function selectSamples(rows) {
  const targetRows = rows.filter((row) => TARGET_PRODUCT_LINES.has(row.product_line));
  const byGroup = new Map();

  targetRows.forEach((row) => {
    const key = `${row.product_line}:${row.site}`;
    if (!byGroup.has(key)) byGroup.set(key, []);
    byGroup.get(key).push(row);
  });

  const samples = [];
  [...byGroup.keys()].sort().forEach((key) => {
    const groupRows = byGroup
      .get(key)
      .sort((a, b) => {
        const aPending = a.scrape_status === "pending_manual" ? 0 : 1;
        const bPending = b.scrape_status === "pending_manual" ? 0 : 1;
        return aPending - bPending || (a.asin || "").localeCompare(b.asin || "");
      })
      .slice(0, samplePerGroup);
    samples.push(...groupRows);
  });

  return maxRows > 0 ? samples.slice(0, maxRows) : samples;
}

function normalizePrice(raw = "") {
  const compact = String(raw).replace(/\s+/g, " ").trim();
  const symbol = compact.match(/[$£€]/)?.[0] || "";
  const number = compact.match(/\d+(?:[.,]\d{2})?/)?.[0] || "";
  const currency = compact.match(/\bUSD\b/i)
    ? "USD"
    : compact.match(/\bGBP\b/i)
      ? "GBP"
      : compact.match(/\bEUR\b/i)
        ? "EUR"
        : symbol === "$"
          ? "USD"
          : symbol === "£"
            ? "GBP"
            : symbol === "€"
              ? "EUR"
              : "";
  return {
    value: number.replace(/\.(?=\d{3}\b)/g, "").replace(",", "."),
    currency,
  };
}

function locationStatus(location, config, robot = false) {
  if (robot) return "robot_check";
  if (!config.postalCode) return "location_not_configured";
  if (!location) return "location_missing";
  const expected = config.postalCode.replace(/\s+/g, "").toUpperCase();
  const actual = location.replace(/\s+/g, "").toUpperCase();
  return actual.includes(expected) ? "location_ok" : "location_unverified";
}

function cleanBrand(value = "") {
  return String(value)
    .replace(/^Visit the\s+/i, "")
    .replace(/^Besuche den\s+/i, "")
    .replace(/^Visitez la boutique\s+/i, "")
    .replace(/^Visita lo Store di\s+/i, "")
    .replace(/^Visita la tienda de\s+/i, "")
    .replace(/\s+Store$/i, "")
    .replace(/-Store$/i, "")
    .trim();
}

async function setupPage(page, config) {
  await page.setUserAgent(USER_AGENT);
  await page.setExtraHTTPHeaders({ "Accept-Language": config.lang });
  await page.setViewport({ width: 1366, height: 900 });
  await page.evaluateOnNewDocument(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
  });
}

async function setSitePreferences(page, config) {
  const cookieUrl = `https://www.${config.domain}/`;
  await page.setCookie(
    { name: "i18n-prefs", value: config.currency, url: cookieUrl },
    { name: config.localeCookieName, value: config.localeCookie, url: cookieUrl }
  );
}

async function isRobotPage(page) {
  const text = await page.evaluate(() => document.body?.innerText || "");
  return /Robot Check|Enter the characters|captcha|Type the characters/i.test(text);
}

async function readLocation(page) {
  return page.evaluate(() => {
    const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const line1 = clean(document.querySelector("#glow-ingress-line1")?.textContent);
    const line2 = clean(document.querySelector("#glow-ingress-line2")?.textContent);
    const shortLine = clean(document.querySelector("#contextualIngressPtLabel_deliveryShortLine")?.textContent);
    return [line1, line2].filter(Boolean).join(" ") || shortLine;
  });
}

async function clickIfPresent(page, selector, timeout = 2500) {
  try {
    await page.waitForSelector(selector, { visible: true, timeout });
    await page.click(selector);
    return true;
  } catch {
    return false;
  }
}

async function setPostalCode(page, config) {
  const current = await readLocation(page);
  if (locationStatus(current, config) === "location_ok") return "already_set";

  const opened =
    (await clickIfPresent(page, "#nav-global-location-popover-link", 4000)) ||
    (await clickIfPresent(page, "#nav-global-location-data-modal-action", 4000));
  if (!opened) return "location_modal_missing";

  try {
    await page.waitForSelector("#GLUXZipUpdateInput, #GLUXZipUpdateInput_0", { visible: true, timeout: 7000 });
  } catch {
    return (await isRobotPage(page)) ? "robot_check" : "postal_input_missing";
  }

  const inputSelector = (await page.$("#GLUXZipUpdateInput")) ? "#GLUXZipUpdateInput" : "#GLUXZipUpdateInput_0";
  await page.click(inputSelector, { clickCount: 3 });
  await page.keyboard.press("Backspace");
  await page.type(inputSelector, config.postalCode, { delay: 35 });

  if (!(await clickIfPresent(page, "#GLUXZipUpdate", 2000))) {
    await page.keyboard.press("Enter");
  }

  await sleep(2500);
  await clickIfPresent(page, "#GLUXConfirmClose, button[name='glowDoneButton']", 2500);
  await sleep(1500);
  return "location_submitted";
}

async function extractProduct(page, fallback, config) {
  return page.evaluate(
    ({ fallback, config }) => {
      const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const visibleText = (node) => clean(node?.innerText || node?.textContent);
      const textOf = (selector) => visibleText(document.querySelector(selector));
      const attrOf = (selector, attr) => clean(document.querySelector(selector)?.getAttribute(attr));
      const firstText = (...selectors) => {
        for (const selector of selectors) {
          const value = textOf(selector);
          if (value) return value;
        }
        return "";
      };
      const priceRoot =
        document.querySelector("#corePriceDisplay_desktop_feature_div") ||
        document.querySelector("#corePrice_feature_div") ||
        document.querySelector("#apex_offerDisplay_desktop") ||
        document;
      const priceText = clean(
        priceRoot.querySelector("#apex-pricetopay-accessibility-label")?.textContent ||
          priceRoot.querySelector(".priceToPay .a-offscreen")?.textContent ||
          priceRoot.querySelector(".a-price .a-offscreen")?.textContent
      );
      const listPriceText = clean(
        priceRoot.querySelector(".basisPrice .a-offscreen")?.textContent ||
          priceRoot.querySelector(".a-text-price .a-offscreen")?.textContent
      );
      const couponText = clean(
        visibleText(document.querySelector("#couponText")) ||
          visibleText(document.querySelector("#couponFeature_feature_div label")) ||
          visibleText(document.querySelector("[id*='couponText']"))
      );
      const dealCandidates = [
        "#dealBadge_feature_div",
        "#dealBadgeSupportingText",
        "#corePriceDisplay_desktop_feature_div [class*='dealBadge']",
        "#corePriceDisplay_desktop_feature_div [class*='badge']",
        "#apex_offerDisplay_desktop [class*='dealBadge']",
      ]
        .map((selector) => visibleText(document.querySelector(selector)))
        .filter(Boolean);
      const dealText =
        dealCandidates.find((text) =>
          /^(Limited time deal|Lightning Deal|Deal of the Day|Prime Day Deal|Zeitlich begrenztes Angebot|Offre à durée limitée|Offerta a tempo limitato|Oferta por tiempo limitado)$/i.test(text)
        ) || "";
      const line1 = textOf("#glow-ingress-line1");
      const line2 = textOf("#glow-ingress-line2");
      const shortLine = textOf("#contextualIngressPtLabel_deliveryShortLine");
      const observerLocation = [line1, line2].filter(Boolean).join(" ") || shortLine;
      const seller = firstText("#sellerProfileTriggerId", "#merchant-info a", "#merchant-info");
      const shipsFrom = firstText("#fulfillerInfoFeature_feature_div .offer-display-feature-text", "#tabular-buybox .tabular-buybox-text");
      const ratingRaw = attrOf("#acrPopover", "title") || firstText("#acrPopover .a-icon-alt", ".reviewCountTextLinkedHistogram .a-icon-alt");
      const reviewRaw = attrOf("#acrCustomerReviewText", "aria-label") || textOf("#acrCustomerReviewText");

      return {
        title: textOf("#productTitle") || fallback.title || "",
        brand: firstText("#bylineInfo") || fallback.brand || "",
        priceText,
        listPriceText,
        discount: firstText(".savingsPercentage"),
        coupon_or_promo: couponText,
        deal_badge: dealText,
        availability: firstText("#availability span", "#availability").replace(/P\.when\([\s\S]*$/i, "").trim(),
        rating: (ratingRaw.match(/\d+(?:[.,]\d+)?/) || [""])[0].replace(",", "."),
        review_count: (reviewRaw.match(/[\d,.]+/) || [""])[0].replace(/[,.](?=\d{3}\b)/g, "").replace(/,/g, ""),
        sold_by: seller.replace(/^Sold by\\s*/i, ""),
        ships_from: shipsFrom.replace(/^Ships from\\s*/i, ""),
        observer_location: observerLocation,
        currency: config.currency,
      };
    },
    { fallback, config }
  );
}

async function scrapeRow(browser, row) {
  const config = SITE_CONFIG[row.site];
  if (!config) return { ...row, scrape_status: "unsupported_site", fetched_at: new Date().toISOString() };

  const page = await browser.newPage();
  await setupPage(page, config);
  await setSitePreferences(page, config);
  const url = `https://www.${config.domain}/dp/${row.asin}?th=1&psc=1`;

  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await sleep(2500);

    if (await isRobotPage(page)) {
      return {
        ...row,
        marketplace_domain: config.domain,
        url: `https://www.${config.domain}/dp/${row.asin}`,
        observer_postcode: config.postalCode,
        observer_location: "",
        location_status: "robot_check",
        scrape_status: "robot_check",
        fetched_at: new Date().toISOString(),
      };
    }

    await setPostalCode(page, config);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await sleep(3000);

    const robot = await isRobotPage(page);
    const extracted = robot ? { observer_location: "" } : await extractProduct(page, row, config);
    const price = normalizePrice(extracted.priceText);
    const listPrice = normalizePrice(extracted.listPriceText);
    const currencyMismatch = Boolean(price.value && price.currency && price.currency !== config.currency);
    const listPriceValue = Number(listPrice.value);
    const priceValue = Number(price.value);
    const validListPrice = Boolean(listPrice.value && (!price.value || listPriceValue > priceValue));
    const unavailable = /Derzeit nicht verfügbar|Currently unavailable|Temporairement indisponible|Non disponibile|No disponible|out of stock/i.test(extracted.availability || "");

    return {
      ...row,
      marketplace_domain: config.domain,
      url: `https://www.${config.domain}/dp/${row.asin}`,
      observer_postcode: config.postalCode,
      observer_location: extracted.observer_location || "",
      location_status: locationStatus(extracted.observer_location || "", config, robot),
      brand: robot ? row.brand : cleanBrand(extracted.brand) || row.brand,
      title: robot ? row.title : extracted.title || row.title,
      current_price: robot || currencyMismatch ? row.current_price : price.value,
      currency: price.currency || row.currency || config.currency,
      list_price: robot || currencyMismatch ? row.list_price : validListPrice ? listPrice.value : "",
      discount: robot ? row.discount : extracted.discount,
      coupon_or_promo: robot ? row.coupon_or_promo : extracted.coupon_or_promo,
      deal_badge: robot ? row.deal_badge : extracted.deal_badge,
      availability: robot ? row.availability : extracted.availability,
      rating: robot ? row.rating : extracted.rating,
      review_count: robot ? row.review_count : extracted.review_count,
      sold_by: robot ? row.sold_by : extracted.sold_by,
      ships_from: robot ? row.ships_from : extracted.ships_from,
      scrape_status: robot ? "robot_check" : currencyMismatch ? `currency_mismatch:${price.currency}` : unavailable ? "unavailable_browser" : price.value ? "ok_browser" : "price_missing_browser",
      fetched_at: new Date().toISOString(),
    };
  } catch (error) {
    return {
      ...row,
      marketplace_domain: config.domain,
      url: `https://www.${config.domain}/dp/${row.asin}`,
      observer_postcode: config.postalCode,
      scrape_status: `error:${error.message}`,
      fetched_at: new Date().toISOString(),
    };
  } finally {
    await page.close().catch(() => {});
  }
}

function mergeRows(inputRows, results) {
  const byKey = new Map(inputRows.map((row) => [`${row.site}:${row.asin}`, row]));
  results.forEach((result) => {
    const key = `${result.site}:${result.asin}`;
    const previous = byKey.get(key) || {};
    byKey.set(key, {
      ...previous,
      ...result,
      product_line: result.product_line || previous.product_line,
      category: result.category || previous.category,
      title: result.title || previous.title,
    });
  });
  return [...byKey.values()].sort(
    (a, b) =>
      (a.product_line || "").localeCompare(b.product_line || "") ||
      (a.site || "").localeCompare(b.site || "") ||
      (a.asin || "").localeCompare(b.asin || "")
  );
}

await fs.mkdir(userDataDir, { recursive: true });
const inputRows = parseCsv(await fs.readFile(inputPath, "utf8"));
const targets = selectSamples(inputRows);
console.log(`Browser sample target rows: ${targets.length}`);

const browser = await puppeteer.launch({
  executablePath: CHROME_PATH,
  headless,
  userDataDir,
  defaultViewport: null,
  args: ["--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled"],
});

const results = [];
try {
  for (const target of targets) {
    const result = await scrapeRow(browser, target);
    results.push(result);
    console.log(`${result.site} ${result.asin} ${result.scrape_status} ${result.currency || ""} ${result.current_price || "-"} ${result.location_status || ""}`);
    await sleep(delayMs);
  }
} finally {
  await browser.close();
}

await fs.mkdir(outputDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const samplePath = path.join(outputDir, `browser-sample-${stamp}.csv`);
await fs.writeFile(samplePath, `${toCsv(results)}\n`);
if (updateInput) {
  await fs.writeFile(inputPath, `${toCsv(mergeRows(inputRows, results))}\n`);
}
console.log(`Wrote ${samplePath}${updateInput ? ` and updated ${inputPath}` : ""}`);
