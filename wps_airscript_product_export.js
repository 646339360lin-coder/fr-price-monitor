const SHEET_NAME = "产品清单";
const ALLOWED_STATUSES = new Set(["新品", "正常在售"]);
const HEADER_ALIASES = {
  asin: ["ASIN"],
  category: ["类型"],
  style: ["款式"],
  model: ["型号"],
  manufacturer_model: ["厂家型号"],
  spec: ["规格"],
  fnsku: ["FNSKU"],
  isku: ["ISKU", "iSKU"],
  sku: ["SKU"],
  phone_brand: ["手机品牌"],
  product_status: ["产品状态", "状态"],
  source_row: ["序号"],
};

function main() {
  const sheet = Application.Sheets.Item(SHEET_NAME);
  if (!sheet) throw new Error(`找不到工作表：${SHEET_NAME}`);

  const values = sheet.UsedRange.Value2;
  if (!Array.isArray(values) || !values.length || !Array.isArray(values[0])) {
    throw new Error(`工作表“${SHEET_NAME}”没有可读取的二维数据区域`);
  }

  const headers = values[0].map(normalizeHeader);
  const indexes = resolveIndexes(headers);
  const requiredFields = [
    "asin",
    "category",
    "style",
    "model",
    "spec",
    "fnsku",
    "isku",
    "sku",
    "phone_brand",
    "product_status",
  ];
  const missing = requiredFields.filter((field) => indexes[field] === -1);
  if (missing.length) {
    const expected = missing.map((field) => HEADER_ALIASES[field].join("/"));
    throw new Error(`缺少必需表头：${expected.join("、")}`);
  }

  const products = [];
  const nonActiveProducts = [];
  const seen = new Set();
  let skippedInvalidAsin = 0;
  let skippedDuplicate = 0;

  for (let rowIndex = 1; rowIndex < values.length; rowIndex += 1) {
    const row = Array.isArray(values[rowIndex]) ? values[rowIndex] : [];
    const asin = cell(row, indexes.asin).toUpperCase();
    const productStatus = cell(row, indexes.product_status);

    const category = cell(row, indexes.category);
    const style = cell(row, indexes.style);
    const model = cell(row, indexes.model);
    const spec = cell(row, indexes.spec);
    const baseProduct = {
      id: asin || `source-row-${rowIndex + 1}`,
      asin,
      url: /^[A-Z0-9]{10}$/.test(asin) ? `https://www.amazon.fr/dp/${asin}` : "",
      brand: "Tentoki",
      category,
      type: category,
      style,
      model,
      manufacturer_model: cell(row, indexes.manufacturer_model),
      spec,
      phone_brand: cell(row, indexes.phone_brand),
      sku: cell(row, indexes.sku),
      isku: cell(row, indexes.isku),
      fnsku: cell(row, indexes.fnsku),
      source_row: cell(row, indexes.source_row) || String(rowIndex + 1),
      product_status: productStatus,
      name: [category, style, model, spec].filter(Boolean).join(" "),
    };

    if (!ALLOWED_STATUSES.has(productStatus)) {
      if (asin || baseProduct.sku || baseProduct.isku || baseProduct.fnsku) {
        nonActiveProducts.push({ ...baseProduct, enabled: false });
      }
      continue;
    }
    if (!/^[A-Z0-9]{10}$/.test(asin)) {
      skippedInvalidAsin += 1;
      continue;
    }
    if (seen.has(asin)) {
      skippedDuplicate += 1;
      continue;
    }
    seen.add(asin);

    products.push({
      ...baseProduct,
      enabled: true,
    });
  }

  return {
    schema_version: 1,
    source: "WPS AirScript",
    file_name: Application.FileInfo && Application.FileInfo.name,
    sheet_name: SHEET_NAME,
    generated_at: new Date().toISOString(),
    filters: { product_status: [...ALLOWED_STATUSES] },
    stats: {
      source_rows: Math.max(0, values.length - 1),
      exported_products: products.length,
      exported_non_active_products: nonActiveProducts.length,
      skipped_invalid_asin: skippedInvalidAsin,
      skipped_duplicate: skippedDuplicate,
    },
    products,
    non_active_products: nonActiveProducts,
  };
}

function resolveIndexes(headers) {
  const indexes = {};
  Object.keys(HEADER_ALIASES).forEach((field) => {
    const aliases = HEADER_ALIASES[field].map(normalizeHeader);
    indexes[field] = headers.findIndex((header) => aliases.includes(header));
  });
  return indexes;
}

function normalizeHeader(value) {
  return String(value == null ? "" : value)
    .replace(/\s+/g, "")
    .replace(/[（(].*?[）)]/g, "")
    .trim();
}

function cell(row, index) {
  if (index < 0 || index >= row.length) return "";
  return String(row[index] == null ? "" : row[index]).trim();
}

return main();
