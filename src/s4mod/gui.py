from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .ai_bundle import ai_review_prompt, export_ai_check_bundle
from .backup import create_full_mods_backup, estimate_backup_bytes
from .executor import apply_plan
from .localization import Translator
from .models import (
    FileKind,
    FindingCode,
    ManifestStatus,
    PlanAction,
    RunManifest,
)
from .paths import build_workspace_paths, candidate_mods_paths, validate_mods_path
from .rollback import undo_run
from .workflow import DROP_EXTENSIONS, RunSession, create_plan_run

APP_STYLE = """
QMainWindow, QWidget#root { background: #F3F8F5; color: #17342D; }
QLabel#brand { color: #2F8F5B; font: 700 12px "Trebuchet MS"; letter-spacing: 2px; }
QLabel#title { font: 700 30px "Trebuchet MS"; color: #17342D; }
QLabel#subtitle { color: #63746F; font-size: 15px; }
QLabel#plumbob { color: #2F8F5B; font-size: 25px; }
QFrame#topRail { background: #FFFFFF; border-bottom: 1px solid #D9E7E0; }
QLabel[step="true"] { color: #83938E; font-weight: 600; padding: 6px 12px; }
QLabel[active="true"] { color: #17342D; background: #DDF2E6; border-radius: 13px; }
QLabel[done="true"] { color: #2F8F5B; }
QFrame#dropZone { background: #FFFFFF; border: 2px dashed #9BC8AE; border-radius: 16px; }
QFrame#dropZone[dragActive="true"] { background: #E4F6EB; border-color: #2F8F5B; }
QFrame#resultCard, QFrame#countCard, QFrame#completionCard {
  background: #FFFFFF; border: 1px solid #D9E7E0; border-radius: 14px;
}
QFrame#resultCard[safety="safe"] { border-top: 4px solid #2F8F5B; }
QFrame#resultCard[safety="consent"] { border-top: 4px solid #C98218; }
QFrame#resultCard[safety="hold"] { border-top: 4px solid #63746F; }
QPushButton { min-height: 38px; padding: 0 16px; border-radius: 9px; font-weight: 650; }
QPushButton[primary="true"] { background: #2F8F5B; color: white; border: 0; }
QPushButton[primary="true"]:hover { background: #267B4D; }
QPushButton[primary="true"]:disabled { background: #A9BDB3; }
QPushButton[secondary="true"] { background: #FFFFFF; color: #17342D; border: 1px solid #B8CEC3; }
QPushButton[danger="true"] { background: #FFF8EC; color: #7B4B07; border: 1px solid #E4BF82; }
QComboBox { min-height: 36px; padding: 0 10px; background: white; border: 1px solid #B8CEC3; border-radius: 8px; }
QListWidget { background: transparent; border: 0; color: #314B44; }
QTextEdit { background: #17342D; color: #DDF2E6; border: 0; border-radius: 9px; font-family: "SF Mono", Consolas, monospace; }
QToolButton { color: #526B64; border: 0; font-weight: 600; }
QCheckBox { spacing: 10px; font-size: 15px; }
"""


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


class DropZone(QFrame):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon = QLabel("◆")
        self.icon.setObjectName("plumbob")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.subtitle = QLabel()
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setStyleSheet("color: #63746F;")
        layout.addWidget(self.icon)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self.setProperty("dragActive", True)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.setProperty("dragActive", False)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("dragActive", False)
        self.style().polish(self)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()


class CallWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self.function = function

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.function())
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or error.__class__.__name__)


class ResultCard(QFrame):
    def __init__(self, safety: str) -> None:
        super().__init__()
        self.setObjectName("resultCard")
        self.setProperty("safety", safety)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 12)
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 17px; font-weight: 750;")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #63746F;")
        self.items = QListWidget()
        self.items.setMinimumHeight(150)
        self.items.setWordWrap(True)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.heading)
        layout.addWidget(self.hint)
        layout.addWidget(self.items)

    def set_items(self, items: list[str], empty_text: str) -> None:
        self.items.clear()
        self.items.addItems(items or [empty_text])


