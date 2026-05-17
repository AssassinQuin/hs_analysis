# -*- coding: utf-8 -*-
"""overlay_ui.py — 主叠加窗口 (PyQt5)

在炉石传说游戏窗口上方浮动的半透明叠加 UI。
参考 Firestone 等工具的设计风格。

窗口属性:
- 无边框、始终置顶、半透明背景
- 可拖动（按住标题栏区域拖动）
- 自动定位到炉石窗口右侧
- 可切换紧凑/展开模式

布局:
- 顶部栏: 对手职业图标 + 名称、回合数、对手手牌数
- 对手手牌区: 预测的对手手牌卡牌（带概率条）
- 卡组列表区: 预测的对手卡组构成（按费用排序）
- 奥秘区: 活跃奥秘及概率（当有奥秘时显示）
- 底部信息栏: 贝叶斯原型预测 + 打法分类
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy, QPushButton, QProgressBar,
    QGraphicsOpacityEffect, QApplication,
)
from PyQt5.QtCore import (
    Qt, QPoint, QTimer, pyqtSignal, QSize, QRect,
)
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QLinearGradient,
    QPixmap, QFontMetrics, QPainterPath,
)

from tracker.game_state import (
    CompleteGameState, PlayerState, CardInDeck, CardInHand,
    SecretState, HandPrediction, DeckPrediction,
)
from tracker.card_images import CardImageManager

logger = logging.getLogger(__name__)

# ── 颜色常量 ──────────────────────────────────────────────────

# 主题色（深色背景）
_BG_COLOR = QColor(20, 22, 30, 220)           # 半透明深色背景
_BG_COLOR_COMPACT = QColor(20, 22, 30, 200)
_BORDER_COLOR = QColor(60, 65, 80, 180)        # 边框
_HEADER_BG = QColor(30, 33, 45, 240)           # 标题栏背景
_TEXT_COLOR = QColor(220, 225, 235)             # 主文字
_TEXT_DIM = QColor(140, 145, 160)               # 次要文字
_TEXT_ACCENT = QColor(100, 200, 255)            # 强调色

# 费用颜色 (0-10+)
_COST_COLORS = [
    QColor(180, 180, 180),  # 0 - 灰色
    QColor(200, 200, 200),  # 1
    QColor(170, 210, 255),  # 2 - 淡蓝
    QColor(100, 180, 255),  # 3 - 蓝
    QColor(80, 160, 230),   # 4
    QColor(255, 200, 80),   # 5 - 金色
    QColor(255, 170, 50),   # 6 - 橙
    QColor(255, 120, 50),   # 7 - 红橙
    QColor(255, 80, 80),    # 8 - 红
    QColor(220, 60, 120),   # 9 - 紫红
    QColor(180, 80, 220),   # 10+ - 紫
]

# 概率颜色
_PROB_HIGH = QColor(80, 200, 120)    # ≥70% 绿色
_PROB_MID = QColor(255, 200, 60)     # 50-70% 黄色
_PROB_LOW = QColor(180, 80, 80)      # <50% 红色
_PROB_CONFIRMED = QColor(60, 220, 100)  # 100% 亮绿

# 打法分类颜色
_PLAYSTYLE_COLORS = {
    "aggro": QColor(255, 80, 80),
    "control": QColor(80, 160, 255),
    "combo": QColor(200, 100, 255),
    "midrange": QColor(255, 200, 60),
    "tempo": QColor(255, 150, 50),
    "unknown": QColor(140, 145, 160),
}

# 打法分类中文
_PLAYSTYLE_CN = {
    "aggro": "快攻",
    "control": "控制",
    "combo": "组合技",
    "midrange": "中速",
    "tempo": "节奏",
    "unknown": "未知",
}

# 职业图标文字（用文字代替图标）
_CLASS_ICONS = {
    "WARRIOR": "⚔", "SHAMAN": "⚡", "ROGUE": "🗡",
    "PALADIN": "🛡", "HUNTER": "🏹", "WARLOCK": "😈",
    "MAGE": "🔮", "PRIEST": "✝", "DRUID": "🌿",
    "DEMONHUNTER": "👁", "DEATHKNIGHT": "💀",
    "UNKNOWN": "?",
}


# ── 辅助函数 ──────────────────────────────────────────────────

def cost_color(cost: int) -> QColor:
    """获取费用对应的颜色。"""
    idx = min(cost, len(_COST_COLORS) - 1)
    return _COST_COLORS[max(0, idx)]


def prob_color(probability: float) -> QColor:
    """获取概率对应的颜色。"""
    if probability >= 1.0:
        return _PROB_CONFIRMED
    elif probability >= 0.7:
        return _PROB_HIGH
    elif probability >= 0.5:
        return _PROB_MID
    else:
        return _PROB_LOW


# ── 自定义控件 ────────────────────────────────────────────────

class CardDeckEntry(QWidget):
    """卡组列表中的一行卡牌条目。

    显示: 费用圆圈 + 卡牌名称 + 数量 + 小缩略图
    """

    def __init__(self, card: dict, parent=None):
        super().__init__(parent)
        self._card = card
        self.setFixedHeight(26)
        self._update_display()

    def _update_display(self):
        """更新显示内容。"""
        # 此控件完全通过 paintEvent 自绘
        pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        card = self._card
        cost = card.get("cost", 0)
        name = card.get("name", "???")
        quantity = card.get("quantity", 1)
        remaining = card.get("remaining", 1)
        played = card.get("played", False)
        in_hand = card.get("in_hand", False)
        card_type = card.get("card_type", "")

        w = self.width()
        h = self.height()

        # 背景
        if in_hand:
            bg = QColor(40, 60, 80, 150)
        elif played:
            bg = QColor(30, 30, 35, 100)
        else:
            bg = QColor(25, 28, 38, 80)
        painter.fillRect(0, 0, w, h, bg)

        # 费用圆圈
        cc = cost_color(cost)
        cx, cy, cr = 13, h // 2, 9
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cc))
        painter.drawEllipse(cx - cr, cy - cr, cr * 2, cr * 2)

        # 费用数字
        painter.setPen(QPen(QColor(0, 0, 0)))
        font = QFont("Arial", 8, QFont.Bold)
        painter.setFont(font)
        cost_text = str(cost) if cost <= 10 else "10+"
        painter.drawText(QRect(cx - cr, cy - cr, cr * 2, cr * 2),
                         Qt.AlignCenter, cost_text)

        # 卡牌名称
        name_color = _TEXT_COLOR if not played else _TEXT_DIM
        if played:
            # 删除线效果
            painter.setPen(QPen(_TEXT_DIM))
        else:
            painter.setPen(QPen(name_color))

        font = QFont("Microsoft YaHei", 9)
        painter.setFont(font)
        name_x = 28
        name_w = w - 65
        if len(name) > 16:
            name = name[:15] + "…"
        painter.drawText(QRect(name_x, 0, name_w, h), Qt.AlignVCenter | Qt.AlignLeft, name)

        # 已打出 → 删除线
        if played:
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(name)
            line_y = h // 2
            painter.setPen(QPen(QColor(200, 80, 80, 180), 1))
            painter.drawLine(name_x, line_y, name_x + min(text_width, name_w), line_y)

        # 数量
        if remaining > 1 or quantity > 1:
            painter.setPen(QPen(_TEXT_ACCENT if remaining > 0 else _TEXT_DIM))
            font = QFont("Arial", 9, QFont.Bold)
            painter.setFont(font)
            qty_text = f"×{remaining}" if remaining != quantity else f"×{quantity}"
            painter.drawText(QRect(w - 35, 0, 30, h), Qt.AlignVCenter | Qt.AlignRight, qty_text)

        painter.end()

    def update_card(self, card: dict):
        """更新卡牌数据。"""
        self._card = card
        self.update()


class HandCardWidget(QWidget):
    """对手手牌预测中的一个卡牌条目。

    显示: 小卡牌图像 + 名称 + 费用 + 概率条
    """

    def __init__(self, card: dict, image_manager: Optional[CardImageManager] = None, parent=None):
        super().__init__(parent)
        self._card = card
        self._image_manager = image_manager
        self.setFixedSize(90, 50)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        card = self._card
        cost = card.get("cost", 0)
        name = card.get("name", "???")
        probability = card.get("probability", 0.0)
        source = card.get("source", "deck")

        w = self.width()
        h = self.height()

        # 背景（带概率着色）
        pc = prob_color(probability)
        bg = QColor(pc.red(), pc.green(), pc.blue(), 30)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 4, 4)

        # 边框
        border_color = pc if probability >= 0.5 else QColor(60, 65, 80, 120)
        if probability >= 1.0:
            border_color = _PROB_CONFIRMED
        painter.setPen(QPen(border_color, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 4, 4)

        # 费用
        cc = cost_color(cost)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cc))
        painter.drawEllipse(6, 4, 18, 18)
        painter.setPen(QPen(QColor(0, 0, 0)))
        font = QFont("Arial", 8, QFont.Bold)
        painter.setFont(font)
        painter.drawText(QRect(6, 4, 18, 18), Qt.AlignCenter, str(cost))

        # 名称
        display_name = name
        if probability < 0.5:
            display_name = "?"
        elif len(name) > 8:
            display_name = name[:7] + "…"

        painter.setPen(QPen(_TEXT_COLOR if probability >= 0.5 else _TEXT_DIM))
        font = QFont("Microsoft YaHei", 7)
        painter.setFont(font)
        painter.drawText(QRect(28, 2, w - 32, 20), Qt.AlignVCenter | Qt.AlignLeft, display_name)

        # 概率条
        bar_y = 30
        bar_h = 6
        bar_w = w - 12
        # 背景
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(40, 45, 55)))
        painter.drawRoundedRect(6, bar_y, bar_w, bar_h, 3, 3)
        # 填充
        fill_w = int(bar_w * min(probability, 1.0))
        if fill_w > 0:
            painter.setBrush(QBrush(pc))
            painter.drawRoundedRect(6, bar_y, fill_w, bar_h, 3, 3)

        # 概率文字
        prob_text = "确认" if probability >= 1.0 else f"{probability:.0%}" if probability >= 0.5 else "?"
        painter.setPen(QPen(pc))
        font = QFont("Arial", 7)
        painter.setFont(font)
        painter.drawText(QRect(6, bar_y + bar_h + 1, bar_w, 12), Qt.AlignCenter, prob_text)

        # 已揭示标记（眼睛图标）
        if source == "revealed":
            painter.setPen(QPen(_PROB_CONFIRMED))
            font = QFont("Arial", 10)
            painter.setFont(font)
            painter.drawText(QRect(w - 16, 2, 14, 14), Qt.AlignCenter, "👁")

        painter.end()

    def update_card(self, card: dict):
        """更新卡牌数据。"""
        self._card = card
        self.update()


# ── 主叠加窗口 ────────────────────────────────────────────────

class OverlayWindow(QWidget):
    """主叠加窗口。

    浮在炉石传说窗口上方的半透明叠加 UI。

    信号:
        toggle_mode() — 切换紧凑/展开模式
    """

    toggle_mode = pyqtSignal()

    # 窗口尺寸
    EXPANDED_WIDTH = 280
    COMPACT_WIDTH = 200
    MIN_HEIGHT = 400

    def __init__(
        self,
        image_manager: Optional[CardImageManager] = None,
        parent=None,
    ):
        super().__init__(parent)

        self._image_manager = image_manager or CardImageManager()
        self._game_state = CompleteGameState()
        self._compact_mode = False
        self._drag_start: Optional[QPoint] = None
        self._drag_offset: QPoint = QPoint(0, 0)

        # 卡组列表控件缓存
        self._deck_entries: list[CardDeckEntry] = []
        self._hand_cards: list[HandCardWidget] = []

        self._setup_window()
        self._setup_ui()

        # 刷新定时器（限制 UI 刷新频率）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._do_refresh)
        self._refresh_timer.setInterval(100)  # 10 FPS

    def _setup_window(self):
        """设置窗口属性。"""
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput  # 可穿透点击
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # 设置初始位置（屏幕右侧）
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = self.EXPANDED_WIDTH
            self.setGeometry(
                geo.right() - w - 20,
                geo.top() + 100,
                w,
                min(700, geo.height() - 200),
            )

        self.setMinimumHeight(self.MIN_HEIGHT)

    def _setup_ui(self):
        """构建 UI 布局。"""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(4, 4, 4, 4)
        self._main_layout.setSpacing(2)

        # ── 顶部栏 ──
        self._header = self._create_header()
        self._main_layout.addWidget(self._header)

        # ── 对手手牌区 ──
        self._hand_section = self._create_hand_section()
        self._main_layout.addWidget(self._hand_section)

        # ── 卡组列表区（可滚动） ──
        self._deck_section = self._create_deck_section()
        self._main_layout.addWidget(self._deck_section, stretch=1)

        # ── 奥秘区 ──
        self._secret_section = self._create_secret_section()
        self._main_layout.addWidget(self._secret_section)
        self._secret_section.hide()  # 默认隐藏

        # ── 底部信息栏 ──
        self._footer = self._create_footer()
        self._main_layout.addWidget(self._footer)

    def _create_header(self) -> QWidget:
        """创建顶部栏。"""
        header = QFrame()
        header.setFixedHeight(36)
        header.setStyleSheet(f"background: {_qcolor_str(_HEADER_BG)}; border-radius: 4px;")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 2, 8, 2)

        # 对手职业图标
        self._opp_class_icon = QLabel("?")
        self._opp_class_icon.setFixedSize(24, 24)
        self._opp_class_icon.setAlignment(Qt.AlignCenter)
        font = QFont("Arial", 14)
        self._opp_class_icon.setFont(font)
        self._opp_class_icon.setStyleSheet("color: white;")
        layout.addWidget(self._opp_class_icon)

        # 对手职业名
        self._opp_class_label = QLabel("未知")
        self._opp_class_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_COLOR)}; font-weight: bold;")
        font = QFont("Microsoft YaHei", 10, QFont.Bold)
        self._opp_class_label.setFont(font)
        layout.addWidget(self._opp_class_label)

        layout.addStretch()

        # 回合数
        self._turn_label = QLabel("回合 0")
        self._turn_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_ACCENT)};")
        font = QFont("Microsoft YaHei", 9)
        self._turn_label.setFont(font)
        layout.addWidget(self._turn_label)

        # 对手手牌数
        self._hand_count_label = QLabel("手牌: 0")
        self._hand_count_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)};")
        font = QFont("Microsoft YaHei", 9)
        self._hand_count_label.setFont(font)
        layout.addWidget(self._hand_count_label)

        # 模式切换按钮
        self._mode_btn = QPushButton("─")
        self._mode_btn.setFixedSize(20, 20)
        self._mode_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 12px; }"
            "QPushButton:hover { color: white; }"
        )
        self._mode_btn.clicked.connect(self._toggle_compact_mode)
        layout.addWidget(self._mode_btn)

        return header

    def _create_hand_section(self) -> QWidget:
        """创建对手手牌区。"""
        section = QFrame()
        section.setStyleSheet(
            f"background: {_qcolor_str(QColor(25, 28, 38, 180))}; border-radius: 4px;"
        )

        layout = QVBoxLayout(section)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # 标题
        title = QLabel("对手手牌")
        title.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)}; font-size: 10px;")
        font = QFont("Microsoft YaHei", 8)
        title.setFont(font)
        layout.addWidget(title)

        # 手牌容器
        self._hand_layout = QHBoxLayout()
        self._hand_layout.setSpacing(4)
        self._hand_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._hand_layout)

        section.setFixedHeight(70)
        return section

    def _create_deck_section(self) -> QWidget:
        """创建卡组列表区。"""
        section = QFrame()
        section.setStyleSheet(
            f"background: {_qcolor_str(QColor(25, 28, 38, 150))}; border-radius: 4px;"
        )

        layout = QVBoxLayout(section)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(1)

        # 标题
        title_layout = QHBoxLayout()
        title = QLabel("对手卡组")
        title.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)}; font-size: 10px;")
        font = QFont("Microsoft YaHei", 8)
        title.setFont(font)
        title_layout.addWidget(title)

        title_layout.addStretch()

        self._deck_count_label = QLabel("0/30")
        self._deck_count_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)}; font-size: 10px;")
        self._deck_count_label.setFont(font)
        title_layout.addWidget(self._deck_count_label)

        layout.addLayout(title_layout)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: #555; border-radius: 2px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._deck_container = QWidget()
        self._deck_container.setStyleSheet("background: transparent;")
        self._deck_layout = QVBoxLayout(self._deck_container)
        self._deck_layout.setContentsMargins(0, 0, 0, 0)
        self._deck_layout.setSpacing(1)
        self._deck_layout.addStretch()

        scroll.setWidget(self._deck_container)
        layout.addWidget(scroll, stretch=1)

        return section

    def _create_secret_section(self) -> QWidget:
        """创建奥秘区。"""
        section = QFrame()
        section.setStyleSheet(
            f"background: {_qcolor_str(QColor(40, 25, 40, 180))}; border-radius: 4px;"
        )

        layout = QVBoxLayout(section)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        title = QLabel("⚠ 奥秘")
        title.setStyleSheet(f"color: {_qcolor_str(QColor(200, 100, 255))}; font-size: 10px;")
        font = QFont("Microsoft YaHei", 8, QFont.Bold)
        title.setFont(font)
        layout.addWidget(title)

        self._secret_content = QLabel("无可疑奥秘")
        self._secret_content.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)}; font-size: 10px;")
        self._secret_content.setWordWrap(True)
        font = QFont("Microsoft YaHei", 8)
        self._secret_content.setFont(font)
        layout.addWidget(self._secret_content)

        self._risk_label = QLabel("")
        self._risk_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)}; font-size: 9px;")
        self._risk_label.setFont(font)
        layout.addWidget(self._risk_label)

        return section

    def _create_footer(self) -> QWidget:
        """创建底部信息栏。"""
        footer = QFrame()
        footer.setFixedHeight(50)
        footer.setStyleSheet(
            f"background: {_qcolor_str(_HEADER_BG)}; border-radius: 4px;"
        )

        layout = QVBoxLayout(footer)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(1)

        # 原型预测
        self._archetype_label = QLabel("等待游戏开始…")
        self._archetype_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_COLOR)};")
        font = QFont("Microsoft YaHei", 9, QFont.Bold)
        self._archetype_label.setFont(font)
        layout.addWidget(self._archetype_label)

        # 打法分类 + Top 3
        info_layout = QHBoxLayout()
        info_layout.setSpacing(4)

        self._playstyle_label = QLabel("")
        self._playstyle_label.setStyleSheet("font-size: 9px;")
        self._playstyle_label.setFont(QFont("Microsoft YaHei", 8))
        info_layout.addWidget(self._playstyle_label)

        info_layout.addStretch()

        self._top_decks_label = QLabel("")
        self._top_decks_label.setStyleSheet(f"color: {_qcolor_str(_TEXT_DIM)}; font-size: 8px;")
        self._top_decks_label.setFont(QFont("Microsoft YaHei", 7))
        info_layout.addWidget(self._top_decks_label)

        layout.addLayout(info_layout)

        return footer

    # ── 更新接口 ───────────────────────────────────────────────

    def update_state(self, game_state: CompleteGameState):
        """更新游戏状态（从外部调用，会触发延迟刷新）。"""
        self._game_state = game_state
        # 不直接刷新，等定时器触发（节流）

    def start_refresh(self):
        """启动 UI 刷新定时器。"""
        self._refresh_timer.start()

    def stop_refresh(self):
        """停止 UI 刷新定时器。"""
        self._refresh_timer.stop()

    def _do_refresh(self):
        """执行 UI 刷新。"""
        gs = self._game_state

        # 更新顶部栏
        opp_class = gs.opponent.hero.hero_class_en if hasattr(gs.opponent.hero, 'hero_class_en') else gs.opponent.hero.hero_class
        icon = _CLASS_ICONS.get(opp_class, "?")
        self._opp_class_icon.setText(icon)
        self._opp_class_label.setText(gs.opponent.hero.hero_class_cn or "未知")
        self._turn_label.setText(f"回合 {gs.turn}")
        self._hand_count_label.setText(f"手牌: {gs.opponent.hand_count}")

        # 更新对手手牌区
        self._update_hand_display(gs)

        # 更新卡组列表
        self._update_deck_display(gs)

        # 更新奥秘区
        self._update_secret_display(gs)

        # 更新底部信息
        self._update_footer(gs)

    def _update_hand_display(self, gs: CompleteGameState):
        """更新对手手牌显示。"""
        # 清除旧控件
        for w in self._hand_cards:
            self._hand_layout.removeWidget(w)
            w.deleteLater()
        self._hand_cards.clear()

        # 添加新控件
        predictions = gs.hand_predictions
        max_show = 5  # 最多显示 5 张
        for pred in predictions[:max_show]:
            widget = HandCardWidget(pred, self._image_manager)
            self._hand_layout.addWidget(widget)
            self._hand_cards.append(widget)

        # 不足 5 张时添加占位符
        remaining = max_show - min(len(predictions), max_show)
        for _ in range(remaining):
            widget = HandCardWidget(
                {"cost": 0, "name": "?", "probability": 0.0, "source": "unknown"},
                self._image_manager,
            )
            self._hand_layout.addWidget(widget)
            self._hand_cards.append(widget)

    def _update_deck_display(self, gs: CompleteGameState):
        """更新卡组列表显示。"""
        # 清除旧控件
        for w in self._deck_entries:
            self._deck_layout.removeWidget(w)
            w.deleteLater()
        self._deck_entries.clear()

        # 添加新控件
        deck_preds = gs.deck_predictions
        for card in deck_preds:
            entry = CardDeckEntry(card)
            self._deck_layout.insertWidget(self._deck_layout.count() - 1, entry)
            self._deck_entries.append(entry)

        # 更新牌库计数
        remaining = sum(c.get("remaining", 0) for c in deck_preds)
        total = gs.opponent.initial_deck_size or 30
        self._deck_count_label.setText(f"{remaining}/{total}")

    def _update_secret_display(self, gs: CompleteGameState):
        """更新奥秘显示。"""
        secrets = gs.opponent.secrets

        if not secrets:
            self._secret_section.hide()
            return

        self._secret_section.show()

        # 构建奥秘文字
        lines = []
        for s in secrets:
            name = s.name or s.card_id
            if s.probability >= 1.0:
                lines.append(f"✓ {name}")
            elif s.probability >= 0.5:
                lines.append(f"? {name} ({s.probability:.0%})")
            else:
                lines.append(f"? {name}")

        self._secret_content.setText("\n".join(lines))

        # 风险提示
        if gs.attack_risk > 0.3:
            self._risk_label.setText(f"⚠ 攻击风险: {gs.attack_risk:.0%}")
        elif gs.spell_risk > 0.3:
            self._risk_label.setText(f"⚠ 施法风险: {gs.spell_risk:.0%}")
        else:
            self._risk_label.setText("")

    def _update_footer(self, gs: CompleteGameState):
        """更新底部信息栏。"""
        # 原型预测
        if gs.archetype_name:
            conf = f" ({gs.archetype_confidence:.0%})" if gs.archetype_confidence > 0 else ""
            self._archetype_label.setText(f"原型: {gs.archetype_name}{conf}")
        else:
            self._archetype_label.setText("推断对手卡组中…")

        # 打法分类
        ps = gs.playstyle
        ps_cn = _PLAYSTYLE_CN.get(ps, "未知")
        ps_color = _PLAYSTYLE_COLORS.get(ps, _TEXT_DIM)
        self._playstyle_label.setText(f"打法: {ps_cn}")
        self._playstyle_label.setStyleSheet(
            f"color: {_qcolor_str(ps_color)}; font-size: 9px;"
        )

        # Top 3 原型
        if gs.top_archetypes:
            parts = []
            for name, prob in gs.top_archetypes[:3]:
                short = name[:12] + "…" if len(name) > 12 else name
                parts.append(f"{short} {prob:.0%}")
            self._top_decks_label.setText(" | ".join(parts))
        else:
            self._top_decks_label.setText("")

    # ── 窗口交互 ───────────────────────────────────────────────

    def _toggle_compact_mode(self):
        """切换紧凑/展开模式。"""
        self._compact_mode = not self._compact_mode
        target_w = self.COMPACT_WIDTH if self._compact_mode else self.EXPANDED_WIDTH
        self._mode_btn.setText("═" if self._compact_mode else "─")
        self.resize(target_w, self.height())

    def set_interactive(self, interactive: bool):
        """设置是否可交互（穿透点击切换）。"""
        if interactive:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
            )
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.WindowTransparentForInput
            )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.show()

    # ── 拖动支持 ───────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos()
            self._drag_offset = self.pos() - event.globalPos()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() + self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_start = None

    # ── 自绘背景 ───────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 半透明背景
        bg = _BG_COLOR_COMPACT if self._compact_mode else _BG_COLOR
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(self.rect(), 6, 6)

        # 边框
        painter.setPen(QPen(_BORDER_COLOR, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

        painter.end()

    def resizeEvent(self, event):
        """重绘。"""
        super().resizeEvent(event)
        self.update()


# ── 辅助函数 ──────────────────────────────────────────────────

def _qcolor_str(color: QColor) -> str:
    """将 QColor 转为 rgba CSS 字符串。"""
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alphaF():.2f})"
