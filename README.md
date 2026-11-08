# marcoRecorderScriptBuilder

冒险岛（MapleStory）自动化脚本工作台。仓库里同时存在两代方案：

- **离线世代（2022）**：用 Python 把动作拼成字符串，生成第三方宏软件可回放的 `.mcr` 文本脚本。不碰游戏进程，纯生成器。
- **在线世代（2023-12 起）**：Python 直接注入按键（`pydirectinput`），同时用 `mss` 截窗口、OpenCV 模板匹配小地图，拿到角色相对坐标做闭环修正。此外还有一批 PaddleOCR 驱动的「洗潜能 / 洗怪怪卡」半自动工具。

> **状态说明**
> 个人自用工具集：**没有 CI、没有打包**；自动化检查都在 `tests/`（不启动游戏、不注入按键），一条命令全跑：
> `.\venv\Scripts\python.exe tests\run_all.py`。
> 提交历史：`2022-08-29` 首次提交 → `2023-12-27` 转入实时方案 → `2025-03-15` 最后一次业务提交。
> 之后做过一次重构：抽出 `maplebot/` 共享内核 + 新增 `run.py` 统一入口（见 [§10](#10-优化候选)）。
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
   timing.py    精确等待（睡眠 + 短自旋，不烧 CPU）
   win32.py     窗口查找 / 矩形 / DPI
   minimap.py   小地图定位（白色圆角边框，§5.8）
   player.py    角色定位/跟踪（黄点 + 白圈，§5.9）
   capture.py   截屏线程 + 小地图识别
   stop.py      急停：stop key、按键记账、退出松键
   runner.py    统一入口实现（run.py 的 CLI）
   rune.py      符文面板定位 / 裁剪 / 按方向键（§8）
   rune_api.py  DeepSeek 视觉 API：截图 → 4 个方向（§8）
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
- `requirements.txt` 里 `torch` / `easyocr` 大部分被注释：本地 TF 符文识别已停用（新方案见 [§8](#8-符文识图deepseek-视觉-api)），不需要 TensorFlow，`easyocr` 也没再被代码引用（代码里统一用 PaddleOCR）。
- **符文识图需要 API key**：放在仓库根的 `deepseek.local.json`（已被 `.gitignore` 的 `*.local.json` 忽略，绝不入库）。文件里 `api_key` 空着就等于是未配置；也接受只写裸 key 的纯文本。依赖 `openai`（官方无独立 Python SDK，DeepSeek 文档指定用 OpenAI SDK，`base_url` 指向 `https://api.deepseek.com`），已加进 `requirements.txt`。

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
| 找窗口 | 按 `maplebot.local.json` 里的候选标题（默认 `MapleStory`）探测，命中就写 `config.window_override`，**覆盖脚本里写死的标题** |
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
   - `haikuScripts/capture.py`：窗口标题从 `maplebot.local.json` 读（默认 `MapleStory`）
   - `auto-maple/src/capture.py`：窗口标题同上
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
| `commandBuilderLib.py` | 按键原语 + 各职业技能连招 + UI 宏 | `delay()`（混合等待，见 §5.7）、`jumpAttack()`、`sellAllEquips()` |
| `detection.py` | 符文箭头方向识别（TF 目标检测） | **已废弃**，改由 §8 的 API 方案取代 |
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

闭环逻辑：距离 > 阈值就选动作（三段跳 / 二段跳 / 按住方向键走 `距离 / 0.097` 秒），垂直方向同理；位置读数累计 4 次没变化就判定卡住并退出（计数器没清零，见 §9），不会无限顶墙。

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

### 5.7 时序与 CPU（P0 之后）

**`delay()` 不再自旋。** 以前 `lib.delay(0.2)` 是 `while perf_counter() < end: pass`——等 200 ms 就烧 200 ms CPU。脚本大部分时间都在等（落地、后摇、点击间隔），于是进程长期占满一个核。

现在由 `maplebot/timing.py` 拆成「先 `time.sleep` 睡到还差几毫秒 → 最后几毫秒自旋」；自旋尾段在启动时实测 `time.sleep` 的过冲量自适应（2~20 ms；本机定时器粒度 15.6 ms，因此 tail≈14 ms）。

实测（本机，20 次 `delay(0.2)` 共 4 秒，×3 次取范围）：

| | 墙钟 | CPU | 单核占用 |
|---|---|---|---|
| 现在（混合等待） | 4000.1 ms | 31~47 ms | **0.8~1.2%** |
| 以前（纯自旋） | 4000.1 ms | 4000 ms | **100%** |

平均每次仍是 200.01~200.03 ms（目标 200 ms）——**精度没变**。复现：

```powershell
.\venv\Scripts\python.exe tests\bench_delay.py
$env:MAPLEBOT_PRECISE_DELAY=1; .\venv\Scripts\python.exe tests\bench_delay.py   # 老行为对比
```

要退回纯自旋（最准、最费 CPU）：`$env:MAPLEBOT_PRECISE_DELAY=1`。

**帧率可在运行时调。** `Capture.set_frame_interval(seconds)` 让截屏线程按新间隔跑（下一帧生效）：等技能 CD / 等落地时可以调到 0.3~1.0 省 CPU，需要精细定位时再调回 0.1。

**注意**：`delay()` 的参数一直是**秒**（`0.008`/`0.015`/`0.2`/`0.55`），旧参数名 `ms` 起错了，P0 里已改成 `seconds`。

### 5.8 小地图定位（客户端改版后）

旧做法靠两张角模板（`minimap_tl_template.png` / `minimap_br_template.png`）匹配小地图的左上/右下角。**客户端改版后这两张模板失效**：在新截图上标定出来是 966×682（几乎半屏），而真实小地图只有 190×78。

现在改成找「白色圆角边框」（`maplebot/minimap.py`）。有两条现实约束决定了算法：

1. **尺寸/形状不固定**（随地图变）→ 不能写死尺寸，只能量出左上、右下两个角；
2. **边框半透明**（颜色随背后的画面漂移，实测同一张图里就有 228/186/177 几种亮度）→ 不能用固定白色阈值。

```
按由严到宽的白阈值依次尝试：V≥210/185/160/135/110（S≤40~95）
→ 连通域 → 对每个候选检查：
     · 尺寸：窗口的 6%~40%，不占满整个搜索区（否则没有"外侧"可比）
     · 宽高比 0.8~6.0（方形、宽扁都允许）
     · 四边各自 ≥30% 是白的、整圈 ≥55%（容忍半透明和遮挡造成的缺口）
     · **边框比外侧 3px 的环亮 ≥20**（面板底色是暗的，这条才是真正的判据）
     · 排除"内部和边框一样亮且毫无纹理"的纯色亮块
→ 取面积最大的那个
```

实测（`rune_example.png`，1368×800）：

```
白框: x=8 y=99 w=198 h=82   内容区=(11, 102, 192, 76)
阈值=(210,40) 四边=[0.98, 0.98, 0.95, 0.95] 边框亮度=224 外侧=58
```

耗时 **0.6 ms**/次；没有白框时返回 `None`。

缩放与「半透明/亮度」容差（测试里都覆盖了）：

| 场景 | 结果 |
|---|---|
| 0.75× / 1.0× / 1.5× / 2.0× 缩放 | 全部命中（尺寸按比例） |
| 地图内部亮度 30 / 60 / 120 / 180 / 220 | 全部命中（判据是外侧对比，不是内部暗） |
| 边框透明度 0.4 / 0.6 / 0.8 / 1.0 | 全部命中（最暗时边框亮度 126，仍低于最严阈值也找得到） |
| 尺寸 140×55 / 200×80 / 300×200 / 400×90 / 120×120（方形） | 全部命中 |

已知取舍：**纯色亮块**（内部和边框一样亮、且没有纹理）会被排除；但如果地图被折叠、只剩标题缩略图（约 44×44），会因为低于 6% 的尺寸下限而不被当成小地图。

`Capture` 的 `minimap_locator` 参数决定用哪种方式：

- `"auto"`（默认）：先找白框，找不到再退回旧模板 —— 新客户端走白框，老客户端自动兼容；
- `"white_border"`：只用白框（找不到就保持未标定，等下一轮）；
- `"template"`：旧行为。

命令行自查：

```powershell
python -m maplebot.minimap rune_example.png --save debug/mm.png
```

### 5.9 角色定位（黄点 + 白圈）

小地图上的图标靠**颜色**区分身份：

| 实体 | 图标 | 实测 HSV |
|---|---|---|
| **自己** | 白圈 + **黄点** | (28, 255, 254) |
| 其他玩家 | 白圈 + **红点** | 红（H≈0） |
| NPC / 传送点 | 白圈 + **绿点** | H≈60 |
| 符文 | 紫菱形 | H≈143 |
| 地形 / 平台 | 暗黄/棕 | (5, 221, 53) ~ (12, 245, 76)，亮度差一个量级 |

所以 `maplebot/player.py` 的做法是：**黄色门控**（H 18–42、S≥190、V≥190）→ 尺寸/面积过滤 →
**白圈校验**（半径 2.8–5.2 的环上要有一圈"亮且不饱和"的像素，V≥170、S≤90）。
最后这条很关键：黄块本身 S=255 会被排除，只有真的白圈才算数，所以"没白圈的黄块"（比如地形）
不会被误判；实测玩家环占比 0.31~0.41，平台/绿点/菱形/空地全是 0.00。

**跟踪**（`PlayerTracker`）：

| 情况 | 行为 |
|---|---|
| 多个候选 | 选离"上一帧位置 + 速度×dt"最近的 |
| 位移超过内容区宽度的 10% | 视为切图/复活：直接对齐，`jumps += 1` |
| 这一帧没找到 | **保持上一帧位置**，`config.player_stale = True`（0.35 s 后仍没找到则位置变 None） |
| 1px 抖动 | 一阶低通（新测量占 65%），并估计速度 |

`Capture` 每帧调用 `_update_player()`，写两个新的全局变量：

- `config.player_position`：归一化坐标（和以前一样，两个轴都除以小地图宽度，保证各向同性）；
- `config.player_stale`：位置是否不可信（**丢失时不再写 `(0,0)`**，脚本看到 stale 就别做依赖位置的动作）；
- `config.player_score`：最近一次检测的置信分，调试用。

性能（真实截图、缓存小地图框）：**0.115 ms/帧 → 30 Hz 下约 0.3% 单核**。对比截屏 6.6 ms/帧，
位置识别不是瓶颈。`Capture.calibrate()` 会顺带 `player_tracker.reset()`（换图/换窗口时轨迹作废）。

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

把它理解成 `haikuScripts` 的 OOP 化尝试 + 一个 Tkinter 小地图窗口（`Displayer`，菜单里的 `Recalibrate` 可以重新标定）。`src/capture.py` / `src/config.py` / `src/utils.py` 现在是共享内核的薄壳（窗口标题同上，符文 / 黑屏 / 符文 buff 检测开启）。**但它跑不起来完整流程**：

- `src/rune.py` 第 18 行 `FLASHJUMP_DISTANCE_THRESHOLD = 2_` 是**语法错误**，整个文件无法解析；
- `src/capture.py` 依赖 TensorFlow 已移除；
- `main.py` 只做 `Capture` + `Displayer` 的循环，不刷图；
- `assets/models/rune_model_rnn_filtered_cannied/` 是 113MB × 2 份（另一份在 `haikuScripts/assets/`）的 TF checkpoint，**已被后续提交弃用**，纯占空间。

---

## 8. 符文识图（DeepSeek 视觉 API）

符文解谜：屏幕上出现「想要解放符文，請按順序輸入方向鍵」和 4 个箭头，**从左到右**敲方向键即可。
现在用视觉模型读箭头，不再需要本地 TensorFlow 模型（`detection.py` + 两份 113 MB checkpoint 可删）。

### 8.1 为什么先本地裁剪再发图

- 箭头在原图里只有 ~28 px，整屏发过去缩放后更小，容易读错；
- 单图 token 有 **1024** 上限，所以「裁剪 + 放大」不额外花钱，却能让箭头占满画面；
- 本地定位顺带产出 bbox，可用于判断「面板还在不在」。

### 8.2 实测几何（`rune_example.png`，1368×800）

| 元素 | 像素 |
|---|---|
| 4 个箭头 bbox | x 487–777，y 245–282（290×37） |
| 外扩 20 px 后裁剪 | x 467–797，y 225–302 |
| 放大 3× 后发给模型 | **990×231** PNG |

### 8.3 定位算法（`maplebot/rune.py`）

HSV 阈值 `H≤75 / S≥140 / V≥150`（箭头是红橙黄绿；天空和大部分 UI 是蓝色）→ 5×5 闭运算 →
连通域 → 尺寸过滤（阈值按窗口宽度缩放）→ 按 y 聚行 → 取「**恰好 4 个**」的那一行。

固定 ROI：**x 20–75%、y 25–45%**，正好避开上方横幅文字与面板下方那行黄字。
实测：0.75×/1.5×/2× 缩放、±25 px 平移都能稳定找到 4 个；把面板抹掉则 0 误报。

### 8.4 触发：小地图菱形 + buff CD

解不解由两个观察点决定（都在 `maplebot/rune.py`）：

| 检测 | 方法 | 实测 |
|---|---|---|
| 小地图上的符文菱形 | 在 `find_minimap().inner()` 里找**紫罗兰色块**（H 132–168、S≥90、V≥120），再按尺寸/宽高比/填充率筛选 | 真实样本命中 `(119,114,7,7)`；无符文的样本返回 `None`；0.75×~2× 缩放仍然命中 |
| buff 栏的符文 CD 图标 | 右上角 ROI（x≥74%、y≤20%）里，用图标**上半部分**（33×18，`assets/rune_cd_top.png`）做 `TM_CCOEFF_NORMED` | 有 CD 时 **1.000**，无 CD 时 **0.70~0.72**；阈值 0.85 |

为什么"上半部分"能解决数字变化：模板只比较它覆盖的那 18 行像素，倒计时数字在图标下半部分，
根本不在比较范围内 —— 数字怎么变都不影响。你把 UI 设置改成"小字 + 右下角"之后会更干净。

```python
icon = rune.find_rune_icon(frame)          # None 或菱形 bbox
visible, score, box = rune.rune_cd_visible(frame)   # (bool, 分数, bbox)
should_solve = icon is not None and not visible
```

`rune_cd_visible` 返回分数而不只是布尔，方便按实际客户端调阈值。

### 8.5 调用链

`maplebot/rune.py`（定位 / 裁剪 / 按键 / 触发检测）+ `maplebot/rune_api.py`（凭据 / 请求 / 解析）：

```python
panel = rune.find_panel(frame)          # None → 屏幕上没有符文面板
crop = rune.crop_panel(frame, panel)    # 990×231 BGR
directions = solver.solve(crop)         # ["down", "down", "left", "down"]
rune.press_directions(directions)       # 100 ms ± 30 ms 抖动，逐键 keyDown/keyUp
```

请求参数：`model=deepseek-flash`、`temperature=0`、`response_format={"type":"json_object"}`、
`thinking=disabled`、图片走 base64 `data:` URL + `detail=high`。
每按一个键之前都会 `stop.check()`，所以急停不会卡在序列中间。

### 8.6 离线验证（不需要游戏）

```powershell
python -m maplebot.rune --no-api rune_example.png    # 只做定位 + 裁剪，不联网
python -m maplebot.rune rune_example.png             # 真调 API（需要 key，见 §2）
python -m maplebot.rune rune_example.png --save-crop debug/crop.png
python -m maplebot.minimap rune_icon.png             # 小地图白框定位
```

### 8.7 解一次符文的完整流程（`RuneSession`）

```python
session = rune.RuneSession()        # 默认读 config.capture.frame，按 alt/esc
ok = session.solve_and_verify()     # True = 解成功；False = 3 次都失败
```

每次尝试的流程：

```
面板不可见 → open_panel()（默认按 alt）→ 等 panel_timeout（1.5 s）
  截图 → 找 4 个箭头 → 裁剪 → 问 API → 按方向键（100 ms ± 30 ms 抖动）
  等 buff 栏出现 CD 图标（cd_timeout 3 s）→ 出现 = 成功
  失败（含"模型看不清"）→ close_panel()（esc）→ 等 reopen_delay（2 s）→ 下一次
3 次都失败 → give_up() → return_to_town()（目前只打印 TODO，回城逻辑未实现）
```

`session.history` 会记录每次尝试的方向与结果，`session.last_error` 是最后一次失败原因。

**前提：地图里只有自己**（单人刷图）。所以流程里**不会**在开始前复查 CD、也不处理
"别人抢先解了符文"的情况 —— 如果以后要多人同图，需要在 `solve_and_verify()` 开头加一次
`rune_cd_visible()` 检查，并把"CD 已亮"当作"跳过而不是成功"。

**`open_panel` / `close_panel` 是可注入的**：默认实现只是"按 alt / 按 esc"。因为
"判断该不该按 alt、走到符文旁边"属于移动/交互逻辑（还没写），所以这里刻意只留一个钩子：

```python
session = rune.RuneSession(open_panel=my_walk_to_rune_and_press_alt)
```

移动逻辑做好以后替换这两者即可，识别 / 验证 / 重试逻辑不用动。

### 8.8 不确定时

解析不出 4 个合法方向（数量不对 / 非法词 / 模型说看不清 / 网络错误）时，`solve()` 抛
`RuneSolveError` 或 `RuneAPIError`，**一个键都不按**，直接进入下一次尝试（ESC → 等 2 s → 重新打开）。

⚠️ 裁剪图会发到 DeepSeek（第三方服务），介意的话不要启用该功能。

---

## 9. 已知问题

| 位置 | 问题 | 影响 |
|---|---|---|
| `auto-maple/src/rune.py:18` | `2_` 非法字面量 | 该文件无法 import（全仓库唯一的语法错误） |
| `detection.py` / `returnToPoint.solveRune()` | 本地 TensorFlow 符文识别链已断（无 `tf` 导入、`self.model` 从未赋值） | **已被新方案取代**：符文区域截图 → DeepSeek 视觉 API 识图（符文出现频率低，API 开销可忽略，无需本地模型/推理环境）。这两个文件与两份 `assets/models/`（2×113 MB）可删 |
| `returnToPoint.py:51` | 卡住判定 `not_change_counter` 从不清零，累计 4 次相同读数就退出 | 正常移动时几乎不触发，但「走开又回到同一读数」也会被计入 |
| `haikuScripts/windowFocusLib.py` | 设了 `paused` 但**全仓库无人读取**；`SetWinEventHook` 句柄未保存/未卸载 | 这个「切出窗口自动暂停」功能实际没生效；且没人 import 它 |
| `haikuScripts/khali/jump_slash.py` | 空文件（0 字节） | — |
| `haikuScripts/input/keyboardmouse.py` | 只有一行 `from pydirectinput import ...` | 死文件 |
| `maplebot/stop.py` | 急停只能拦 `pydirectinput.*` 与 `time.sleep` | 纯计算循环（`legionBoard.py`）不响应；进程被强杀时来不及松键 |
| `maplebot/capture.py` | 仍在后台线程写全局 `config`（无锁） | 偶发读到半更新状态（既有行为，未改） |
| 小地图角模板 | `minimap_tl/br_template.png` 是旧客户端 UI，新客户端匹配不到（会标定出半屏大小） | 已由 §5.8 的白框定位取代；`minimap_locator="auto"` 会先试白框、失败才退回模板 |
| ~~`commandBuilderLib.py`~~ | ~~`delay()` 是自旋 busy-wait~~ | ✅ **已修复（P0，见 §5.7）**：单核占用 100% → 0.8%，精度不变 |
| 全局 `config` | 跨线程读写无锁，靠轮询 | 偶发读到半更新状态（坐标/帧不同步），表现为「偶尔跳错方向」 |
| 各脚本顶部 | 地图坐标、阈值、`+30` 标题栏、1366×768 全硬编码 | 换分辨率要重标全部常量 |
| `z_*.png` | 调试截图直接写当前目录，无开关 | 仓库里长期残留；`git status` 现在就挂着 4 个未跟踪的 `z_*.png` |
| `requirements.txt` | `easyocr` 注释掉又单独列一行；`pynewinput`/`pyautogui` 实际未使用 | 装环境时容易困惑 |
| `marcoRecorder/adele-meso-world-ending-2-5.py` | 产物名 `adele-meso-world-ending.mcr` 与文件名不一致 | 容易找不到输出 |

---

## 10. 优化候选

### 已完成

1. ✅ **消重**（重构）：`capture/config/utils` 合并进 `maplebot/`，`haikuScripts/` 与 `auto-maple/src/`
   只剩薄壳（只声明默认窗口标题、素材目录、检测开关）。原先 6 个文件里的两份重复实现
   变成「一份实现 + 六个几行的薄壳」。
2. ✅ **统一入口**（重构）：`run.py`（实现见 `maplebot/runner.py`）负责找脚本 → 找窗口 → 起会话
   → `l` 急停 → 收尾松键；附带窗口重试、自动识别标题、`--list` / `--check` / `--dry-run` /
   `--stop-after`。脚本本身一行都不用改。
3. ✅ **P0：等待不再烧 CPU**：`delay()` 自旋 → 混合等待（`maplebot/timing.py`），
   等 4 秒的 CPU 从 4000 ms 降到 31 ms（100% → 0.8% 单核），精度不变；
   另加 `Capture.set_frame_interval()` 供脚本按需降帧。见 §5.7。

### 待办（按性价比排序）

4. **坐标外置**：把每张图的常量（录点得到的坐标、阈值、循环间隔）抽成一个 `maps/<map>.json` 或 `maps/<map>.py`，让 `util_recordpoints.py` 直接吐出配置文件，替代「看控制台手工抄数字」。
5. ✅ **符文改 API 识图**（本体已完成，见 §8）：本地定位 4 个箭头 → 裁剪放大 3× → DeepSeek 读出 4 个方向 → 100 ms±30 ms 抖动按键。**最小范围**只到「返回方向 + 按键」，时机与「不确定 → ESC → 等 2 秒 → 重试」留待调用方。后续清理：删掉 `detection.py` + `returnToPoint.solveRune()` + 两份 `assets/models/`（2×113 MB）。
6. **`config` 结构化**：换成 dataclass + `threading.Event`/`Lock`，顺手解决「读到半更新状态」。
7. **调试输出开关**：`z_*.png` 收进 `debug/` 目录，用环境变量或 `--debug` 控制。
8. **加 `__init__.py`**：现在靠命名空间包 import（`from catms.cube_washer import ...`），换 IDE/换 Python 版本容易出问题，`catms/FAQ.md` 里已经记过这个坑。
9. **脚本模板化**：把每个脚本开头重复的 8 行（`time.sleep(3)` / `Return(...)` / `r.start()` / `r.save()`）
   收进一个 `maplebot.script.standard_open()`，新脚本只写主循环。
10. **P1/P2（架构）**：采屏与识别分离（最新帧 + 时间戳）→ 识别改「ROI + 按需频率 + 变化门控」的调度器，
    替脚本提供 `wait_until` / `wait_for_stable`。当前实测每帧 CV 只有 0.48 ms，所以这一步是为了
    「能加新识别而不拖慢采集」，不是为省 CPU —— 详细数据见提交讨论与 `tests/bench_pipeline.py`。

---

## 11. 测试与基准

**一条命令跑全部**（约 40 秒，不启动游戏、不注入按键、不联网）：

```powershell
.\venv\Scripts\python.exe tests\run_all.py
```

它做两件事：跑 `tests/test_*.py` 的 unittest，再跑 `tests/check_*.py` 两个独立自检脚本。

### 11.1 单元测试（unittest，176 个用例）

| 文件 | 覆盖 |
|---|---|
| `tests/test_utils.py` | 模板匹配（单/多目标、阈值、模板大于画面）、相对/绝对坐标换算（含 ratio=1 回退）、HSV 颜色过滤 |
| `tests/test_win32.py` | 窗口查找（精确标题）、矩形（负坐标裁剪/API 失败）、可截屏判断（最小化/隐藏）、`wait_for_window` 轮询与超时 |
| `tests/test_capture.py` | **小地图自动标定**（算出左上/右下/比例）、幂等性、窗口缺失/矩形失败/取帧失败的降级、`@bot` 区域定位、检测开关与缺模板告警、`window_override` 优先级、`set_frame_interval`、素材目录缺失报错 |
| `tests/test_stop.py` | 急停信号（`BaseException`）、`check()` 带原因、`request_stop` 幂等、按键/鼠标记账与松键、只松按过的键、`session()` 异常也还原、后台线程不被中断、重复 install 不叠加包装 |
| `tests/test_runner.py` | 脚本解析（名字/路径/`--dir`/绝对路径/拼错建议）、分类、`uses_capture`、import 收集与解析状态、`--list` 排除库文件、`check_sources` 通过、窗口探测（mock）、CLI 分派 |
| `tests/test_command_builder.py` | **haikuScripts 按键序列**：click/rapid/press/release、jump/cleave/二段跳/三段跳/上跳/下跳/普攻/跳攻/闪跳攻、`inputAt` 的 `@`、`totem`、`buffHs`、`check()` 发 `@check`、`delay`/`delayRandomly` 转发到 `maplebot.timing` |
| `tests/test_marco_builder.py` | 离线 `.mcr` 生成器：`Keyboard`/`DELAY`/`REPEAT` 格式、`countDuration` 正则行为、`holding`/`holdingMultiple` 嵌套、`click` 的 70ms、真实跑 `scriptWriter.py` 与 `adele-truth2.py` 产出文件 |
| `tests/test_cli.py` | `run.py` 端到端：无参退出码 2、`--list`、`--check`、`--dry-run`（含「不使用截屏」）、拼错脚本的建议、`--stop-after` 停住死循环 |
| `tests/test_rune.py` | 符文面板定位（4 个色块、行聚类、尺寸/ROI 过滤、缩放与平移不变性）、裁剪（padding/放大/贴边收敛）、按键序列（顺序、100 ms±抖动、急停中断）、**小地图菱形**（有/无、缩放、地图上的紫色块不干扰）、**buff CD 图标**（有/无、分数分离 >0.15、缩放）、**状态机**（一次成功不按 alt/esc、3 次失败后 esc×2/alt×2、API 失败不按键、面板打不开不调 API、history/last_error、回城 TODO 输出）、真实截图用例、`python -m maplebot.rune --no-api` |
| `tests/test_rune_api.py` | 凭据文件（JSON/裸 key/BOM/空 key/坏 JSON）、PNG 编码与 `data:` URL、模型回复解析（围栏/废话/裸数组/中文/箭头符号/数量或非法词报错）、请求参数契约（model/temperature/JSON 模式/thinking/图片块）、异常包装 |
| `tests/test_minimap.py` | 白色圆角边框定位：合成白框、纯白块/断边/过小/过宽/ROI 外等反例、多候选取最大、缩放与平移不变性、`MinimapBox` 几何、真实截图的 (8,99,198,82)、`Capture` 集成（auto 优先白框、template 模式忽略白框、非法参数报错） |
| `tests/test_player.py` | 角色定位：真实 fixture 找到玩家 (43,118)/(35,142)、绿点/红点/暗黄平台/无白圈黄块全部拒绝、多候选排序；跟踪：首次对齐、遮挡保留 + 过期、双候选选近的、远跳对齐计数、抖动被平滑、reset；`Capture._update_player()` 写归一化坐标 / 丢失保持上一帧并置 stale / 从未定位保持 (0,0) / 重标定重置轨迹 |
| `tests/test_botcheck.py` | 挂机监测：4 张同尺度截图模板命中、OCR 兜底定位（detection3）、验证码裁剪与放大、`clean_captcha` 字符集/长度/UNKNOWN、三次一致才返回（含不一致/网络错误）、大写用 shift 输入并回车、`BotCheckGuard` 全链路（无面板不取证、验证码不确定仍先取证、先取证后输入、面板不消失只输入一次） |
| `tests/test_qq.py` | QQ 发送（全假窗口）：`dry_run` 只贴图不回车、点击位置在输入框、真发送按回车、窗口找不到/激活失败/剪贴板异常各自返回 `sent=False`、标题子串匹配 |

只跑 unittest：

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -t . -p "test_*.py"
# 或单个模块：
.\venv\Scripts\python.exe -m unittest tests.test_capture -v
```

### 11.2 独立自检脚本

| 文件 | 内容 |
|---|---|
| `tests/check_refactor.py` | 全仓库语法、`config` 模块别名、`Capture` 薄壳与素材路径、`stop` 假按键、`run.py` 端到端停止（55 项） |
| `tests/check_p0_timing.py` | 等待精度（不早于 deadline）+ CPU 回归 + 逃生开关 + 帧间隔（21 项） |

### 11.3 基准

```powershell
.\venv\Scripts\python.exe tests\bench_delay.py     # 等待的 CPU 开销
$env:MAPLEBOT_PRECISE_DELAY=1; .\venv\Scripts\python.exe tests\bench_delay.py   # 老行为对比
.\venv\Scripts\python.exe tests\bench_pipeline.py  # 每帧各步骤耗时（加 --ocr 测 OCR）
```

### 11.4 其它

- **语法自检**（只做 AST 解析，不写盘）：`.\venv\Scripts\python.exe run.py --check`
- **目录权限**：本机该目录的权限继承曾被断开，受限账户在目录内写文件会被拒。恢复：`icacls "E:\workspace\marcoRecorderScriptBuilder" /inheritance:e`。
- **`.mcr` 产物与 `z_*.png` 都不入库**（`.gitignore` 忽略 `*.mcr`；`z_*.png` 属于误提交残留）。

---

## 12. 挂机监测（bot check）：检测 / 取证 / 验证码

管理员会人工触发挂机监测：屏幕上弹出一块半透明蓝面板（约 210×200），里面是
「將下方圖片中的文字 / 輸入顯示的內容後 / 請按下ENTER鍵」+ 一张验证码图 + 倒计时（约 60s）。
处理方式：**先截图发 QQ 群当证据，再输入验证码**；输入错就靠那张截图自证。

### 12.1 面板检测（`maplebot/botcheck.py`）

| 方法 | 成本 | 可靠度（7 张真实截图实测） |
|---|---|---|
| 文字块模板匹配（3 个尺度） | ~5 ms | 4/7 命中（0.90~1.00），换尺度/亮背景掉到 0.2~0.4 |
| PaddleOCR（缩到 1000 px 宽） | ~366 ms | 3/3 都能认出「請按下ENTER鍵」，500 px 就认不出 |

所以用法是：**每帧模板快速筛，模板没命中时每隔几秒跑一次 OCR 兜底**。
OCR 命中后还能用文字行的位置 + 缩放反推验证码框（`find_panel_ocr`），
实测三张不同尺度的截图都裁到了正确的验证码。

关键常量（都实测过）：

- `PANEL_TEMPLATE = "botcheck_text.png"`（`haikuScripts/assets/`，156×64 的三行文字）
- `CAPTCHA_OFFSET = (-33, 70, 224, 60)`：验证码框相对文字块左上角的偏移
- 面板**位置不固定**（左下/中上/顶部都有），所以只能内容识别，不能写死坐标

### 12.2 验证码读取：三次一致才答

```python
crop = botcheck.captcha_crop(frame, panel, upscale=3.0)
text = botcheck.read_captcha(crop, attempts=3)   # 三次完全一致才返回，否则 None
```

- 提示词要求「只输出字符，看不清输出 UNKNOWN」；`clean_captcha` 会校验字符集和长度（3~10）；
- 任何一次 UNKNOWN / 三次不一致 / 网络错误 → 返回 `None`，**宁可不答**；
- 实测两张样本各问两次，结果都稳定一致（`igood` / `QZD`），但没有 ground truth，
  准确率只能靠"三次一致"来保证一致性，不能保证正确性。

### 12.3 输入与验收

```
点击验证码框中心 → 等 0.2s → 逐字符输入（大写用 shift，每字间隔 60ms）→ 回车
→ 3 秒内面板消失 = 成功
→ 面板还在 = 失败，**不重复输入**（答错代价未知，只答一次）
```

`type_text` 走的是 `pydirectinput`，每个字符前都会 `stop.check()`，急停随时打断。

### 12.4 发 QQ 群（`maplebot/qq.py`）

```python
sender = qq.QQSender(dry_run=True)      # 群名读 maplebot.local.json，测试务必 dry_run
sender.send(png_bytes)
```

流程：按标题子串找窗口 → 激活 → 点输入框（相对位置 0.45/0.90）→ 剪贴板放 PNG（CF_DIB）
→ `Ctrl+V` → `Enter`。

- 群名从本地配置读（`maplebot.local.json` 的 `qq_group`），仓库里没有；
- **`dry_run=True` 时只贴图、随后清空输入框，绝不按回车**；
- 窗口找不到 / 激活失败 / 剪贴板被占用都会返回 `SendResult(sent=False, reason=...)`；
- 测试建议把 `group_title` 指向「文件传输助手」，正式跑再改回群名（或之后换群图标识别）。

### 12.5 整条链路（`BotCheckGuard`）

```python
guard = botcheck.BotCheckGuard(send_evidence=my_qq_send)   # 取证动作可注入
result = guard.handle()
# result.handled / result.reason(solved|still_there|captcha_uncertain|no_panel) / result.captcha
```

顺序固定：**检测 → 取证（先发群）→ 读验证码 → 点击输入 → 验收**。
取证失败会记 `evidence="failed"`，但不会中断后续输入——证据能补，检测不能等。

> ⚠️ 测试期间绝对不能把截图发到真群：`QQSender` 默认 `dry_run=True`，
> 单测里所有发送动作都是假的（[tests/test_qq.py](tests/test_qq.py)）。

### 12.6 已知的未知

- **输入前是否需要精确点击某个位置**：面板写着「請先點擊再輸入」，我们点验证码框中心；
  是否需要点输入框、是否需要先激活游戏窗口，只能在真监测出现时验证；
- **答错的后果未知**：所以只答一次，失败就报警（截图已经发群，可作为自证）；
- **验证码字符集**：目前按「字母+数字、3~10 位」处理，遇到别的字符会判为不可读。
