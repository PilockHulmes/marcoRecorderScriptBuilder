"""把任意分辨率的画面归一化到 1366x768（所有坐标和模板都是按这个基准做的）。

实测依据：MapleStory 把整个画面按 `宽/1366` 等比放大。1920x1080 下人蔘图标
88x88（原本 63x63），比例 1.397 ≈ 1920/1366。缩回 1366 后商店/货舱/图标/
价格全部能正常识别（已用真实截图验证）。

地图名是例外：缩放会把"只差一位数字"的地名模糊到分不开，所以地图名要用
**原生分辨率**去匹配（见 mapwatch），这里只服务商店/货舱/数字这些模块。
"""

from __future__ import annotations

import cv2

#: 所有坐标和模板的基准尺寸（宽, 高）
CANONICAL_SIZE = (1366, 768)

#: 小于这个尺寸的帧当成测试/合成帧，直接原样返回
_MIN_WIDTH = 1024
_MIN_HEIGHT = 576


def canonical(frame):
    """把游戏画面缩放到基准尺寸；已经是基准尺寸就原样返回。"""
    if frame is None:
        return None
    height, width = frame.shape[:2]
    if (width, height) == CANONICAL_SIZE:
        return frame
    if width < _MIN_WIDTH or height < _MIN_HEIGHT:
        return frame            # 测试用的合成小图，别动
    return cv2.resize(frame, CANONICAL_SIZE, interpolation=cv2.INTER_AREA)


def scale_of(frame):
    """这张画面的缩放比（相对 1366x768）。"""
    if frame is None:
        return 1.0
    height, width = frame.shape[:2]
    if width < _MIN_WIDTH:
        return 1.0
    return width / float(CANONICAL_SIZE[0])
