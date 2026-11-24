import { encodeCode128B } from "./code128";

const MM_TO_PT = 72 / 25.4;

function pdfEsc(str: string): string {
  return str.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function pt(mm: number): string {
  return (mm * MM_TO_PT).toFixed(2);
}

/** 构造 100% 合法的多页矢量 PDF 文件字节（纯前端生成虚构测试示例，绝不内置任何真实商家数据）。 */
function buildPdfFileFromPageStreams(
  pageWidthMm: number,
  pageHeightMm: number,
  pageStreams: string[],
  fileName: string,
): File {
  const pw = pt(pageWidthMm);
  const ph = pt(pageHeightMm);

  const objects: string[] = [];
  // obj 1: Catalog, obj 2: Pages, obj 3: Helvetica, obj 4: Helvetica-Bold
  const kidsRefs: string[] = [];
  const baseObjId = 5;
  pageStreams.forEach((_, idx) => {
    const pageObjId = baseObjId + idx * 2;
    kidsRefs.push(`${pageObjId} 0 R`);
  });

  objects.push(`1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n`);
  objects.push(`2 0 obj\n<< /Type /Pages /Kids [${kidsRefs.join(" ")}] /Count ${pageStreams.length} >>\nendobj\n`);
  objects.push(`3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n`);
  objects.push(`4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n`);

  pageStreams.forEach((stream, idx) => {
    const pageObjId = baseObjId + idx * 2;
    const contentObjId = pageObjId + 1;
    objects.push(
      `${pageObjId} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw} ${ph}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentObjId} 0 R >>\nendobj\n`,
    );
    objects.push(`${contentObjId} 0 obj\n<< /Length ${stream.length} >>\nstream\n${stream}\nendstream\nendobj\n`);
  });

  let body = "%PDF-1.4\n";
  const offsets: number[] = [0];
  for (const obj of objects) {
    offsets.push(body.length);
    body += obj;
  }
  const xrefPos = body.length;
  let xref = `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  for (let i = 1; i < offsets.length; i += 1) {
    xref += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  }
  const trailer = `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF`;

  const bytes = new TextEncoder().encode(body + xref + trailer);
  return new File([bytes], fileName, { type: "application/pdf" });
}

function pdfBarcodeCommands(code: string, xMm: number, yBottomMm: number, wMm: number, hMm: number): string {
  const enc = encodeCode128B(code);
  const modMm = wMm / enc.totalWidth;
  const cmds: string[] = ["0 0 0 rg"];
  for (const b of enc.bars) {
    cmds.push(`${pt(xMm + b.x * modMm)} ${pt(yBottomMm)} ${pt(b.w * modMm)} ${pt(hMm)} re f`);
  }
  return cmds.join("\n");
}

function pdfDrawQrMockMatrix(seed: string, xMm: number, yBottomMm: number, sizeMm: number): string {
  const grid = 15;
  const cell = sizeMm / grid;
  let h = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const cmds: string[] = ["0 0 0 rg"];
  const isFinder = (r: number, c: number) =>
    (r < 5 && c < 5) || (r < 5 && c >= grid - 5) || (r >= grid - 5 && c < 5);

  for (let r = 0; r < grid; r += 1) {
    for (let c = 0; c < grid; c += 1) {
      let dark = false;
      if (isFinder(r, c)) {
        const lr = r >= grid - 5 ? r - (grid - 5) : r;
        const lc = c >= grid - 5 ? c - (grid - 5) : c;
        dark = lr === 0 || lr === 4 || lc === 0 || lc === 4 || (lr >= 1 && lr <= 3 && lc >= 1 && lc <= 3);
      } else {
        dark = (((h >>> ((r + c * 3) % 24)) ^ (r * 17 + c * 31)) & 1) === 1;
      }
      if (dark) {
        cmds.push(`${pt(xMm + c * cell)} ${pt(yBottomMm + (grid - 1 - r) * cell)} ${pt(cell)} ${pt(cell)} re f`);
      }
    }
  }
  return cmds.join("\n");
}

export function createFictionalFbaDemoFile(
  shipmentId = "FBA00DEMO01",
  warehouse = "DMO1",
  totalBoxes = 2,
  skuList?: string[],
): File {
  const wMm = 101.6;
  const hMm = 152.4; // 故意使用 4x6 含留白页面，真实触发后端裁切
  const streams: string[] = [];

  for (let i = 1; i <= totalBoxes; i += 1) {
    const boxId = `${shipmentId}U${String(i).padStart(6, "0")}`;
    const boxSku = skuList?.[i - 1] || (i === 1 ? "DEMO-SKU-A" : "DEMO-SKU-B");
    const s = [
      `0 0 0 rg`,
      `BT /F2 13 Tf ${pt(5)} ${pt(hMm - 10)} Td (${pdfEsc("FBA")}) Tj ET`,
      `BT /F2 9 Tf ${pt(60)} ${pt(hMm - 10)} Td (${pdfEsc(`Box ${i} of ${totalBoxes} - 32lb`)}) Tj ET`,
      `1.2 w ${pt(5)} ${pt(hMm - 12)} m ${pt(96)} ${pt(hMm - 12)} l S`,
      `BT /F2 8 Tf ${pt(5)} ${pt(hMm - 17)} Td (${pdfEsc("SHIP FROM:")}) Tj ET`,
      `BT /F1 7 Tf ${pt(5)} ${pt(hMm - 21)} Td (${pdfEsc("Demo Sender Co Ltd")}) Tj ET`,
      `BT /F1 7 Tf ${pt(5)} ${pt(hMm - 24.5)} Td (${pdfEsc("88 Example Road, Demo City")}) Tj ET`,
      `BT /F1 7 Tf ${pt(5)} ${pt(hMm - 28)} Td (${pdfEsc("Demo Country")}) Tj ET`,
      `BT /F2 8 Tf ${pt(52)} ${pt(hMm - 17)} Td (${pdfEsc("SHIP TO:")}) Tj ET`,
      `BT /F2 7 Tf ${pt(52)} ${pt(hMm - 21)} Td (${pdfEsc("FBA: Example Seller Co Ltd")}) Tj ET`,
      `BT /F1 7 Tf ${pt(52)} ${pt(hMm - 24.5)} Td (${pdfEsc("Amazon Demo FC")}) Tj ET`,
      `BT /F1 7 Tf ${pt(52)} ${pt(hMm - 28)} Td (${pdfEsc("100 Demo Ave, Demo City, US 00000")}) Tj ET`,
      `0 0 0 rg ${pt(5)} ${pt(hMm - 36)} ${pt(91)} ${pt(5)} re f`,
      `1 1 1 rg BT /F2 6.5 Tf ${pt(6.5)} ${pt(hMm - 34.6)} Td (${pdfEsc(`FBA STA (DEMO) - ${warehouse}`)}) Tj ET`,
      `0 0 0 rg`,
      pdfBarcodeCommands(boxId, 6, hMm - 64, 62, 23),
      `BT /F2 7.5 Tf ${pt(20)} ${pt(hMm - 68)} Td (${pdfEsc(boxId)}) Tj ET`,
      pdfDrawQrMockMatrix(boxId, 72, hMm - 64, 22),
      `BT /F2 7.5 Tf ${pt(46)} ${pt(hMm - 77)} Td (${pdfEsc(`${boxSku} · Qty 100`)}) Tj ET`,
      `BT /F2 8 Tf ${pt(22)} ${pt(hMm - 92)} Td (${pdfEsc("PLEASE LEAVE THIS LABEL UNCOVERED")}) Tj ET`,
    ].join("\n");
    streams.push(s);
  }

  return buildPdfFileFromPageStreams(wMm, hMm, streams, `${shipmentId}_Demo_BoxLabel_${warehouse}.pdf`);
}

export function createFictionalCarrierDemoFile(
  shipmentId: string | null = "FBA00DEMO01",
  warehouse = "DMO1",
  totalBoxes = 2,
): File {
  const wMm = 110;
  const hMm = 115;
  const streams: string[] = [];

  for (let ctn = 1; ctn <= totalBoxes; ctn += 1) {
    const trk = `TRK00DEMO0${ctn}`;
    const s = [
      `1.4 w 0 0 0 RG ${pt(7)} ${pt(10)} ${pt(96)} ${pt(96)} re S`,
      `1.2 w ${pt(7)} ${pt(hMm - 50)} m ${pt(103)} ${pt(hMm - 50)} l S`,
      pdfDrawQrMockMatrix(`${shipmentId || "UNASSIGNED"}-${ctn}`, 12, hMm - 36, 23),
      `BT /F2 11 Tf ${pt(13)} ${pt(hMm - 44)} Td (${pdfEsc(`CTNS:${ctn}/${totalBoxes}`)}) Tj ET`,
      `BT /F2 18 Tf ${pt(60)} ${pt(hMm - 25)} Td (${pdfEsc(warehouse)}) Tj ET`,
      `BT /F1 10 Tf ${pt(56)} ${pt(hMm - 36)} Td (${pdfEsc("DEMO EXPRESS LINE")}) Tj ET`,
      `BT /F2 12 Tf ${pt(36)} ${pt(hMm - 61)} Td (${pdfEsc(shipmentId || "MARK-NO-FBA-ID")}) Tj ET`,
      `BT /F2 11 Tf ${pt(38)} ${pt(hMm - 70)} Td (${pdfEsc("MADE IN CHINA")}) Tj ET`,
      pdfBarcodeCommands(trk, 18, hMm - 92, 74, 17),
      `BT /F1 8 Tf ${pt(44)} ${pt(hMm - 97)} Td (${pdfEsc(trk)}) Tj ET`,
    ].join("\n");
    streams.push(s);
  }

  const fname = shipmentId
    ? `${shipmentId}_DemoExpress_${warehouse}_${totalBoxes}CTNS.pdf`
    : `CarrierMark_NoShipmentId_${warehouse}_${totalBoxes}CTNS.pdf`;
  return buildPdfFileFromPageStreams(wMm, hMm, streams, fname);
}
