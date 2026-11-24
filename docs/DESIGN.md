# FBA 一体化标签打印工作台 — 架构设计与项目规划文档

> **文档状态**：v0.3.0 生产架构基线（M1–M4 及 v0.2.0 / v0.3.0 均已交付验证）  
> **适用平台**：macOS / Windows（跨平台本地独立发行包 & 本地 Web 工作台）  
> **支持打印机与协议**：兼容 **TSPL2**（TSC / 芯烨 / 佳博 / 汉印 / Rollo）、**ZPL II**（斑马 Zebra / 工业机）、系统原生驱动与局域网 **TCP 9100** 直连（`203` / `300 dpi`），支持多机分卷绑定与印刷级 PDF 导出。

---

## 1. 产品定位与灵活业务流设计

### 1.1 核心痛点与解决目标
彻底替代目前“手动用 PDF 编辑器抹除 FBA 标签信息 → 人工截图 → 导入 OpenLabel+ 逐张贴图并调整至 `98×98mm` → 人工肉眼核对货代箱唛箱号”的高重复、易出错流程，将 **产品标签（`50×30mm` 双排）** 与 **外箱标签 / 货代箱唛（`100×100mm` 单排）** 整合入同一本地工作台，实现：
1. **矢量级语义真脱敏与自动排版**：零人工截图、零底层隐私信息残留、零中文字体丢失。
2. **多规格灵活解耦**：支持先打产品标贴货、装箱称重后再打外箱标，也支持单打 FBA 标或单打货代箱唛，**绝不强行绑定执行顺序**。
3. **跨文档强校验与防错出纸**：自动核对货件号、仓点、箱数与箱号对应关系，支持每箱 `3~5` 套交替或分组出纸、单箱破损精准补打。
4. **单机双规格换纸防呆**：针对单台 `TSC TTP-244 Pro` 切换 `50×30 双排` 与 `100×100 单排` 的场景，自动下发尺寸参数并在切纸时弹出防呆提醒。
5. **隐私与零真实数据内置原则**：用户提供的真实业务 PDF 仅作开发期版式分析与本地回归验证之用，**严禁内置到交互原型、前端打包资产或设计文档示例展示中**；原型与公开示例统一使用默认空白待导入态或前端代码动态生成的 100% 虚构占位图。

### 1.2 灵活业务工作流（完全解耦）
在实际亚马逊 FBA 发货作业中，产品打标与外箱打标往往处于不同时间节点：
- **阶段 A（货品预处理期）**：随时打开「标签设计工作台」，拖入或选择亚马逊产品标签 PDF（或从本地模板库直接选中已有模板），输入本次发货数量（例如 `120`），一键双排打印并保存到本地模板库。
- **阶段 B（装箱打包期）**：打包称重并在亚马逊创建箱标、向货代拿到箱唛后，打开「外箱标 & 箱唛工作台」，通过**双通道独立导入舱**分别导入（支持批量多选/拖入）原始 FBA 外箱标 PDF 与货代箱唛 PDF，导入瞬间**自动执行空白区裁切 + 语义脱敏 + `98×98mm` 居中落版**，并严格**以 FBA 编号（Shipment ID）为第一主键**自动完成多票配对分组，按需选择以下 **3 种独立工作模式**：
  1. **按号配对模式（最常用）**：系统按 FBA 编号自动配齐两份 PDF 的对应箱号，做强校验（货件号/仓点/箱数一致）→ 设定每箱套数（默认 4 套，支持 3~5 套任意设或单箱微调）→ 按“贴面交替”或“同箱紧邻”出纸。
  2. **仅处理 FBA 外箱标模式**：仅拖入亚马逊箱标 PDF → 导入即自动脱敏、裁边、居中至 `98×98mm`（`100×100mm` 画布）→ 单独打印或导出 PDF。
  3. **仅处理货代箱唛模式**：仅拖入货代箱唛 PDF → 自动校验规格与边距居中 → 批量多份打印或单独补打。

### 1.3 V1.0 MVP 范围与 V2.0 延后边界（严控不过度优化）

| 范围划分 | 模块与功能项 | 说明 |
| :--- | :--- | :--- |
| **V1.0 MVP（本期核心交付）** | **FBA 外箱标语义脱敏引擎** | 支持中文版（4×6 单页）与英文版（多合一拼版/单页），抹除 `SHIP FROM:` / `发货地：` 内容与 `FBA:` 后公司名，保留亚马逊仓库地址，可选补印 `Made In China`，自动裁切留白并按 `98×98mm` 居中放入 `100×100mm` 画布。 |
| **V1.0 MVP** | **货代箱唛解析与配对兜底** | 提取货件号、仓点、总箱数与单箱序号，红框阻断错配并支持人工核对放行；当箱唛未带 FBA 编号时支持手动选择归属到指定货件后按箱号配对。 |
| **V1.0 MVP** | **多套防错出纸与单箱精准补打** | 全局每箱 `3~5` 套（支持单箱覆写），支持「贴面交替」「同箱紧邻」「分组出纸」；历史批次记录支持勾选任意单箱单独补打 1 张或多张。 |
| **V1.0 MVP** | **新建任意尺寸标签 & OpenLabel+ 自由编辑器** | 支持「新建标签」（预设 `50×30 双排` / `40×30 双排` / `100×100 单排` 或自定义宽高 `mm` 与单/双排排版）；支持自由添加文本、Code128 一维码、QR 二维码、白色遮罩块、边框及合规图标（`Made in China` / `New` 等）；支持拖拽、8 向缩放、网格对齐吸附、撤销/重做与热转印清晰度提醒。 |
| **V1.0 MVP** | **单机双通道打印与换纸防呆** | 自动记忆上次纸张规格并弹换纸确认；支持 `TSPL 裸指令直出`、`系统驱动 PDF 直打`、`印刷级 PDF 导出`。 |
| **V2.0 延后项（暂不开发）** | **FBA 自动反推产品标队列** | 后续按需评估是否增加从 FBA 箱标读取 `Single SKU / Qty` 一键带入产品标队列（注意不强迫先后顺序）。 |
| **V2.0 延后项** | **超重 `Team Lift` 智能提醒与警示贴库** | 根据 FBA 箱标重量自动标黄提醒 `>50lb` 超重箱并内置警示贴。 |
| **V2.0 延后项** | **独立桌面安装包封装** | PyInstaller / 一键免环境安装包（`.app` / `.exe`），V1 阶段先采用轻量脚本一键启动本地工作台。 |

