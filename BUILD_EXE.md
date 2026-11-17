# 打包成 exe（PyInstaller，单文件）

目标：给别人一个 **双击就能跑、不用装 Python、首次运行不用联网** 的 exe。

当前结果：**261 MB 单文件**，冷启动约 **6 秒**，GUI 正常出窗口，日志写在 exe 旁边的 `logs/`。

---

## 一、怎么打

在仓库根目录：

```powershell
.\venv\Scripts\python.exe -m PyInstaller --noconfirm ^
    --distpath build_exe\dist_gui --workpath build_exe\work_gui ^
    tools\pyinstaller\gui.spec
```

产物：`build_exe\dist_gui\小助手.exe`

配置和入口都在仓库里（**会随版本提交**）：

```
tools/pyinstaller/gui.spec      GUI 版（console=False）
tools/pyinstaller/exe_entry.py  自检版入口（console=True，打印 SMOKE OK）
tools/pyinstaller/gui_main.py   GUI 版入口
```

`build_exe/`（产物、中间文件）已加入 `.gitignore`，不进版本库。

---

## 二、实测数据

| 版本 | 大小 | 结果 |
|---|---|---|
| 不加任何排除（天真打包） | **5,221 MB** | 把 venv 里的 torch(3.5G)、tensorflow(870M) 全拖了进来 |
| 精简 + 自检入口 | 255 MB | `SMOKE OK`：正确读出 `coins=0 weight=5 capacity=135` |
| 精简 + GUI 入口 | **255 MB** | 出窗口「小助手」，内存 69 MB，冷启动 **5.7 秒** |

体积构成：paddle 274 MB、cv2 133 MB、OCR 模型 46 MB（压缩后合计 255 MB）。

---

## 三、踩过的坑（都写进 spec 了）

### 1. 不排除无关大包 → 5 GB

venv 里装了 torch / tensorflow（别的项目用的），PyInstaller 的 hook 会顺着依赖拖进来。

```python
EXCLUDES = ["torch", "torchvision", "torchaudio", "tensorflow", "keras", ...]
```

### 2. bundle 里的 Cython 会遮蔽真正的包

现象：

```
FileNotFoundError: ...\_MEI\Cython\Utility\StringTools.c
```

`from paddleocr import PaddleOCR` 直接失败。排除 `Cython` 后正常。

### 3. paddleocr 真的依赖 scipy / scikit-image / pandas

一开始为了瘦身把它们排掉了，逐个报错：

```
No module named 'unittest'   → 不能排 unittest
No module named 'skimage'    → 不能排 scikit-image
```

结论：**只排与跑商无关的包，别对 paddleocr 的依赖做猜测式裁剪。**

### 4. OCR 模型要一起打包

模型默认在 `~/.paddleocr`（约 46 MB）。打包时复制进包内，
运行时用环境变量指过去：

```python
os.environ.setdefault("PADDLEOCR_HOME", str(root / ".paddleocr"))
```

这样**首次运行不用联网**。

---

## 四、还没解决的问题（分享前必须处理）

### 4.1 数据写到临时目录，退出就丢（**已解决**，见第五节）

工具会写 `data/trade/*.jsonl`（价格记录、时间样本）。打包后
`Path(__file__).resolve().parents[1]` 指向 `_MEIPASS`（临时解包目录），
写完就在退出时被删掉。

需要改成：**exe 同目录**，或 `%LOCALAPPDATA%\小助手\`。

### 4.2 分辨率 / DPI 没做检查

所有坐标按 **1366×768 客户区 + 100% 缩放** 写死。别人不同分辨率会
静默读错，不会报错。分享前应加启动检查并明确提示。

### 4.3 体积 255 MB

想再小只能换 OCR 方案（ONNX / 系统自带 OCR），那是重写级别的改动，
见 `TRADE_DESIGN.md` 里关于 C# 移植的讨论。

## 五、运行期数据落在哪里（2026-11-17 加入）

### 5.1 为什么需要

单文件 exe 运行时会把内容解压到临时目录（`sys._MEIPASS`），**exe 一退出就删掉**。
如果还往那里写观察记录、学到的模板，用户每次重开都从零开始（甚至写入直接失败）。

### 5.2 现在的规则（`maplebot/paths.py`）

```
只读资源（RES_ROOT = _MEIPASS）
    图标、数字模板、预置地图名、goods.json …

可写数据（DATA_ROOT）
    观察记录、过图记录、新学的模板、调试图
