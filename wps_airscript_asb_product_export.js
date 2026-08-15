const SHEET_NAME = "产品清单";
const ACCOUNT_KEY = "asb";
const TARGET_ACCOUNT = "ASB";
const DEFAULT_BRAND = "Tentoki";
const HEADER_SEARCH_ROWS = 30;

const HEADER_ALIASES = {
  source_row: ["序号", "编号"],
  source_account: ["账号", "账户", "店铺", "产品线", "所属账号", "所属账户"],
  created_at: ["创建日期", "创建时间", "日期"],
  asin: ["ASIN", "Asin", "asin"],
  category: ["类型", "产品类型", "品类"],
  style: ["款式", "产品款式"],
  model: ["型号", "适用型号", "手机型号"],
  manufacturer_model: ["厂家型号", "工厂型号"],
  spec: ["规格", "颜色", "尺寸"],
  fnsku: ["FNSKU", "Fnsku", "fnsku"],
  isku: ["ISKU", "iSKU", "Isku", "isku"],
  sku: ["SKU", "Sku", "sku"],
  phone_brand: ["手机品牌", "适用品牌", "机型品牌"],
  product_status: ["产品状态", "状态", "销售状态"],
  brand: ["品牌", "产品品牌"],
  remark_1: ["备注1", "备注 1", "备注一", "备注"],
  remark_2: ["备注2", "备注 2", "备注二"],
  remark_3: ["备注3", "备注 3", "备注三"],
};

function main() {
  const sheet = Application.Sheets.Item(SHEET_NAME);
  if (!sheet) {
    throw new Error("找不到工作表：" + SHEET_NAME);
  }

  const values = sheet.UsedRange.Value2;
  if (!Array.isArray(values) || !values.length) {
    throw new Error("工作表没有可读取的数据：" + SHEET_NAME);
  }

  const headerRowIndex = findHeaderRow(values);
  if (headerRowIndex < 0) {
    throw new Error("前 " + HEADER_SEARCH_ROWS + " 行中找不到 ASIN 表头");
  }

  const headers = values[headerRowIndex].map(normalizeHeader);
  const indexes = resolveIndexes(headers);
  if (indexes.asin < 0) {
    throw new Error("缺少必需表头：ASIN");
  }

  const productsByAsin = {};
  const productOrder = [];
  const nonActiveProducts = [];
  let sourceRows = 0;
  let skippedBlankRows = 0;
  let skippedInvalidAsin = 0;
  let skippedDuplicateAsin = 0;
  let skippedOtherAccounts = 0;

  for (let rowIndex = headerRowIndex + 1; rowIndex < values.length; rowIndex += 1) {
    const row = Array.isArray(values[rowIndex]) ? values[rowIndex] : [];
    if (isBlankRow(row)) {
      skippedBlankRows += 1;
      continue;
    }

    sourceRows += 1;
    const sourceAccount = cell(row, indexes.source_account);
    if (indexes.source_account >= 0 && sourceAccount && !isTargetAccount(sourceAccount)) {
      skippedOtherAccounts += 1;
      continue;
    }
    const item = buildProduct(row, indexes, rowIndex + 1);
    if (isValidAsin(item.asin)) {
      if (productsByAsin[item.asin]) {
        productsByAsin[item.asin] = mergeMissingFields(productsByAsin[item.asin], item);
        skippedDuplicateAsin += 1;
      } else {
        productsByAsin[item.asin] = item;
        productOrder.push(item.asin);
      }
      continue;
    }

    if (item.asin) {
      skippedInvalidAsin += 1;
    }
    nonActiveProducts.push({
      ...item,
      enabled: false,
      url: "",
    });
  }

  const products = productOrder.map(function (asin) {
    return productsByAsin[asin];
  });

  return {
    schema_version: 1,
    account_key: ACCOUNT_KEY,
    source: "WPS AirScript: ASB和XND备货表格-20250730 / 产品清单",
    file_name: Application.FileInfo && Application.FileInfo.name
      ? Application.FileInfo.name
      : "",
    sheet_name: SHEET_NAME,
    generated_at: new Date().toISOString(),
    filters: {
      product_status: "all",
      valid_asin_required: true,
    },
    stats: {
      header_row: headerRowIndex + 1,
      source_rows: sourceRows,
      exported_products: products.length,
      exported_non_active_products: nonActiveProducts.length,
      skipped_blank_rows: skippedBlankRows,
      skipped_invalid_asin: skippedInvalidAsin,
      skipped_duplicate_asin: skippedDuplicateAsin,
      skipped_other_accounts: skippedOtherAccounts,
      account_column_found: indexes.source_account >= 0,
    },
    products: products,
    non_active_products: nonActiveProducts,
  };
}