---

## 2. 参考 PDF 版式与工程特征实证分析（已脱敏）

> **隐私说明**：以下特征仅提炼自内部参考样本的版式布局与底层坐标规律，所有真实商家身份、货件编号、地址与商品信息均已作脱敏占位处理，严禁将原始样本内置到任何对外原型或代码中。

### 2.1 中文版 FBA 外箱标版式规律（参考样本 A）
- **文件类型**：中文版 4×6 热敏单页外箱 PDF（共 2 页）
- **页面物理尺寸**：`306.00 × 432.00 pt`（折合 `107.95 × 152.40 mm`，即标准 4×6 英寸热敏格式）
- **字体特征**：
  - `Helvetica`（标准 14 字体，未嵌入）
  - `STSong-Light-UniGB-UCS2-H`（**未嵌入 CJK CID 字体**，直接用通用渲染器转图会导致中文丢字空白，必须在处理管道中配置中文字体回退映射）
  - `ArialMT`（嵌入子集，用于附加的 `Made In China`）
- **图像与矢量对象**：第 1 页含 1 个图像对象（右侧 2D 码区）、6 个矢量绘图对象（分割线、黑底条、Code128 一维条码矢量条）。
- **关键坐标规律（第 1 页，单位 pt）**：
  - 顶栏标题：`FBA` `[17.3, 1.9, 46.5, 22.5]`；`纸箱编号 1，共 2 个纸箱 - <WEIGHT>` `[183.9, 4.8, 286.7, 19.8]`
  - **左栏（目的地，需保留仓库地址，仅擦除公司名）**：
    - `目的地：` `[17.3, 25.0, 49.3, 33.0]`
    - 独立文本 span：`FBA: <SELLER_COMPANY_NAME>` `[17.3, 31.4, 119.9, 42.4]`（`Helvetica 6.0pt`）
    - 仓库地址：`<WAREHOUSE_RECEIVER>` / `<WAREHOUSE_STREET>` / `<WAREHOUSE_CITY_STATE_ZIP>` / `美国` (`x=17.3..101.9, y=41.0..73.0`)
  - **右栏（发货地，需擦除内容）**：
    - `发货地：` `[154.0, 25.0, 186.0, 33.0]`
    - 发货人信息：`<SENDER_NAME>` / `<SENDER_CITY_ZIP>` / `<SENDER_STREET>` / `中国` (`x=154.0..256.6, y=33.0..65.0`)
  - 黑条时间戳：`FBA STA (<TIMESTAMP>)-<WAREHOUSE_CODE>` `[16.3, 74.7, 100.2, 80.7]`、`Created: <CREATED_TIME>` `[202.1, 74.7, 287.7, 80.7]`
  - 货件箱码：`<SHIPMENT_ID_A>U000001` `[62.7, 160.4, 156.5, 171.4]`
  - SKU 与数量：`Single SKU` `[161.1, 177.1, 202.0, 188.1]`、`<SKU_EXAMPLE>` `[152.9, 186.5, 202.0, 193.5]`、`数量 <QTY>` `[176.8, 193.5, 202.0, 200.5]`、`MB` `[191.8, 200.5, 202.0, 207.5]`
  - 人工附加区：`Made In China` `[30.5, 177.6, 89.0, 187.6]`
  - 标签底边：`请不要遮住此标签` `[120.0, 218.4, 184.0, 226.4]` → **有效区集中在 `y: 1.9 ~ 226.4 pt`，下半页 `y: 226.4 ~ 432.0 pt` 为纯留白**，裁剪后恰好接近正方形，非常契合 `100×100mm` 纸张。

### 2.2 货代箱唛版式规律（参考样本 B）
- **文件类型**：`100×100mm` 货代箱唛 PDF（共 2 页）
- **页面物理尺寸**：`283.46 × 283.46 pt`（标准 `100.00 × 100.00 mm` 正方形）
- **字体特征**：`Helvetica` + 已嵌入子集字体 `AAAAAA+MicrosoftYaHei-0`（无中文丢字风险）
- **图像与矢量对象**：第 1 页含 1 个图像对象（左上角二维码）与 45 个矢量对象（边框线 + 底部一维条码）。
- **关键提取字段**：仓点代码 `<WAREHOUSE_CODE>`、邮编 `<WAREHOUSE_ZIP>`、渠道名 `<FORWARDER_LINE_NAME>`、箱号 `CTNS:1/2` / `CTNS:2/2`、货件编号 `<SHIPMENT_ID_B>`、`MADE IN CHINA` 与跟踪条码 `<TRACKING_NO>`。
- **处理结论**：自带精准 `100×100mm` 外框，只需按安全边距配置（如 `98×98mm`）做等比微缩居中即可。

