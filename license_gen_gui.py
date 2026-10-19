"""激活码生成器（图形界面版）—— 仅供作者本人使用，切勿随软件分发给买家！

四档套餐（与 activation.py 中的 PLANS 严格一致）：

    月版   30 天   ¥19    代码 M
    半年版 180 天  ¥68    代码 H
    年版   365 天  ¥90    代码 Y
    终身版 永久    ¥160   代码 L

两种码型：
    绑定码 —— 一码一机，必须填用户机器码，防盗版更强
    通用码 —— 不绑机器，可批量备货供平台自动发卡；有效期从买家首次激活当天起算

依赖 activation.py 中的 SECRET。改过 SECRET 后，之前发出的激活码全部失效。
"""

import os
import re
import sys
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import activation

PLAN_KEYS = ["M", "H", "Y", "L"]

STYLE = """
QWidget {
    background: #0f1115;
    color: #e6e8ec;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow { background: #0f1115; }

QLabel#Title {
    font-size: 17px; font-weight: 700; color: #ffffff; letter-spacing: 1px;
}
QLabel#Sub { color: #8b93a1; font-size: 12px; }
QLabel#Label { color: #9aa3b2; font-size: 12px; font-weight: 600; }
QLabel#Warn { color: #f0a45d; font-size: 11px; }

QFrame#Card {
    background: #161a21;
    border: 1px solid #252b36;
    border-radius: 8px;
}

QPushButton {
    background: #1d222c;
    border: 1px solid #2c3340;
    border-radius: 6px;
    padding: 8px 14px;
    color: #d6dae2;
}
QPushButton:hover { background: #252c38; border-color: #3a4250; }
QPushButton:pressed { background: #14181f; }

QPushButton#PlanBtn {
    padding: 10px 8px;
    font-size: 13px;
}
QPushButton#PlanBtn:checked {
    background: #1b3a5c;
    border: 1px solid #3b82f6;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#Primary {
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
    font-weight: 700;
    padding: 10px 18px;
}
QPushButton#Primary:hover { background: #1d4ed8; }
QPushButton#Primary:disabled {
    background: #262b34; border-color: #2c3340; color: #6b7280; font-weight: 400;
}

QLineEdit, QSpinBox {
    background: #0f1319;
    border: 1px solid #2c3340;
    border-radius: 6px;
    padding: 8px 10px;
    color: #e6e8ec;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QSpinBox:focus { border-color: #3b82f6; }
QLineEdit:disabled { background: #15181e; color: #5b6472; }

QPlainTextEdit {
    background: #0b0d11;
    border: 1px solid #2c3340;
    border-radius: 6px;
    color: #7ee2b8;
    font-family: Consolas, "Courier New", monospace;
    font-size: 13px;
    padding: 8px;
}
"""

