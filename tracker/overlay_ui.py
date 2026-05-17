# -*- coding: utf-8 -*-
"""overlay_ui.py — 主叠加窗口 (PyQt5)

浮在炉石窗口上方的半透明叠加 UI。
可拖动标题栏移动，内容区域点击穿透到游戏。
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QApplication, QSizeGrip,
)
from PyQt5.QtCore import (
    Qt, QPoint, QTimer, pyqtSignal, QSize, QRect,
)
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QFontMetrics,
)

from tracker.game_state import CompleteGameState
from tracker.hand_predictor import HandPrediction, DeckPrediction
from tracker.card_images import CardImageManager

logger = logging.getLogger(__name__)

# ── 颜色 ────────────────────────────────────────────────────────

_BG = QColor(16, 18, 26, 210)
_BORDER = QColor(50, 55, 70, 160)
_HEADER_BG = QColor(26, 29, 40, 230)
_SECTION_BG = QColor(22, 25, 35, 170)
_TEXT = QColor(220, 225, 235)
_TEXT_DIM = QColor(130, 135, 155)
_TEXT_ACCENT = QColor(80, 190, 255)
_COLORS = [QColor(180,180,180),QColor(200,200,200),QColor(170,210,255),
           QColor(100,180,255),QColor(80,160,230),QColor(255,200,80),
           QColor(255,170,50),QColor(255,120,50),QColor(255,80,80),
           QColor(220,60,120),QColor(180,80,220)]
_CLASS_ICONS = {"WARRIOR":"⚔","SHAMAN":"⚡","ROGUE":"🗡","PALADIN":"🛡",
                "HUNTER":"🏹","WARLOCK":"😈","MAGE":"🔮","PRIEST":"✝",
                "DRUID":"🌿","DEMONHUNTER":"👁","DEATHKNIGHT":"💀","UNKNOWN":"?"}

def _c(c): return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f})"
def _cost_col(c): return _COLORS[min(c, len(_COLORS)-1)]

# ── 卡组条目 ────────────────────────────────────────────────────

class CardDeckEntry(QWidget):
    def __init__(self, card: dict, parent=None):
        super().__init__(parent)
        self._c = card
        self.setFixedHeight(22)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._c
        cost, name = c.get("cost", 0), c.get("name", "???")
        qty, rem = c.get("quantity", 1), c.get("remaining", 1)
        played, in_hand = c.get("played", False), c.get("in_hand", False)
        hp = c.get("hand_probability", 0.0)
        w, h = self.width(), self.height()

        bg = QColor(40,60,80,130) if in_hand else QColor(30,30,35,80) if played else QColor(25,28,38,60)
        p.fillRect(0, 0, w, h, bg)

        # 费用
        cc = _cost_col(cost)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(cc))
        p.drawEllipse(4, h//2-7, 14, 14)
        p.setPen(QPen(QColor(0,0,0)))
        ft = QFont("Arial", 7, QFont.Bold); p.setFont(ft)
        p.drawText(QRect(4, h//2-7, 14, 14), Qt.AlignCenter, str(cost) if cost<=10 else "10+")

        # 名称
        p.setPen(QPen(_TEXT if not played else _TEXT_DIM))
        ft = QFont("Microsoft YaHei", 8); p.setFont(ft)
        nw = w - 80
        dn = name[:14]+"…" if len(name)>14 else name
        p.drawText(QRect(22, 0, nw, h), Qt.AlignVCenter|Qt.AlignLeft, dn)
        if played:
            fm = QFontMetrics(ft); tw = fm.horizontalAdvance(dn)
            p.setPen(QPen(QColor(200,80,80,160), 1))
            p.drawLine(22, h//2, 22+min(tw,nw), h//2)

        # 统计
        pc = qty - rem
        info = f"{pc}/{qty}"
        if rem > 0: info += f" 剩{rem}"
        if hp > 0.05: info += f" {hp:.0%}"
        p.setPen(QPen(_TEXT_ACCENT if rem>0 else _TEXT_DIM))
        ft = QFont("Arial", 7); p.setFont(ft)
        p.drawText(QRect(w-76, 0, 72, h), Qt.AlignVCenter|Qt.AlignRight, info)
        p.end()

    def update_card(self, card):
        self._c = card; self.update()

# ── 主窗口 ──────────────────────────────────────────────────────

class OverlayWindow(QWidget):
    toggle_mode = pyqtSignal()

    def __init__(self, image_manager=None, parent=None):
        super().__init__(parent)
        self._img_mgr = image_manager or CardImageManager()
        self._gs = CompleteGameState()
        self._compact = False
        self._drag_start = None
        self._drag_off = QPoint(0, 0)
        self._deck_entries = []
        self._sel_arch = 0
        self._deck_exp = False

        self._setup_window()
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.setInterval(100)

    def _setup_window(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.setGeometry(g.right() - 300, g.top() + 80, 280, 500)

    def _section(self, color=QColor(40,45,60,80)) -> QFrame:
        f = QFrame()
        f.setStyleSheet(f"background:{_c(_SECTION_BG)};border-radius:4px;border-left:2px solid {_c(color)};")
        return f

    def _sec_layout(self, sec):
        l = QVBoxLayout(sec); l.setContentsMargins(6,4,6,4); l.setSpacing(2)
        return l

    def _mkfont(self, family, size, bold=False):
        return QFont(family, size, QFont.Bold if bold else QFont.Normal)

    def _build_ui(self):
        m = QVBoxLayout(self)
        m.setContentsMargins(4, 4, 4, 4)
        m.setSpacing(3)

        # ── 标题栏（可拖动/交互） ──
        hdr = QFrame()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(f"background:{_c(_HEADER_BG)};border-radius:4px;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(8,2,6,2); hl.setSpacing(4)

        self._cls_icon = QLabel("?")
        self._cls_icon.setFixedSize(20,20); self._cls_icon.setAlignment(Qt.AlignCenter)
        self._cls_icon.setFont(self._mkfont("Arial",12)); self._cls_icon.setStyleSheet("color:white;")
        hl.addWidget(self._cls_icon)

        self._cls_name = QLabel("等待对战")
        self._cls_name.setStyleSheet(f"color:{_c(_TEXT)};font-weight:bold;")
        self._cls_name.setFont(self._mkfont("Microsoft YaHei", 9, True))
        hl.addWidget(self._cls_name)

        hl.addStretch()
        self._turn_lbl = QLabel("")
        self._turn_lbl.setStyleSheet(f"color:{_c(_TEXT_ACCENT)};")
        self._turn_lbl.setFont(self._mkfont("Microsoft YaHei", 8))
        hl.addWidget(self._turn_lbl)

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(18,18)
        self._close_btn.setStyleSheet("QPushButton{background:transparent;color:#a55;border:none;font-size:13px;}QPushButton:hover{color:#f77;}")
        self._close_btn.clicked.connect(self.hide)
        hl.addWidget(self._close_btn)

        m.addWidget(hdr)

        # ── 手牌区（内容透传） ──
        self._hand_sec = self._section(QColor(60,180,100,100))
        m.addWidget(self._hand_sec)
        self._rebuild_hand()

        # ── 卡组区（按钮交互，列表透传） ──
        self._deck_sec = self._section(QColor(80,160,255,100))
        m.addWidget(self._deck_sec, stretch=1)
        self._rebuild_deck()

        # ── 底部 ──
        self._foot = QFrame()
        self._foot.setFixedHeight(22)
        self._foot.setStyleSheet(f"background:{_c(_HEADER_BG)};border-radius:4px;")
        fl = QHBoxLayout(self._foot); fl.setContentsMargins(8,2,8,2)
        self._arch_lbl = QLabel("")
        self._arch_lbl.setStyleSheet(f"color:{_c(_TEXT_ACCENT)};")
        self._arch_lbl.setFont(self._mkfont("Microsoft YaHei", 8))
        fl.addWidget(self._arch_lbl)
        m.addWidget(self._foot)

        # 调整大小手柄（交互）
        grip = QSizeGrip(self)
        grip.setStyleSheet("QSizeGrip{background:transparent;width:10px;height:10px;}")

    # ── 手牌区 ──────────────────────────────────────────────────

    def _rebuild_hand(self):
        """重建手牌区布局。"""
        lay = self._sec_layout(self._hand_sec) if not hasattr(self,'_hand_lay') else self._hand_sec.layout()
        # 清除旧内容
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()

        self._hdr_lbl = QLabel("手牌")
        self._hdr_lbl.setStyleSheet(f"color:{_c(_TEXT_DIM)};font-size:9px;")
        self._hdr_lbl.setFont(self._mkfont("Microsoft YaHei", 8))
        self._hdr_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._hdr_lbl)

        self._rev_lbl = QLabel("")
        self._rev_lbl.setStyleSheet(f"color:{_c(QColor(60,220,100))};font-size:9px;"); self._rev_lbl.setWordWrap(True)
        self._rev_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._rev_lbl)

        self._prob_lbl = QLabel("")
        self._prob_lbl.setStyleSheet(f"color:{_c(_TEXT)};font-size:9px;"); self._prob_lbl.setWordWrap(True)
        self._prob_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._prob_lbl)

        self._deckp_lbl = QLabel("")
        self._deckp_lbl.setStyleSheet(f"color:{_c(_TEXT_DIM)};font-size:8px;"); self._deckp_lbl.setWordWrap(True)
        self._deckp_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._deckp_lbl)

        self._played_d_lbl = QLabel("")
        self._played_d_lbl.setStyleSheet(f"color:{_c(QColor(200,150,100))};font-size:8px;"); self._played_d_lbl.setWordWrap(True)
        self._played_d_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._played_d_lbl)

        self._played_g_lbl = QLabel("")
        self._played_g_lbl.setStyleSheet(f"color:{_c(QColor(150,100,200))};font-size:8px;"); self._played_g_lbl.setWordWrap(True)
        self._played_g_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._played_g_lbl)

    def _upd_hand(self, gs):
        self._g(gs)

    def _g(self, gs):
        hp = gs.hand_predictions
        dp = gs.deck_predictions
        hc = gs.opponent.hand_count

        rev = [h for h in hp if h.get("source")=="revealed"]
        prob = [h for h in hp if h.get("source")!="revealed" and h.get("source")!="unknown" and h.get("probability",0)>0]
        unk = [h for h in hp if h.get("source")=="unknown" or (h.get("source")!="revealed" and h.get("probability",0)<=0)]

        self._hdr_lbl.setText(f"手牌 {len(rev)}已确 {len(prob)}可能 {len(unk)}未知")

        if rev:
            parts = [f"[{h.get('cost',0)}]{h.get('name','?')}" for h in rev[:5]]
            self._rev_lbl.setText("✓ " + " ".join(parts))
        else: self._rev_lbl.setText("")

        if prob:
            parts = [f"[{h.get('cost',0)}]{h.get('name','?')}{h.get('probability',0):.0%}" for h in prob[:6]]
            self._prob_lbl.setText("▸ " + " ".join(parts))
        else: self._prob_lbl.setText("")

        dr = [d for d in dp if d.get("remaining",0)>0 and not d.get("in_hand") and not d.get("played")]
        dr.sort(key=lambda d: d.get("hand_probability",0), reverse=True)
        if dr:
            parts = [f"[{d.get('cost',0)}]{d.get('name','?')}{d.get('hand_probability',0):.0%}" for d in dr[:5]]
            if len(dr)>5: parts.append(f"+{len(dr)-5}")
            self._deckp_lbl.setText("▸ " + " ".join(parts))
        else: self._deckp_lbl.setText("")

        pd = [d for d in dp if d.get("played") and d.get("source")=="deck"]
        if pd:
            parts = [f"[{d.get('cost',0)}]{d.get('name','?')}" for d in pd[:5]]
            if len(pd)>5: parts.append(f"+{len(pd)-5}")
            self._played_d_lbl.setText("▸ " + " ".join(parts))
        else: self._played_d_lbl.setText("")

        pg = [d for d in dp if d.get("played") and d.get("source")=="generated"]
        if pg:
            parts = [f"[{d.get('cost',0)}]{d.get('name','?')}" for d in pg[:5]]
            if len(pg)>5: parts.append(f"+{len(pg)-5}")
            self._played_g_lbl.setText("▸ " + " ".join(parts))
        else: self._played_g_lbl.setText("")

    # ── 卡组区 ──────────────────────────────────────────────────

    def _rebuild_deck(self):
        lay = self._sec_layout(self._deck_sec) if not hasattr(self,'_deck_lay') else self._deck_sec.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()

        # 第一行：标题 + 计数 + 展开
        r1 = QHBoxLayout(); r1.setSpacing(4)
        t = QLabel("卡组"); t.setStyleSheet(f"color:{_c(_TEXT_DIM)};font-size:9px;")
        t.setFont(self._mkfont("Microsoft YaHei",8))
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        r1.addWidget(t)
        r1.addStretch()
        self._cnt_lbl = QLabel("")
        self._cnt_lbl.setStyleSheet(f"color:{_c(_TEXT_DIM)};font-size:9px;")
        self._cnt_lbl.setFont(self._mkfont("Microsoft YaHei",8))
        self._cnt_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        r1.addWidget(self._cnt_lbl)
        self._exp_btn = QPushButton("▼")
        self._exp_btn.setFixedSize(16,16)
        self._exp_btn.setStyleSheet("QPushButton{background:transparent;color:#888;border:none;font-size:9px;}QPushButton:hover{color:white;}")
        self._exp_btn.clicked.connect(self._tog_exp)
        r1.addWidget(self._exp_btn)
        lay.addLayout(r1)

        # 卡组标签（交互按钮）
        self._arch_tabs = QHBoxLayout(); self._arch_tabs.setSpacing(2)
        self._arch_btns = []
        lay.addLayout(self._arch_tabs)

        # 卡组名
        self._arch_nm = QLabel("")
        self._arch_nm.setStyleSheet(f"color:{_c(_TEXT_ACCENT)};font-size:8px;")
        self._arch_nm.setFont(self._mkfont("Microsoft YaHei",7))
        self._arch_nm.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._arch_nm)

        # 滚动区
        self._sc = QScrollArea()
        self._sc.setWidgetResizable(True)
        self._sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._sc.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._dc = QWidget(); self._dc.setStyleSheet("background:transparent;")
        self._dc.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._dl = QVBoxLayout(self._dc); self._dl.setContentsMargins(0,0,0,0); self._dl.setSpacing(1); self._dl.addStretch()
        self._sc.setWidget(self._dc)
        lay.addWidget(self._sc, stretch=1)

        self._deck_exp = False
        self._upd_exp()

    def _tog_exp(self):
        self._deck_exp = not self._deck_exp
        self._upd_exp()

    def _upd_exp(self):
        self._exp_btn.setText("▲" if self._deck_exp else "▼")
        self._sc.setFixedHeight(400 if self._deck_exp else 60)

    def _sw_arch(self, idx):
        self._sel_arch = idx
        self._upd_deck(self._gs)

    def _upd_deck(self, gs):
        self._gs = gs

        # 清除旧条目
        for w in self._deck_entries:
            self._dl.removeWidget(w); w.deleteLater()
        self._deck_entries.clear()
        for btn in self._arch_btns:
            self._arch_tabs.removeWidget(btn); btn.deleteLater()
        self._arch_btns.clear()

        multi = gs.multi_deck_predictions
        if multi:
            for i, md in enumerate(multi):
                nm = md.get("archetype_name","未知"); pb = md.get("probability",0)
                btn = QPushButton(f"{nm} {pb:.0%}")
                btn.setFixedHeight(18); btn.setFont(self._mkfont("Microsoft YaHei",7))
                act = i==self._sel_arch
                btn.setStyleSheet(
                    "QPushButton{background:"+("rgba(80,160,255,140)" if act else "rgba(60,65,80,150)")+
                    ";color:"+("white" if act else "#aaa")+";border:none;border-radius:3px;padding:0 4px;}"+
                    "QPushButton:hover{background:rgba(80,90,120,180);color:white;}")
                btn.clicked.connect(lambda _,x=i: self._sw_arch(x))
                self._arch_tabs.addWidget(btn); self._arch_btns.append(btn)

            sel = multi[self._sel_arch] if self._sel_arch<len(multi) else multi[0]
            cards = sel.get("cards",[])
            for c in cards:
                e = CardDeckEntry(c); e.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._dl.insertWidget(self._dl.count()-1, e)
                self._deck_entries.append(e)
            rem = sum(c.get("remaining",0) for c in cards)
            total = gs.opponent.initial_deck_size or 30
            self._cnt_lbl.setText(f"{rem}/{total}")
            self._arch_nm.setText(f"{sel.get('archetype_name','')} ({sel.get('probability',0):.0%})")
        else:
            self._cnt_lbl.setText("")
            self._arch_nm.setText("")
            for c in gs.deck_predictions:
                e = CardDeckEntry(c); e.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._dl.insertWidget(self._dl.count()-1, e)
                self._deck_entries.append(e)
            rem = sum(c.get("remaining",0) for c in gs.deck_predictions)
            total = gs.opponent.initial_deck_size or 30
            self._cnt_lbl.setText(f"{rem}/{total}")

    # ── 公开接口 ───────────────────────────────────────────────

    def update_state(self, gs):
        self._gs = gs

    def start_refresh(self):
        self._timer.start()

    def stop_refresh(self):
        self._timer.stop()

    def _refresh(self):
        gs = self._gs

        cls_en = getattr(gs.opponent.hero, 'hero_class_en', gs.opponent.hero.hero_class)
        self._cls_icon.setText(_CLASS_ICONS.get(cls_en, "?"))
        self._cls_name.setText(gs.opponent.hero.hero_class_cn or "未知")
        self._turn_lbl.setText(f"T{gs.turn}" if gs.turn else "")

        self._g(gs)
        self._upd_deck(gs)

        # 底部
        if gs.archetype_name:
            conf = f" ({gs.archetype_confidence:.0%})" if gs.archetype_confidence>0 else ""
            self._arch_lbl.setText(f"{gs.archetype_name}{conf}")
        else:
            self._arch_lbl.setText("推断中…")

    # ── 交互 ───────────────────────────────────────────────────

    def set_interactive(self, on):
        for w in [self._hand_sec, self._deck_sec, self._foot]:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, not on)
        for w in [self._close_btn]:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def mousePressEvent(self, e):
        if e.button()==Qt.LeftButton:
            self._drag_start = e.globalPos()
            self._drag_off = self.pos() - e.globalPos()

    def mouseMoveEvent(self, e):
        if self._drag_start is not None and e.buttons()&Qt.LeftButton:
            self.move(e.globalPos()+self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_start = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(_BG))
        p.drawRoundedRect(self.rect(), 8, 8)
        p.setPen(QPen(_BORDER, 1)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRect(0,0,self.width()-1,self.height()-1), 8, 8)
        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e); self.update()
