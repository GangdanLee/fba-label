import type { CanvasElement } from "../types";

const CODE128_PATTERNS: string[] = [
  "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
  "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
  "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
  "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
  "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
  "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
  "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
  "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
  "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
  "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
  "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
  "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
  "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
  "211214", "211232", "2331112",
];

export interface EncodedBarcode {
  code: string;
  bars: Array<{ x: number; w: number }>;
  totalWidth: number;
}

export function encodeCode128B(text: string): EncodedBarcode {
  const clean = (text || "X000DEMO01").replace(/[^\x20-\x7e]/g, "-") || "X000DEMO01";
  const codes: number[] = [104];
  let sum = 104;
  for (let i = 0; i < clean.length; i += 1) {
    const val = clean.charCodeAt(i) - 32;
    codes.push(val);
    sum += val * (i + 1);
  }
  codes.push(sum % 103);
  codes.push(106);

  const bars: Array<{ x: number; w: number }> = [];
  let pos = 0;
  for (const sym of codes) {
    const pat = CODE128_PATTERNS[sym];
    for (let j = 0; j < pat.length; j += 1) {
      const w = parseInt(pat[j], 10);
      if (j % 2 === 0) bars.push({ x: pos, w });
      pos += w;
    }
  }
  return { code: clean, bars, totalWidth: pos };
}

export function evaluateBarcodeDots(
  code: string,
  widthMm: number,
  dpi: 203 | 300 = 203,
): {
  dpm: number;
  level: "safe" | "warn" | "danger";
  message: string;
} {
  const enc = encodeCode128B(code);
  const dpm = (widthMm * (dpi / 25.4)) / (enc.totalWidth + 20);
  if (dpm < 1.35) {
    return { dpm, level: "danger", message: `条码过细（${dpi}dpi 下 <1.35 dots/module），建议拉宽条码框` };
  }
  if (dpm < 2.0) {
    return { dpm, level: "warn", message: `接近 ${dpi}dpi 最小安全宽度，建议适当拉宽条码框` };
  }
  return { dpm, level: "safe", message: `✓ 条码粗细适中，${dpi}dpi 打印清晰易扫` };
}

export function createDefaultElementsForSpec(
  widthMm: number,
  heightMm: number,
  fnsku = "X000DEMO01",
  title = "New - Demo Product Item (DEMO-SKU-01)",
): CanvasElement[] {
  const padX = widthMm <= 42 ? 1.5 : Math.max(2, Math.round(widthMm * 0.06 * 10) / 10);
  const innerW = Math.max(12, Math.round((widthMm - padX * 2) * 10) / 10);
  const bcH = Math.max(9, Math.min(20, Math.round(heightMm * 0.48 * 10) / 10));
  const titleY = Math.round((1.8 + bcH + 0.8) * 10) / 10;
  const micY = Math.max(titleY + 5, Math.round((heightMm - 4.8) * 10) / 10);

  return [
    {
      id: `el_${Date.now()}_bc`,
      type: "barcode1d",
      name: "FNSKU 条码",
      x: padX,
      y: 1.5,
      w: innerW,
      h: bcH,
      rotate: 0,
      locked: false,
      code: fnsku,
      showText: true,
      fontSize: heightMm >= 40 ? 9.5 : 8.5,
    },
    {
      id: `el_${Date.now()}_title`,
      type: "text",
      name: "商品名称",
      x: padX,
      y: titleY,
      w: innerW,
      h: Math.max(5.5, micY - titleY - 0.8),
      rotate: 0,
      locked: false,
      text: title,
      fontSize: heightMm >= 40 ? 8.0 : 7.0,
      lineHeight: 1.2,
      align: "left",
      bold: false,
      italic: false,
    },
    {
      id: `el_${Date.now()}_mic`,
      type: "text",
      name: "产地标识",
      x: padX,
      y: micY,
      w: Math.round(innerW * 0.55 * 10) / 10,
      h: 3.6,
      rotate: 0,
      locked: false,
      text: "Made in China",
      fontSize: 7.5,
      lineHeight: 1.1,
      align: "left",
      bold: true,
      italic: false,
    },
  ];
}
