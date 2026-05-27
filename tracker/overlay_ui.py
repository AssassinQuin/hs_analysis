# -*- coding: utf-8 -*-
"""overlay_ui.py — 炉石传说对手追踪叠加窗口 (PyQt5)

参考 Firestone(火石) UI 设计：
  - 三段式布局：手牌区 → 卡组区(A/B/C切换) → 墓地区(卡组/衍生牌分区)
  - 深色半透明背景，蓝色法力水晶，稀有度颜色编码
  - 可折叠/展开的 section，可切换的卡组标签
  - 动态可缩放窗口，拖拽移动
  - 鼠标穿透/交互模式切换
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QPushButton, QApplication,
)
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QRect, QSize, QSettings
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QFontMetrics, QCursor,
    QLinearGradient, QPainterPath,
)

from tracker.game_state import CompleteGameState

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  设计常量 (参考 Firestone 风格)
# ═══════════════════════════════════════════════════════════════

# ── 窗口 ──
_W_DEFAULT, _H_DEFAULT = 268, 720
_W_MIN, _H_MIN = 180, 400
_GRIP_SIZE = 12
_HDR_H = 30
_SEC_HDR_H = 26
_ROW_H_DEFAULT = 24  # 模块级默认行高常量（仅作 OverlayWindow 初始化参考）
_TAB_H = 24

# ── 颜色 ──
_C_BG         = QColor(10, 12, 20, 220)     # 主背景
_C_BG_SEC     = QColor(14, 16, 28, 180)     # section 背景
_C_BORDER     = QColor(40, 48, 72, 160)     # 边框
_C_HDR_BG     = QColor(18, 22, 38, 240)     # 标题栏背景
_C_SEC_HDR    = QColor(22, 26, 44, 220)     # section header 背景
_C_TEXT        = QColor(200, 210, 230)       # 主文字
_C_TEXT_DIM    = QColor(100, 110, 135)       # 次要文字
_C_TEXT_ACC    = QColor(70, 175, 255)        # 强调色 (蓝)
_C_TEXT_WARN   = QColor(255, 190, 50)        # 警告色 (黄)
_C_CONFIRM     = QColor(50, 210, 100)        # 已确认 (绿)
_C_PROB_HIGH   = QColor(70, 200, 120)        # 高概率
_C_PROB_MID    = QColor(240, 190, 50)        # 中概率
_C_PROB_LOW    = QColor(200, 70, 70)         # 低概率
_C_MANA_GEM    = QColor(40, 120, 230)        # 法力水晶蓝
_C_MANA_BORDER = QColor(20, 70, 160)         # 水晶边框
_C_ROW_EVEN    = QColor(18, 22, 38, 100)     # 偶数行
_C_ROW_ODD     = QColor(24, 28, 48, 100)     # 奇数行
_C_ROW_PLAYED  = QColor(35, 35, 45, 120)     # 已打出
_C_ROW_HAND    = QColor(30, 55, 85, 120)     # 在手
_C_TAB_ACT     = QColor(50, 130, 230, 200)   # 激活 tab
_C_TAB_INACT   = QColor(35, 40, 58, 180)     # 非激活 tab
_C_TAB_HOVER   = QColor(55, 65, 90, 200)     # hover tab
_C_CHEVRON     = QColor(130, 140, 170)       # 折叠箭头
_C_SRC_DECK    = QColor(180, 190, 210)       # 卡组来源牌标签
_C_SRC_GEN     = QColor(255, 170, 60)        # 衍生牌标签

# ── 稀有度颜色 ──
_RARITY_FREE       = QColor(160, 165, 180)
_RARITY_COMMON     = QColor(210, 215, 225)
_RARITY_RARE       = QColor(50, 120, 230)
_RARITY_EPIC       = QColor(160, 60, 220)
_RARITY_LEGENDARY  = QColor(255, 160, 20)

# ── 职业图标 ──
_CLASS_ICO = {
    "WARRIOR": "W", "SHAMAN": "S", "ROGUE": "R", "PALADIN": "P",
    "HUNTER": "H", "WARLOCK": "L", "MAGE": "M", "PRIEST": "Pr",
    "DRUID": "D", "DEMONHUNTER": "DH", "DEATHKNIGHT": "DK", "UNKNOWN": "?",
}
_CLASS_CLR = {
    "WARRIOR": QColor(200, 155, 75), "SHAMAN": QColor(0, 155, 225),
    "ROGUE": QColor(255, 240, 105), "PALADIN": QColor(245, 200, 155),
    "HUNTER": QColor(170, 210, 80), "WARLOCK": QColor(150, 100, 210),
    "MAGE": QColor(105, 185, 255), "PRIEST": QColor(235, 235, 235),
    "DRUID": QColor(255, 125, 10), "DEMONHUNTER": QColor(165, 45, 210),
    "DEATHKNIGHT": QColor(195, 215, 230), "UNKNOWN": QColor(140, 145, 165),
}


def _rgba(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f})"

def _rarity_color(rarity: str) -> QColor:
    r = (rarity or "").upper()
    return {
        "FREE": _RARITY_FREE, "COMMON": _RARITY_COMMON,
        "RARE": _RARITY_RARE, "EPIC": _RARITY_EPIC,
        "LEGENDARY": _RARITY_LEGENDARY,
    }.get(r, _RARITY_COMMON)

def _prob_color(p: float) -> QColor:
    if p >= 1.0: return _C_CONFIRM
    if p >= 0.6: return _C_PROB_HIGH
    if p >= 0.3: return _C_PROB_MID
    return _C_PROB_LOW


# ═══════════════════════════════════════════════════════════════
#  卡牌行组件 — 自绘法力水晶 + 卡名 + 数量/概率
# ═══════════════════════════════════════════════════════════════

class _CardRow(QWidget):
    """单行卡牌：[法力水晶] [卡名(稀有度色)] [数量/概率]"""

    def __init__(self, row_height: int = _ROW_H_DEFAULT, parent=None):
        super().__init__(parent)
        self.setFixedHeight(row_height)
        self._d: dict = {}
        self._mode = "deck"  # "deck" | "hand" | "grave"

    def set_data(self, d: dict, mode: str = "deck"):
        self._d = d or {}
        self._mode = mode
        self.update()

    def paintEvent(self, _):
        d = self._d
        if not d:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 行背景
        idx = d.get("_idx", 0)
        played = d.get("played", False)
        in_hand = d.get("in_hand", False)
        if played:
            bg = _C_ROW_PLAYED
        elif in_hand:
            bg = _C_ROW_HAND
        elif idx % 2 == 0:
            bg = _C_ROW_EVEN
        else:
            bg = _C_ROW_ODD
        p.fillRect(0, 0, w, h, bg)

        # 已打出：删除线标记
        if played:
            p.setPen(QPen(QColor(180, 60, 60, 100), 1))
            p.drawLine(0, h // 2, w, h // 2)

        x = 4
        gem_sz = min(h - 6, 16)

        # ── 法力水晶 ──
        cost = d.get("cost", 0)
        src = d.get("source", "")

        if cost < 0 and src == "unknown":
            # 未知占位符"？？"：绘制空心水晶，不显示费用数字
            cx, cy = x + gem_sz // 2, h // 2
            r = gem_sz // 2
            path = QPainterPath()
            path.moveTo(cx, cy - r)
            path.lineTo(cx + r, cy)
            path.lineTo(cx, cy + r)
            path.lineTo(cx - r, cy)
            path.closeSubpath()
            p.setPen(QPen(QColor(80, 90, 120, 120), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            # 绘制 "?" 在水晶中央
            p.setPen(QPen(QColor(120, 130, 160, 180)))
            ft_q = QFont("Arial", max(gem_sz // 3, 7))
            p.setFont(ft_q)
            p.drawText(QRect(cx - r, cy - r, gem_sz, gem_sz), Qt.AlignCenter, "?")
        else:
            cx, cy = x + gem_sz // 2, h // 2
            self._draw_mana_gem(p, cx, cy, gem_sz, cost)
        x += gem_sz + 6

        # ── 位置编号（手牌模式）──
        if self._mode == "hand":
            pos = d.get("position", 0)
            if pos > 0:
                p.save()
                p.setFont(QFont("Arial", 6))
                p.setPen(QPen(QColor(140, 150, 180, 140)))
                pos_w = 8
                p.drawText(QRect(x, 0, pos_w, h), Qt.AlignVCenter | Qt.AlignLeft, str(pos))
                x += pos_w + 2
                p.restore()

        # ── 卡名 ──
        rarity = d.get("rarity", "")
        name = d.get("name", "???")
        if played:
            name_color = _C_TEXT_DIM
        elif src == "unknown":
            # 未知占位符使用暗淡颜色
            name_color = _C_TEXT_DIM
        elif name.startswith("[") or src == "inferred":
            # 类型约束标记或推断卡牌使用强调色
            name_color = _C_TEXT_ACC
        elif src == "possible":
            # 不在 top-1 卡组但可能在其他卡组中的牌：稍暗
            name_color = QColor(160, 170, 200)
        else:
            name_color = _rarity_color(rarity)
        # 预留右测空间：衍生标签(~30) + 概率条(44) + 概率文本(32) ≈ 110px
        max_name_w = w - x - 110
        p.setPen(QPen(name_color))
        ft = QFont("Microsoft YaHei", 8)
        # 跨平台字体回退：macOS 用 PingFang SC，Linux 用 Noto Sans CJK SC
        if not ft.exactMatch():
            ft = QFont("PingFang SC", 8)
        if not ft.exactMatch():
            ft = QFont("Noto Sans CJK SC", 8)
        p.setFont(ft)
        fm = QFontMetrics(ft)
        dn = fm.elidedText(name, Qt.ElideRight, max_name_w)
        p.drawText(QRect(x, 0, max_name_w, h), Qt.AlignVCenter | Qt.AlignLeft, dn)

        # ── 右侧信息 ──
        x_right = w - 4
        p.setFont(QFont("Arial", 7))
        mode = self._mode

        if mode == "grave":
            # 墓地：来源标记
            source = d.get("source", "deck")
            src_text = "衍生" if source == "generated" else "卡组"
            src_color = _C_SRC_GEN if source == "generated" else _C_SRC_DECK
            p.setPen(QPen(src_color))
            tw = fm.horizontalAdvance(src_text) + 4
            x_right -= tw
            p.drawText(QRect(x_right, 0, tw, h), Qt.AlignVCenter | Qt.AlignRight, src_text)

        elif mode == "hand":
            # 手牌：概率条 + 概率文本 + 衍生标签
            prob = d.get("probability", 0.0)
            src = d.get("source", "unknown")

            if src == "unknown":
                # 未知占位符"？？"：不显示概率条和概率文本
                pass
            else:
                # ── 衍生牌来源标记（相位5）──
                if d.get("is_generated", False):
                    gen_text = "衍生"
                    p.setPen(QPen(_C_SRC_GEN))
                    fm_gen = QFontMetrics(QFont("Arial", 7))
                    tw = fm_gen.horizontalAdvance(gen_text) + 4
                    x_right -= tw
                    p.drawText(QRect(x_right, 0, tw, h), Qt.AlignVCenter | Qt.AlignRight, gen_text)

                if src == "revealed" or prob >= 1.0:
                    prob_text = "确认"
                    prob_color = _C_CONFIRM
                else:
                    prob_text = f"{prob:.0%}"
                    prob_color = _prob_color(prob)

                # 概率条（在右侧概率文本左侧）
                if prob > 0 and prob < 1.0:
                    bar_max_w = 40
                    bar_h = 4
                    bar_w = int(min(prob, 1.0) * bar_max_w)
                    bar_x = x_right - bar_max_w - 4
                    bar_y = (h - bar_h) // 2
                    # 背景条
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor(40, 45, 65, 150)))
                    p.drawRoundedRect(bar_x, bar_y, bar_max_w, bar_h, 2, 2)
                    # 前景条
                    p.setBrush(QBrush(prob_color))
                    p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 2, 2)
                    x_right = bar_x - 4

                # 概率文本
                p.setPen(QPen(prob_color))
                p.setFont(QFont("Arial", 7))
                fm_prob = QFontMetrics(QFont("Arial", 7))
                tw = max(fm_prob.horizontalAdvance(prob_text), 28) + 4
                x_right -= tw
                p.drawText(QRect(x_right, 0, tw, h), Qt.AlignVCenter | Qt.AlignRight, prob_text)

        else:
            # 卡组：数量 x N + 剩余
            qty = d.get("quantity", 1)
            rem = d.get("remaining", 0)
            if rem > 0:
                info = f"x{rem}"
                info_color = _C_TEXT_ACC
            else:
                info = f"0/{qty}"
                info_color = _C_TEXT_DIM
            p.setPen(QPen(info_color))
            tw = max(fm.horizontalAdvance(info), 20) + 4
            x_right -= tw
            p.drawText(QRect(x_right, 0, tw, h), Qt.AlignVCenter | Qt.AlignRight, info)

            # 手牌概率条
            hp = d.get("hand_probability", 0.0)
            if hp > 0.02 and rem > 0:
                bar_w = int(min(hp, 1.0) * 30)
                bar_h = 3
                bar_x = x_right - bar_w - 6
                bar_y = h - 4
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(_prob_color(hp)))
                p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 1, 1)

        p.end()

    @staticmethod
    def _draw_mana_gem(p: QPainter, cx: int, cy: int, sz: int, cost: int):
        """绘制菱形法力水晶。"""
        r = sz // 2
        path = QPainterPath()
        path.moveTo(cx, cy - r)      # 顶
        path.lineTo(cx + r, cy)      # 右
        path.lineTo(cx, cy + r)      # 底
        path.lineTo(cx - r, cy)      # 左
        path.closeSubpath()

        # 渐变填充
        grad = QLinearGradient(cx, cy - r, cx, cy + r)
        grad.setColorAt(0, QColor(80, 180, 255))
        grad.setColorAt(1, QColor(20, 80, 200))
        p.setPen(QPen(_C_MANA_BORDER, 1))
        p.setBrush(QBrush(grad))
        p.drawPath(path)

        # 费用数字
        p.setPen(QPen(QColor(255, 255, 255)))
        ft = QFont("Arial", max(sz // 3, 7), QFont.Bold)
        p.setFont(ft)
        text = str(cost) if cost <= 10 else "10+"
        p.drawText(QRect(cx - r, cy - r, sz, sz), Qt.AlignCenter, text)


# ═══════════════════════════════════════════════════════════════
#  Section Header — 可折叠 section 标题栏
# ═══════════════════════════════════════════════════════════════

class _SectionHeader(QWidget):
    """可点击折叠的 section 标题：[名称] (数量) [▼/▶]"""

    clicked = pyqtSignal()

    def __init__(self, title: str = "", is_grave: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_SEC_HDR_H)
        self._title = title
        self._count = 0
        self._expanded = True
        self._hover = False
        self._is_grave = is_grave
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def set_title(self, title: str, count: int = 0):
        self._title = title
        self._count = count
        self.update()

    def set_expanded(self, on: bool):
        self._expanded = on
        self.update()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._expanded = not self._expanded
            self.clicked.emit()
            self.update()

    def enterEvent(self, e):
        self._hover = True; self.update()

    def leaveEvent(self, e):
        self._hover = False; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 背景
        if self._is_grave:
            # 墓地区使用更醒目的暗红/紫色背景
            bg = QColor(50, 28, 38, 240) if self._hover else QColor(35, 20, 30, 230)
        else:
            bg = QColor(28, 34, 56, 220) if self._hover else _C_SEC_HDR
        p.fillRect(0, 0, w, h, bg)

        # 底部分割线
        if self._is_grave:
            # 墓地区分割线使用更明显的颜色
            p.setPen(QPen(QColor(120, 60, 80, 200), 1))
        else:
            p.setPen(QPen(_C_BORDER, 0.5))
        p.drawLine(0, h - 1, w, h - 1)

        # 标题
        if self._is_grave:
            # 墓地标题使用骷髅图标 + 暖色文字
            title_color = QColor(255, 160, 130)
        else:
            title_color = _C_TEXT
        p.setPen(QPen(title_color))
        p.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        # 墓地区前加骷髅图标
        display_title = ("☠ " + self._title) if self._is_grave else self._title
        p.drawText(QRect(8, 0, w - 60, h), Qt.AlignVCenter | Qt.AlignLeft, display_title)

        # 数量
        if self._count > 0:
            if self._is_grave:
                p.setPen(QPen(QColor(255, 120, 100)))
            else:
                p.setPen(QPen(_C_TEXT_ACC))
            p.setFont(QFont("Arial", 8))
            cnt_text = f"({self._count})"
            p.drawText(QRect(w - 50, 0, 30, h), Qt.AlignVCenter | Qt.AlignRight, cnt_text)

        # 箭头
        arrow = "▼" if self._expanded else "▶"
        if self._is_grave:
            p.setPen(QPen(QColor(200, 120, 100)))
        else:
            p.setPen(QPen(_C_CHEVRON))
        p.setFont(QFont("Arial", 9))
        p.drawText(QRect(w - 20, 0, 16, h), Qt.AlignVCenter | Qt.AlignRight, arrow)

        p.end()


# ═══════════════════════════════════════════════════════════════
#  卡组切换标签栏 — A/B/C
# ═══════════════════════════════════════════════════════════════

class _DeckTabBar(QWidget):
    """卡组切换标签栏：[A: 卡组1 60%] [B: 卡组2 30%] [C: 卡组3 10%]"""

    tab_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_TAB_H)
        self._tabs: List[dict] = []
        self._active = 0
        self._hover_idx = -1
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def set_tabs(self, tabs: List[dict]):
        """tabs: [{name, probability}]"""
        self._tabs = tabs
        self._hover_idx = -1
        if self._active >= len(tabs):
            self._active = 0
        self.update()

    def set_active(self, idx: int):
        self._active = idx
        self.update()

    @property
    def active_index(self) -> int:
        return self._active

    def _hit_test(self, pos) -> int:
        n = len(self._tabs)
        if n == 0 or self.width() == 0:
            return -1
        tab_w = self.width() / n
        idx = int(pos.x() / tab_w)
        return idx if 0 <= idx < n else -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            idx = self._hit_test(e.pos())
            if idx >= 0:
                self._active = idx
                self.tab_changed.emit(idx)
                self.update()

    def mouseMoveEvent(self, e):
        idx = self._hit_test(e.pos())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def leaveEvent(self, e):
        self._hover_idx = -1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._tabs)

        if n == 0:
            p.end()
            return

        tab_w = w / n
        labels = "ABCDEFGH"
        for i, tab in enumerate(self._tabs):
            x = int(i * tab_w)
            tw = int(tab_w)

            # 背景
            if i == self._active:
                bg = _C_TAB_ACT
            elif i == self._hover_idx:
                bg = _C_TAB_HOVER
            else:
                bg = _C_TAB_INACT
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(bg))
            p.drawRoundedRect(x + 1, 1, tw - 2, h - 2, 3, 3)

            # 文字
            name = tab.get("name", "?")
            prob = tab.get("probability", 0)
            label = labels[i] if i < len(labels) else str(i)
            text = f"{label}: {name}"
            if prob > 0:
                text += f" {prob:.0%}"

            color = QColor(255, 255, 255) if i == self._active else _C_TEXT_DIM
            p.setPen(QPen(color))
            p.setFont(QFont("Microsoft YaHei", 7, QFont.Bold if i == self._active else QFont.Normal))
            p.drawText(QRect(x + 4, 0, tw - 8, h), Qt.AlignVCenter | Qt.AlignLeft, text)

        p.end()


# ═══════════════════════════════════════════════════════════════
#  卡牌列表区域 — 可滚动卡牌行列表
# ═══════════════════════════════════════════════════════════════

class _CardListArea(QScrollArea):
    """可滚动的卡牌行列表区域。"""

    def __init__(self, max_rows: int = 35, row_height: int = _ROW_H_DEFAULT, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._container.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(2, 1, 2, 1)
        self._layout.setSpacing(0)
        self._layout.addStretch()

        self._rows: List[_CardRow] = []
        for _ in range(max_rows):
            r = _CardRow(row_height, self._container)
            r.hide()
            self._layout.insertWidget(self._layout.count() - 1, r)
            self._rows.append(r)

        self.setWidget(self._container)

    def update_cards(self, cards: List[dict], mode: str = "deck"):
        """更新卡牌列表。cards 中每个 dict 传入 _CardRow.set_data()"""
        for i, row in enumerate(self._rows):
            if i < len(cards):
                d = dict(cards[i])
                d["_idx"] = i
                row.set_data(d, mode)
                row.show()
            else:
                row.hide()

        # 隐藏多余行
        for i in range(len(cards), len(self._rows)):
            self._rows[i].hide()


# ═══════════════════════════════════════════════════════════════
#  主窗口 — 叠加层
# ═══════════════════════════════════════════════════════════════

class OverlayWindow(QWidget):
    """炉石传说对手追踪叠加窗口。

    三段式布局 (从上到下)：
      1. 手牌区 — 对手手牌概率最高预测
      2. 卡组区 — 最可能卡组 A/B/C 切换 + 卡牌列表
      3. 墓地区 — 区分卡组来源牌和衍生牌

    特性：
      - 拖拽移动 (标题栏)
      - 右下角缩放手柄
      - 鼠标穿透/交互模式切换 (双击标题栏)
      - 折叠/展开各 section
      - 动态自适应窗口大小
    """

    close_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, image_manager=None, parent=None):
        super().__init__(parent)
        self._gs = CompleteGameState()
        self._interactive = True
        self._drag_start = None
        self._drag_off = QPoint(0, 0)

        # 卡组选择
        self._sel_arch = 0

        # section 折叠状态
        self._hand_expanded = True
        self._deck_expanded = True
        self._grave_expanded = True

        # 增量刷新哈希
        self._hand_hash = ""
        self._deck_hash = ""
        self._grave_hash = ""

        # 动态行高（实例级控制，初始值来自模块常量）
        self._row_height: int = _ROW_H_DEFAULT

        # 缩放手柄
        self._resizing = False
        self._resize_edge = None  # 'left' | 'right' | 'bottom' | 'bottom_right'
        self._resize_start = None
        self._resize_start_geo = None

        self._init_window()
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.setInterval(150)

    # ── 窗口初始化 ──

    # ── 设置持久化键名 ──
    _SETTINGS_GEOM = "overlay/geometry"
    _SETTINGS_HAND_EXP = "overlay/hand_expanded"
    _SETTINGS_DECK_EXP = "overlay/deck_expanded"
    _SETTINGS_GRAVE_EXP = "overlay/grave_expanded"
    _SETTINGS_INTERACTIVE = "overlay/interactive"

    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumSize(_W_MIN, _H_MIN)

        # 恢复上次窗口位置和大小
        settings = QSettings("HSAnalysis", "Overlay")
        geom = settings.value(self._SETTINGS_GEOM)
        if geom and isinstance(geom, QRect):
            # 确保恢复的位置在可用屏幕范围内
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                # 如果保存的位置在屏幕外（比如换了显示器），则回到默认位置
                if (geom.right() < avail.left() + 50 or
                    geom.bottom() < avail.top() + 50 or
                    geom.left() > avail.right() - 50 or
                    geom.top() > avail.bottom() - 50):
                    geom = None
            if geom:
                # 确保尺寸不低于最小值
                geom = QRect(geom.x(), geom.y(),
                             max(geom.width(), _W_MIN),
                             max(geom.height(), _H_MIN))
                self.setGeometry(geom)
            else:
                self._set_default_geometry()
        else:
            self._set_default_geometry()

        # 恢复折叠状态
        self._hand_expanded = settings.value(self._SETTINGS_HAND_EXP, True, type=bool)
        self._deck_expanded = settings.value(self._SETTINGS_DECK_EXP, True, type=bool)
        self._grave_expanded = settings.value(self._SETTINGS_GRAVE_EXP, True, type=bool)

        # 恢复交互模式
        self._interactive = settings.value(self._SETTINGS_INTERACTIVE, True, type=bool)

    def _set_default_geometry(self):
        """设置默认窗口位置（屏幕右侧）。"""
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.setGeometry(
                g.right() - _W_DEFAULT - 16,
                g.top() + 80,
                _W_DEFAULT,
                min(_H_DEFAULT, g.height() - 160),
            )

    def _save_geometry(self):
        """保存当前窗口位置、大小和折叠状态。"""
        settings = QSettings("HSAnalysis", "Overlay")
        settings.setValue(self._SETTINGS_GEOM, self.geometry())
        settings.setValue(self._SETTINGS_HAND_EXP, self._hand_expanded)
        settings.setValue(self._SETTINGS_DECK_EXP, self._deck_expanded)
        settings.setValue(self._SETTINGS_GRAVE_EXP, self._grave_expanded)
        settings.setValue(self._SETTINGS_INTERACTIVE, self._interactive)

    # ── UI 构建 ──

    def _build_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(2, 2, 2, 2)
        self._root.setSpacing(0)

        # 1. 标题栏
        self._root.addWidget(self._build_header())

        # 2. 手牌区
        self._hand_header = _SectionHeader("对手手牌")
        self._hand_header.clicked.connect(self._toggle_hand)
        self._root.addWidget(self._hand_header)
        self._hand_list = _CardListArea(max_rows=10, row_height=self._row_height)
        # 手牌区设置最小高度，避免窗口缩小时完全看不到
        self._hand_list.setMinimumHeight(30)
        self._root.addWidget(self._hand_list, stretch=3)

        # 3. 卡组区
        self._deck_header = _SectionHeader("对手卡组")
        self._deck_header.clicked.connect(self._toggle_deck)
        self._root.addWidget(self._deck_header)
        self._deck_tab = _DeckTabBar()
        self._deck_tab.tab_changed.connect(self._switch_arch)
        self._root.addWidget(self._deck_tab)
        self._deck_list = _CardListArea(max_rows=35, row_height=self._row_height)
        # 卡组区设置最小高度
        self._deck_list.setMinimumHeight(40)
        self._root.addWidget(self._deck_list, stretch=4)

        # 4. 墓地区 — 更显眼的设计
        self._grave_header = _SectionHeader("墓地", is_grave=True)
        self._grave_header.clicked.connect(self._toggle_grave)
        self._root.addWidget(self._grave_header)
        self._grave_list = _CardListArea(max_rows=35, row_height=self._row_height)
        # 墓地区设置最小高度，确保窗口缩小时仍能看到
        self._grave_list.setMinimumHeight(30)
        self._root.addWidget(self._grave_list, stretch=3)

        # ── 恢复折叠状态 ──
        self._hand_header.set_expanded(self._hand_expanded)
        self._hand_list.setVisible(self._hand_expanded)
        self._hand_list.setMinimumHeight(30 if self._hand_expanded else 0)
        self._deck_header.set_expanded(self._deck_expanded)
        self._deck_tab.setVisible(self._deck_expanded)
        self._deck_list.setVisible(self._deck_expanded)
        self._deck_list.setMinimumHeight(40 if self._deck_expanded else 0)
        self._grave_header.set_expanded(self._grave_expanded)
        self._grave_list.setVisible(self._grave_expanded)
        self._grave_list.setMinimumHeight(30 if self._grave_expanded else 0)
        self._update_min_size()

        # ── 恢复交互模式 ──
        if not self._interactive:
            self.set_interactive(False)
            self._interact_btn.setText("👁")
            self._interact_btn.setToolTip("穿透模式(点击穿过到游戏)")

    # ── 标题栏 ──

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(_HDR_H)
        w.setCursor(QCursor(Qt.SizeAllCursor))
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 0, 4, 0)
        lay.setSpacing(4)

        # 职业图标
        self._ico = QLabel("?")
        self._ico.setFixedSize(20, 20)
        self._ico.setAlignment(Qt.AlignCenter)
        self._ico.setFont(QFont("Arial", 9, QFont.Bold))
        self._ico.setStyleSheet("color:white;")
        self._ico.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._ico)

        # 职业名
        self._class_lbl = QLabel("等待对战")
        self._class_lbl.setStyleSheet(f"color:{_rgba(_C_TEXT)};font-weight:bold;")
        self._class_lbl.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self._class_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._class_lbl)

        lay.addStretch()

        # 回合
        self._turn_lbl = QLabel("")
        self._turn_lbl.setStyleSheet(f"color:{_rgba(_C_TEXT_ACC)};")
        self._turn_lbl.setFont(QFont("Arial", 8))
        self._turn_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._turn_lbl)

        # 手牌计数
        self._hand_count_lbl = QLabel("")
        self._hand_count_lbl.setStyleSheet(f"color:{_rgba(_C_TEXT_DIM)};")
        self._hand_count_lbl.setFont(QFont("Arial", 8))
        self._hand_count_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._hand_count_lbl)

        # MCTS状态指示器
        self._mcts_lbl = QLabel("")
        self._mcts_lbl.setStyleSheet(f"color:{_rgba(_C_TEXT_WARN)};")
        self._mcts_lbl.setFont(QFont("Arial", 7))
        self._mcts_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._mcts_lbl)

        # 交互切换按钮 (📌/👁)
        self._interact_btn = QPushButton("📌")
        self._interact_btn.setFixedSize(20, 20)
        self._interact_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;font-size:11px;}"
            "QPushButton:hover{background:rgba(80,90,120,100);border-radius:3px;}"
        )
        self._interact_btn.clicked.connect(self._toggle_interactive)
        self._interact_btn.setToolTip("切换交互/穿透模式")
        lay.addWidget(self._interact_btn)

        # 关闭按钮
        self._close_btn = QPushButton("x")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#955;border:none;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{color:#f77;background:rgba(200,50,50,80);border-radius:3px;}"
        )
        self._close_btn.clicked.connect(self._on_close)
        lay.addWidget(self._close_btn)

        return w

    # ── 折叠/展开 ──

    def _toggle_hand(self):
        self._hand_expanded = not self._hand_expanded
        self._hand_header.set_expanded(self._hand_expanded)
        self._hand_list.setVisible(self._hand_expanded)
        self._hand_list.setMinimumHeight(30 if self._hand_expanded else 0)
        self._update_min_size()
        self._save_geometry()

    def _toggle_deck(self):
        self._deck_expanded = not self._deck_expanded
        self._deck_header.set_expanded(self._deck_expanded)
        self._deck_tab.setVisible(self._deck_expanded)
        self._deck_list.setVisible(self._deck_expanded)
        self._deck_list.setMinimumHeight(40 if self._deck_expanded else 0)
        self._update_min_size()
        self._save_geometry()

    def _toggle_grave(self):
        self._grave_expanded = not self._grave_expanded
        self._grave_header.set_expanded(self._grave_expanded)
        self._grave_list.setVisible(self._grave_expanded)
        self._grave_list.setMinimumHeight(30 if self._grave_expanded else 0)
        self._update_min_size()
        self._save_geometry()

    def _update_min_size(self):
        """折叠/展开后动态调整窗口最小尺寸。

        折叠 section 后内容减少，允许窗口缩小到更合理的尺寸。
        """
        min_h = _HDR_H + 4
        min_h += _SEC_HDR_H
        if self._hand_expanded:
            min_h += 30
        min_h += _SEC_HDR_H
        if self._deck_expanded:
            min_h += _TAB_H + 40
        min_h += _SEC_HDR_H
        if self._grave_expanded:
            min_h += 30
        min_h = max(min_h, 120)
        self.setMinimumSize(_W_MIN, min_h)

    # ── 卡组切换 ──

    def _switch_arch(self, idx: int):
        self._sel_arch = idx
        self._deck_hash = ""  # 强制刷新

    # ── 交互模式 ──

    def _toggle_interactive(self):
        self._interactive = not self._interactive
        self.set_interactive(self._interactive)
        self._interact_btn.setText("📌" if self._interactive else "👁")
        self._interact_btn.setToolTip(
            "交互模式" if self._interactive else "穿透模式(点击穿过到游戏)"
        )
        self._save_geometry()

    def set_interactive(self, on: bool):
        self._interactive = on
        # 内容区域：穿透/交互
        for w in [self._hand_list, self._deck_list, self._grave_list]:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, not on)
        # header/tab 始终可交互
        for w in [self._hand_header, self._deck_header, self._grave_header, self._deck_tab]:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    # ── 公开接口 ──

    def update_state(self, gs: CompleteGameState):
        self._gs = gs
        # reset 后 _gs 已更新，清空增量哈希以强制刷新
        self._hand_hash = ""
        self._deck_hash = ""
        self._grave_hash = ""

    def start_refresh(self):
        self._timer.start()

    def stop_refresh(self):
        self._timer.stop()

    def _on_close(self):
        """关闭按钮：停止刷新并退出整个进程。"""
        self.stop_refresh()
        self._save_geometry()
        self.close_requested.emit()
        QApplication.quit()

    # ── 核心刷新 ──

    def _refresh(self):
        gs = self._gs

        # ── 标题栏 ──
        cls_en = getattr(gs.opponent.hero, 'hero_class_en', gs.opponent.hero.hero_class)
        cls_cn = gs.opponent.hero.hero_class_cn or "未知"
        self._ico.setText(_CLASS_ICO.get(cls_en, "?"))
        cls_color = _CLASS_CLR.get(cls_en, _C_TEXT)
        self._ico.setStyleSheet(f"color:{_rgba(cls_color)};font-weight:bold;font-size:11px;")
        self._class_lbl.setText(cls_cn)
        self._class_lbl.setStyleSheet(f"color:{_rgba(cls_color)};font-weight:bold;")
        self._turn_lbl.setText(f"T{gs.turn}" if gs.turn else "")

        # 手牌/牌库计数
        opp = gs.opponent
        self._hand_count_lbl.setText(f"手{opp.hand_count} 库{opp.deck_remaining}")

        # MCTS状态指示器
        if getattr(gs, 'mcts_applied', False):
            top_preds = getattr(gs, 'mcts_top_predictions', [])
            if top_preds:
                top_card, top_prob = top_preds[0]
                self._mcts_lbl.setText(f"MCTS✓ {top_prob:.0%}")
                self._mcts_lbl.setStyleSheet(f"color:{_rgba(_C_CONFIRM)};")
            else:
                self._mcts_lbl.setText("MCTS✓")
                self._mcts_lbl.setStyleSheet(f"color:{_rgba(_C_CONFIRM)};")
        else:
            self._mcts_lbl.setText("")
            self._mcts_lbl.setStyleSheet(f"color:{_rgba(_C_TEXT_DIM)};")

        # ── 手牌区 ──
        self._refresh_hand(gs)

        # ── 卡组区 ──
        self._refresh_deck(gs)

        # ── 墓地区 ──
        self._refresh_grave(gs)

    def _refresh_hand(self, gs: CompleteGameState):
        """刷新手牌区 — 按手牌位置显示对手手牌预测。

        设计原则（参考 Firestone UI）：
        - 已确认手牌（source=revealed, probability=1.0）：显示卡名 + "确认"
        - 预测手牌：显示卡名 + 概率百分比
        - 不确定的手牌位置：用 "？？" 表示（占位符行）
        - 衍生牌标记 "衍生" 标签
        - 位置编号标记
        - 手牌总数在 section header 显示
        """
        opp = gs.opponent
        hand_count = opp.hand_count

        # ── 逐位手牌预测索引（Phase 3/5）──
        pos_pred_map = {pp["position"]: pp for pp in gs.position_predictions}

        # 衍生牌快速查找
        gen_card_ids = set()
        gen_card_source = {}
        for rec in gs.generated_card_records:
            cid = rec.get("card_id", "")
            if cid:
                gen_card_ids.add(cid)
                if rec.get("source_card_id"):
                    gen_card_source[cid] = rec["source_card_id"]

        # card_id → CardInHand 映射（补充稀有度等字段）
        card_in_hand_map = {}
        for h in opp.hand:
            if h.card_id:
                card_in_hand_map[h.card_id] = h

        # 按手牌位置遍历 (1-based)
        hand_cards = []
        for pos in range(1, hand_count + 1):
            pp = pos_pred_map.get(pos)
            if pp and pp.get("card_id") and not pp["card_id"].startswith("_unk_"):
                cid = pp["card_id"]
                ch = card_in_hand_map.get(cid)
                card = {
                    "card_id": cid,
                    "name": pp.get("name", "?"),
                    "cost": pp.get("cost", 0),
                    "probability": pp.get("probability", 0.0),
                    "source": pp.get("source", "unknown"),
                    "rarity": getattr(ch, 'rarity', '') or getattr(ch, 'race', '') or "",
                    "race": getattr(ch, 'race', '') if ch else "",
                    "position": pos,
                    "is_generated": cid in gen_card_ids,
                    "source_card": gen_card_source.get(cid, ""),
                }
            else:
                card = {
                    "card_id": "_unk_placeholder",
                    "name": "？？",
                    "cost": -1,
                    "probability": 0.0,
                    "source": "unknown",
                    "rarity": "",
                    "race": "",
                    "position": pos,
                    "is_generated": False,
                    "source_card": "",
                }
            hand_cards.append(card)

        # 限制显示行数（手牌上限 10 张）
        hand_cards = hand_cards[:10]

        # 增量刷新 — 使用 tuple 避免不必要的重绘
        h_hash = tuple((c["card_id"], c.get("probability", 0), c.get("position", 0))
                       for c in hand_cards)
        if h_hash == self._hand_hash and hand_count == getattr(self, '_hand_count_cache', -1):
            return
        self._hand_hash = h_hash
        self._hand_count_cache = hand_count

        # 标题显示手牌总数
        title = f"对手手牌 ({hand_count})" if hand_count else "对手手牌"
        self._hand_header.set_title(title, hand_count)
        self._hand_list.update_cards(hand_cards, "hand")

    def _refresh_deck(self, gs: CompleteGameState):
        """刷新卡组区 — 显示预测卡组，标记已打出/已打完。"""
        opp = gs.opponent

        # 选择卡组数据源：根据用户选择的卡组标签索引
        deck_cards = []
        if gs.multi_deck_predictions and self._sel_arch > 0:
            idx = min(self._sel_arch, len(gs.multi_deck_predictions) - 1)
            deck_cards = gs.multi_deck_predictions[idx].get("cards", [])
        if not deck_cards:
            deck_cards = gs.deck_predictions
        
        # 回退到已知打出卡牌
        if not deck_cards:
            deck_cards = [
                {
                    "card_id": c.card_id,
                    "name": c.name,
                    "cost": c.cost,
                    "quantity": c.quantity,
                    "remaining": c.remaining,
                    "source": c.source,
                    "played": c.played,
                    "in_hand": c.in_hand,
                    "card_type": c.card_type,
                    "race": c.race,
                    "hand_probability": 0.0,
                }
                for c in opp.deck
            ]

        # 构建显示数据（排除衍生牌：卡组区只显示牌库来源的牌）
        display = []
        for c in deck_cards:
            source = c.get("source", "deck")
            if source == "generated":
                continue  # 衍生牌不显示在卡组区，只在墓地区显示
            display.append({
                "card_id": c.get("card_id", ""),
                "name": c.get("name", ""),
                "cost": c.get("cost", 0),
                "quantity": c.get("quantity", 1),
                "remaining": c.get("remaining", 1),
                "source": source,
                "played": c.get("played", False),
                "in_hand": c.get("in_hand", False),
                "rarity": c.get("rarity", ""),
                "race": c.get("race", ""),
                "hand_probability": c.get("hand_probability", 0.0),
            })

        # 按费用排序
        display.sort(key=lambda c: (c.get("cost", 0), c.get("name", "")))

        # 统计
        total = sum(c.get("quantity", 1) for c in display)
        played_count = sum(1 for c in display if c.get("remaining", 1) == 0)
        self._deck_header.set_title("对手卡组", total)

        # Tab bar: 多卡组预测
        tabs = []
        for mp in gs.multi_deck_predictions:
            tabs.append({
                "name": mp.get("archetype_name", "?"),
                "probability": mp.get("probability", 0),
            })
        if tabs:
            self._deck_tab.set_tabs(tabs)
            self._deck_tab.set_active(self._sel_arch)
            self._deck_tab.setVisible(self._deck_expanded)
        else:
            self._deck_tab.setVisible(False)

        # 增量刷新（包含 hand_probability，概率变化时也触发重绘）
        d_hash = tuple(
            (c["card_id"], c.get("remaining", 0), c.get("played", False),
             round(c.get("hand_probability", 0.0), 4))
            for c in display
        )
        if d_hash == self._deck_hash:
            return
        self._deck_hash = d_hash

        self._deck_list.update_cards(display, mode="deck")

    def _refresh_grave(self, gs: CompleteGameState):
        """刷新墓地区 — 使用 opp_graveyard 作为主数据源。

        数据来源优先级：
        1. gs.opp_graveyard: 直接区域变化检测到的（PLAY/HAND/SECRET→GRAVEYARD）
        2. deck_predictions/multi_deck_predictions 中 played=True 的卡牌（补充）

        这样即使 deck_predictions 为空（贝叶斯未初始化），
        也能显示通过区域变化检测到的对手出牌/随从死亡。
        """
        grave_cards = []
        seen_ids = set()

        # ── 主数据源：opp_graveyard（区域变化检测） ──
        for entry in gs.opp_graveyard:
            cid = entry.get("card_id", "")
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            grave_cards.append({
                "card_id": cid,
                "name": entry.get("name", cid),
                "cost": entry.get("cost", 0),
                "quantity": 1,
                "remaining": 0,
                "source": entry.get("source", "deck"),
                "played": True,
                "rarity": entry.get("rarity", ""),
            })

        # ── 补充：从 deck_predictions 获取（贝叶斯推断的已打出卡牌） ──
        # 只补充 opp_graveyard 中没有的
        predictions = []
        multi = gs.multi_deck_predictions
        if multi:
            if self._sel_arch >= len(multi):
                sel = multi[0]
            else:
                sel = multi[self._sel_arch]
            predictions = sel.get("cards", [])
        else:
            predictions = gs.deck_predictions

        for c in predictions:
            cid = c.get("card_id", "")
            if not cid or cid in seen_ids:
                continue
            if c.get("played", False) or c.get("remaining", 0) <= 0:
                seen_ids.add(cid)
                grave_cards.append({
                    "card_id": cid,
                    "name": c.get("name", cid),
                    "cost": c.get("cost", 0),
                    "quantity": c.get("quantity", 1),
                    "remaining": c.get("remaining", 0),
                    "source": c.get("source", "deck"),
                    "played": True,
                    "rarity": c.get("rarity", ""),
                })

        # 排序：卡组来源优先，然后按费用
        grave_cards.sort(key=lambda c: (0 if c.get("source") == "deck" else 1, c["cost"], c["name"]))

        # 增量刷新 — 使用 frozenset 避免字符串拼接顺序敏感性
        g_hash = frozenset((c["card_id"], c.get("source", "")) for c in grave_cards)
        if g_hash == self._grave_hash:
            return
        self._grave_hash = g_hash

        deck_count = sum(1 for c in grave_cards if c.get("source") == "deck")
        gen_count = len(grave_cards) - deck_count
        title = f"墓地"
        if gen_count > 0:
            title = f"墓地 (卡组{deck_count} / 衍生{gen_count})"
        self._grave_header.set_title(title, len(grave_cards))
        self._grave_list.update_cards(grave_cards, "grave")

    # ── 鼠标事件 ──

    def _hit_edge(self, pos) -> Optional[str]:
        """检测鼠标位置对应的缩放边缘。

        返回: 'left' | 'right' | 'bottom' | 'bottom_right' | None
        """
        r = self.rect()
        g = _GRIP_SIZE
        on_right = pos.x() >= r.right() - g
        on_left = pos.x() <= r.left() + g
        on_bottom = pos.y() >= r.bottom() - g
        if on_right and on_bottom:
            return "bottom_right"
        if on_right:
            return "right"
        if on_left:
            return "left"
        if on_bottom:
            return "bottom"
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            edge = self._hit_edge(e.pos())
            if edge:
                self._resizing = True
                self._resize_edge = edge
                self._resize_start = e.globalPos()
                self._resize_start_geo = self.geometry()
            else:
                self._drag_start = e.globalPos()
                self._drag_off = self.pos() - e.globalPos()

    def mouseMoveEvent(self, e):
        if self._resizing and self._resize_start is not None:
            delta = e.globalPos() - self._resize_start
            geo = self._resize_start_geo
            edge = self._resize_edge

            min_w = self.minimumWidth()
            min_h = self.minimumHeight()

            if edge in ("left", "bottom_right"):
                new_w = max(min_w, geo.width() - delta.x())
            else:
                new_w = geo.width()

            if edge in ("bottom", "bottom_right"):
                new_h = max(min_h, geo.height() + delta.y())
            else:
                new_h = geo.height()

            if edge == "left":
                new_x = geo.right() - new_w
            else:
                new_x = geo.x()

            self.setGeometry(new_x, geo.y(), new_w, new_h)
        elif self._drag_start is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() + self._drag_off)
        else:
            edge = self._hit_edge(e.pos())
            if edge in ("left", "right"):
                self.setCursor(Qt.SizeHorCursor)
            elif edge == "bottom":
                self.setCursor(Qt.SizeVerCursor)
            elif edge == "bottom_right":
                self.setCursor(Qt.SizeFDiagCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        was_dragging = self._drag_start is not None or self._resizing
        self._drag_start = None
        self._resizing = False
        self._resize_edge = None
        self._resize_start = None
        self._resize_start_geo = None
        if was_dragging:
            self._save_geometry()

    def mouseDoubleClickEvent(self, e):
        """双击标题栏切换交互/穿透模式。"""
        if e.pos().y() < _HDR_H:
            self._toggle_interactive()

    # ── 绘制 ──

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()

        # 主背景 — 圆角
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_C_BG))
        p.drawRoundedRect(r, 6, 6)

        # 边框
        p.setPen(QPen(_C_BORDER, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 6, 6)

        # 标题栏背景
        hdr_rect = QRect(2, 2, r.width() - 4, _HDR_H)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_C_HDR_BG))
        p.drawRoundedRect(hdr_rect, 4, 4)

        # 缩放提示 — 右下角三行点 + 左/右/下边缘高亮线
        grip_color = QColor(90, 100, 130, 140)
        edge_color = QColor(90, 100, 130, 60)
        gx, gy = r.right() - 4, r.bottom() - 4
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grip_color))
        for dy in range(0, 9, 3):
            for dx in range(0, 9, 3):
                if dx + dy >= 3:
                    p.drawEllipse(gx - dx - 2, gy - dy - 2, 2, 2)
        # 左边缘
        p.setBrush(QBrush(edge_color))
        p.drawRect(r.left(), r.top() + _HDR_H, 2, r.height() - _HDR_H)
        # 右边缘
        p.drawRect(r.right() - 2, r.top() + _HDR_H, 2, r.height() - _HDR_H)
        # 下边缘
        p.drawRect(r.left(), r.bottom() - 2, r.width(), 2)

        p.end()

    # ── 缩放支持 ──

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 根据窗口大小动态调整行高
        h = self.height()
        if h < 400:
            new_h = 20
        elif h < 600:
            new_h = 22
        else:
            new_h = 24
        # 只在行高变化时更新（避免不必要的布局重算）
        if new_h != self._row_height:
            self._row_height = new_h
            for row_list in [self._hand_list, self._deck_list, self._grave_list]:
                for row in row_list._rows:
                    row.setFixedHeight(new_h)