### 2.3 亚马逊产品标签版式规律（参考样本 C）
- **文件类型**：卖家后台导出的单页 FNSKU 产品标签 PDF（共 1 页）
- **页面物理尺寸**：`199.17 × 142.26 pt`（`70.26 × 50.19 mm`）
- **字体与对象**：`STSong-Light-UniGB-UCS2-H`（**未嵌入**），0 图像、1 个矢量绘图对象（条码）。
- **版式坐标规律**：
  - FNSKU 编码：`X000DEMO01` `[75.5, 64.1, 123.6, 72.1]`
  - 产品标题行 1：`新品 - Demo Product Item,` `[18.0, 76.1, 130.1, 84.1]`
  - 产品标题行 2：`Demo Variant，Color：S1` `[18.0, 84.1, 87.9, 92.1]`
- **发现的问题**：原文件不仅尺寸偏大（`70×50mm`）不适配 `50×30mm` 双排，且自带中文 `新品` 与中文全角逗号 `，`、全角冒号 `：`；并且因未嵌入中文字体，直接渲染存在丢字与换行不均问题。本系统通过提取纯文本参数，在自有引擎内重新生成矢量/203dpi 对齐排版，彻底根治上述问题。

### 2.4 英文版无未脱敏原件的测试策略
由于英文版未脱敏原始亚马逊 PDF 暂缺，结合已确认的英文拼版样式（单页包含 `Box 1 of 2` 与 `Box 2 of 2` 上下多箱；每箱**左栏为 `SHIP FROM:`，右栏为 `SHIP TO:` + `FBA:`**），M1 阶段采取：
1. 在测试套件中编写“英文未脱敏多箱拼版合成器”（用 PyMuPDF 严格按该左右分栏、多箱拼版坐标生成包含真实模拟发货地与 `FBA: <Company Name>` 的测试 PDF）。
2. 在脱敏算法中完全不硬编码任何固定 `x/y` 坐标，而是**基于锚点词汇与半栏聚类动态计算坐标框**——确保无论左右栏如何调换、或每页放 1/2/4/6 箱，算法均能自适应命中。
3. 后续用户一旦有新的英文原始 PDF 产生，直接补入 `tests/fixtures/` 纳入回归用例即可。

---

## 3. 硬件驱动实证与无打印机离线 4 重验证方案

### 3.1 macOS 通用 CUPS PPD 热敏驱动工程约束（以 TSC 203dpi 系列为例）
依据标准 macOS CUPS 热敏 PPD 驱动规范，汇总以下关键工程约束：

| PPD 参数项 | 典型规格值 | 工程意义 |
| :--- | :--- | :--- |
| `*ModelName` / 队列名 | `TSC TTP-244 Pro` 等通用热敏机 | 支持按系统打印队列自动探测并推荐协议/DPI |
| `*cupsFilter` | 通用厂商 CUPS 光栅滤镜 | 驱动底层最终仍需将光栅流转译为 TSPL/ZPL 发往打印机 |
| `*DefaultResolution` | `203dpi` (`cupsBitsPerColor 1`) | **1 dot = 1/8 mm = 0.125 mm**（关键像素对齐基准） |
| `*MaxMediaWidth` | `306.14 pt` (`108.00 mm`) | 支持 `100mm` 单排及 `50+2+50=102mm` 双排 |
| `*HWMargins` / `*CustomPageSize` | `0.00 0.00 0.00 0.00` / `True` | 支持传入任意 `Custom.WIDTHxHEIGHT` 无边距打印 |
| `MediaMethod` / `PaperType` | `*Normal Direct Transfer` / `*LabelGaps` | 碳带热转印模式须显式使用 `Transfer` 与 `LabelGaps` |
| `ColorOption` | `*None GrayScale Halftone` | **禁止使用 `Halftone`**（半色调抖动会破坏条码边缘对比度，须锁死 `None` 纯黑白二值） |
| **驱动已知坑点** | PPD 中存在选项名拼写错误 `AdjustHoriaontal` | 若走系统驱动设偏移参数，不可凭猜想写 `AdjustHorizontal`，必须按需适配或直接在图像/TSPL 坐标层做毫米偏移（**优先推荐在软件渲染层与 TSPL 指令层统一做坐标偏移，彻底规避系统驱动选项差异**） |

### 3.2 离线开发期「4 重验证体系」（无实体打印机照常保质）
1. **PDF 几何精确断言**：pytest 断言所有导出 PDF 的 MediaBox/CropBox 误差 `< 0.05 pt`（如 `100×100mm` 为 `283.46×283.46 pt`，`102×30mm` 为 `289.13×85.04 pt`），且所有非白内容边界严格位于 `98×98mm` 安全框内。
2. **203dpi 1-bit 热转印仿真视图**：前端和后端测试均可生成严格 `8 dots/mm` 的纯 1-bit 黑白点阵图（`800×800 px` 对应 `100×100mm`，`816×240 px` 对应 `102×30mm`），直观检查小字清晰度、条码条空比和脱敏洁净度。
3. **TSPL 裸指令干跑（Dry-Run）与逆向校验**：`TSPLRawAdapter` 在离线模式下生成完整 `.tspl` 字节流并落盘，测试脚本解析校验 `SIZE`、`GAP`、`DIRECTION`、`DENSITY`、`BITMAP` 字节长度（`ceil(width_dots/8) * height_dots`）和 `PRINT` 语法，并可将 `BITMAP` 载荷逆向还原为 PNG 肉眼复查。
4. **`zxing-cpp` 自动机读扫码回归**：用 `zxing-cpp` 直接识别 **203dpi 仿真位图**，强制验证：
   - 脱敏后的 FBA 一维码与右侧 2D 码可读且数值 100% 未损坏；
   - 货代箱唛 QR 码与底部 Code128 可读且内容一致；
   - 自生成的 `50×30mm` FNSKU Code128 条码机读 100% 识别且静区（Quiet Zone）达标。

> **接机投产收尾**：打印机连上电脑后，仅需进入「硬件校准中心」打印 1 张 `100×100` 和 1 排 `50×30` 校准标尺卡，填入 X/Y 毫米微调即可正式上产线。

