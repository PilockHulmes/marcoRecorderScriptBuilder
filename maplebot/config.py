"""进程内唯一的一份全局状态。

`haikuScripts/config.py` 与 `auto-maple/src/config.py` 现在都是指向本模块的别名
（见那两个文件），所以下面三种写法拿到的是**同一个模块对象**：

    import config            # 从 haikuScripts/ 里
    import src.config        # 从 auto-maple/ 里
    from maplebot import config

赋值对所有使用者立即可见 —— 这正是以前「两份 config 各自为政、脚本读到空值」的坑。

注意：这些是模块级变量，不做加锁。Capture 线程写、脚本线程读，读到的是
「某一时刻的值」，偶发的半更新状态属于既有行为（见 README §8）。
"""

# ---------------------------------------------------------------- 小地图状态
# 角色在小地图上的归一化坐标 (x, y)，范围 0~1
player_position = (0, 0)
# 符文在小地图上的归一化坐标
rune_position = (0, 0)
# 小地图上检测到了符文
rune_active = False
# 符文已处理（预留字段，当前没有写入方）
rune_solved = False
# 符文 buff 图标在屏幕上的绝对坐标，用来点掉 buff
rune_buff_position = None
# 小地图上出现了其他玩家
map_invaded = False
# 屏幕大面积变黑（掉线 / 换图）
blackscreened = False
# 当前小地图截图（cv2 BGR ndarray）
minimap = None
# 检测到 @bot 验证码弹窗
bottesting = False

# ---------------------------------------------------------------- 共享模块
# Capture 实例，由 Capture.__init__ 写入，供 utils 读取 minimap_ratio
capture = None

# ---------------------------------------------------------------- 运行期覆盖
# 非空时覆盖脚本里写死的窗口标题（由 run.py --window 或自动探测写入）
window_override = None
