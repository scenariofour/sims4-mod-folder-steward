from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from s4mod.gui import MainWindow
from s4mod.models import ManifestStatus


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "The Sims 4"
    mods = root / "Mods"
    inbox = tmp_path / "Downloads" / "Inbox"
    dropped = tmp_path / "Downloads" / "New.package"
    mods.mkdir(parents=True)
    inbox.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (mods / "Keep.package").write_bytes(b"duplicate")
    (mods / "Creator").mkdir()
    (mods / "Creator" / "Copy.package").write_bytes(b"duplicate")
    (mods / "Mystery.xyz").write_bytes(b"unknown current")
    (inbox / "Unknown.txt").write_bytes(b"unknown inbox")
    dropped.write_bytes(b"new package")
    return mods, inbox, dropped


def test_gui_has_three_pages_and_retranslates(qtbot: QtBot) -> None:
    window = MainWindow(auto_discover=False)
    qtbot.addWidget(window)

    assert window.pages.count() == 3
    assert window.check_button.text() == "Check my Mods"
    window.language_combo.setCurrentIndex(window.language_combo.findData("zh-CN"))
    assert window.check_button.text() == "检查我的 Mods"
    assert window.pages.count() == 3


def test_gui_automatically_finds_usual_mods_folder(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch,
) -> None:
    mods = tmp_path / "Documents" / "Electronic Arts" / "The Sims 4" / "Mods"
    mods.mkdir(parents=True)
    monkeypatch.setattr("s4mod.gui.candidate_mods_paths", lambda: (mods,))

    window = MainWindow(auto_discover=True)
    qtbot.addWidget(window)

    assert window.mods_root == mods.resolve()
    assert window.check_button.isEnabled()


def test_gui_check_apply_and_undo_use_shared_services(tmp_path: Path, qtbot: QtBot) -> None:
    mods, inbox, dropped = _fixture(tmp_path)
    window = MainWindow(auto_discover=False)
    qtbot.addWidget(window)
    window.show()
    window.accept_paths([mods, inbox, dropped])

    assert window.check_button.isEnabled()
    qtbot.mouseClick(window.check_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.session is not None and window.isEnabled(), timeout=10_000)

    assert window.pages.currentIndex() == 1
    assert window.safe_card.items.count() >= 1
    assert window.consent_card.items.count() >= 2
    assert window.hold_card.items.count() >= 1
    assert not (mods / "New.package").exists()

    qtbot.mouseClick(window.review_button, Qt.MouseButton.LeftButton)
    assert window.pages.currentIndex() == 2
    assert window.count_values["hold"].text() != "0"
    window.full_backup_check.setChecked(True)
    qtbot.mouseClick(window.approve_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.manifest is not None and window.isEnabled(), timeout=10_000)

    assert window.manifest is not None
    assert window.manifest.status == ManifestStatus.APPLIED
    assert (mods / "New.package").read_bytes() == b"new package"
    assert not (mods / "Creator" / "Copy.package").exists()
    assert (mods / "Mystery.xyz").read_bytes() == b"unknown current"
    assert window.session is not None
    assert (
        window.session.run_directory / "full-mods-backup" / "Creator" / "Copy.package"
    ).read_bytes() == b"duplicate"

    qtbot.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: (
            window.manifest is not None
            and window.manifest.status == ManifestStatus.ROLLED_BACK
            and window.isEnabled()
        ),
        timeout=10_000,
    )
    assert not (mods / "New.package").exists()
    assert (mods / "Creator" / "Copy.package").read_bytes() == b"duplicate"
    assert (mods / "Mystery.xyz").read_bytes() == b"unknown current"
    assert (window.session.run_directory / "full-mods-backup").is_dir()
