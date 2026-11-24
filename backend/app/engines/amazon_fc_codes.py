"""轻量级亚马逊 FBA/AWD 高频仓点代码词典与防误判提取器。"""

from __future__ import annotations

import re

# 收录美/加/墨/英/德/法/意/西/波/日高频亚马逊运营中心 (FC / IXD / AWD) 代码
KNOWN_AMAZON_FC_CODES: frozenset[str] = frozenset(
    {
        # 美国西部 & 美西热点
        "ONT2", "ONT6", "ONT8", "ONT9", "LAX9", "LGB3", "LGB4", "LGB6", "LGB7", "LGB8",
        "LAX5", "OAK3", "OAK4", "SCK1", "SCK3", "SCK4", "SCK8", "SMF1", "SMF3", "SMF6",
        "SMF7", "SBD1", "SBD2", "SBD3", "SJC7", "FAT1", "FAT2", "SNA4", "PSP1", "SAN3",
        "PHX3", "PHX5", "PHX6", "PHX7", "GYR1", "GYR2", "GYR3", "GEU2", "GEU3", "GEU5",
        "TUS1", "TUS2", "LAS1", "LAS2", "LAS6", "VGT2", "RNO4", "BFI1", "BFI3", "BFI4",
        "BFI7", "BFI9", "SEA6", "SEA8", "PDX7", "PDX9", "SLC1", "SLC2", "DEN2", "DEN3",
        "DEN5", "DEN8", "ABQ1", "BOI2",
        # 美国中南部 & 德州/中西部
        "FTW1", "FTW2", "FTW3", "FTW5", "FTW6", "FTW8", "FTW9", "DFW6", "DFW7", "DFW8",
        "DAL2", "DAL3", "HOU1", "HOU2", "HOU3", "HOU5", "HOU6", "SAT1", "SAT2", "SAT4",
        "AUS2", "AUS3", "ELP1", "OKC1", "TUL2", "LIT1", "LIT2", "MCI3", "MCI5", "MCI7",
        "MCI9", "STL3", "STL4", "STL8", "MDW2", "MDW4", "MDW5", "MDW6", "MDW7", "MDW8",
        "MDW9", "ORD2", "ORD4", "ORD5", "ORD9", "RFD1", "RFD2", "RFD3", "RFD4", "MKE1",
        "MKE2", "MKE5", "MSP1", "MSP6", "MSP8", "MSP9", "FSD1", "IND1", "IND2", "IND4",
        "IND5", "IND8", "IND9", "FWA4", "FWA6", "SBN1", "DET1", "DET2", "DET3", "DET6",
        "DTW1", "DTW3", "DTW5", "CLE2", "CLE3", "CLE5", "CMH1", "CMH2", "CMH3", "CMH4",
        "CVG1", "CVG2", "CVG3", "SDF1", "SDF4", "SDF6", "SDF8", "SDF9", "LEX1", "LEX2",
        "BNA2", "BNA3", "BNA5", "BNA6", "BNA7", "BNA8", "MQY1", "CHA1", "CHA2", "MEM1",
        "MEM2", "MEM3", "MEM4", "MEM6", "BHM1", "HSV1", "JAN1", "BTR1", "OMA2",
        # 美国东部
        "ABE2", "ABE3", "ABE4", "ABE5", "ABE8", "AVP1", "AVP8", "AVP9", "MDT1", "MDT2",
        "MDT4", "MDT5", "MDT9", "PHL4", "PHL5", "PHL6", "PHL7", "PIT2", "PIT5", "PIT9",
        "EWR4", "EWR5", "EWR6", "EWR7", "EWR8", "EWR9", "TEB3", "TEB4", "TEB6", "TEB9",
        "ACY1", "ACY2", "LGA5", "LGA6", "LGA7", "LGA8", "LGA9", "JFK8", "SWF1", "SWF2",
        "ALB1", "ROC1", "SYR1", "BDL1", "BDL2", "BDL3", "BDL4", "BDL6", "BOS3", "BOS7",
        "BWI1", "BWI2", "BWI4", "BWI5", "MTN1", "RIC1", "RIC2", "RIC3", "RIC4", "RIC5",
        "ORF2", "ORF3", "DCA1", "DCA2", "DCA6", "CLT2", "CLT3", "CLT4", "CLT5", "CLT6",
        "CLT9", "RDU1", "RDU2", "RDU4", "RDU5", "GSO1", "CAE1", "CAE3", "GSP1", "SAV3",
        "AGS1", "ATL2", "ATL6", "ATL8", "SAV4", "RMN3", "MIT2", "JAX2", "JAX3", "JAX5",
        "JAX7", "MCO1", "MCO2", "MCO4", "MIA1", "MIA2", "MIA5", "TPA1", "TPA2", "TPA3",
        "TPA4", "PBI2", "PBI3", "XLX1", "XLX6", "XLX7", "XLX8", "AWD1", "AWD2", "IUSB",
        # 加拿大 / 墨西哥
        "YVR1", "YVR2", "YVR3", "YVR4", "YYC1", "YYC4", "YYZ1", "YYZ2", "YYZ3", "YYZ4",
        "YYZ7", "YYZ9", "YOW1", "YOW3", "YHM1", "YOO1", "YUL2", "YUL5", "MEX1", "MEX2",
        "MEX3", "GDL1", "MTY1",
        # 英国
        "BHX1", "BHX2", "BHX3", "BHX4", "BHX5", "BHX7", "BHX8", "BRS1", "BRS2", "CWL1",
        "EDI4", "EMA1", "EMA2", "EMA3", "EMA4", "EUK5", "GLA1", "LBA1", "LBA2", "LBA4",
        "LCY1", "LCY2", "LCY3", "LCY8", "LHR1", "LTN1", "LTN2", "LTN4", "LTN7", "MAN1",
        "MAN2", "MAN3", "MAN4", "MAN8", "MME1", "MME2", "NCL1", "NCL2", "STN8",
        # 欧洲大陆 (DE / FR / IT / ES / PL / CZ)
        "BER3", "BER6", "BER8", "BRE2", "BRE4", "CGN1", "CGN9", "DTM1", "DTM2", "DTM3",
        "DTM8", "DUS2", "DUS4", "EDE4", "EDE5", "ERF1", "FRA1", "FRA3", "FRA7", "HAJ1",
        "HAM2", "LEJ1", "LEJ3", "LEJ5", "MUC3", "NUE1", "PAD1", "PAD2", "STR1", "WRO1",
        "WRO2", "WRO3", "WRO4", "WRO5", "KTW1", "KTW3", "KTW4", "KTW5", "POZ1", "POZ2",
        "SZZ1", "LCJ2", "LCJ3", "PRG1", "PRG2", "ORY1", "ORY4", "BVA1", "CDG7", "LIL1",
        "LIL8", "LYS1", "MRS1", "ETZ2", "MAD4", "MAD6", "MAD7", "MAD8", "MAD9", "BCN1",
        "BCN2", "BCN3", "BCN4", "BCN8", "SVQ1", "VLC1", "RMU1", "MXP3", "MXP5", "MXP6",
        "MXP8", "BLQ1", "FCO1", "FCO2", "FCO5", "TRN1", "TRN3", "VCE1",
        # 日本
        "NRT1", "NRT2", "NRT5", "HND2", "HND3", "HND6", "HND8", "HND9", "KIX1", "KIX2",
        "KIX3", "KIX4", "KIX5", "KIX6", "TYO1", "TYO2", "TYO3", "TYO6", "TYO7", "TYO8",
        "TYO9", "NGO2", "FSZ1", "ITM2", "QCB1", "QCB3", "TPF2", "TPF3", "TPF6", "VJNA",
    }
)

