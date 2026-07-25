"""数据管理页：数据导出 / 本地备份恢复 / 远程 MySQL 备份恢复与迁移。

三个功能区：
    1. 数据导出   —— 勾选核心业务表，导出 CSV（Excel 可开）/ JSON，或整库打包 ZIP；
    2. 本地备份   —— 一键把整个 SQLite 库备份为 .db 文件；从备份文件覆盖恢复；
    3. 远程 MySQL —— 备份本地库到远程 MySQL；从 MySQL 恢复/迁移历史数据到本地。

所有耗时操作走后台线程（Worker），进度通过信号回显到页面日志区；
恢复类操作（覆盖本地数据）一律先弹窗确认 + 自动生成安全备份。
"""
from __future__ import annotations

import datetime as dt
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from .pages import BasePage
from ..storage import data_transfer as dtf


class DataPage(BasePage):
    """数据管理（导出 / 备份 / 恢复 / MySQL 迁移）。"""

    # 后台线程 → UI 的进度消息（跨线程安全）
    progress = pyqtSignal(str)

    def __init__(self, mdm, store, config=None, session=None) -> None:
        super().__init__(mdm, store, config, session)
        self._busy = False
        self._build()
        self.progress.connect(self._append_log)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        title = QLabel("数据管理")
        f = title.font()
        f.setPointSize(15)
        f.setBold(True)
        title.setFont(f)
        sub = QLabel("数据导出 · 本地备份恢复 · 远程 MySQL 备份 / 迁移　（本地库："
                     + self.store.path + "）")
        sub.setObjectName("sub")
        outer.addWidget(title)
        outer.addWidget(sub)

        # 主体滚动区（小屏防挤压）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(12)

        lay.addWidget(self._build_export_card())
        lay.addWidget(self._build_local_backup_card())
        lay.addWidget(self._build_mysql_card())

        # 操作日志
        log_card, log_lay = self._card("操作日志")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(140)
        log_lay.addWidget(self.log_view)
        lay.addWidget(log_card)

        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("toolbar")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)
        lab = QLabel(title)
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
        v.addWidget(lab)
        return card, v

    # ---- ① 数据导出 ----
    def _build_export_card(self) -> QFrame:
        card, v = self._card("① 数据导出")
        tip = QLabel("导出数据库中的核心业务数据；CSV 可直接用 Excel 打开。")
        tip.setObjectName("sub")
        v.addWidget(tip)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        self._tbl_checks: dict[str, QCheckBox] = {}
        for i, t in enumerate(dtf.CORE_TABLES):
            cb = QCheckBox(f"{dtf.TABLE_LABELS.get(t, t)} ({t})")
            cb.setChecked(True)
            self._tbl_checks[t] = cb
            grid.addWidget(cb, i // 4, i % 4)
        v.addLayout(grid)

        row = QHBoxLayout()
        row.addWidget(QLabel("格式："))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["CSV（Excel 可打开）", "JSON"])
        self.fmt_combo.setFixedWidth(180)
        row.addWidget(self.fmt_combo)
        row.addStretch(1)
        self.btn_export = QPushButton("导出到文件夹…")
        self.btn_export.clicked.connect(self._do_export)
        self.btn_export_zip = QPushButton("打包导出 ZIP…")
        self.btn_export_zip.setObjectName("secondary")
        self.btn_export_zip.clicked.connect(self._do_export_zip)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_export_zip)
        v.addLayout(row)
        return card

    # ---- ② 本地备份 ----
    def _build_local_backup_card(self) -> QFrame:
        card, v = self._card("② 本地备份 / 恢复")
        tip = QLabel("将整个数据库备份为单个 .db 文件；恢复时自动先生成安全备份，可回退。")
        tip.setObjectName("sub")
        v.addWidget(tip)

        row = QHBoxLayout()
        self.btn_backup_file = QPushButton("备份数据库到文件…")
        self.btn_backup_file.clicked.connect(self._do_backup_file)
        self.btn_restore_file = QPushButton("从备份文件恢复…")
        self.btn_restore_file.setObjectName("danger")
        self.btn_restore_file.clicked.connect(self._do_restore_file)
        row.addWidget(self.btn_backup_file)
        row.addWidget(self.btn_restore_file)
        row.addStretch(1)
        v.addLayout(row)
        return card

    # ---- ③ 远程 MySQL ----
    def _build_mysql_card(self) -> QFrame:
        card, v = self._card("③ 远程 MySQL 备份 / 迁移")
        tip = QLabel("可选功能：将本地数据备份到远程 MySQL 服务器；或把旧版 MySQL "
                     "中的历史数据迁移 / 恢复到本地（覆盖前自动安全备份）。需已安装 pymysql。")
        tip.setObjectName("sub")
        tip.setWordWrap(True)
        v.addWidget(tip)

        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        cfg = (lambda k, d: self.config.get(f"backup.mysql.{k}", d)) \
            if self.config else (lambda _k, d: d)

        self.my_host = QLineEdit(str(cfg("host", "127.0.0.1")))
        self.my_port = QSpinBox()
        self.my_port.setRange(1, 65535)
        self.my_port.setValue(int(cfg("port", 3306)))
        self.my_db = QLineEdit(str(cfg("db", "quantvortex")))
        self.my_user = QLineEdit(str(cfg("user", "root")))
        self.my_pwd = QLineEdit(str(cfg("password", "")))
        self.my_pwd.setEchoMode(QLineEdit.EchoMode.Password)

        for i, (lab, w) in enumerate((("主机", self.my_host), ("端口", self.my_port),
                                      ("数据库", self.my_db), ("用户名", self.my_user),
                                      ("密码", self.my_pwd))):
            g.addWidget(QLabel(lab), 0, i * 2)
            g.addWidget(w, 0, i * 2 + 1)
        g.setColumnStretch(1, 2)
        g.setColumnStretch(5, 1)
        g.setColumnStretch(7, 1)
        g.setColumnStretch(9, 1)
        v.addLayout(g)

        row = QHBoxLayout()
        self.btn_my_test = QPushButton("测试连接")
        self.btn_my_test.setObjectName("secondary")
        self.btn_my_test.clicked.connect(self._do_mysql_test)
        self.btn_my_backup = QPushButton("备份到 MySQL")
        self.btn_my_backup.clicked.connect(self._do_mysql_backup)
        self.btn_my_restore = QPushButton("从 MySQL 迁移 / 恢复到本地")
        self.btn_my_restore.setObjectName("danger")
        self.btn_my_restore.clicked.connect(self._do_mysql_restore)
        row.addWidget(self.btn_my_test)
        row.addWidget(self.btn_my_backup)
        row.addWidget(self.btn_my_restore)
        row.addStretch(1)
        v.addLayout(row)
        return card

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------
    def _append_log(self, msg: str) -> None:
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{ts}] {msg}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for b in (self.btn_export, self.btn_export_zip, self.btn_backup_file,
                  self.btn_restore_file, self.btn_my_test, self.btn_my_backup,
                  self.btn_my_restore):
            b.setEnabled(not busy)

    def _guard(self) -> bool:
        if self._busy:
            QMessageBox.information(self, "请稍候", "上一个数据操作尚未完成。")
            return False
        return True

    def _mysql_params(self) -> tuple:
        p = (self.my_host.text().strip(), int(self.my_port.value()),
             self.my_db.text().strip(), self.my_user.text().strip(),
             self.my_pwd.text())
        # 记住连接参数（含密码，仅存本机用户配置）
        if self.config:
            for k, val in zip(("host", "port", "db", "user", "password"), p):
                self.config.set(f"backup.mysql.{k}", val)
            self.config.save()
        return p

    def _run(self, fn, done_msg: str, refresh_hint: bool = False) -> None:
        """后台执行 fn()，完成/失败回显日志与弹窗。"""
        self._set_busy(True)

        def on_done(result):
            self._set_busy(False)
            self._append_log(done_msg)
            detail = self._format_report(result)
            hint = ("\n\n注意：本地数据已被覆盖，建议重启程序以刷新各页面显示。"
                    if refresh_hint else "")
            QMessageBox.information(self, "完成", done_msg +
                                    (("\n\n" + detail) if detail else "") + hint)
            try:
                self.store.add_log(str(dt.datetime.now()), "INFO", done_msg)
            except Exception:
                pass

        def on_err(err: str):
            self._set_busy(False)
            self._append_log(f"失败：{err}")
            QMessageBox.critical(self, "操作失败", str(err))

        self._run_worker(fn, on_done, on_err)

    @staticmethod
    def _format_report(result) -> str:
        if isinstance(result, dict):
            lines = []
            for t, v in result.items():
                label = dtf.TABLE_LABELS.get(t, t)
                if isinstance(v, dict):
                    n = v.get("rows", 0)
                    ok = "✓" if v.get("verified") else "✗"
                    lines.append(f"{label}：{n} 行 {ok}")
                else:
                    lines.append(f"{label}：{v} 行")
            return "\n".join(lines)
        if isinstance(result, str):
            return result
        return ""

    # ------------------------------------------------------------------
    # ① 导出
    # ------------------------------------------------------------------
    def _sel_tables(self) -> list[str]:
        return [t for t, cb in self._tbl_checks.items() if cb.isChecked()]

    def _fmt(self) -> str:
        return "json" if self.fmt_combo.currentIndex() == 1 else "csv"

    def _do_export(self) -> None:
        if not self._guard():
            return
        tables = self._sel_tables()
        if not tables:
            QMessageBox.warning(self, "提示", "请至少勾选一个要导出的数据表。")
            return
        out = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out:
            return
        fmt = self._fmt()
        self._append_log(f"开始导出 {len(tables)} 张表 → {out}")
        self._run(lambda: dtf.export_tables(self.store.conn, out, tables, fmt,
                                            progress=self.progress.emit),
                  f"数据导出完成（{out}）")

    def _do_export_zip(self) -> None:
        if not self._guard():
            return
        out = QFileDialog.getExistingDirectory(self, "选择 ZIP 保存目录")
        if not out:
            return
        fmt = self._fmt()
        self._append_log(f"开始打包导出全部核心数据 → {out}")
        self._run(lambda: dtf.export_all_zip(self.store.conn, out, fmt,
                                             progress=self.progress.emit),
                  "打包导出完成")

    # ------------------------------------------------------------------
    # ② 本地备份 / 恢复
    # ------------------------------------------------------------------
    def _do_backup_file(self) -> None:
        if not self._guard():
            return
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "备份数据库到文件", f"quantvortex_backup_{stamp}.db",
            "SQLite 数据库 (*.db)")
        if not path:
            return
        self._append_log(f"开始备份数据库 → {path}")
        self._run(lambda: dtf.backup_to_file(self.store.conn, path,
                                             progress=self.progress.emit),
                  f"数据库备份完成（{path}）")

    def _do_restore_file(self) -> None:
        if not self._guard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "", "SQLite 数据库 (*.db);;所有文件 (*)")
        if not path:
            return
        if QMessageBox.question(
                self, "确认恢复",
                "恢复将用备份文件【整库覆盖】当前数据！\n\n"
                "当前数据会先自动备份为 *.pre_restore.db，可回退。\n是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._append_log(f"开始从备份恢复 ← {path}")
        self._run(lambda: dtf.restore_from_file(self.store.conn, path,
                                                self.store.path,
                                                progress=self.progress.emit),
                  "数据恢复完成", refresh_hint=True)

    # ------------------------------------------------------------------
    # ③ 远程 MySQL
    # ------------------------------------------------------------------
    def _do_mysql_test(self) -> None:
        if not self._guard():
            return
        host, port, db, user, pwd = self._mysql_params()

        def _test():
            conn = dtf._mysql_connect(host, port, db, user, pwd, create_db=True)
            conn.close()
            return f"连接成功：{host}:{port}/{db}"

        self._append_log(f"测试 MySQL 连接 {host}:{port}/{db} …")
        self._run(_test, "MySQL 连接测试通过")

    def _do_mysql_backup(self) -> None:
        if not self._guard():
            return
        host, port, db, user, pwd = self._mysql_params()
        if QMessageBox.question(
                self, "确认备份",
                f"将把本地全部核心数据【全量覆盖】上传到\n"
                f"MySQL {host}:{port}/{db}（远端同名表会被重建）。\n是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._append_log(f"开始备份到 MySQL {host}:{port}/{db} …")
        self._run(lambda: dtf.backup_to_mysql(self.store.conn, host, port, db,
                                              user, pwd,
                                              progress=self.progress.emit),
                  "备份到 MySQL 完成")

    def _do_mysql_restore(self) -> None:
        if not self._guard():
            return
        host, port, db, user, pwd = self._mysql_params()
        if QMessageBox.question(
                self, "确认迁移 / 恢复",
                f"将从 MySQL {host}:{port}/{db} 拉取全部表数据，\n"
                "并【整库覆盖】本地数据（旧版 MySQL 用户迁移历史数据也用此功能）。\n\n"
                "当前本地数据会先自动备份为 *.pre_restore.db。\n是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._append_log(f"开始从 MySQL {host}:{port}/{db} 迁移 / 恢复 …")
        self._run(lambda: dtf.restore_from_mysql(self.store.conn, host, port,
                                                 db, user, pwd, self.store.path,
                                                 progress=self.progress.emit),
                  "从 MySQL 迁移 / 恢复完成", refresh_hint=True)
