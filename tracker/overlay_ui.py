# -*- coding: utf-8 -*-
"""overlay_ui.py — 炉石传说对手追踪叠加窗口 (PyQt5)

半透明浮动侧栏叠加 UI，内容点击穿透到游戏。
"""

from __future__ import annotations

import logging
import math
from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QPushButton, QSizeGrip, QApplication, QToolTip,
)
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QRect
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QFontMetrics, QCursor,
)

from tracker.game_state import CompleteGameState

logger = logging.getLogger(__name__)

# ── 颜色 ────────────────────────────────────────────────────────
_BG = QColor(16, 18, 26, 215)
_BORDER = QColor(50, 55, 70, 150)
_HDR_BG = QColor(26, 29, 40, 235)
_SECT_BG = QColor(22, 25, 35, 160)
_TEXT = QColor(220, 225, 235)
_TEXT_DIM = QColor(130, 135, 155)
_TEXT_ACC = QColor(80, 190, 255)
_P_CONFIRM = QColor(60, 220, 100)
_P_HIGH = QColor(80, 200, 120)
_P_MID = QColor(255, 200, 60)
_P_LOW = QColor(180, 80, 80)
_COLORS = [QColor(180,180,180),QColor(200,200,200),QColor(170,210,255),
           QColor(100,180,255),QColor(80,160,230),QColor(255,200,80),
           QColor(255,170,50),QColor(255,120,50),QColor(255,80,80),
           QColor(220,60,120),QColor(180,80,220)]
_CLASS_ICO = {"WARRIOR":"⚔","SHAMAN":"⚡","ROGUE":"🗡","PALADIN":"🛡",
              "HUNTER":"🏹","WARLOCK":"😈","MAGE":"🔮","PRIEST":"✝",
              "DRUID":"🌿","DEMONHUNTER":"👁","DEATHKNIGHT":"💀","UNKNOWN":"?"}
_ROW_H, _HAND_MAX = 18, 50
_W, _H = 260, 480
_MIN_W, _MIN_H = 180, 200
_GRIP = 10

def _c(c): return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f})"
def _cost_c(c): return _COLORS[min(c, len(_COLORS)-1)]
def _prob_c(p):
    if p >= 1.0: return _P_CONFIRM
    if p >= 0.7: return _P_HIGH
    if p >= 0.5: return _P_MID
    return _P_LOW

# ── 卡组行 ────────────────────────────────────────────────────

