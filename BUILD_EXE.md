# 打包成 exe（PyInstaller，单文件）

目标：给别人一个 **双击就能跑、不用装 Python、首次运行不用联网** 的 exe。

当前结果：**255 MB 单文件**，冷启动约 **6 秒**，GUI 正常出窗口。

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

### 4.1 数据写到临时目录，退出就丢

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