MONO = "Consolas, 'Courier New', monospace"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("激活码生成器 · 抖音无水印解析器（作者专用）")
        self.setMinimumSize(760, 620)
        self.resize(820, 680)
        self.setStyleSheet(STYLE)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # ---------- 标题 ----------
        title = QLabel("激活码生成器")
        title.setObjectName("Title")
        layout.addWidget(title)

        sub = QLabel("四档套餐 · 支持绑定码与通用码 · 激活私钥来自 activation.py")
        sub.setObjectName("Sub")
        layout.addWidget(sub)

        # ---------- 套餐选择 ----------
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        lbl = QLabel("第一步 · 选择套餐")
        lbl.setObjectName("Label")
        card_layout.addWidget(lbl)

        plan_row = QHBoxLayout()
        plan_row.setSpacing(8)
        self.plan_group = QButtonGroup(self)
        self.plan_group.setExclusive(True)
        self.plan_buttons = {}
        for key in PLAN_KEYS:
            name, days, price = activation.PLANS[key]
            dur = "永久" if days is None else f"{days} 天"
            btn = QPushButton(f"{name}\n{price} · {dur}")
            btn.setObjectName("PlanBtn")
            btn.setCheckable(True)
            btn.setMinimumHeight(54)
            btn.clicked.connect(self._on_plan_changed)
            self.plan_group.addButton(btn)
            self.plan_buttons[key] = btn
            plan_row.addWidget(btn)
        self.plan_buttons["M"].setChecked(True)
        card_layout.addLayout(plan_row)

        # ---------- 码型选择 ----------
        kind_row = QHBoxLayout()
        kind_row.setSpacing(16)
        lbl2 = QLabel("第二步 · 码型")
        lbl2.setObjectName("Label")
        kind_row.addWidget(lbl2)

        self.kind_group = QButtonGroup(self)
        self.kind_group.setExclusive(True)
        self.rb_bind = QRadioButton("绑定码（一码一机）")
        self.rb_universal = QRadioButton("通用码（不绑机器，可批量备货）")
        self.rb_bind.setChecked(True)
        self.kind_group.addButton(self.rb_bind)
        self.kind_group.addButton(self.rb_universal)
        kind_row.addWidget(self.rb_bind)
        kind_row.addWidget(self.rb_universal)
        kind_row.addStretch()
        card_layout.addLayout(kind_row)

        # ---------- 机器码 ----------
        mid_row = QHBoxLayout()
        lbl3 = QLabel("机器码")
        lbl3.setObjectName("Label")
        mid_row.addWidget(lbl3)
        self.mid_edit = QLineEdit()
        self.mid_edit.setPlaceholderText("粘贴用户软件里显示的 16 位机器码")
        self.mid_edit.setEnabled(False)
        self.mid_edit.setClearButtonEnabled(True)
        self.mid_edit.setMinimumWidth(280)
        self.mid_edit.textChanged.connect(self._on_mid_changed)
        mid_row.addWidget(self.mid_edit, 1)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 5000)
        self.count_spin.setValue(100)
        self.count_spin.setSuffix(" 条")
        self.count_spin.setFixedWidth(110)
        mid_row.addWidget(self.count_spin)
        card_layout.addLayout(mid_row)

        self.mid_hint = QLabel("机器码为 16 位，复制时不要漏字符")
        self.mid_hint.setObjectName("Sub")
        card_layout.addWidget(self.mid_hint)

        layout.addWidget(card)

        # ---------- 结果 ----------
        res_head = QHBoxLayout()
        lbl4 = QLabel("生成结果")
        lbl4.setObjectName("Label")
        res_head.addWidget(lbl4)
        res_head.addStretch()

        self.btn_copy = QPushButton("复制选中")
        self.btn_save = QPushButton("保存到文件")
        self.btn_clear = QPushButton("清空")
        self.btn_copy.clicked.connect(self._copy_all)
        self.btn_save.clicked.connect(self._save)
        self.btn_clear.clicked.connect(lambda: self.output.clear())
        for b in (self.btn_copy, self.btn_save, self.btn_clear):
            res_head.addWidget(b)
        layout.addLayout(res_head)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("生成的激活码会显示在这里，一行一条")
        self.output.setFont(QFont("Consolas", 13))
        layout.addWidget(self.output, 1)

        # ---------- 底部操作 ----------
        bottom = QHBoxLayout()
        self.status = QLabel("就绪")
        self.status.setObjectName("Sub")
        bottom.addWidget(self.status, 1)
        self.btn_gen = QPushButton("生成激活码")
        self.btn_gen.setObjectName("Primary")
        self.btn_gen.setFixedWidth(180)
        self.btn_gen.clicked.connect(self._generate)
        bottom.addWidget(self.btn_gen)
        layout.addLayout(bottom)

        warn = QLabel("本工具含激活私钥，仅供作者本人使用，请勿打包进分发给买家的软件。")
        warn.setObjectName("Warn")
        layout.addWidget(warn)

        self.rb_bind.toggled.connect(self._on_kind_changed)
        self._on_kind_changed()
        self._on_plan_changed()

    # ---------------- 交互 ----------------
    def _current_plan(self) -> str:
        btn = self.plan_group.checkedButton()
        for key, b in self.plan_buttons.items():
            if b is btn:
                return key
        return "M"

    def _on_plan_changed(self):
        key = self._current_plan()
        name, days, price = activation.PLANS[key]
        dur = "永久有效" if days is None else f"{days} 天"
        self.status.setText(f"当前：{name} {price} · {dur}")

    def _on_kind_changed(self):
        bind = self.rb_bind.isChecked()
        self.mid_edit.setEnabled(bind)
        self.count_spin.setEnabled(not bind)
        self._update_mid_hint()

    def _on_mid_changed(self):
        """用户粘贴机器码时自动去掉横线、统一大写。"""
        txt = self.mid_edit.text()
        norm = re.sub(r"[^0-9A-Za-z]", "", txt).upper()
        if norm != txt:
            self.mid_edit.setText(norm)
        self._update_mid_hint()

    def _update_mid_hint(self):
        if not self.rb_bind.isChecked():
            self.mid_hint.setText("机器码为 16 位，复制时不要漏字符")
            self.mid_hint.setStyleSheet("")
            return
        n = len(self.mid_edit.text().strip())
        if n == 0:
            self.mid_hint.setText("机器码为 16 位，复制时不要漏字符")
            self.mid_hint.setStyleSheet("color: #8b93a1;")
        elif n < 16:
            self.mid_hint.setText(f"⚠ 当前只有 {n} 位，请补全到 16 位")
            self.mid_hint.setStyleSheet("color: #f0a45d;")
        else:
            self.mid_hint.setText(f"✓ 已输入 {n} 位，可以生成")
            self.mid_hint.setStyleSheet("color: #7ee2b8;")

    def _generate(self):
        plan = self._current_plan()
        universal = self.rb_universal.isChecked()
        name, days, price = activation.PLANS[plan]

        if universal:
            n = self.count_spin.value()
            codes = [activation.make_code(None, plan, universal=True) for _ in range(n)]
            if len(set(codes)) != len(codes):
                QMessageBox.warning(self, "异常", "生成了重复激活码，请重试")
                return
            self.output.setPlainText("\n".join(codes))
            self.status.setText(
                f"已生成 {n} 条【{name}】通用码（{price}），不绑机器，"
                f"有效期自买家首次激活起 {'永久' if days is None else str(days) + ' 天'}"
            )
            return

        mid = self.mid_edit.text().strip()
        if not mid:
            QMessageBox.warning(self, "缺少机器码", "绑定码必须填写用户的机器码。\n若无需绑定，请切换为「通用码」。")
            return
        if len(mid) < 16:
            QMessageBox.warning(
                self, "机器码不完整",
                f"当前机器码只有 {len(mid)} 位，用户软件里显示的机器码应为 16 位。\n"
                "请完整复制后再生成。"
            )
            return
        try:
            code = activation.make_code(mid, plan, universal=False)
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))
            return
        expiry = activation.expiry_of(mid, code)
        self.output.setPlainText(code)
        self._copy_to_clipboard(code)
        self.status.setText(f"已生成【{name}】绑定码（{price}），有效期至 {expiry}，已复制到剪贴板")

    def _copy_to_clipboard(self, text: str):
        try:
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _copy_all(self):
        text = self.output.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "无内容", "还没有生成任何激活码")
            return
        self._copy_to_clipboard(text)
        self.status.setText("已复制到剪贴板")

    def _save(self):
        text = self.output.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "无内容", "还没有生成任何激活码")
            return
        plan = self._current_plan()
        name = activation.PLANS[plan][0]
        stamp = datetime.now().strftime("%Y%m%d")
        default = os.path.join(os.getcwd(), f"卡密_{name}_{stamp}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存激活码", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.status.setText(f"已保存到 {path}")


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