---

## 4. 开源借鉴与系统技术架构

### 4.1 开源项目深度调研结论
| 借鉴来源 | 采纳的工程思路 | 本项目差异化自研部分 |
| :--- | :--- | :--- |
| `PyMuPDF` / `nav17/label_converter` / `pdf-pack-and-crop` | 基于 `fitz` 提取页面元素并做非白像素 `getbbox()` 自动裁边，以及对比度锐化防淡印。 | 增加中英文左右互异栏位的**语义锚点物理擦除（Redaction）**与 CJK 缺字回退。 |
| `abrasive/pdf2tspl` / `littlecxm/tspl-manual` | 将单页转为 `203dpi` 1-bit `BITMAP` 封装 `SIZE / GAP / CLS / BITMAP / PRINT` 原生指令；macOS 走 `lp -o raw`，Windows 走 `win32print`。 | 增加双规格换纸自动切换 `SIZE`、`GAP`、防呆锁与 203dpi 整数 dot 条码对齐。 |
| `pdfme/pdfme` / `Konva` / 本地桥接架构 | **JSON 驱动标签布局 Schema** + 浏览器前端与本地打印服务分离架构。 | 采纳 **OpenLabel+ 风格统一自由画布编辑器**（支持元素增删、鼠标自由拖拽、8 向缩放、智能吸附、撤销/重做与快捷键），并耦合 **203dpi 条码可读性实时预警**，兼顾操作自由度与扫码可靠性。 |

### 4.2 技术栈选型（已定稿）
- **后端服务**：Python 3.12 + `FastAPI` + `Uvicorn` + `Pydantic v2` + `SQLite`（由 `uv` 管理独立虚拟环境 `backend/.venv`）
- **PDF 与图形引擎**：定义抽象 `PDFEngine` 接口（`pdf_engine.py`），一期采用 `PyMuPDF (fitz)`（自用/团队内用效率最高），保留未来闭源商业分发无缝切换 Apache-2.0 `pypdfium2 + pikepdf` 引擎的扩展边界；配合 `Pillow`、自研整数 dot Code128B 引擎、`ReportLab`、`zxing-cpp`（离线扫码闭环校验）
- **前端界面**：`React 18+ + TypeScript + Vite + Mantine（原生 CSS Modules，零 Tailwind CSS） + Zustand + 矢量 SVG 毫米坐标画布`
- **运行形态**：一期本地 FastAPI 静态托管（浏览器零打包运行）；二期如需独立桌面安装包，可无缝外套 `Tauri v2`（挂载 Python Sidecar，业务代码零重写）
- **Windows 兼容依赖**：`pywin32` (`win32print`)，仅在 Windows 环境条件导入

### 4.3 项目目录结构
```text
fba-label/
├── .github/workflows/release.yml     # macOS / Windows 双平台 PyInstaller 自动打包发布流
├── .gitignore                        # 全局忽略 *.pdf 真实样本、虚拟环境、构建产物与本地库
├── LICENSE                           # GNU AGPL-3.0 开源协议
├── README.md                         # 简体中文主文档（含实机截图、能力对比与 FAQ）
├── README.en.md                      # English README（SEO/GEO 优化完整英文版）
├── llms.txt                          # 面向 AI 检索与 GEO 的结构化项目索引
├── docs/
│   ├── DESIGN.md                     # 系统架构与核心引擎算法设计文档
│   └── screenshots/                  # 100% 虚构数据渲染的实机运行截图
├── backend/
│   ├── pyproject.toml                # Python 3.12 依赖、单测与打包配置
│   ├── launcher.py                   # 独立包启动入口（自动探测空闲端口并拉起浏览器）
│   ├── app/
│   │   ├── main.py                   # FastAPI 应用入口 & 前端静态产物托管
│   │   ├── config.py                 # 跨平台用户数据目录、DPI 常量与默认纸卷参数
│   │   ├── db.py                     # SQLite 初始化、版本迁移与仓储封装
│   │   ├── models/
│   │   │   └── schemas.py            # Pydantic v2 请求/响应与领域模型
│   │   ├── engines/
│   │   │   ├── font_manager.py       # 系统 CJK 字体探测与自动嵌入回退
│   │   │   ├── pdf_engine.py         # PDFEngine 抽象层与 PyMuPDF 实现
│   │   │   ├── code128.py            # 完整 Code128B 整数 dot 矢量/点阵生成器
│   │   │   ├── fba_processor.py      # FBA 拼版切分、语义锚点真脱敏、98×98 居中
│   │   │   ├── carrier_parser.py     # 货代箱唛解析（内置通用规则 + 自定义正则规则引擎）
│   │   │   ├── pairing_engine.py     # 三维度强校验 + 多套队列编排器
│   │   │   └── fnsku_engine.py       # 亚马逊产品标 PDF 解析、CSV 解析与多 SKU 批量渲染
│   │   ├── printers/
│   │   │   ├── base.py               # PrinterAdapter 抽象接口
│   │   │   ├── registry.py           # 跨平台打印机探测与品牌/协议/DPI 智能推荐
│   │   │   ├── tspl_encoder.py       # 203/300dpi 1-bit Bitmap & TSPL2 指令编码与逆向校验
│   │   │   ├── zpl_encoder.py        # 203/300dpi 1-bit Bitmap & ZPL II (^GF) 编码与逆向校验
│   │   │   ├── network_raw.py        # 局域网 TCP 9100 原始套接字探测与直传
│   │   │   ├── macos_cups.py         # macOS CUPS lp -o raw 与原生 PDF 打印
│   │   │   ├── windows_raw.py        # Windows win32print RAW 与原生 GDI 备选
│   │   │   └── simulator.py          # 点阵仿真图导出、干跑指令检验与 zxing-cpp 扫码回归
│   │   └── api/
│   │       ├── fnsku.py              # 产品标解析、预览、SKU 库、CSV 导入与批量渲染接口
│   │       ├── box_labels.py         # 外箱标/箱唛上传、脱敏预览、配对、货代规则管理接口
│   │       ├── batches.py            # 历史批次查询、快照下载与单箱精准补打
│   │       └── hardware.py           # 打印机探测、网口探测、自定义校准档与打印路由执行
│   └── tests/
│       ├── conftest.py               # 100% 虚构中英文 PDF 测试夹具与数据目录隔离
│       ├── test_fba_redaction.py     # 物理脱敏残留检测 + 尺寸精度 + 扫码测试
│       ├── test_pairing.py           # 货件号/仓点/箱数校验、叠层与交替队列测试
│       ├── test_fnsku_layout.py      # 双排排版 + 203dpi 整数 dot 扫码测试
│       ├── test_tspl_dryrun.py       # TSPL 指令逆向解码与 API 烟雾测试
│       ├── test_multi_printer.py     # ZPL/TSPL 300dpi、TCP 9100、SQLite 迁移与硬件路由测试
│       └── test_v030_batch_and_rules.py # 多编码 CSV 批量套打、自定义校准卡与货代规则测试
├── frontend/                         # React 19 + TypeScript + Mantine 9 + Zustand 工作台
│   └── src/components/               # BoxStudio / CarrierRulesModal / EditorStudio / BatchSkuModal / BatchesView / HardwareView / PrintModal 等
└── scripts/
    ├── start_mac.command             # macOS 源码开发一键启动脚本
    ├── start_win.bat                 # Windows 源码开发一键启动脚本
    ├── build_release.py              # 跨平台 PyInstaller 免安装压缩包构建器
    └── smoke_test_release.py         # 独立包解压、冷启动与全链 API 冒烟测试
```

