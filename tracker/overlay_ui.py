# -*- coding: utf-8 -*-
"""overlay_ui.py — 炉石传说对手追踪叠加窗口 (PyQt5)

参考 Firestone/HDT 的设计风格，半透明浮动侧栏叠加 UI。

核心设计:
- 无边框、始终置顶、半透明背景
- 动态可拖拽调整大小（右下角拖拽手柄）
- 双击标题栏切换紧凑/展开模式
- 点击穿透可切换（快捷键 Ctrl+Shift+I）
- 按住标题栏拖动窗口位置
- 关闭按钮 + 设置齿轮图标
- 自绘所有控件（QPainter），无 QLabel 闪烁

布局（展开模式）:
┌────────────────────────────────┐
│ ⚔法师  T5  手牌4  ⚙ ─ ×     │ ← 标题栏(拖拽区)
├────────────────────────────────┤
│ [?][3火球][7?][?][?]          │ ← 手牌横条(自适应)
├────────────────────────────────┤
│ 对手卡组              12/30   │
│ (3) 火球术           ×2      │ ← 卡组列表(可滚动)
│ (5) 暴风雪                   │
│ ...                          │
├────────────────────────────────┤
│ ⚠奥秘: 爆炸陷阱 85%          │ ← 条件显示
├────────────────────────────────┤
│ 快攻 - T1龙牧 65%            │ ← 底部原型
│ 龙牧65%|宇宙牧20%|心火15%     │
└────────────────────────────────┘
                            ⋮⋮  ← 缩放手柄
"""

from __future__ import annotations

import logging
import math
from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QScrollArea, QSizePolicy, QPushButton,
    QSizeGrip, QApplication,
)
from PyQt5.QtCore import (
    Qt, QPoint, QTimer, pyqtSignal, QSize, QRect, QPropertyAnimation,
)
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QLinearGradient,
    QFontMetrics, QPainterPath, QCursor,
)

from tracker.game_state import CompleteGameState
from tracker.card_images import CardImageManager

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 主题色系 — Firestone 风格深色主题
# ═══════════════════════════════════════════════════════════════

_BG = QColor(18, 20, 28, 225)               # 主背景
_BG_HEADER = QColor(28, 30, 42, 245)         # 标题栏
_BG_SECTION = QColor(24, 26, 36, 160)        # 分区背景
_BG_HOVER = QColor(40, 44, 60, 200)          # 悬停
_BORDER = QColor(55, 60, 78, 120)            # 边框
_TEXT = QColor(215, 220, 230)                 # 主文字
_TEXT_DIM = QColor(120, 128, 148)             # 次要文字
_TEXT_ACCENT = QColor(90, 195, 255)           # 强调色(蓝)
_GOLD = QColor(255, 210, 80)                 # 金色

# 费用色 — 模拟炉石法力宝石
_COST = [
    QColor(160, 165, 175),  # 0 灰
    QColor(185, 190, 200),  # 1
    QColor(140, 195, 255),  # 2 淡蓝
    QColor(90, 170, 255),   # 3 蓝
    QColor(65, 145, 235),   # 4
    QColor(255, 200, 60),   # 5 金
    QColor(245, 155, 45),   # 6 橙
    QColor(240, 100, 45),   # 7 红橙
    QColor(235, 65, 65),    # 8 红
    QColor(210, 55, 115),   # 9 玫红
    QColor(170, 75, 215),   # 10+ 紫
]

# 概率色
_P_CONFIRM = QColor(55, 215, 95)    # 确认(100%)
_P_HIGH = QColor(75, 195, 115)      # 高概率(>=70%)
_P_MID = QColor(245, 195, 55)       # 中概率(50-70%)
_P_LOW = QColor(175, 70, 70)        # 低概率(<50%)