```

`DATA_ROOT` 的选择顺序：

1. exe 旁边有 `portable.txt` 且目录可写 → `<exe目录>\data`
2. exe 旁边有 `localdata.txt` → `%LOCALAPPDATA%\MapleTrade\data`
3. exe 目录可写 → `<exe目录>\data`（默认，便携：数据跟着文件夹走）
4. 不可写（`C:\Program Files` 之类）→ `%LOCALAPPDATA%\MapleTrade\data`

**种子复制**：首次启动把只读资源里的 `data/` 补到 `DATA_ROOT`，
**只补缺失文件，绝不覆盖**用户已有数据。实测种子 296 个文件。

**环境变量覆盖**：`MAPLE_TRADE_DATA=<目录>` 可以强制指定（调试用）。

### 5.3 启动日志

```
[啟動] 数据目录：E:\MapleTrade\data（资源目录：C:\Users\...\Temp\_MEIxxxxx）
```

出问题时先看这一行，就能知道数据落在哪。

### 5.4 还没验证

- **没有在真正打包出来的 exe 上测过**：种子复制、便携/兜底切换都只在源码模式
  和临时目录模拟里验证过；下次打包后要实测这三件事。
- `gui.spec` 已经包含 `(data/trade, "data/trade")`，种子数据会进 exe。
### 5.3 日志（2026-11-17 加入）

exe 会在**自己旁边**建 `logs/`：

```
<exe 目录>\logs\assistant-YYYYMMDD-HHMMSS.log     单个 2 MB 上限，留 5 个
不可写时退到 %LOCALAPPDATA%\MapleTrade\logs\
```

发给别人测试时，让他出问题就把**最新的那个 .log 发回来**，里面有：

```
启动环境（版本/Python/Windows/屏幕/数据目录/依赖版本）
每 30 秒一次心跳（地图、金币、负重、缩放、帧数、失败次数、共享统计）
所有异常（含 traceback）和所有 print 输出
```

隐私：不截屏、不读角色名、不记录账号信息（日志第一行有写）。

打包时不用额外处理：`logs/` 是运行时创建的，不会进包。

### 5.4 只打包程序需要的数据（2026-11-17 加入）

`data/trade` 里混着运行期产物（记录簿、地图访问记录、学习到的未知图标等）。
以前整个目录打进包，等于把本机历史数据发给每个测试者。现在 spec 里白名单：

```
目录：anchors  icons  merchants  merchants_face  map_names
文件：digits.json  good_names.json  goods.json  goods_routes.json
      map_graph.json  map_tree.md  merchant_faces.json  merchant_index.json
      merchant_maps.json  edge_times.json  edge_truth.json  edge_worklist.md
```

不打包：`observations*`、`*.jsonl`、`seen_portals.json`、`map_nodes.json`、
`map_graph_user.json`、`icons_unknown/`。

实测：exe 首次运行只生成空的 `data/trade/`，没有 observations 文件。
## 六、打包检查清单（2026-11-18 事故后加）

### 6.1 事故：包里没有数据 → 看板空

打包时我用：

```powershell
robocopy $src $stage /E /XD data logs
```

`/XD data` 排除的是**所有叫 data 的目录**，包括 `_internal\data`——
而商人表、图标模板、地图名模板全在那里。结果：

```
exe 能启动、能截屏、能识别地图名（从画面里学）
但 _fixed_merchants() 读到空的商人数 → 看板一条商人都不显示
直到玩家进到某张图，程序"现学"一个地图/商人才显示出来
```

**正确写法：排除项用绝对路径，只排掉顶层的运行期目录**

```powershell
robocopy $src $stage /E /XD "$src\data" "$src\logs"
```

### 6.2 打包后必须验证的四件事

```powershell
# 1) 包里有数据
Get-ChildItem "$stage\小助手\_internal\data\trade" | Measure-Object      # 应为 17 项
Get-ChildItem "$stage\小助手\_internal\data\trade\merchants" | Measure-Object  # 应为 15 个
# 2) 共享配置在 data 里（不在 _internal）
Test-Path "$stage\小助手\data\share.json"                                # True
# 3) 解压到干净目录跑一次，日志前几行应当是
#    [啟動] 版本=... 打包=True
#    [共享] 已啟用（後台同步）
#    [mapwatch] 起点地图：<某张已知地图>     ← 说明模板加载成功
# 4) 运行时补种
(Get-ChildItem "$folder\data\trade\merchants").Count                      # 应为 15
```

### 6.3 另一个坑：空名字模板

`save_name_template("")` 会写成 `map_names\.png`，加载时变成一张**无名模板**，
既占位置又可能干扰匹配。现在函数里加了空名字守卫，并且已删掉历史生成的 `.png`。

### 6.4 版本号从哪来

exe 里的版本 = 打包时仓库根目录的 `BUILD.txt`（spec 会把它塞进 `_internal`），
格式 `2.0.0+<git 提交>`。排错时先看日志第一行的版本，确认群友跑的是哪一版。