### 4.4 SQLite 核心表结构与统一画布元素 Schema
1. **`skus`（产品 SKU 档案与自由排版模板）**
   - `id` (PK), `sku` (UNIQUE), `fnsku`, `title_raw`, `title_clean`, `canvas_elements_json` (存储统一画布元素 JSON 数组，替代固定参数字段，完整保存用户的自由拖放排版), `updated_at`
2. **`calibration_profiles`（双规格硬件校准与通道配置）**
   - `spec_key` (PK: `'50x30_double'` | `'100x100_single'`), `label_width_mm`, `label_height_mm`, `cols`, `col_gap_mm`, `row_gap_mm`, `safe_width_mm`, `safe_height_mm`, `offset_x_mm`, `offset_y_mm`, `darkness` (0~15), `print_speed` (20~50), `preferred_channel` (`'tspl_raw'` | `'os_driver'` | `'pdf_export'`), `printer_name`
3. **`app_state`（运行时防呆状态）**
   - `key` (PK: `'last_printed_spec'`), `value` (`'50x30_double'` | `'100x100_single'` | `''`), `updated_at`
4. **`print_batches`（历史打印批次与补打快照）**
   - `id` (PK), `batch_type` (`'fnsku'` | `'box_paired'` | `'box_fba_only'` | `'box_carrier_only'`), `shipment_id`, `warehouse_code`, `total_units_or_boxes`, `copies_per_box`, `order_mode`, `source_files_json`, `overlay_elements_json` (记录外箱精修手动叠加层快照), `snapshot_dir` (保存已处理好的标准单页矢量 PDF，确保任意时间零误差秒补打), `created_at`
5. **`carrier_rules`（货代箱唛解析规则扩展表）**
   - `id` (PK), `name`, `shipment_regex`, `warehouse_regex`, `ctn_regex`, `default_rotate`, `enabled`

#### 统一画布元素 JSON Schema（产品标 & 外箱叠层精修通用）
所有元素坐标与尺寸**统一以物理毫米（`mm`）存储**，彻底解耦屏幕缩放与 203dpi 打印输出：
```json
{
  "id": "el_9a8f12",
  "type": "text | barcode1d | qrcode | rect | line | icon | image",
  "name": "FNSKU 条码",
  "x": 3.0,
  "y": 1.5,
  "w": 44.0,
  "h": 14.5,
  "rotate": 0,
  "locked": false,
  // 类型专属字段示例：
  // text:      { "text": "...", "fontSize": 7.5, "lineHeight": 1.25, "bold": false, "italic": false, "align": "left" }
  // barcode1d: { "code": "X000DEMO01", "showText": true, "fontSize": 8.5 }
  // qrcode:    { "code": "FBA00DEMO001" }
  // rect:      { "rectMode": "outline | white_mask | black_fill", "strokeWidth": 0.4, "radius": 0 }
  // line:      { "strokeWidth": 0.45, "dashed": false }
  // icon:      { "iconKey": "ce | ukca | recycle | weee | warn | fragile", "threshold": 145 }
  // image:     { "src": "data:image/... 或本地资产路径", "threshold": 145 }
}
```