# 打法分类色
_STYLE_C = {
    "aggro": QColor(245, 75, 75), "control": QColor(75, 155, 250),
    "combo": QColor(195, 95, 250), "midrange": QColor(250, 195, 55),
    "tempo": QColor(245, 145, 45), "unknown": _TEXT_DIM,
}
_STYLE_CN = {
    "aggro": "快攻", "control": "控制", "combo": "组合技",
    "midrange": "中速", "tempo": "节奏", "unknown": "未知",
}

# 职业图标
_CLASS_ICO = {
    "WARRIOR": "W", "SHAMAN": "S", "ROGUE": "R", "PALADIN": "P",
    "HUNTER": "H", "WARLOCK": "L", "MAGE": "M", "PRIEST": "I",
    "DRUID": "D", "DEMONHUNTER": "DH", "DEATHKNIGHT": "DK", "UNKNOWN": "?",
}

# 尺寸
_DEFAULT_W = 260
_DEFAULT_H = 560
_MIN_W = 180
_MIN_H = 300
_HEADER_H = 32
_FOOTER_H = 44
_HAND_H = 52
_ROW_H = 22
_GRIP_SIZE = 14

# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════


def _cost_color(c: int) -> QColor:
    return _COST[min(max(c, 0), len(_COST) - 1)]


def _prob_color(p: float) -> QColor:
    if p >= 1.0: return _P_CONFIRM
    if p >= 0.7: return _P_HIGH
    if p >= 0.5: return _P_MID
    return _P_LOW


def _rgba(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f})"


def _elide(font: QFont, text: str, max_w: int) -> str:
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.ElideRight, max_w)


# ═══════════════════════════════════════════════════════════════
# 自绘控件 — 不用 QLabel 避免闪烁
# ═══════════════════════════════════════════════════════════════