class _DeckRow(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.d = data
        self.setFixedHeight(_ROW_H)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_data(self, d):
        self.d = d; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = self.d
        cost, name = d.get("cost",0), d.get("name","???")
        qty, rem = d.get("quantity",1), d.get("remaining",1)
        played, hand = d.get("played",False), d.get("in_hand",False)
        hp = d.get("hand_probability",0.0)
        w, h = self.width(), self.height()

        bg = QColor(40,60,85,100) if hand else QColor(25,25,30,60) if played else QColor(22,25,35,40)
        p.fillRect(0, 0, w, h, bg)

        # 费用
        cc = _cost_c(cost)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(cc))
        p.drawEllipse(4, h//2-6, 12, 12)
        p.setPen(QPen(QColor(0,0,0)))
        ft = QFont("Arial", 6, QFont.Bold); p.setFont(ft)
        p.drawText(QRect(4, h//2-6, 12, 12), Qt.AlignCenter, str(cost) if cost<=10 else "10+")

        # 名称
        p.setPen(QPen(_TEXT if not played else _TEXT_DIM))
        ft = QFont("Microsoft YaHei", 8); p.setFont(ft)
        nw = w - 76
        dn = name[:14]+"…" if len(name)>14 else name
        p.drawText(QRect(19, 0, nw, h), Qt.AlignVCenter|Qt.AlignLeft, dn)
        if played:
            fm = QFontMetrics(ft); tw = fm.horizontalAdvance(dn)
            p.setPen(QPen(QColor(200,80,80,160),1))
            p.drawLine(19, h//2, 19+min(tw,nw), h//2)

        # 统计
        pc = qty - rem
        info = f"{pc}/{qty}"
        if rem > 0: info += f" 剩{rem}"
        if hp > 0.05: info += f" {hp:.0%}"
        p.setPen(QPen(_TEXT_ACC if rem>0 else _TEXT_DIM))
        ft = QFont("Arial", 7); p.setFont(ft)
        p.drawText(QRect(w-72, 0, 68, h), Qt.AlignVCenter|Qt.AlignRight, info)
        p.end()

# ── 主窗口 ──────────────────────────────────────────────────────

class OverlayWindow(QWidget):
    toggle_mode = pyqtSignal()
    close_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, image_manager=None, parent=None):
        super().__init__(parent)
        self._gs = CompleteGameState()
        self._compact = False
        self._interactive = True
        self._drag_start = None
        self._drag_off = QPoint(0,0)
        self._hand_rows: list[QLabel] = []
        self._deck_rows: list[_DeckRow] = []
        self._hand_hash = ""
        self._deck_hash = ""
        self._sel_arch = 0
        self._deck_remaining = 0
        self._deck_total = 30

        self._init_window()
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.setInterval(100)

    def _init_window(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumSize(_MIN_W, _MIN_H)
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.setGeometry(g.right()-_W-16, g.top()+80, _W, min(_H, g.height()-160))

    def _build_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(3,3,3,3)
        self._root.setSpacing(2)

        # 标题栏
        self._root.addWidget(self._build_header())
        # 手牌区（竖排）
        self._hand_sec = self._build_hand_section()
        self._root.addWidget(self._hand_sec)
        # 卡组区
        self._deck_sec = self._build_deck_section()
        self._root.addWidget(self._deck_sec, stretch=1)
        # 底部
        self._footer = self._build_footer()
        self._root.addWidget(self._footer)
        # 缩放手柄
        g = QSizeGrip(self)
        g.setFixedSize(_GRIP, _GRIP)
        g.setStyleSheet("QSizeGrip{background:transparent;}")

    # ── 标题栏 ──────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(28)
        w.setCursor(QCursor(Qt.SizeAllCursor))
        lay = QHBoxLayout(w); lay.setContentsMargins(6,0,4,0); lay.setSpacing(4)

        self._ico = QLabel("?")
        self._ico.setFixedSize(18,18); self._ico.setAlignment(Qt.AlignCenter)
        self._ico.setFont(QFont("Arial",12)); self._ico.setStyleSheet("color:white;")
        self._ico.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._ico)

        self._class_lbl = QLabel("等待对战")
        self._class_lbl.setStyleSheet(f"color:{_c(_TEXT)};font-weight:bold;")
        self._class_lbl.setFont(QFont("Microsoft YaHei",9,QFont.Bold))
        self._class_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._class_lbl)

        lay.addStretch()

        self._turn_lbl = QLabel("")
        self._turn_lbl.setStyleSheet(f"color:{_c(_TEXT_ACC)};")
        self._turn_lbl.setFont(QFont("Microsoft YaHei",8))
        self._turn_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._turn_lbl)

        self._hand_lbl = QLabel("")
        self._hand_lbl.setStyleSheet(f"color:{_c(_TEXT_DIM)};")
        self._hand_lbl.setFont(QFont("Microsoft YaHei",8))
        self._hand_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._hand_lbl)

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(18,18)
        self._close_btn.setStyleSheet("QPushButton{background:transparent;color:#a55;border:none;font-size:14px;}"
                                       "QPushButton:hover{color:#f77;background:rgba(200,50,50,80);border-radius:2px;}")
        self._close_btn.clicked.connect(self.hide)
        lay.addWidget(self._close_btn)

        return w

    # ── 手牌区（竖排） ─────────────────────────────────────────

    def _build_hand_section(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._hand_vlay = QVBoxLayout(w)
        self._hand_vlay.setContentsMargins(4,2,4,2)
        self._hand_vlay.setSpacing(1)

        # 预创建50行手牌标签
        for _ in range(_HAND_MAX):
            lbl = QLabel()
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            lbl.setStyleSheet(f"color:{_c(_TEXT)};font-size:9px;")
            lbl.setFont(QFont("Microsoft YaHei",8))
            lbl.setWordWrap(False)
            lbl.hide()
            self._hand_vlay.addWidget(lbl)
            self._hand_rows.append(lbl)

        # 占位符
        self._hand_empty = QLabel("等待游戏开始…")
        self._hand_empty.setStyleSheet(f"color:{_c(_TEXT_DIM)};font-size:9px;")
        self._hand_empty.setFont(QFont("Microsoft YaHei",8))
        self._hand_empty.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._hand_vlay.addWidget(self._hand_empty)

        return w

    def _upd_hand(self, gs):
        preds = gs.hand_predictions
        dp = gs.deck_predictions

        # 分类
        rev = [h for h in preds if h.get("source")=="revealed"]
        uk = [h for h in preds if h.get("source")=="unknown"]
        prob = [h for h in preds if h not in rev and h not in uk]
        prob.sort(key=lambda h: -h.get("probability",0))

        # 组合：已揭示 → 高概率(>30%) → 其他
        shown = []
        for h in rev:
            nm = h.get("name", h.get("card_id","?"))
            c = h.get("cost",0)
            shown.append(f"[{c}]{nm}")

        for h in prob:
            if h.get("probability",0) >= 0.3:
                nm = h.get("name", h.get("card_id","?"))
                c = h.get("cost",0)
                p = h.get("probability",0)
                shown.append(f"[{c}]{nm} {p:.0%}")

        # 卡组概率
        dr = [d for d in dp if d.get("remaining",0)>0 and not d.get("in_hand") and not d.get("played")]
        dr.sort(key=lambda d: -d.get("hand_probability",0))
        deck_cards = []
        for d in dr[:_HAND_MAX]:
            nm = d.get("name", d.get("card_id","?"))
            c = d.get("cost",0)
            hp = d.get("hand_probability",0)
            deck_cards.append(f"[{c}]{nm} {hp:.0%}")

        # 超出50张不显示
        total = len(shown) + len(deck_cards)
        if total > _HAND_MAX:
            return

        # 填充行
        all_items = shown + ["───"] + deck_cards if deck_cards else shown
        n = len(all_items)
        for i, lbl in enumerate(self._hand_rows):
            if i < n:
                lbl.setText(all_items[i])
                lbl.show()
            else:
                lbl.hide()

        # 手牌计数标签
        self._hand_lbl.setText(f"手{gs.opponent.hand_count} {len(rev)}确 {len(prob)}?")

    # ── 卡组区 ──────────────────────────────────────────────

    def _build_deck_section(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # 标题行
        self._deck_title = QWidget()
        self._deck_title.setFixedHeight(20)
        self._deck_title.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._deck_title)

        # 卡组切换标签
        self._arch_row = QWidget()
        self._arch_row.setFixedHeight(0)
        self._arch_row.hide()
        self._arch_lay = QHBoxLayout(self._arch_row)
        self._arch_lay.setContentsMargins(4,0,4,0); self._arch_lay.setSpacing(2)
        self._arch_btns: list[QPushButton] = []
        lay.addWidget(self._arch_row)

        # 滚动区
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setAttribute(Qt.WA_TransparentForMouseEvents)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        dc = QWidget(); dc.setAttribute(Qt.WA_TransparentForMouseEvents); dc.setStyleSheet("background:transparent;")
        self._dl = QVBoxLayout(dc); self._dl.setContentsMargins(0,0,0,0); self._dl.setSpacing(1); self._dl.addStretch()
        for _ in range(30):
            r = _DeckRow({"cost":0,"name":"","remaining":0,"quantity":0})
            r.hide(); self._dl.insertWidget(self._dl.count()-1, r); self._deck_rows.append(r)
        sc.setWidget(dc)
        lay.addWidget(sc, stretch=1)

        self._deck_exp = False
        return w

    def _tog_exp(self):
        self._deck_exp = not self._deck_exp
        sc = self.findChild(QScrollArea)
        if sc: sc.setFixedHeight(400 if self._deck_exp else 60)

    def _sw_arch(self, idx):
        self._sel_arch = idx
        self._upd_deck(self._gs)

    def _upd_deck(self, gs):
        for r in self._deck_rows: r.hide()
        for b in self._arch_btns: b.deleteLater()
        self._arch_btns.clear()
        self._arch_row.hide()
        self._arch_row.setFixedHeight(0)

        multi = gs.multi_deck_predictions
        if multi:
            if self._sel_arch >= len(multi):
                self._sel_arch = 0
            self._arch_row.show()
            self._arch_row.setFixedHeight(22)
            for i, md in enumerate(multi):
                nm = md.get("archetype_name","未知"); pb = md.get("probability",0)
                b = QPushButton(f"{nm} {pb:.0%}")
                b.setFixedHeight(18); b.setFont(QFont("Microsoft YaHei",7))
                act = i==self._sel_arch
                b.setStyleSheet("QPushButton{background:"+("rgba(80,160,255,140)" if act else "rgba(60,65,80,150)")+
                                ";color:"+("white" if act else "#aaa")+";border:none;border-radius:3px;padding:0 4px;}"
                                "QPushButton:hover{background:rgba(80,90,120,180);color:white;}")
                b.clicked.connect(lambda _,x=i: self._sw_arch(x))
                self._arch_lay.addWidget(b); self._arch_btns.append(b)

            sel = multi[self._sel_arch]
            cards = sel.get("cards",[])
            self._deck_remaining = sum(c.get("remaining",0) for c in cards)
            self._deck_total = gs.opponent.initial_deck_size or 30
            for j, c in enumerate(cards):
                if j < len(self._deck_rows):
                    self._deck_rows[j].set_data(c); self._deck_rows[j].show()

    # ── 底部 ──────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._arch_lbl = QLabel("")
        self._arch_lbl.setStyleSheet(f"color:{_c(_TEXT_ACC)};")
        self._arch_lbl.setFont(QFont("Microsoft YaHei",8))
        self._arch_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(w); lay.setContentsMargins(8,2,8,2)
        lay.addWidget(self._arch_lbl)
        return w

    # ── 公开接口 ───────────────────────────────────────────────

    def update_state(self, gs):
        self._gs = gs

    def start_refresh(self):
        self._timer.start()

    def stop_refresh(self):
        self._timer.stop()

    # ── 核心刷新 ─────────────────────────────────────────────

    def _refresh(self):
        gs = self._gs

        # 标题栏
        cls_en = getattr(gs.opponent.hero,'hero_class_en',gs.opponent.hero.hero_class)
        self._ico.setText(_CLASS_ICO.get(cls_en,"?"))
        self._class_lbl.setText(gs.opponent.hero.hero_class_cn or "未知")
        self._turn_lbl.setText(f"T{gs.turn}" if gs.turn else "")

        # 手牌
        self._upd_hand(gs)

        # 卡组
        self._upd_deck(gs)

        # 底部
        if gs.archetype_name:
            conf = f" ({gs.archetype_confidence:.0%})" if gs.archetype_confidence>0 else ""
            self._arch_lbl.setText(f"{gs.archetype_name}{conf}")
        else:
            self._arch_lbl.setText("推断中…")

        # 重绘
        self._deck_title.update()
        self._footer.update()

    # ── 鼠标事件 ───────────────────────────────────────────

    def set_interactive(self, on: bool):
        self._interactive = on
        for w in [self._hand_sec, self._deck_sec, self._footer]:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, not on)

    def mousePressEvent(self, e):
        if not self._interactive: return
        if e.button()==Qt.LeftButton:
            self._drag_start = e.globalPos()
            self._drag_off = self.pos() - e.globalPos()

    def mouseMoveEvent(self, e):
        if self._drag_start is not None and e.buttons()&Qt.LeftButton:
            self.move(e.globalPos()+self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_start = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen); p.setBrush(QBrush(_BG))
        p.drawRoundedRect(r, 5,5)
        p.setPen(QPen(_BORDER, 0.8)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0,0,-1,-1), 5,5)

        # 缩放手柄
        gx, gy = r.right()-4, r.bottom()-4
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(100,105,125,120)))
        for dy in range(0,7,3):
            for dx in range(0,7,3):
                if dx+dy>=3: p.drawEllipse(gx-dx-2, gy-dy-2,2,2)
        p.end()

    # ── 标题自绘 ───────────────────────────────────────────

    def _deck_title_paintEvent(self, _):
        p = QPainter(self._deck_title)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._deck_title.width(), self._deck_title.height()
        p.setPen(QPen(_TEXT_DIM))
        p.setFont(QFont("Microsoft YaHei",8))
        p.drawText(QRect(4,0,60,h), Qt.AlignVCenter, "对手卡组")
        rem = getattr(self,'_deck_remaining',0)
        total = getattr(self,'_deck_total',30)
        p.setPen(QPen(_TEXT_ACC if rem>0 else _TEXT_DIM))
        p.setFont(QFont("Arial",8))
        p.drawText(QRect(w-50,0,46,h), Qt.AlignVCenter|Qt.AlignRight, f"{rem}/{total}")
        p.end()

    def _footer_paintEvent(self, _):
        p = QPainter(self._footer)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._footer.width(), self._footer.height()
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(26,29,40,230)))
        p.drawRoundedRect(0,0,w,h,3,3)
        p.end()

    # ── 事件过滤 ───────────────────────────────────────────

    def eventFilter(self, obj, event):
        t = event.type()
        if t == event.Paint:
            if obj is self._deck_title: self._deck_title_paintEvent(event)
            elif obj is self._footer: self._footer_paintEvent(event)
        return super().eventFilter(obj, event)

    def showEvent(self, e):
        super().showEvent(e)
        self._deck_title.installEventFilter(self)
        self._footer.installEventFilter(self)

    def hideEvent(self, e):
        self._deck_title.removeEventFilter(self)
        self._footer.removeEventFilter(self)
        super().hideEvent(e)