### 4.5 核心 REST API 契约
- `POST /api/box/parse-fba`：批量上传 1 个或多个 FBA 原始 PDF + 脱敏选项 → **立即自动切分拼版、裁切多余空白区、物理脱敏并按 `98×98mm` 居中落入 `100×100mm` 画布** → 返回各文件解析与提取出的 `shipment_id` 列表及每箱预览图 URL（含裁切前整页框与脱敏对比图）。
- `POST /api/box/parse-carrier`：批量上传 1 个或多个货代箱唛 PDF → 自动裁切边距至 `98×98mm` 居中并提取 `shipment_id`、`warehouse_code` 与 `CTNS:X/N` 箱号 → 返回箱唛文件池列表。
- `POST /api/box/validate-pair`：基于当前 FBA 文件池与货代箱唛文件池，**以 `shipment_id`（FBA 编号）为第一配对主键、箱号序号 `1..N` 为第二配对主键**自动聚合为多个配对分组（支持多票货件混导自动拆组），返回每组状态（`matched` / `fba_only` / `carrier_only` / `mismatch_detail`）与差异明细。
- `POST /api/box/execute`：传入工作模式（配对/仅FBA/仅箱唛）、选中箱列表、每箱套数、出纸顺序、输出通道 → 执行打印或返回印刷级合并 PDF 下载链接，并自动保存历史批次快照。
- `POST /api/fnsku/import-pdf`：上传本地亚马逊产品标签 PDF → 提取 `fnsku` 与原始标题，返回清洗前后对照结果。
- `GET/POST/PUT /api/skus`：SKU 档案库增删改查与版式保存。
- `POST /api/fnsku/preview` & `POST /api/fnsku/execute`：传入 SKU 参数与打印数量 → 返回单张/双排/203dpi 仿真预览图，或执行双排打印 / 导出 PDF。
- `GET /api/batches` & `POST /api/batches/{id}/reprint`：获取历史批次并支持指定单箱、指定标签类型（仅 FBA / 仅箱唛 / 成套）与指定张数精准补打。
- `GET/PUT /api/hardware/config` & `POST /api/hardware/test-card`：读取系统打印机列表、更新校准配置、打印校准标尺测试卡。

---

## 5. 核心引擎算法设计细则

### 5.1 FBA 语义锚点“真脱敏”与切箱算法 (`fba_processor.py`)
1. **中文字体映射补齐**：初始化渲染上下文前，检测 PDF 页内是否引用了未嵌入的 CJK 字体（如 `STSong-Light-UniGB-UCS2-H`），通过 `font_manager.py` 自动加载系统可用黑体/宋体（macOS 苹方/华文黑体，Windows 微软雅黑，或内置 Noto Sans CJK SC）防止渲染丢字。
2. **智能拼版切分**：
   - 使用 `page.get_text("dict")` 查找页面内所有形如 `FBA[A-Z0-9]{9,}U\d{6}` 或顶栏 `FBA` + `Box \d+ of \d+` / `纸箱编号 \d+` 的锚点。
   - 若一页出现 1 个锚点 → 单箱页；若出现多个锚点 → 按相邻锚点的垂直/网格间距切分为多个独立的子箱区域（兼容每页 2/4/6 张的拼版）。
3. **跨版式语义定位与物理擦除（Redaction）**：
   - 先识别标签上半区信息分隔线（通常在 `FBA STA` 黑底横条上方，如样本中 `y=74.7pt` 上方），划定顶部地址检索区 `addr_rect`。
   - **定位并擦除发货地内容**：在 `addr_rect` 内搜索关键词 `SHIP FROM:` 或 `发货地：`（支持中英文冒号及大小写容错）。取该关键词的中心 X 坐标判断其处于左半栏还是右半栏（**自动兼容英文左栏与中文右栏相反布局**），构建该半栏内自标题行起（若勾选“连标题一起抹”则含标题行，否则从标题行下缘 `y1` 起）至 `FBA STA` 黑条上缘的矩形区域，调用 `page.add_redact_annot(rect, fill=(1, 1, 1))`。
   - **定位并擦除 `FBA:` 后公司名**：在 `addr_rect` 内搜索 `FBA:` 所在 span（如中文版式规律中 `[17.3, 31.4, 119.9, 42.4]`）。实证发现 `PyMuPDF` 的 `add_redact_annot()` 矩形若与上下行 `目的地：` (`y1=33.0`) 或 `<WAREHOUSE_RECEIVER>` (`y0=41.0`) 的行框 bbox 哪怕接触 0.1pt 都会误删相邻行首尾字符；因此必须将红框纵向内缩至字体核心区并删去该行后，在原 `origin` 精准补回干净的 `"FBA:"` 文本。
   - **执行物理抹除**：在 `PyMuPDF 1.26.7` 下调用 `page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)`——**只彻底删除指定区域的底层 PDF 文字流，绝对保护所有一维码、2D 码图像和外框线条不被误伤**。
4. **有效边界裁切与 `98×98mm` 居中落版**：
   - 在单箱子区域内（已擦除部分忽略），计算保留矢量对象、图像与文本的联合外接框（对于中文 `4×6` 单页，自动丢弃 `请不要遮住此标签` 以下的半页留白），外扩 `1mm` 呼吸边距后裁切为独立子页面；
   - 按等比例缩放到目标安全框（默认 `98.0 × 98.0 mm`，可在校准中心调节），居中贴入标准 `100.0 × 100.0 mm` (`283.46 × 283.46 pt`) 新 PDF 页面。
   - 若勾选“缺失 `Made In China` 时自动补印”且页内未检索到 `Made in China`（忽略大小写），则在左下角空白安全区自动绘制矢量文字 `Made In China`。

### 5.2 货代箱唛解析与三维度强校验 (`carrier_parser.py` & `pairing_engine.py`)
1. **字段提取**：
   - `shipment_id`：正则匹配 `\bFBA[A-Z0-9]{8,12}\b`（排除末尾带 `U000001` 的箱码）。
   - `box_index / total_boxes`：支持 `CTNS[:：\s]*(\d+)\s*/\s*(\d+)`、`Box\s*(\d+)\s*(?:of|/)\s*(\d+)`、`(\d+)\s*/\s*(\d+)\s*箱` 等多货代常见写法（并可在 `carrier_rules` 表扩展）。
   - `warehouse_code`：结合已知 FBA 仓点模式（如 `[A-Z]{3}\d` 且排除 `FBA`/`US` 等干扰词，优先取独立大字号文本块如 `DMO1`）。