class _DeckRow(QWidget):
    """卡组列表中的一行: 费用圆 + 名称 + 数量"""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.d = data
        self.setFixedHeight(_ROW_H)
        self._hover = False

    def set_data(self, data: dict):
        self.d = data
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        d = self.d
        cost = d.get("cost", 0)
        name = d.get("name", "???")
        remaining = d.get("remaining", 1)
        quantity = d.get("quantity", 1)
        played = d.get("played", False)
        in_hand = d.get("in_hand", False)

        # 背景条
        if in_hand:
            p.fillRect(0, 0, w, h, QColor(40, 60, 85, 100))
        elif played:
            p.fillRect(0, 0, w, h, QColor(25, 25, 30, 60))
        elif self._hover:
            p.fillRect(0, 0, w, h, QColor(40, 44, 60, 80))

        # 费用圆
        cc = _cost_color(cost)
        cx, cy, cr = 12, h // 2, 8
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(cc))
        p.drawEllipse(cx - cr, cy - cr, cr * 2, cr * 2)
        # 费用数字
        p.setPen(QPen(QColor(10, 10, 15)))
        p.setFont(QFont("Arial", 8, QFont.Bold))
        p.drawText(QRect(cx - cr, cy - cr, cr * 2, cr * 2),
                   Qt.AlignCenter, str(min(cost, 10)) if cost <= 10 else "10+")

        # 名称
        name_font = QFont("Microsoft YaHei", 8)
        p.setFont(name_font)
        name_w = w - 60
        display = _elide(name_font, name, name_w)
        color = _TEXT if not played else _TEXT_DIM
        p.setPen(QPen(color))
        p.drawText(QRect(26, 0, name_w, h), Qt.AlignVCenter | Qt.AlignLeft, display)

        # 删除线
        if played:
            fm = QFontMetrics(name_font)
            tw = min(fm.horizontalAdvance(display), name_w)
            p.setPen(QPen(QColor(200, 70, 70, 160), 1))
            p.drawLine(26, h // 2, 26 + tw, h // 2)

        # 数量
        if remaining > 1 or quantity > 1:
            p.setPen(QPen(_TEXT_ACCENT if remaining > 0 else _TEXT_DIM))
            p.setFont(QFont("Arial", 8, QFont.Bold))
            p.drawText(QRect(w - 32, 0, 28, h), Qt.AlignVCenter | Qt.AlignRight,
                       f"x{remaining}" if remaining != quantity else f"x{quantity}")
        p.end()

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()


class _HandCard(QWidget):
    """手牌预测条目: 费用圆 + 名称 + 概率条"""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.d = data

    def set_data(self, data: dict):
        self.d = data
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        d = self.d
        cost = d.get("cost", 0)
        name = d.get("name", "???")
        prob = d.get("probability", 0.0)
        source = d.get("source", "deck")
        pc = _prob_color(prob)

        # 背景(概率着色)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(pc.red(), pc.green(), pc.blue(), 25)))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 3, 3)

        # 边框
        border = pc if prob >= 0.5 else QColor(55, 60, 78, 90)
        if prob >= 1.0: border = _P_CONFIRM
        p.setPen(QPen(border, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 3, 3)

        # 费用圆
        cc = _cost_color(cost)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(cc))
        r = min(8, h // 3)
        p.drawEllipse(4, (h - 14) // 2, r * 2, r * 2)
        p.setPen(QPen(QColor(10, 10, 15)))
        p.setFont(QFont("Arial", 7, QFont.Bold))
        p.drawText(QRect(4, (h - 14) // 2, r * 2, r * 2), Qt.AlignCenter, str(min(cost, 10)))

        # 名称
        name_font = QFont("Microsoft YaHei", 7)
        p.setFont(name_font)
        display = name if prob >= 0.5 else "?"
        if len(display) > 6:
            display = display[:5] + ".."
        p.setPen(QPen(_TEXT if prob >= 0.5 else _TEXT_DIM))
        p.drawText(QRect(4 + r * 2 + 3, 0, w - r * 2 - 10, h - 10),
                   Qt.AlignVCenter | Qt.AlignLeft, display)

        # 概率条
        bar_y = h - 8
        bar_h = 4
        bar_w = w - 8
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(35, 38, 50)))
        p.drawRoundedRect(4, bar_y, bar_w, bar_h, 2, 2)
        fill = int(bar_w * min(prob, 1.0))
        if fill > 0:
            p.setBrush(QBrush(pc))
            p.drawRoundedRect(4, bar_y, fill, bar_h, 2, 2)

        # 概率文字
        prob_text = "OK" if prob >= 1.0 else f"{prob:.0%}" if prob >= 0.5 else "?"
        p.setPen(QPen(pc))
        p.setFont(QFont("Arial", 6))
        p.drawText(QRect(4, bar_y - 10, bar_w, 10), Qt.AlignCenter, prob_text)

        # 已揭示标记
        if source == "revealed":
            p.setPen(QPen(_P_CONFIRM))
            p.setFont(QFont("Arial", 7))
            p.drawText(QRect(w - 14, 1, 12, 12), Qt.AlignCenter, "*")

        p.end()


# ═══════════════════════════════════════════════════════════════
# 主叠加窗口
# ═══════════════════════════════════════════════════════════════


class OverlayWindow(QWidget):
    """Firestone 风格半透明叠加窗口。

    特性:
    - 动态缩放: 右下角拖拽手柄可自由调整大小
    - 紧凑/展开: 双击标题栏 或 点击 ─/═ 按钮
    - 拖动: 按住标题栏拖动窗口
    - 点击穿透: 默认穿透，按 Ctrl+Shift+I 切换
    - 关闭: 标题栏 × 按钮
    - 设置: 标题栏 ⚙ 按钮(预留)
    """

    # 信号
    toggle_mode = pyqtSignal()
    close_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, image_manager: Optional[CardImageManager] = None, parent=None):
        super().__init__(parent)
        self._image_manager = image_manager or CardImageManager()
        self._gs = CompleteGameState()
        self._compact = False
        self._interactive = False

        # 拖动状态
        self._drag_start: Optional[QPoint] = None
        self._drag_offset = QPoint(0, 0)
        self._resizing = False
        self._resize_start_geo = None
        self._resize_start_pos = None

        # 控件缓存 — 不每次 deleteLater
        self._hand_widgets: List[_HandCard] = []
        self._deck_rows: List[_DeckRow] = []

        # 原始数据哈希 — 避免无变化时重建
        self._hand_hash = ""
        self._deck_hash = ""

        self._init_window()
        self._init_ui()

        # 刷新节流
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.setInterval(100)

    # ── 窗口初始化 ──────────────────────────────────────────

    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
            | Qt.Tool  # 不在任务栏出现
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumSize(_MIN_W, _MIN_H)

        # 初始位置: 屏幕右侧
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.setGeometry(
                g.right() - _DEFAULT_W - 16,
                g.top() + 80,
                _DEFAULT_W,
                min(_DEFAULT_H, g.height() - 160),
            )

    # ── UI 构建 ─────────────────────────────────────────────

    def _init_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(3, 3, 3, 3)
        self._root.setSpacing(2)

        # 标题栏
        self._root.addWidget(self._build_header())

        # 手牌区
        self._hand_section = self._build_hand_section()
        self._root.addWidget(self._hand_section)

        # 卡组区
        self._deck_section = self._build_deck_section()
        self._root.addWidget(self._deck_section, stretch=1)

        # 奥秘区
        self._secret_section = self._build_secret_section()
        self._root.addWidget(self._secret_section)
        self._secret_section.hide()

        # 底部栏
        self._root.addWidget(self._build_footer())

        # 缩放手柄 (右下角)
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(_GRIP_SIZE, _GRIP_SIZE)
        self._grip.setStyleSheet("QSizeGrip{background:transparent;}")

    # ── 标题栏 ──────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        """标题栏 — 拖拽区 + 信息 + 按钮"""
        w = QWidget()
        w.setFixedHeight(_HEADER_H)
        w.setCursor(QCursor(Qt.SizeAllCursor))

        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 0, 4, 0)
        lay.setSpacing(4)

        # 职业图标(字母)
        self._ico = QPushButton("?")
        self._ico.setFixedSize(22, 22)
        self._ico.setFont(QFont("Arial", 9, QFont.Bold))
        self._ico.setStyleSheet(
            "QPushButton{background:rgba(60,65,85,200);color:#ddd;border:none;border-radius:4px;}"
            "QPushButton:hover{background:rgba(80,85,105,220);}"
        )
        lay.addWidget(self._ico)

        # 职业名
        self._class_lbl = QPushButton("未知")
        self._class_lbl.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self._class_lbl.setStyleSheet(
            "QPushButton{background:transparent;color:#dde;border:none;text-align:left;}"
            "QPushButton:hover{color:#fff;}"
        )
        self._class_lbl.setFixedHeight(22)
        lay.addWidget(self._class_lbl)

        lay.addStretch()

        # 回合
        self._turn_lbl = QPushButton("T0")
        self._turn_lbl.setFont(QFont("Consolas", 9, QFont.Bold))
        self._turn_lbl.setStyleSheet(
            "QPushButton{background:transparent;color:#5ac3ff;border:none;}"
        )
        self._turn_lbl.setFixedSize(28, 22)
        lay.addWidget(self._turn_lbl)

        # 手牌数
        self._hand_lbl = QPushButton("4")
        self._hand_lbl.setFont(QFont("Consolas", 9, QFont.Bold))
        self._hand_lbl.setStyleSheet(
            "QPushButton{background:rgba(60,65,85,150);color:#bbb;border:none;border-radius:3px;}"
        )
        self._hand_lbl.setFixedSize(20, 22)
        lay.addWidget(self._hand_lbl)

        # 设置齿轮
        self._gear_btn = QPushButton()
        self._gear_btn.setFixedSize(18, 18)
        self._gear_btn.setText("\u2699")  # ⚙
        self._gear_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#777;border:none;font-size:13px;}"
            "QPushButton:hover{color:#ccc;}"
        )
        self._gear_btn.clicked.connect(self.settings_requested.emit)
        lay.addWidget(self._gear_btn)

        # 模式切换
        self._mode_btn = QPushButton("\u2500")  # ─
        self._mode_btn.setFixedSize(18, 18)
        self._mode_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#777;border:none;font-size:12px;}"
            "QPushButton:hover{color:#ccc;}"
        )
        self._mode_btn.clicked.connect(self._toggle_compact)
        lay.addWidget(self._mode_btn)

        # 关闭
        self._close_btn = QPushButton("\u00d7")  # ×
        self._close_btn.setFixedSize(18, 18)
        self._close_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#777;border:none;font-size:14px;}"
            "QPushButton:hover{color:#e55;background:rgba(200,50,50,80);border-radius:2px;}"
        )
        self._close_btn.clicked.connect(self.close_requested.emit)
        lay.addWidget(self._close_btn)

        return w

    # ── 手牌区 ──────────────────────────────────────────────

    def _build_hand_section(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(_HAND_H)
        self._hand_lay = QHBoxLayout(w)
        self._hand_lay.setContentsMargins(4, 2, 4, 2)
        self._hand_lay.setSpacing(3)

        # 预创建 10 个手牌位(最大手牌数)
        for _ in range(10):
            hc = _HandCard({"cost": 0, "name": "", "probability": 0.0, "source": ""})
            hc.hide()
            self._hand_lay.addWidget(hc)
            self._hand_widgets.append(hc)

        return w

    # ── 卡组区 ──────────────────────────────────────────────

    def _build_deck_section(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 标题行(自绘)
        self._deck_title = QWidget()
        self._deck_title.setFixedHeight(20)
        lay.addWidget(self._deck_title)

        # 滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:3px;background:transparent;}"
            "QScrollBar::handle:vertical{background:rgba(100,100,120,120);border-radius:1px;min-height:16px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        self._deck_container = QWidget()
        self._deck_container.setStyleSheet("background:transparent;")
        self._deck_inner_lay = QVBoxLayout(self._deck_container)
        self._deck_inner_lay.setContentsMargins(0, 0, 0, 0)
        self._deck_inner_lay.setSpacing(0)
        self._deck_inner_lay.addStretch()

        # 预创建 30 行(最大卡组数)
        for _ in range(30):
            row = _DeckRow({"cost": 0, "name": "", "remaining": 0, "quantity": 0})
            row.hide()
            self._deck_inner_lay.insertWidget(self._deck_inner_lay.count() - 1, row)
            self._deck_rows.append(row)

        scroll.setWidget(self._deck_container)
        lay.addWidget(scroll, stretch=1)

        self._deck_remaining = 0
        self._deck_total = 30

        return w

    # ── 奥秘区 ──────────────────────────────────────────────

    def _build_secret_section(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(28)
        return w

    # ── 底部栏 ──────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(_FOOTER_H)
        return w

    # ═══════════════════════════════════════════════════════════
    # 更新接口
    # ═══════════════════════════════════════════════════════════

    def update_state(self, gs: CompleteGameState):
        self._gs = gs

    def start_refresh(self):
        self._timer.start()

    def stop_refresh(self):
        self._timer.stop()

    # ── 核心刷新（增量） ─────────────────────────────────────

    def _refresh(self):
        gs = self._gs

        # 1. 标题栏
        opp_class = getattr(gs.opponent.hero, 'hero_class_en',
                             gs.opponent.hero.hero_class)
        self._ico.setText(_CLASS_ICO.get(opp_class, "?"))
        cn = gs.opponent.hero.hero_class_cn or "未知"
        self._class_lbl.setText(cn)
        self._turn_lbl.setText(f"T{gs.turn}")
        self._hand_lbl.setText(str(gs.opponent.hand_count))

        # 2. 手牌区（增量对比）
        preds = gs.hand_predictions
        new_hash = str([(p.get("card_id", ""), p.get("probability", 0)) for p in preds])
        if new_hash != self._hand_hash:
            self._hand_hash = new_hash
            n = len(preds)
            for i, hw in enumerate(self._hand_widgets):
                if i < n:
                    hw.set_data(preds[i])
                    hw.show()
                else:
                    hw.hide()

        # 3. 卡组区（增量对比）
        dp = gs.deck_predictions
        deck_hash = str([(c.get("card_id", ""), c.get("remaining", 0)) for c in dp])
        if deck_hash != self._deck_hash:
            self._deck_hash = deck_hash
            n = len(dp)
            for i, row in enumerate(self._deck_rows):
                if i < n:
                    row.set_data(dp[i])
                    row.show()
                else:
                    row.hide()
            self._deck_remaining = sum(c.get("remaining", 0) for c in dp)
            self._deck_total = gs.opponent.initial_deck_size or 30

        # 4. 奥秘区
        secrets = gs.opponent.secrets
        if secrets:
            self._secret_section.show()
        else:
            self._secret_section.hide()

        # 触发自绘区域重绘
        self._deck_title.update()
        self._secret_section.update()
        self._footer.update()

    # ═══════════════════════════════════════════════════════════
    # 自绘: 背景 + 标题栏 + 分区 + 奥秘 + 底部
    # ═══════════════════════════════════════════════════════════

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()

        # 主背景
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_BG))
        p.drawRoundedRect(r, 5, 5)

        # 边框
        p.setPen(QPen(_BORDER, 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 5, 5)

        # 缩放手柄指示点
        gx = r.right() - 4
        gy = r.bottom() - 4
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(100, 105, 125, 120)))
        for dy in range(0, 7, 3):
            for dx in range(0, 7, 3):
                if dx + dy >= 3:
                    p.drawEllipse(gx - dx - 2, gy - dy - 2, 2, 2)

        p.end()

    # ── 卡组标题自绘 ─────────────────────────────────────────

    def _deck_title_paintEvent(self, _):
        # 由 _refresh 调用 update() 触发
        p = QPainter(self._deck_title)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._deck_title.width(), self._deck_title.height()

        # 标题文字
        p.setPen(QPen(_TEXT_DIM))
        p.setFont(QFont("Microsoft YaHei", 7))
        p.drawText(QRect(6, 0, w // 2, h), Qt.AlignVCenter | Qt.AlignLeft, "对手卡组")

        # 计数
        p.setPen(QPen(_TEXT_DIM))
        p.setFont(QFont("Consolas", 7))
        p.drawText(QRect(w - 40, 0, 34, h), Qt.AlignVCenter | Qt.AlignRight,
                   f"{self._deck_remaining}/{self._deck_total}")
        p.end()

    # ── 奥秘区自绘 ──────────────────────────────────────────

    def _secret_section_paintEvent(self, _):
        p = QPainter(self._secret_section)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._secret_section.width(), self._secret_section.height()

        # 背景
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(45, 25, 50, 160)))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        secrets = self._gs.opponent.secrets
        parts = []
        for s in secrets:
            name = s.name or s.card_id
            if s.probability >= 1.0:
                parts.append(f"* {name}")
            elif s.probability >= 0.5:
                parts.append(f"? {name} {s.probability:.0%}")
            else:
                parts.append(f"? {name}")

        text = "  ".join(parts) if parts else ""
        p.setPen(QPen(QColor(200, 100, 250)))
        p.setFont(QFont("Microsoft YaHei", 7))
        p.drawText(QRect(4, 0, w - 8, h), Qt.AlignVCenter | Qt.AlignLeft, text)

        # 风险
        gs = self._gs
        risk = ""
        if gs.attack_risk > 0.3:
            risk = f"ATK:{gs.attack_risk:.0%}"
        elif gs.spell_risk > 0.3:
            risk = f"SPC:{gs.spell_risk:.0%}"
        if risk:
            p.setPen(QPen(QColor(255, 150, 50)))
            p.setFont(QFont("Consolas", 7))
            p.drawText(QRect(w - 60, 0, 56, h), Qt.AlignVCenter | Qt.AlignRight, risk)

        p.end()

    # ── 底部自绘 ────────────────────────────────────────────

    def _footer_paintEvent(self, _):
        p = QPainter(self._footer)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._footer.width(), self._footer.height()

        # 背景
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_BG_HEADER))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        gs = self._gs

        # 原型名
        if gs.archetype_name:
            conf = f" {gs.archetype_confidence:.0%}" if gs.archetype_confidence > 0 else ""
            p.setPen(QPen(_TEXT))
            p.setFont(QFont("Microsoft YaHei", 8, QFont.Bold))
            p.drawText(QRect(6, 2, w - 12, 16), Qt.AlignVCenter | Qt.AlignLeft,
                       f"{gs.archetype_name}{conf}")
        else:
            p.setPen(QPen(_TEXT_DIM))
            p.setFont(QFont("Microsoft YaHei", 8))
            p.drawText(QRect(6, 2, w - 12, 16), Qt.AlignVCenter | Qt.AlignLeft,
                       "推断中...")

        # 打法 + Top3
        ps = gs.playstyle
        ps_cn = _STYLE_CN.get(ps, "未知")
        ps_color = _STYLE_C.get(ps, _TEXT_DIM)

        line2_y = 22
        p.setPen(QPen(ps_color))
        p.setFont(QFont("Microsoft YaHei", 7))
        p.drawText(QRect(6, line2_y, 50, 14), Qt.AlignVCenter | Qt.AlignLeft, ps_cn)

        if gs.top_archetypes:
            parts = " | ".join(
                f"{n[:10]}{'..' if len(n) > 10 else ''} {pr:.0%}"
                for n, pr in gs.top_archetypes[:3]
            )
            p.setPen(QPen(_TEXT_DIM))
            p.setFont(QFont("Microsoft YaHei", 6))
            p.drawText(QRect(56, line2_y, w - 62, 14), Qt.AlignVCenter | Qt.AlignLeft, parts)

        p.end()

    # ── 重定向子控件 paintEvent ──────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == event.Paint:
            if obj is self._deck_title:
                self._deck_title_paintEvent(event)
                return True
            if obj is self._secret_section:
                self._secret_section_paintEvent(event)
                return True
            if obj is self._footer:
                self._footer_paintEvent(event)
                return True
        return super().eventFilter(obj, event)

    # ═══════════════════════════════════════════════════════════
    # 交互: 拖动 + 缩放 + 模式切换
    # ═══════════════════════════════════════════════════════════

    def _toggle_compact(self):
        self._compact = not self._compact
        self._mode_btn.setText("\u2550" if self._compact else "\u2500")  # ═ / ─
        target_w = _MIN_W if self._compact else _DEFAULT_W
        self.resize(target_w, self.height())

    def set_interactive(self, on: bool):
        self._interactive = on
        if on:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
            )
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.WindowTransparentForInput
                | Qt.Tool
            )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.show()

    # ── 鼠标事件: 拖动 ──────────────────────────────────────

    def mousePressEvent(self, event):
        if not self._interactive:
            return
        if event.button() == Qt.LeftButton:
            # 判断是否在标题栏区域
            header_bottom = self._root.itemAt(0).widget().geometry().bottom()
            if event.y() <= header_bottom + 5:
                self._drag_start = event.globalPos()
                self._drag_offset = self.pos() - event.globalPos()
            else:
                self._drag_start = None

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() + self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_start = None

    def mouseDoubleClickEvent(self, event):
        if not self._interactive:
            return
        header_bottom = self._root.itemAt(0).widget().geometry().bottom()
        if event.y() <= header_bottom + 5:
            self._toggle_compact()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 确保 QSizeGrip 在右下角
        if hasattr(self, '_grip'):
            self._grip.move(self.width() - _GRIP_SIZE, self.height() - _GRIP_SIZE)
        self.update()

    # ── 子控件事件过滤安装 ───────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        # 安装事件过滤器（用于自绘子控件）
        self._deck_title.installEventFilter(self)
        self._secret_section.installEventFilter(self)
        self._footer.installEventFilter(self)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._deck_title.removeEventFilter(self)
        self._secret_section.removeEventFilter(self)
        self._footer.removeEventFilter(self)