class MainWindow(QMainWindow):
    def __init__(self, *, auto_discover: bool = True) -> None:
        super().__init__()
        self.translator = Translator.load("en")
        self.mods_root: Path | None = None
        self.inbox_roots: list[Path] = []
        self.dropped_files: list[Path] = []
        self.session: RunSession | None = None
        self.manifest: RunManifest | None = None
        self._tasks: list[tuple[QThread, CallWorker]] = []
        self._build_ui()
        self._retranslate()
        if auto_discover:
            self._auto_discover()

    def _build_ui(self) -> None:
        self.resize(1040, 760)
        self.setMinimumSize(860, 650)
        self.setStyleSheet(APP_STYLE)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("topRail")
        rail_layout = QHBoxLayout(rail)
        rail_layout.setContentsMargins(28, 14, 28, 14)
        self.brand = QLabel()
        self.brand.setObjectName("brand")
        rail_layout.addWidget(self.brand)
        rail_layout.addStretch()
        self.step_labels = [QLabel() for _ in range(3)]
        for label in self.step_labels:
            label.setProperty("step", True)
            rail_layout.addWidget(label)
        outer.addWidget(rail)

        self.pages = QStackedWidget()
        self.pages.currentChanged.connect(self._update_steps)
        self.pages.addWidget(self._build_start_page())
        self.pages.addWidget(self._build_results_page())
        self.pages.addWidget(self._build_confirm_page())
        outer.addWidget(self.pages, 1)

        self.status = QLabel()
        self.status.setStyleSheet("padding: 9px 28px; color: #526B64; background: #E7F1EC;")
        outer.addWidget(self.status)

    def _page_shell(self) -> tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 30, 36, 34)
        layout.setSpacing(16)
        scroll.setWidget(content)
        return scroll, layout

    def _page_heading(self, layout: QVBoxLayout) -> tuple[QLabel, QLabel]:
        title = QLabel()
        title.setObjectName("title")
        subtitle = QLabel()
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return title, subtitle

    def _build_start_page(self) -> QWidget:
        page, layout = self._page_shell()
        self.start_title, self.start_subtitle = self._page_heading(layout)
        self.drop_zone = DropZone()
        self.drop_zone.paths_dropped.connect(self.accept_paths)
        layout.addWidget(self.drop_zone)

        selection = QFrame()
        selection.setObjectName("resultCard")
        selection_layout = QGridLayout(selection)
        selection_layout.setContentsMargins(18, 15, 18, 15)
        self.mods_label = QLabel()
        self.mods_label.setWordWrap(True)
        self.inbox_label = QLabel()
        self.inbox_label.setWordWrap(True)
        self.files_label = QLabel()
        self.choose_mods_button = QPushButton()
        self.choose_mods_button.setProperty("secondary", True)
        self.choose_mods_button.clicked.connect(self._choose_mods)
        self.choose_inbox_button = QPushButton()
        self.choose_inbox_button.setProperty("secondary", True)
        self.choose_inbox_button.clicked.connect(self._choose_inbox)
        selection_layout.addWidget(self.mods_label, 0, 0)
        selection_layout.addWidget(self.choose_mods_button, 0, 1)
        selection_layout.addWidget(self.inbox_label, 1, 0)
        selection_layout.addWidget(self.choose_inbox_button, 1, 1)
        selection_layout.addWidget(self.files_label, 2, 0, 1, 2)
        layout.addWidget(selection)

        controls = QHBoxLayout()
        self.interface_label = QLabel()
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("简体中文", "zh-CN")
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        self.folder_label = QLabel()
        self.profile_combo = QComboBox()
        controls.addWidget(self.interface_label)
        controls.addWidget(self.language_combo)
        controls.addSpacing(14)
        controls.addWidget(self.folder_label)
        controls.addWidget(self.profile_combo)
        controls.addStretch()
        layout.addLayout(controls)

        self.check_button = QPushButton()
        self.check_button.setProperty("primary", True)
        self.check_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.check_button.clicked.connect(self._check_mods)
        layout.addWidget(self.check_button)
        layout.addStretch()
        return page

    def _build_results_page(self) -> QWidget:
        page, layout = self._page_shell()
        self.results_title, self.results_subtitle = self._page_heading(layout)
        cards = QHBoxLayout()
        self.safe_card = ResultCard("safe")
        self.consent_card = ResultCard("consent")
        self.hold_card = ResultCard("hold")
        cards.addWidget(self.safe_card)
        cards.addWidget(self.consent_card)
        cards.addWidget(self.hold_card)
        layout.addLayout(cards)

        self.advanced_button = QToolButton()
        self.advanced_button.setCheckable(True)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        self.advanced_text = QTextEdit()
        self.advanced_text.setReadOnly(True)
        self.advanced_text.setMinimumHeight(180)
        self.advanced_text.hide()
        layout.addWidget(self.advanced_button)
        layout.addWidget(self.advanced_text)

        actions = QHBoxLayout()
        self.results_back = QPushButton()
        self.results_back.setProperty("secondary", True)
        self.results_back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.ai_help_button = QPushButton()
        self.ai_help_button.setProperty("secondary", True)
        self.ai_help_button.clicked.connect(self._copy_ai_prompt)
        self.ai_export_button = QPushButton()
        self.ai_export_button.setProperty("secondary", True)
        self.ai_export_button.clicked.connect(self._export_ai_bundle)
        self.review_button = QPushButton()
        self.review_button.setProperty("primary", True)
        self.review_button.clicked.connect(self._show_confirmation)
        actions.addWidget(self.results_back)
        actions.addWidget(self.ai_help_button)
        actions.addWidget(self.ai_export_button)
        actions.addStretch()
        actions.addWidget(self.review_button)
        layout.addLayout(actions)
        return page

    def _build_confirm_page(self) -> QWidget:
        page, layout = self._page_shell()
        self.confirm_title, self.confirm_subtitle = self._page_heading(layout)
        count_layout = QHBoxLayout()
        self.count_values: dict[PlanAction | str, QLabel] = {}
        for key in (PlanAction.INSTALL, PlanAction.REPLACE, PlanAction.BACKUP, "hold"):
            card = QFrame()
            card.setObjectName("countCard")
            card_layout = QVBoxLayout(card)
            label = QLabel()
            label.setProperty("countLabel", key.value if isinstance(key, PlanAction) else key)
            value = QLabel("0")
            value.setStyleSheet("font-size: 28px; font-weight: 750; color: #17342D;")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            count_layout.addWidget(card)
            self.count_values[key] = value
        layout.addLayout(count_layout)

        backup_card = QFrame()
        backup_card.setObjectName("resultCard")
        backup_layout = QVBoxLayout(backup_card)
        self.full_backup_check = QCheckBox()
        self.full_backup_space = QLabel()
        self.full_backup_note = QLabel()
        self.full_backup_note.setWordWrap(True)
        self.full_backup_note.setStyleSheet("color: #63746F;")
        backup_layout.addWidget(self.full_backup_check)
        backup_layout.addWidget(self.full_backup_space)
        backup_layout.addWidget(self.full_backup_note)
        layout.addWidget(backup_card)

        self.completion_card = QFrame()
        self.completion_card.setObjectName("completionCard")
        completion_layout = QVBoxLayout(self.completion_card)
        self.complete_title = QLabel()
        self.complete_title.setStyleSheet("font-size: 20px; font-weight: 750; color: #2F8F5B;")
        self.complete_subtitle = QLabel()
        self.complete_subtitle.setWordWrap(True)
        completion_layout.addWidget(self.complete_title)
        completion_layout.addWidget(self.complete_subtitle)
        result_buttons = QHBoxLayout()
        self.open_mods_button = QPushButton()
        self.view_result_button = QPushButton()
        self.open_backup_button = QPushButton()
        self.undo_button = QPushButton()
        self.undo_button.setProperty("danger", True)
        self.open_mods_button.clicked.connect(self._open_mods)
        self.view_result_button.clicked.connect(self._view_result)
        self.open_backup_button.clicked.connect(self._open_backup)
        self.undo_button.clicked.connect(self._undo)
        for button in (
            self.open_mods_button,
            self.view_result_button,
            self.open_backup_button,
            self.undo_button,
        ):
            result_buttons.addWidget(button)
        completion_layout.addLayout(result_buttons)
        self.completion_card.hide()
        layout.addWidget(self.completion_card)

        actions = QHBoxLayout()
        self.confirm_back = QPushButton()
        self.confirm_back.setProperty("secondary", True)
        self.confirm_back.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        self.approve_button = QPushButton()
        self.approve_button.setProperty("primary", True)
        self.approve_button.clicked.connect(self._apply)
        actions.addWidget(self.confirm_back)
        actions.addStretch()
        actions.addWidget(self.approve_button)
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def _t(self, key: str, **values: object) -> str:
        return self.translator.text(key, **values)

    def _retranslate(self) -> None:
        self.setWindowTitle(self._t("gui.window_title"))
        self.brand.setText("◆  " + self._t("gui.brand"))
        for label, key in zip(
            self.step_labels,
            ("gui.step.start", "gui.step.results", "gui.step.confirm"),
            strict=True,
        ):
            label.setText(self._t(key))
        self.start_title.setText(self._t("gui.start.title"))
        self.start_subtitle.setText(self._t("gui.start.subtitle"))
        self.drop_zone.title.setText(self._t("gui.drop.title"))
        self.drop_zone.subtitle.setText(self._t("gui.drop.subtitle"))
        self.choose_mods_button.setText(self._t("gui.choose_mods"))
        self.choose_inbox_button.setText(self._t("gui.choose_inbox"))
        self.interface_label.setText(self._t("gui.interface_language"))
        self.folder_label.setText(self._t("gui.folder_language"))
        selected_profile = self.profile_combo.currentData() or "neutral"
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in ("neutral", "en", "zh-CN"):
            self.profile_combo.addItem(self._t(f"gui.folder.{profile}"), profile)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(selected_profile)))
        self.profile_combo.blockSignals(False)
        self.check_button.setText(self._t("gui.check"))
        self.results_title.setText(self._t("gui.results.title"))
        self.results_subtitle.setText(self._t("gui.results.subtitle"))
        for card, name in (
            (self.safe_card, "safe"),
            (self.consent_card, "consent"),
            (self.hold_card, "hold"),
        ):
            card.heading.setText(self._t(f"gui.group.{name}"))
            card.hint.setText(self._t(f"gui.group.{name}_hint"))
        self.advanced_button.setText(self._t("gui.advanced"))
        self.results_back.setText(self._t("gui.back"))
        self.ai_help_button.setText(self._t("gui.ai_help"))
        self.ai_export_button.setText(self._t("gui.ai_export"))
        self.review_button.setText(self._t("gui.review_plan"))
        self.confirm_title.setText(self._t("gui.confirm.title"))
        self.confirm_subtitle.setText(self._t("gui.confirm.subtitle"))
        for label in self.findChildren(QLabel):
            key = label.property("countLabel")
            if key:
                label.setText(self._t(f"gui.count.{key}"))
        self.full_backup_check.setText(self._t("gui.full_backup"))
        self.full_backup_note.setText(self._t("gui.full_backup_note"))
        self.approve_button.setText(self._t("gui.approve"))
        self.confirm_back.setText(self._t("gui.back"))
        self.complete_title.setText(self._t("gui.complete.title"))
        self.complete_subtitle.setText(self._t("gui.complete.subtitle"))
        self.open_mods_button.setText(self._t("gui.open_mods"))
        self.view_result_button.setText(self._t("gui.view_result"))
        self.open_backup_button.setText(self._t("gui.open_backup"))
        self.undo_button.setText(self._t("gui.undo_run"))
        self._refresh_selection_labels()
        if self.session is not None:
            self._render_results()
            self._render_confirmation()
        self._update_steps(self.pages.currentIndex())
        if not self.status.text():
            self.status.setText(self._t("gui.ready"))

    def _update_steps(self, current: int) -> None:
        for index, label in enumerate(self.step_labels):
            label.setProperty("active", index == current)
            label.setProperty("done", index < current)
            label.style().unpolish(label)
            label.style().polish(label)

    def _language_changed(self) -> None:
        language = cast(str, self.language_combo.currentData())
        self.translator = Translator.load(language)
        self._retranslate()

    def _auto_discover(self) -> None:
        for candidate in candidate_mods_paths():
            if candidate.is_dir():
                self.mods_root = validate_mods_path(candidate)
                self.status.setText(self._t("gui.auto_found"))
                self._refresh_selection_labels()
                return

    @Slot(list)
    def accept_paths(self, paths: list[Path]) -> None:
        accepted = False
        for raw_path in paths:
            path = raw_path.expanduser()
            if path.is_dir() and path.name.casefold() == "mods":
                try:
                    self.mods_root = validate_mods_path(path)
                    accepted = True
                except (OSError, ValueError) as error:
                    self._show_error(str(error))
            elif path.is_dir() and path.name.casefold() != "saves":
                self.inbox_roots = [path.resolve(strict=True)]
                accepted = True
            elif path.is_file() and path.suffix.casefold() in DROP_EXTENSIONS:
                resolved = path.resolve(strict=True)
                if resolved not in self.dropped_files:
                    self.dropped_files.append(resolved)
                accepted = True
        if not accepted:
            self.status.setText(self._t("gui.drop.unsupported"))
        else:
            self.status.setText(self._t("gui.ready"))
        self._refresh_selection_labels()

    def _refresh_selection_labels(self) -> None:
        if self.mods_root is None:
            self.mods_label.setText(self._t("gui.mods.missing"))
        else:
            self.mods_label.setText(self._t("gui.mods.selected", path=self.mods_root))
        if self.inbox_roots:
            self.inbox_label.setText(self._t("gui.inbox.selected", path=self.inbox_roots[0]))
        else:
            self.inbox_label.setText(self._t("gui.inbox.empty"))
        self.files_label.setText(self._t("gui.files.selected", count=len(self.dropped_files)))
        self.check_button.setEnabled(self.mods_root is not None)

    def _choose_mods(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._t("gui.choose_mods"))
        if selected:
            self.accept_paths([Path(selected)])

    def _choose_inbox(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._t("gui.choose_inbox"))
        if selected:
            path = Path(selected)
            if path.name.casefold() == "mods":
                self.status.setText(self._t("gui.drop.unsupported"))
            else:
                self.inbox_roots = [path.resolve(strict=True)]
                self._refresh_selection_labels()

    def _start_task(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        busy_text: str,
    ) -> None:
        self.status.setText(busy_text)
        self.setEnabled(False)
        thread = QThread(self)
        worker = CallWorker(function)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(success)
        worker.failed.connect(self._task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._task_finished(thread, worker))
        self._tasks.append((thread, worker))
        thread.start()

    def _task_finished(self, thread: QThread, worker: CallWorker) -> None:
        self.setEnabled(True)
        if (thread, worker) in self._tasks:
            self._tasks.remove((thread, worker))
        thread.deleteLater()
        worker.deleteLater()

    @Slot(str)
    def _task_failed(self, detail: str) -> None:
        self.status.setText(self._t("gui.error.title"))
        self._show_error(detail)

    def _show_error(self, detail: str) -> None:
        QMessageBox.warning(
            self,
            self._t("gui.error.title"),
            self._t("gui.error.detail", detail=detail),
        )

    def _check_mods(self) -> None:
        if self.mods_root is None:
            return
        workspace = build_workspace_paths(self.mods_root)
        language = cast(str, self.language_combo.currentData())
        profile = cast(str, self.profile_combo.currentData())
        inbox_roots = tuple(self.inbox_roots)
        dropped_files = tuple(self.dropped_files)
        self._start_task(
            lambda: create_plan_run(
                workspace,
                language=language,
                profile_name=profile,
                inbox_roots=inbox_roots,
                dropped_files=dropped_files,
            ),
            self._plan_ready,
            self._t("gui.checking"),
        )

    @Slot(object)
    def _plan_ready(self, result: object) -> None:
        self.session = cast(RunSession, result)
        self.manifest = None
        self._render_results()
        self.pages.setCurrentIndex(1)
        self.status.setText(self._t("gui.ready"))

    def _result_items(self) -> tuple[list[str], list[str], list[str]]:
        assert self.session is not None
        safe: list[str] = []
        consent: list[str] = []
        hold_paths: set[str] = set()
        for operation in self.session.plan.operations:
            path = operation.destination or operation.source
            display_path = cast(str, operation.evidence.get("source_label", path))
            if operation.action == PlanAction.BACKUP:
                safe.append(self._t("gui.item.backup", path=path))
            elif operation.action == PlanAction.SKIP:
                safe.append(self._t("gui.item.skip", path=path))
            elif operation.action == PlanAction.INSTALL:
                consent.append(self._t("gui.item.install", path=path))
            elif operation.action == PlanAction.REPLACE:
                consent.append(self._t("gui.item.replace", path=path))
            elif operation.action == PlanAction.REVIEW:
                consent.append(self._t("gui.item.review", path=display_path))

        for record in self.session.before.files:
            if record.kind in {FileKind.OTHER, FileKind.ARCHIVE}:
                hold_paths.add(record.relative_path)
        hold_codes = {
            FindingCode.NAME_CONFLICT,
            FindingCode.SCRIPT_TOO_DEEP,
            FindingCode.ARCHIVE_IN_MODS,
            FindingCode.UNSAFE_SYMLINK,
            FindingCode.READ_ERROR,
        }
        for finding in self.session.before.findings:
            if finding.code in hold_codes:
                hold_paths.update(finding.paths)
        hold = [self._t("gui.item.current_unknown", path=path) for path in sorted(hold_paths)]
        return safe, consent, hold

    def _render_results(self) -> None:
        assert self.session is not None
        safe, consent, hold = self._result_items()
        empty = self._t("gui.empty")
        self.safe_card.set_items(safe, empty)
        self.consent_card.set_items(consent, empty)
        self.hold_card.set_items(hold, empty)
        detail = {
            "plan": self.session.plan.to_dict(),
            "scan_summary": self.session.before.summary.to_dict(),
            "findings": [finding.to_dict() for finding in self.session.before.findings],
        }
        self.advanced_text.setPlainText(json.dumps(detail, ensure_ascii=False, indent=2))

    def _toggle_advanced(self, visible: bool) -> None:
        self.advanced_text.setVisible(visible)

    def _copy_ai_prompt(self) -> None:
        QApplication.clipboard().setText(ai_review_prompt(self.translator.language))
        self.status.setText(self._t("gui.ai_prompt_copied"))

    def _export_ai_bundle(self) -> None:
        if self.session is None:
            return
        suggested = (
            self.session.workspace.workspace_root / f"AI_CHECK_{self.session.plan.run_id}.zip"
        )
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self._t("gui.ai_export"),
            str(suggested),
            "ZIP (*.zip)",
        )
        if not selected:
            return
        try:
            destination = export_ai_check_bundle(
                self.session.run_directory,
                Path(selected),
                language=self.translator.language,
            )
        except (OSError, ValueError) as error:
            self._show_error(str(error))
            return
        self.status.setText(self._t("gui.ai_exported", path=destination))

    def _show_confirmation(self) -> None:
        self._render_confirmation()
        self.pages.setCurrentIndex(2)

    def _render_confirmation(self) -> None:
        if self.session is None:
            return
        counts = {action: 0 for action in PlanAction}
        for operation in self.session.plan.operations:
            counts[operation.action] += 1
        _, _, hold = self._result_items()
        self.count_values[PlanAction.INSTALL].setText(str(counts[PlanAction.INSTALL]))
        self.count_values[PlanAction.REPLACE].setText(str(counts[PlanAction.REPLACE]))
        self.count_values[PlanAction.BACKUP].setText(str(counts[PlanAction.BACKUP]))
        self.count_values["hold"].setText(str(len(hold) + counts[PlanAction.REVIEW]))
        size = format_bytes(estimate_backup_bytes(self.session.before))
        self.full_backup_space.setText(self._t("gui.full_backup_space", size=size))

    def _apply(self) -> None:
        if self.session is None:
            return
        session = self.session
        complete_backup = self.full_backup_check.isChecked()
        approved = {
            operation.operation_id
            for operation in session.plan.operations
            if operation.requires_review
            and operation.action in {PlanAction.INSTALL, PlanAction.REPLACE}
        }

        def apply() -> object:
            if complete_backup:
                create_full_mods_backup(session.workspace, session.run_directory, session.before)
            return apply_plan(
                session.plan,
                session.workspace,
                session.run_directory,
                session.before,
                approved_operation_ids=approved,
            )

        self._start_task(apply, self._apply_ready, self._t("gui.applying"))

    @Slot(object)
    def _apply_ready(self, result: object) -> None:
        self.manifest = cast(RunManifest, result)
        self.completion_card.show()
        self.approve_button.hide()
        self.confirm_back.setEnabled(False)
        self.status.setText(self._t("gui.complete.title"))

    def _open_local(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_mods(self) -> None:
        if self.session is not None:
            self._open_local(self.session.workspace.mods_root)

    def _view_result(self) -> None:
        if self.session is not None:
            self._open_local(self.session.run_directory / "report.html")

    def _open_backup(self) -> None:
        if self.session is None:
            return
        full = self.session.run_directory / "full-mods-backup"
        quarantine = self.session.run_directory / "quarantine"
        self._open_local(
            full
            if full.exists()
            else quarantine
            if quarantine.exists()
            else self.session.run_directory
        )

    def _undo(self) -> None:
        if self.session is None or self.manifest is None:
            return
        session = self.session
        self._start_task(
            lambda: undo_run(session.run_directory, session.workspace),
            self._undo_ready,
            self._t("gui.undoing"),
        )

    @Slot(object)
    def _undo_ready(self, result: object) -> None:
        manifest = cast(RunManifest, result)
        if manifest.status == ManifestStatus.ROLLED_BACK:
            self.manifest = manifest
            self.undo_button.setEnabled(False)
            self.complete_title.setText(self._t("gui.undo_complete"))
            self.status.setText(self._t("gui.undo_complete"))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._tasks:
            event.ignore()
            self.status.setText(self._t("gui.wait_for_task"))
            return
        event.accept()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Sims 4 Mod Folder Steward")
    window = MainWindow()
    window.show()
    if os.environ.get("S4MOD_SMOKE_TEST") == "1":
        QTimer.singleShot(250, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