2. **以 FBA 编号为核心的自动配对与人工兜底**：
   - **第一配对主键（`shipment_id`）**：支持用户一次性拖入多票货件的多份 FBA PDF 与货代箱唛 PDF，系统自动按提取出的 `shipment_id`（如虚构示例 `FBA00DEMO001`、`FBA00DEMO002`）归类配对；不同 FBA 编号的文件**严格隔离，绝不混配**，并显式标出缺失配对的那一侧文件。
   - **未识别 FBA 编号的人工归属兜底**：当少数货代箱唛的文件名与正文均未含可识别的 `FBA...` 货件号时，标记为「未识别货件号」，在文件条与异常提醒区提供「归属到货件」下拉框，用户手动选定目标 FBA 货件后，即刻按箱号自动配对。
   - **第二配对主键（箱号序号 `1..N`）**：在同一 `shipment_id` 分组内，将 `Box X of N` 与 `CTNS:X/N` 一一绑定。
   - **异常阻断与单边放行**：同一 FBA 编号下，若 `warehouse_code` 不一致或总箱数 `{1..N}` 无法 1:1 覆盖，立即红框告警阻断；同时支持「人工核对后仅打外箱标」或单箱「仅打外箱标 / 仅打箱唛」的克制放行模式。
3. **出纸队列编排**：
   - **贴面交替（默认推荐）**：对每箱 `i`，按 `[FBA_i, Carrier_i]` 重复 `copies_i` 次；
   - **同箱紧邻**：对每箱 `i`，先输出 `copies_i` 张 `FBA_i`，再输出 `copies_i` 张 `Carrier_i`；
   - **分组出纸**：先输出全部勾选箱的 FBA 标，再输出全部货代箱唛。

### 5.3 统一画布矢量渲染与多规格排版引擎 (`fnsku_engine.py` & `canvas_renderer.py`)
1. **新建任意尺寸模板与统一渲染复用**：用户可通过「新建标签」从预设（`50×30mm 双排`、`40×30mm 双排`、`100×100mm 单排`）或自定义宽高（`15~106mm × 15~200mm`）与单/双排排版创建新标签；产品标签设计与外箱标（`100×100mm`）单张微调共用同一套 `Element[]` JSON Schema 与后端矢量渲染管道，保证画布所见与 PDF/TSPL 打印输出 100% 毫米级一致。
2. **导入解析本地产品标签 PDF**：读取首行命中 `[BX][0-9A-Z]{9}` 的编码作为 FNSKU；收集其下方剩余文本行合并为原始标题；提取后自动执行可选清洗（行首 `新品\s*[-–—:]?\s*` → `New - `，全角标点 `，：（）` → 半角 `, : ()`），并直接生成初始可自由拖动的 `barcode1d` + `text` + `Made in China` 元素组落入画布。
3. **203dpi 整数 dot 对齐算法与实时可读性诊断（核心保扫码率）**：
   - 物理宽度：`50mm = 400 dots`，`30mm = 240 dots`（按 `8 dots/mm`）。
   - 前端在用户拖拉缩放 `barcode1d` 元素宽度 `W` 时，实时计算 `dots_per_module = (W * 8) / total_modules`：`< 1.5` 标红提示粘连拒扫风险，`< 2.0` 标黄预警，`>= 2.0` 显示扫码安全。
   - 后端最终出图生成条码时，将最窄条宽**向下取整为整数 dot（如 2 dots 或 3 dots）**并居中填入用户设定的 `(x, y, w, h)` 区域内、保护两侧静区，绝不产生半像素插值锯齿。
4. **双排拼版逻辑**：
   - 页面总宽：`50 + col_gap(默认2) + 50 = 102 mm`（`289.13 pt`），高 `30 mm`（`85.04 pt`）。
   - 打印 `N` 张时，生成 `ceil(N / 2)` 行双排标签，右栏按左栏元素集平移 `50 + col_gap` 毫米复刻渲染；若 `N` 为奇数，最后一行右栏保持空白。

### 5.4 跨平台打印抽象层 (`printers/`)
- **`TSPLRawAdapter`（推荐主路径）**：
  - 每次打印前自动写入对应规格 `SIZE {w} mm, {h} mm` + `GAP {gap} mm, 0 mm` + `DENSITY {darkness}` + `SPEED {speed}` + `DIRECTION 1` + `CLS` + `BITMAP 0,0,{bytes_per_row},{height_dots},0,{raw_1bit_bytes}` + `PRINT 1,1`。
  - **换纸完全无需去系统里改打印机驱动默认纸张**；
  - macOS 通过 `subprocess` 调用 `lp -d TSC_TTP_244_Pro -o raw`（支持传入临时 `.tspl` 文件）；Windows 通过 `win32print.WritePrinter(..., "RAW")` 发送。
- **`OSDriverPDFAdapter`（备选）**：macOS 使用 `lp -d {printer} -o PageSize=Custom.{w}mmx{h}mm -o ColorOption=None -o MediaMethod=Transfer ...`；Windows 使用 SumatraPDF/原生 GDI 传入自定义纸张尺寸打印 PDF。
- **`ExportPDFAdapter`（通用兜底）**：合并输出标准 PDF 文件，文件名自动带入货件号/SKU、规格与时间。

---

## 6. 实施里程碑与验收标准

1. **M1：后端核心引擎与离线 4 重测试闭环**
   - 实现 `fba_processor.py`、`carrier_parser.py`、`pairing_engine.py`、`fnsku_engine.py`、`tspl_encoder.py` 与 `simulator.py`。
   - **验收标准**：以程序生成的合成中英文测试夹具跑通 pytest 套件，验证 PDF 文本流中已无法检索到被抹除的发货人地址和公司名、中文零丢字、尺寸偏差 `< 0.1mm`、`zxing-cpp` 对所有输出 203dpi 仿真位图扫码 100% 通过。
