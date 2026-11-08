# marcoRecorderScriptBuilder

冒险岛（MapleStory）自动化脚本工作台。仓库里同时存在两代方案：

- **离线世代（2022）**：用 Python 把动作拼成字符串，生成第三方宏软件可回放的 `.mcr` 文本脚本。不碰游戏进程，纯生成器。
- **在线世代（2023-12 起）**：Python 直接注入按键（`pydirectinput`），同时用 `mss` 截窗口、OpenCV 模板匹配小地图，拿到角色相对坐标做闭环修正。此外还有一批 PaddleOCR 驱动的「洗潜能 / 洗怪怪卡」半自动工具。

> **状态说明**
> 个人自用工具集：**没有 CI、没有打包**；`tests/test_refactor.py` 是唯一自动化检查（不启动游戏）。
> 提交历史：`2022-08-29` 首次提交 → `2023-12-27` 转入实时方案 → `2025-03-15` 最后一次业务提交。
> 之后做过一次重构：抽出 `maplebot/` 共享内核 + 新增 `run.py` 统一入口（见 [§9](#9-优化候选)）。
> `auto-maple/` 是一次未完成的重构，见 [§7](#7-auto-maple半成品重构)。

---

## 1. 目录速查

| 路径 | 作用 | 状态 |
|---|---|---|
| `run.py` | **统一入口**：找脚本 → 找窗口 → 起会话 → 收尾松键 | 新增 |
| `maplebot/` | **共享内核**：`config` / `utils` / `win32` / `capture` / `stop` / `runner` | 新增，唯一实现 |
| `tests/` | 重构自检（不启动游戏、不注入真实按键） | 新增 |
| `marcoRecorder/` | 生成 `.mcr` 宏文本（离线） | 可用，已停更 |
| `haikuScripts/` | 实时刷图主线：截屏识别 + 按键注入 | 主力，2025 年仍在改 |
| `haikuScripts/khali/` | 卡莉职业的按键原语 + 技能 CD 调度层 | 可用 |
| `haikuScripts/catms/` | OCR 洗潜能 / 洗怪怪卡核心类 | 可用（需人工摆窗口） |
| `auto-maple/` | 抄自开源 `tanjeffreyz/auto-maple` 的 OOP 版本 + 小地图窗口 | **半成品** |
| `src/` | 早期一次性试验脚本（图片过滤、OCR） | 废弃 |
| 根目录 `*.png` | 调试截图 / 模板素材 | 杂物 |
| `venv/` | Python 3.10.6 虚拟环境（`pyvenv.cfg` 指向 `E:\python10`） | 已在 `.gitignore` |

### 1.1 分层

```
haikuScripts/s2_clp.py 等                ← 刷图路线，仍是 while True + lib.xxx()
   │   老的扁平 import 一个字都不用改：
   │   import commandBuilderLib as lib / from capture import Capture
   ▼
haikuScripts/{capture,config,utils}.py   ← 薄壳：只给默认值（窗口标题 / 素材目录 / 检测开关）
auto-maple/src/{capture,config,utils}.py ← 薄壳：同上，默认值不同
   │
   ▼
maplebot/                                ← 唯一实现（haikuScripts 与 auto-maple 共用一份）
   config.py    全局状态
   utils.py     模板匹配 / 坐标换算 / HSV 过滤
   win32.py     窗口查找 / 矩形 / DPI
   capture.py   截屏线程 + 小地图识别
   stop.py      急停：stop key、按键记账、退出松键
   runner.py    统一入口实现（run.py 的 CLI）
```

`haikuScripts/config.py` 与 `auto-maple/src/config.py` 用
`sys.modules[__name__] = maplebot.config` 做成**模块别名**，所以 `import config`、
`import src.config`、`from maplebot import config` 拿到的是**同一个对象**——
以前「capture 写一份、脚本读另一份」的坑已经消失。

代码规模：73 个 `.py`（含新增的 `maplebot/` 与 `tests/`），最大的三个是 `catms/cube_washer.py`（419 行）、`commandBuilderLib.py`（382 行）、`khali/commands.py`（359 行）。

---

## 2. 环境准备

```powershell
# 依赖（pydirectinput / mss / opencv / paddleocr / pygame / pynput / pyautogui）
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

要点：

- **仅 Windows**：`pydirectinput`、`mss.windows`、`win32gui`、`pynput` 都是 Windows 专用。
- **Python 3.10**：`venv` 里是 3.10.11。
- **PaddleOCR 首次运行会联网下载模型**（落在 `~/.paddleocr`），第一次跑会卡几十秒，之后可离线。
- `requirements.txt` 里 `torch` / `easyocr` 大部分被注释：**符文自动求解已停用**（见 [§8](#8-已知问题)），不需要 TensorFlow，`easyocr` 也没再被代码引用（代码里统一用 PaddleOCR）。

---

## 3. 怎么跑

### 3.1 统一入口 `run.py`（推荐）

```powershell
python run.py --list                     # 看有哪些脚本、各是什么类型
python run.py --script s2_clp            # 跑一张图
python run.py --script khali_library_1 --window "MapleStory" --wait 60
python run.py --script s2_clp --dry-run  # 只看解析结果 + 逐条 import 检查
python run.py --check                    # 全仓库语法自检
```

它替脚本做了四件事（**脚本本身一行都不用改**）：

| 步骤 | 行为 |
|---|---|
| 找脚本 | 在 `haikuScripts/`、`marcoRecorder/`、`auto-maple/` 里按名字查；拼错会给近似建议（`s2_clpp` → `s2_clp`） |
| 找窗口 | 依次探测 `MapleStory` / `Haiku v236 (x64)` / `Haiku v224`，命中就写 `config.window_override`，**覆盖脚本里写死的标题** |
| 起会话 | 装好急停键（默认 `l`）与按键记账，然后 `runpy` 执行目标脚本 |
| 收尾 | 正常结束 / 按 `l` / Ctrl+C / 异常，都会**松开所有按下的键和鼠标键**，并停掉正在播的警报音 |

常用参数：

| 参数 | 说明 |
|---|---|
| `--script NAME`（或位置参数） | 脚本名（`s2_clp`）或路径 |
| `--dir DIR` | 只在指定目录里找（例如 `--dir tests/fixtures`） |
| `--window TITLE` | 显式指定窗口标题，优先级最高 |
| `--wait SEC` | 最多等窗口出现 SEC 秒，默认 0（不等待） |
| `--stop-key KEY` | 急停键，默认 `l`（大小写都认） |
| `--no-stop-key` | 不装急停键（只靠 Ctrl+C） |
| `--dry-run` | 只打印解析结果 + import 检查，不碰游戏 |
| `--stop-after SEC` | N 秒后自动停（自测用） |

**急停是怎么实现的**（为什么能停下任意 `while True` 脚本）：`maplebot/stop.py` 在
`pydirectinput.*` 和 `time.sleep` 上包一层「先检查停止标记」，停止时抛
`StopScript`（继承 `BaseException`，脚本里的 `except Exception` 吞不掉），把脚本
栈展开；同时记账按下过的键，收尾逐个松开。局限：**纯计算、不 sleep 的循环**
（目前只有 `legionBoard.py`）不会响应；Python 进程被强杀（任务管理器）时也来不及松键。

### 3.2 直接运行单个脚本（老方式，仍然可用）

```powershell
cd haikuScripts
..\venv\Scripts\python.exe s2_clp.py
```

导入关系没变（`capture` / `config` / `utils` 现在是薄壳），所以老脚本照旧能跑，
只是没有统一收尾——停止后请自己确认没有方向键/技能键卡住。

### 3.3 通用约定（两边都适用，最容易踩的坑）

1. **直接运行时，工作目录必须是代码目录**（扁平 import 靠它找模块）。模板图已经
   改成绝对路径（`haikuScripts/assets`），不再随 cwd 漂移；用 `run.py` 时 cwd 由它设置。
2. **先开游戏，再跑脚本。** `Capture.calibrate()` 找不到窗口时现在会**每秒重试**并
   打印提示，而不是拿全 0 矩形继续跑；`run.py --wait 60` 可以直接替你等。
3. **窗口标题写死在三个地方**，优先级 `--window` > run.py 自动识别 > 脚本显式传参 > 薄壳默认值：
   - `haikuScripts/capture.py`：默认 `'Haiku v236 (x64)'`
   - `auto-maple/src/capture.py`：`'Haiku v224'`
   - 各脚本里的 `Return(window_name="MapleStory")` / `Capture("MapleStory")`
4. **窗口必须完整可见**：`mss` 抓的是屏幕像素，最小化 / 被遮挡 / 远程桌面断开都会导致识别失效。DPI 已用 `SetProcessDPIAware()` 处理，但系统缩放仍会影响 UI 像素尺寸，建议 100%。
5. **开头 `time.sleep(3)` 是给你切窗口用的**，别删。
6. **坐标体系**：小地图归一化坐标 `(x, y) ∈ [0,1]`，纵轴再除以 `minimap_ratio` 让两个轴向同尺度（见 `utils.convert_to_relative`）。脚本里所有「地图坐标」都是这个体系。
7. **停止方式**：
   - 用 `run.py`：**任何脚本都按 `l`**（也可以 Ctrl+C）；
   - 直接运行：khali 系脚本按 `l`，其余 `while True` 脚本回终端 Ctrl+C。
8. **同一时间只能跑一个脚本**：`Capture.__init__` 会把实例挂到全局 `config.capture`，两个脚本会互相覆盖 `config.player_position`。
9. **管理员权限要一致**：游戏以管理员运行时，Python 也必须以管理员运行，否则 UIPI 会拦掉注入的按键（表现为「脚本在跑但角色不动」）。

---

## 4. `marcoRecorder/`：离线生成 `.mcr`

```powershell
python run.py --script scriptWriter        # 推荐；产物写到 marcoRecorder/script.mcr
```

老方式：

```powershell
cd marcoRecorder
..\venv\Scripts\python.exe scriptWriter.py   # → script.mcr
```

| 脚本 | 产物 |
|---|---|
| `scriptWriter.py` | `script.mcr`（最小示例：召唤 + 前跳） |
| `adele-truth1.py` | `adele-truth1.mcr` |
| `adele-truth2.py` | `adele-truth2.mcr`（最复杂，两层 `REPEAT` 嵌套） |
| `adele-car-theater.py` | `adele-car-theater.mcr` |
| `adele-meso-world-ending-2-5.py` | `adele-meso-world-ending.mcr`（注意产物名与文件名不一致） |

**原理**：`commandBuilderLib.py` 里每个函数只返回字符串，用 `\n` 拼接。

```python
keyDown("F")   -> "Keyboard : F : KeyDown"
wait(70)       -> "DELAY : 70"
forLoop(20, s) -> "REPEAT : 20 : 0 : 0 : Enter the number of iterations: : 0 : 0" + s + "ENDREPEAT"
```

**改一个路线**：在脚本里组装 `combination = [clib.xxx(), ...]`，最后 `open("xxx.mcr", "w")` 写出。`clib.countDuration(text)` 会正则累加所有 `DELAY` 值，用来核对一轮动作的总毫秒数（`adele-truth2.py` 末尾就打印了十几个 Loop 的时长对比）。没有反馈、没有识别，跳早了只能改 `DELAY` 数值重来。

---

## 5. `haikuScripts/`：实时刷图主线

### 5.1 最小运行步骤

```powershell
python run.py --script s2_clp --wait 60     # 推荐：run.py 负责等窗口、急停、松键
```

老方式也还能用（见 §3.2）：

```powershell
cd haikuScripts
..\venv\Scripts\python.exe s2_clp.py
```

### 5.2 运行时结构

```
Capture 线程（20fps，time.sleep(0.05)）
   截图 → 裁剪小地图 → 模板匹配 → 写全局 config
      config.player_position / map_invaded / rune_position / minimap / frame
主脚本线程
   读 config.player_position → 和硬编码的目标坐标比 → 决定按什么键
```

| 模块 | 职责 | 关键位置 |
|---|---|---|
| `capture.py`（薄壳 → `maplebot/capture.py`） | 找窗口、自动标定小地图矩形（左上/右下角模板匹配）、后台截屏循环 | `Capture.calibrate()` / `Capture._main()` |
| `config.py`（别名 → `maplebot/config.py`） | 全局状态板（模块级变量，跨线程无锁） | `player_position`、`map_invaded`、`capture` |
| `utils.py`（薄壳 → `maplebot/utils.py`） | 模板匹配（单/多目标）、HSV 颜色过滤、坐标换算 | `multi_match()`、`convert_to_relative()` |
| `returnToPoint.py` | 位置闭环：回到保存点 / 走向符文；警报线程；自动答题 | `returnToPoint()`、`approachHorizontal()`、`botTesting()` |
| `botCheckSolver.py` | PaddleOCR 读聊天框（符文提示）和 `@bot` 验证码弹窗 | `needSolveRune()`、`getBotText()` |
| `commandBuilderLib.py` | 按键原语 + 各职业技能连招 + UI 宏 | `delay()`、`jumpAttack()`、`sellAllEquips()` |
| `detection.py` | 符文箭头方向识别（TF 目标检测） | **已废弃**，见 §8 |
| `khali/commands.py` | 卡莉版原语 + `l` 急停 + 技能 CD 调度闭包 | `stopIfNotRunning`、`callWithInterval` |
| `khali/common_used_funcs.py` | 把 CD 绑成模块级函数对象，脚本里直接调用 | `totem`、`guild_dmg`、`rightForwardRing` |

### 5.3 入口脚本一览

**需要视觉闭环（用 `Return`，会启动 Capture + 警报线程）**

| 脚本 | 职业库 | 备注 |
|---|---|---|
| `s2_clp.py`、`s2_flat_vj.py`、`s2_flat_chuchu.py`、`s2_fami_card.py`、`s2_frenzy_clp.py` | `commandBuilderLib` | 每 2 轮 `returnToSavePoint()` 一次 |
| `endofworld14.py`、`vj.py` | `commandBuilderLib` | 用 `Return` 起 Capture/警报并 `r.save()`，但**没调用** `returnToSavePoint()`，靠写死的跳法硬走 |
| `khali_library_1.py`、`khali_hexa_library_1.py`、`khali_eow_2-7.py`、`khali_hexa_eof_1-4.py` | `khali` | 中文 OCR（`ocr_lang="ch"`，`rune_text="的诅咒应用中"`），按 `l` 停 |
| `util_recordpoints.py` | `Return` | **录点工具**，见 5.5 |

**纯按键盲打（不截屏，靠固定节奏）**

`castleGolem.py`、`clp.py`、`spiders.py`、`crown1.py`、`swallowSea1.py`、`lowerPast.py`、`bananaDogs.py`、`abandonArea2.py`、`yumyumFungosForest4.py`、`voidCurrent3.py`、`voidCurrent3Alter.py`、`catEnhance.py`（`catEnhance.py` 自带 `l` 停止）。
`fallout4build.py` / `fallout4scrap.py` 是**调试用**的「狂按 enter / r」，不是刷图脚本。

**工具脚本**

- `util_recordpoints.py`：坐标采集（5.5）
- `clicker.py`：每 0.2s 左键一次，测输入链路是否通
- `legionBoard.py`：连盟板块数小算盘（纯 print）
- `playground.py`：实验场，全是注释掉的调用，改代码时当草稿用

### 5.4 关键参数

```python
Return(
    window_name="MapleStory",              # 窗口标题，必须和客户端一致
    rune_text="must activate the Runestone",  # 聊天框里出现这个子串就警报
    ocr_lang="en",                         # PaddleOCR 语言：中文客户端用 "ch"
    ignore_rune_text_seconds=180,          # 开局 N 秒内不报符文（避免历史聊天记录误报）
    horizontal_threshold=0.01,             # 水平到位阈值（归一化坐标）
    vertical_threshold=0.02,               # 垂直到位阈值
)
```

`window_name` 的实际取值优先级：`config.window_override`（`run.py` 写入）> 这里传的值 > 薄壳默认值。

`returnToPoint.py` 顶部的动作距离阈值：`DOUBLE_JUMP=0.15`、`TRIPLE_JUMP=0.25`、`UPPER_JUMP=0.05`、`DOUBLE_UPPER_JUMP=0.15`、`WALKING_PER_SECOND=0.097`。换职业移动速度变了要重标这几个。

闭环逻辑：距离 > 阈值就选动作（三段跳 / 二段跳 / 按住方向键走 `距离 / 0.097` 秒），垂直方向同理；位置读数累计 4 次没变化就判定卡住并退出（计数器没清零，见 §8），不会无限顶墙。

### 5.5 录点工作流（新地图必用）

```powershell
cd haikuScripts
..\venv\Scripts\python.exe util_recordpoints.py   # 会先起 Capture，等 "Initialized"
```

进游戏走到关键位置，**按数字键 0–9**，控制台立刻打印 `Saved position in 3 (0.19230769, 0.33333333)`。把这些数字抄进脚本顶部当常量：

```python
LEFT_STAIR_GROUND  = (0.19230769230769232, 0.3333333333333333)
RIGHT_STAIR_PLATFORM = (0.8589743589743589, 0.23076923076923075)
```

（按 `l` 只结束循环、不会汇总打印；要汇总就 Ctrl+C，会在退出前把 0–9 全部打出来。）

### 5.6 新增一张图的脚本骨架

```python
import time
import commandBuilderLib as lib
from returnToPoint import Return

time.sleep(3)                                    # 给你切窗口

r = Return(window_name="MapleStory", rune_text="的诅咒应用中", ocr_lang="ch")
r.start()                                        # 起 Capture + 警报线程
time.sleep(1)
r.save()                                         # 记录当前点为返回点（index 0）

lib.totem()                                      # 轮回图腾（按 2）

while True:
    r.botTesting()                               # 出现 @bot 验证码就自动答
    r.returnToSavePoint()                        # 回到出发点
    lib.right(); lib.groundAttack()
    time.sleep(0.2)
    lib.left(); lib.groundAttack()
    time.sleep(0.2)
```

`commandBuilderLib` 常用件：`jump/cleave/groundAttack/jumpAttack/doubleJumpAttack/tribleJumpAttack/flashJumpAttack`（战斗）、`totem/buffSharpEyes/buffDsi/buffHs`（buff，分别按 2/3/4/5）、`sellAllEquips`（回收）、`check`（发 `@check` 聊天）、`delayRandomly`（加 0–70ms 抖动）。

---

## 6. `haikuScripts/catms/`：OCR 半自动（洗潜能 / 洗怪怪卡）

**这不是挂机脚本**，是「你摆好窗口，它帮你点」的助手：OCR 读三行潜能文本 → 命中词表就停，否则点「再次使用」。

```powershell
python run.py --script cat_wash_cube          # 洗魔方（方形潜能窗口）
python run.py --script cat_wash_fami          # 洗怪怪卡
# 老方式：cd haikuScripts && ..\venv\Scripts\python.exe cat_wash_cube.py
```

前置条件（全是硬编码的像素，换分辨率/UI 布局必须改）：

- 窗口标题 `"MapleStory"`，且 `+30` 是标题栏高度补偿（代码里到处是 `y + 30`）。
- 魔方窗口放在约定位置：三行文本裁剪区 `[426+30:441+30]` / `[441+30:455+30]` / `[455+30:469+30]`，`x` 范围 `610:765`。
- 怪怪卡：裁剪区 `471/485/498` 行，`x 465:663`；卡位坐标写在入口脚本里（`FAMI_POS = (725, 292)`）。
- 每次运行都会把中间图存成 `z_*.png` 到当前目录，**用来肉眼核对裁剪位置是否对**——这是调坐标时的唯一手段。

判定词表在 `cube_washer.py` 顶部（`CDR`、`STR_PRIME`、`LUK_SEC_250`…）和 `fami_washer.py` 顶部（`ATT_LINE = "物理攻击力：+14%"` 等）。要改「什么算毕业」，改这些常量；用哪个判定函数在入口脚本里选（`cat_wash_cube.py` 里被注释掉的若干 `if` 就是备选方案）。

---

## 7. `auto-maple/`（半成品重构）

```powershell
cd auto-maple
..\venv\Scripts\python.exe main.py
```

把它理解成 `haikuScripts` 的 OOP 化尝试 + 一个 Tkinter 小地图窗口（`Displayer`，菜单里的 `Recalibrate` 可以重新标定）。`src/capture.py` / `src/config.py` / `src/utils.py` 现在是共享内核的薄壳（默认窗口 `Haiku v224`，符文 / 黑屏 / 符文 buff 检测开启）。**但它跑不起来完整流程**：

- `src/rune.py` 第 18 行 `FLASHJUMP_DISTANCE_THRESHOLD = 2_` 是**语法错误**，整个文件无法解析；
- `src/capture.py` 依赖 TensorFlow 已移除；
- `main.py` 只做 `Capture` + `Displayer` 的循环，不刷图；
- `assets/models/rune_model_rnn_filtered_cannied/` 是 113MB × 2 份（另一份在 `haikuScripts/assets/`）的 TF checkpoint，**已被后续提交弃用**，纯占空间。

---

## 8. 已知问题

| 位置 | 问题 | 影响 |
|---|---|---|
| `auto-maple/src/rune.py:18` | `2_` 非法字面量 | 该文件无法 import（全仓库唯一的语法错误） |
| `haikuScripts/detection.py` | 用了 `tf` 但没 import；`load_model` 已删 | 调用即 `NameError` |
| `haikuScripts/returnToPoint.py:153` | `solveRune()` 里 `self.model` 从未赋值 | 调用即 `AttributeError`，符文求解整体**已废弃**，现在只能响警报 |
| `returnToPoint.py:51` | 卡住判定 `not_change_counter` 从不清零，累计 4 次相同读数就退出 | 正常移动时几乎不触发，但「走开又回到同一读数」也会被计入 |
| `haikuScripts/windowFocusLib.py` | 设了 `paused` 但**全仓库无人读取**；`SetWinEventHook` 句柄未保存/未卸载 | 这个「切出窗口自动暂停」功能实际没生效；且没人 import 它 |
| `haikuScripts/khali/jump_slash.py` | 空文件（0 字节） | — |
| `haikuScripts/input/keyboardmouse.py` | 只有一行 `from pydirectinput import ...` | 死文件 |
| `maplebot/stop.py` | 急停只能拦 `pydirectinput.*` 与 `time.sleep` | 纯计算循环（`legionBoard.py`）不响应；进程被强杀时来不及松键 |
| `maplebot/capture.py` | 仍在后台线程写全局 `config`（无锁） | 偶发读到半更新状态（既有行为，未改） |
| `commandBuilderLib.py` | `delay()` 是自旋 busy-wait | 占满单核（提交 `reduce cpu cost` 就是在调这个） |
| 全局 `config` | 跨线程读写无锁，靠轮询 | 偶发读到半更新状态（坐标/帧不同步），表现为「偶尔跳错方向」 |
| 各脚本顶部 | 地图坐标、阈值、`+30` 标题栏、1366×768 全硬编码 | 换分辨率要重标全部常量 |
| `z_*.png` | 调试截图直接写当前目录，无开关 | 仓库里长期残留；`git status` 现在就挂着 4 个未跟踪的 `z_*.png` |
| `requirements.txt` | `easyocr` 注释掉又单独列一行；`pynewinput`/`pyautogui` 实际未使用 | 装环境时容易困惑 |
| `marcoRecorder/adele-meso-world-ending-2-5.py` | 产物名 `adele-meso-world-ending.mcr` 与文件名不一致 | 容易找不到输出 |

---

## 9. 优化候选

### 已完成（本次重构）

1. ✅ **消重**：`capture/config/utils` 合并进 `maplebot/`，`haikuScripts/` 与 `auto-maple/src/`
   只剩薄壳（只声明默认窗口标题、素材目录、检测开关）。原先 6 个文件里的两份重复实现
   变成「一份实现 + 六个几行的薄壳」。
2. ✅ **统一入口**：`run.py`（实现见 `maplebot/runner.py`）负责找脚本 → 找窗口 → 起会话
   → `l` 急停 → 收尾松键；附带窗口重试、自动识别标题、`--list` / `--check` / `--dry-run` /
   `--stop-after`。脚本本身一行都不用改。

### 待办（按性价比排序）

3. **坐标外置**：把每张图的常量（录点得到的坐标、阈值、循环间隔）抽成一个 `maps/<map>.json` 或 `maps/<map>.py`，让 `util_recordpoints.py` 直接吐出配置文件，替代「看控制台手工抄数字」。
4. **`delay()` 换成 `time.sleep` + 事件**：现有精度收益已被 `pydirectinput` 自身开销淹没，busy-wait 只是在烧 CPU。
5. **决定符文识别的去留**：要么删掉 `detection.py` + `rune.py` + 两份 113MB 模型，要么把它真正修好（`load_model` + `self.model`）。
6. **`config` 结构化**：换成 dataclass + `threading.Event`/`Lock`，顺手解决「读到半更新状态」。
7. **调试输出开关**：`z_*.png` 收进 `debug/` 目录，用环境变量或 `--debug` 控制。
8. **加 `__init__.py`**：现在靠命名空间包 import（`from catms.cube_washer import ...`），换 IDE/换 Python 版本容易出问题，`catms/FAQ.md` 里已经记过这个坑。
9. **脚本模板化**：把每个脚本开头重复的 8 行（`time.sleep(3)` / `Return(...)` / `r.start()` / `r.save()`）
   收进一个 `maplebot.script.standard_open()`，新脚本只写主循环。

---

## 10. 环境备忘

- **语法自检**（不写盘，只做 AST 解析，已知坏文件会单独标注）：

  ```powershell
  .\venv\Scripts\python.exe run.py --check
  ```

- **重构自检**（不启动游戏、不注入真实按键，约 20 秒）：

  ```powershell
  .\venv\Scripts\python.exe tests\test_refactor.py
  ```

  覆盖：全仓库语法、模块同一性（`config` 别名）、`Capture` 薄壳与素材加载、
  `stop` 的急停/记账/松键（用假的 pydirectinput）、`run.py` 的解析与 `--stop-after` 端到端停止。

- **目录权限**：本机 `E:\workspace\marcoRecorderScriptBuilder` 的权限继承被断开过，受限账户在该目录内写文件会被拒。需要恢复继承时：`icacls "E:\workspace\marcoRecorderScriptBuilder" /inheritance:e`。
- **`.mcr` 产物与 `z_*.png` 都不入库**（`.gitignore` 忽略 `*.mcr`；`z_*.png` 属于误提交残留）。
