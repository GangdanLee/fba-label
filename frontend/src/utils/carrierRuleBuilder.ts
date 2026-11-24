/** 货代箱唛免正则关键词转义构建器与常见货代模板预设。 */

import type { CarrierRule } from "../types";

export interface CarrierRulePreset {
  id: string;
  label: string;
  description: string;
  rule: CarrierRule;
  shipmentKeywords: string;
  warehouseKeywords: string;
  ctnKeywords: string;
}

export function escapeRegexLiteral(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function splitKeywords(raw: string): string[] {
  return raw
    .split(/[,，、;；\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 根据用户填写的前缀关键词自动生成安全的正则（带标准捕获组）。 */
export function buildRegexFromKeywords(
  kind: "shipment" | "warehouse" | "ctn",
  rawKeywords: string,
): string {
  const words = splitKeywords(rawKeywords);
  if (!words.length) return "";
  const joined = words.map(escapeRegexLiteral).join("|");
  if (kind === "shipment") {
    return `(?:${joined})[:：\\s#-]*([A-Z0-9-]{6,20})`;
  }
  if (kind === "warehouse") {
    return `(?:${joined})[:：\\s#-]*([A-Z]{3}\\d)`;
  }
  return `(?:${joined})[:：\\s#-]*(\\d+)\\s*(?:/|of|OF|\\|)\\s*(\\d+)`;
}

export const CARRIER_RULE_PRESETS: CarrierRulePreset[] = [
  {
    id: "preset_general_cn",
    label: "常见海派/空派中文箱唛（进仓号 / 目的仓 / 件数）",
    description: "匹配如「进仓号: FBA...」「目的仓: ONT8」「件数: 1/5」等通用中文箱唛格式",
    shipmentKeywords: "进仓号, FBA单号, 货件号, FBA#, Shipment ID",
    warehouseKeywords: "目的仓, 仓库代码, 仓库, DEST, FC",
    ctnKeywords: "箱号, 件数, 箱数, CTN, CTNS",
    rule: {
      id: "",
      name: "通用中文海派箱唛",
      shipment_regex: buildRegexFromKeywords("shipment", "进仓号, FBA单号, 货件号, FBA#, Shipment ID"),
      warehouse_regex: buildRegexFromKeywords("warehouse", "目的仓, 仓库代码, 仓库, DEST, FC"),
      ctn_regex: buildRegexFromKeywords("ctn", "箱号, 件数, 箱数, CTN, CTNS"),
      default_rotate: 0,
      enabled: true,
    },
  },
  {
    id: "preset_express_en",
    label: "英文专线/快递箱唛（SHIP_NO / DEST / CARTON X OF Y）",
    description: "匹配如「SHIP_NO: FBA...」「DEST: LAX9」「CARTON 2 OF 5」英文模板",
    shipmentKeywords: "SHIP_NO, SHIPMENT, REF_NO, FBA_NO",
    warehouseKeywords: "DEST, WAREHOUSE, TO_FC",
    ctnKeywords: "CARTON, BOX, CTNS",
    rule: {
      id: "",
      name: "英文专线箱唛规则",
      shipment_regex: buildRegexFromKeywords("shipment", "SHIP_NO, SHIPMENT, REF_NO, FBA_NO"),
      warehouse_regex: buildRegexFromKeywords("warehouse", "DEST, WAREHOUSE, TO_FC"),
      ctn_regex: buildRegexFromKeywords("ctn", "CARTON, BOX, CTNS"),
      default_rotate: 0,
      enabled: true,
    },
  },
  {
    id: "preset_matson_3pl",
    label: "美森限时达/海外仓调拨（客户单号 / 仓点 / 第X箱）",
    description: "匹配如「客户单号: FBA...」「海外仓/仓点: SCK4」「CTN: 1/3」",
    shipmentKeywords: "客户单号, 订单号, FBA编号",
    warehouseKeywords: "仓点, 目的港仓, WH",
    ctnKeywords: "箱序, 编号, CTN",
    rule: {
      id: "",
      name: "美森海外仓专线规则",
      shipment_regex: buildRegexFromKeywords("shipment", "客户单号, 订单号, FBA编号"),
      warehouse_regex: buildRegexFromKeywords("warehouse", "仓点, 目的港仓, WH"),
      ctn_regex: buildRegexFromKeywords("ctn", "箱序, 编号, CTN"),
      default_rotate: 0,
      enabled: true,
    },
  },
];