function buildProduct(row, indexes, physicalRow) {
  const asin = cell(row, indexes.asin).toUpperCase();
  const category = cell(row, indexes.category);
  const style = cell(row, indexes.style);
  const model = cell(row, indexes.model);
  const spec = cell(row, indexes.spec);
  const sourceRow = cell(row, indexes.source_row) || String(physicalRow);

  return {
    account_key: ACCOUNT_KEY,
    source_account: cell(row, indexes.source_account),
    id: isValidAsin(asin) ? asin : "source-row-" + physicalRow,
    asin: asin,
    url: isValidAsin(asin) ? "https://www.amazon.com/dp/" + asin : "",
    brand: cell(row, indexes.brand) || DEFAULT_BRAND,
    category: category,
    type: category,
    style: style,
    model: model,
    manufacturer_model: cell(row, indexes.manufacturer_model),
    spec: spec,
    phone_brand: cell(row, indexes.phone_brand),
    sku: cell(row, indexes.sku),
    isku: cell(row, indexes.isku),
    fnsku: cell(row, indexes.fnsku),
    source_row: sourceRow,
    created_at: cell(row, indexes.created_at),
    product_status: cell(row, indexes.product_status),
    remark_1: cell(row, indexes.remark_1),
    remark_2: cell(row, indexes.remark_2),
    remark_3: cell(row, indexes.remark_3),
    name: [category, style, model, spec].filter(Boolean).join(" "),
    enabled: isValidAsin(asin),
  };
}

function findHeaderRow(values) {
  const limit = Math.min(values.length, HEADER_SEARCH_ROWS);
  for (let rowIndex = 0; rowIndex < limit; rowIndex += 1) {
    const row = Array.isArray(values[rowIndex]) ? values[rowIndex] : [];
    const headers = row.map(normalizeHeader);
    const asinAliases = HEADER_ALIASES.asin.map(normalizeHeader);
    if (headers.some(function (header) { return asinAliases.includes(header); })) {
      return rowIndex;
    }
  }
  return -1;
}

function resolveIndexes(headers) {
  const indexes = {};
  Object.keys(HEADER_ALIASES).forEach(function (field) {
    const aliases = HEADER_ALIASES[field].map(normalizeHeader);
    indexes[field] = headers.findIndex(function (header) {
      return aliases.includes(header);
    });
  });
  return indexes;
}

function normalizeHeader(value) {
  return String(value == null ? "" : value)
    .replace(/\s+/g, "")
    .replace(/[（(][^）)]*[）)]/g, "")
    .trim();
}

function cell(row, index) {
  if (index == null || index < 0 || index >= row.length) {
    return "";
  }
  return String(row[index] == null ? "" : row[index]).trim();
}

function isBlankRow(row) {
  return !row.some(function (value) {
    return String(value == null ? "" : value).trim() !== "";
  });
}

function isValidAsin(value) {
  return /^[A-Z0-9]{10}$/.test(String(value || "").toUpperCase());
}

function isTargetAccount(value) {
  return String(value == null ? "" : value)
    .toUpperCase()
    .replace(/\s+/g, "")
    .includes(TARGET_ACCOUNT);
}

function mergeMissingFields(current, incoming) {
  const merged = { ...current };
  Object.keys(incoming).forEach(function (key) {
    if ((merged[key] == null || merged[key] === "") && incoming[key] != null && incoming[key] !== "") {
      merged[key] = incoming[key];
    }
  });
  return merged;
}

return main();