2. **M2：`React + TypeScript + Mantine (CSS Modules) + Zustand + 矢量 SVG 毫米画布` 工作台前端开发**
   - 依确认后的交互原型与零 Tailwind 规范实现 4 个主模块、实时预览、参数持久化、双排仿真与可交互换纸防呆胶囊。
   - **验收标准**：完整走通上传、脱敏对比、配对异常拦截修正、双排调整与批次补打全流程。
3. **M3：跨平台真机实测与校准**
   - 连接实体 `TSC TTP-244 Pro`，实打 `100×100mm` 与 `50×30mm` 双排校准卡与测试样张各 1 组；在 Windows 环境完成相同测试。
   - **验收标准**：手机/工业扫码枪实扫全部条码秒识别，纸张裁切无错位偏移。
4. **M4：启动脚本与交付文档**
   - 交付 `start_mac.command` / `start_win.bat` 一键启动脚本与简明操作手册。

---

## 7. UI/UX 交互与无障碍极简设计规范（Studio 标准）

1. **左置 Icon Rail + 精简顶栏 + 三栏 Studio 工作台骨架**：
   - 保留高效率桌面端专业工作台架构：左侧 `68px` 暗色 Icon Rail 导航轨（外箱标签 / 标签设计 / 打印记录 / 打印机设置 + 左下导入入口）+ `50px` 精简顶部栏（左侧页面标题与完整上下文面包屑；右侧紧凑示例下拉、`⌘K` 快捷命令、可点击并实时预警的纸卷规格胶囊、主打印按钮）+ 三栏工作台布局。
   - **编辑器画布工具下沉归位**：画布模式分段、撤销/重做、吸附/网格与缩放步进器收拢到中央画布上方双胶囊工具条（与外箱舞台保持一致视觉语言），独立承接选中元素悬浮对齐栏，不挤占全局顶栏。
   - **去黑话自然语言**：统一采用卖家日常用语：**外箱标签**、**标签设计**、**打印记录**、**打印机设置**、**隐藏敏感信息**、**隐藏发货人地址**、**隐藏公司名称（保留仓库地址）**、**原图与处理对比**、**显示留白边距**、**打印效果模拟**。
   - **默认空白待导入态与零真实数据内置**：首次打开默认处于空白待导入状态，不预置、不加载、不嵌入任何真实商家信息或参考 PDF；示例下拉框仅按用户主动切换才生成 100% 前端代码合成的虚构 SVG 示意标签。
2. **无障碍（WCAG AA）与可读性硬约束**：
   - **字号与对比度底线**：禁止为追求极简缩小字号或淡化对比度，全站 UI CSS 文本字号保持 `>= 12px`（基准正文 `13px`），浅色与深色主题文本均满足 WCAG AA `>= 4.5:1` 对比度。
   - **标签与表单可访问性**：每一个 `<input>`、`<select>` 与 `<textarea>` 均必须拥有显式 `<label for>`（可见或 `.sr-only` 视觉隐藏）或包裹在 `<label>` 内，**严禁将 `placeholder` 作为唯一标签**；所有纯图标/符号按钮配备 `aria-label`。
   - **语义化交互与键盘支持**：主导航与抽屉页签使用 `role="tablist" / "tab" / aria-selected` 与 `role="tabpanel"`；弹窗使用 `role="dialog" aria-modal="true" aria-labelledby` 并支持 `Escape` 关闭；错误与未归属提示使用 `role="alert"`，状态与 Toast 使用 `role="status" aria-live="polite"`；全站保持清晰的 `:focus-visible` 焦点环。
3. **外箱三栏配对工作台与克制的人工兜底**：
   - **左栏**：双通道独立导入舱（① 亚马逊外箱 PDF、② 货代箱唛 PDF）、作业模式切换（成对配对 / 仅打外箱 / 仅打箱唛）、按 FBA 编号自动配对分组及箱号步进队列；未含 FBA 编号的箱唛在通道 ② 文件卡片中醒目标记并提供「归属货件」下拉框人工归属。
   - **中栏大舞台**：双联卡片与对比盒按可用宽高自适应等比缩放且 `flex-wrap: nowrap` 水平单排居中齐平（常规桌面屏不折行、顶部无裁切），支持「双联配对」（Box X ↔ CTNS:X/N 桥梁与缺失槽位补导）与「原图与处理对比」（第 1 步自动裁切示意 + 第 2 步左右拖动卷帘对比），顶部保留「调整这张标签」入口可将该箱带入设计器做叠层微调。
   - **右栏控制台**：每箱套数步进（默认 4 套，建议 3~5 面）、出纸顺序（贴面交替 / 同箱紧邻 / 分组先后）实时排队芯片预览、隐藏敏感信息 4 项规则开关、单箱单独补打与一键直连打印 / 导出合并 PDF。
4. **标签设计工作台、新建标签与条码文本一体化约束**：
   - **条形码与可读编码一体化**：FNSKU 一维码采用单个 `barcode1d` 元素一体化渲染条纹与正下方人类可读编码文字（提供「同时显示下方编号文字」开关与字号调节），**严禁把条形码和其正下方编号拆成两个独立元素**；修改编码时条形与文字同步联动更新，杜绝错号风险。
   - **新建标签与自由画布**：左栏支持 `+ 新建标签`（预设 `50×30mm 双排` / `40×30mm 双排` / `100×100mm 单排` 或自定义宽高与单/双排排版）、本地标签导入及基础元素/图层/模板抽屉；中栏自由画布支持毫米刻度尺、拖拽、8 向缩放、网格对齐吸附、悬浮上下文对齐栏、底部出纸实时预览与打印效果模拟；右栏防溢出属性检查器（`min-width: 0`）。