# 过滤常见非仓点“三字母+一位数字”编号（绝不包含演示/测试仓点 DMO1/DMO2）
NOISE_FC_CODES: frozenset[str] = frozenset(
    {
        *(f"{p}{d}" for p in ("BOX", "CTN", "SKU", "QTY", "PCS", "PDF", "TRK", "PKG", "STD", "MIX", "PAL", "REF", "INV", "DOC", "NUM", "VER") for d in "0123456789"),
        "AIR1", "AIR2", "SEA1", "SEA2", "EXP1", "EXP2", "USA1", "CHN1", "EUR1", "VAT1", "TAX1", "ROW1", "COL1",
    }
)

_FC_STA_RE = re.compile(r"(?:FBA|AWD)\s*(?:STA)?[^-\n]{0,24}-\s*([A-Z]{3}\d)\b", re.IGNORECASE)
_FC_TOKEN_RE = re.compile(r"\b([A-Z]{3}\d)\b")


def extract_amazon_fc_code(text: str, file_name: str = "") -> str | None:
    """
    提取亚马逊仓库代码，按可信度降序：
    1) FBA/AWD STA - XXXX 锚点；
    2) 正文中命中高频 FBA 仓点词典的代码；
    3) 文件名中命中高频 FBA 仓点词典的代码；
    4) 正文及文件名中未命中噪声表的 [A-Z]{3}\\d 兜底。
    """
    raw_text = text or ""
    raw_file = file_name or ""

    sta_m = _FC_STA_RE.search(raw_text)
    if sta_m:
        cand = sta_m.group(1).upper()
        if not cand.startswith("FBA"):
            return cand

    text_up = raw_text.upper()
    file_up = raw_file.upper()

    for cand in _FC_TOKEN_RE.findall(text_up):
        if cand in KNOWN_AMAZON_FC_CODES:
            return cand

    for cand in _FC_TOKEN_RE.findall(file_up):
        if cand in KNOWN_AMAZON_FC_CODES:
            return cand

    for source in (text_up, file_up):
        for cand in _FC_TOKEN_RE.findall(source):
            if not cand.startswith("FBA") and cand not in NOISE_FC_CODES:
                return cand

    return None
