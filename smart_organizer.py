"""
smart_organizer.py

A desktop tool I built to stop dealing with messy Downloads folders.
Scans a directory, groups files by type, and moves them into clean subfolders.
Has a preview step so nothing moves without you seeing it first.

Author: safouane02
finished when I got tired of the mess lol
"""

import os
import sys
import shutil
from pathlib import Path
from collections import defaultdict

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QTreeWidget, QTreeWidgetItem, QProgressBar,
    QStatusBar, QSplitter, QFrame, QMessageBox,
    QHeaderView
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QIcon


# file type buckets — easy to extend later
FILE_CATEGORIES = {
    "Images":     [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff"],
    "Videos":     [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
    "Audio":      [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
    "PDFs":       [".pdf"],
    "Docs":       [".doc", ".docx", ".odt", ".txt", ".rtf", ".md", ".xlsx", ".xls", ".csv", ".pptx"],
    "Code":       [".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".java", ".go",
                   ".rs", ".rb", ".php", ".sh", ".bat", ".json", ".xml", ".yaml", ".yml"],
    "Archives":   [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
    "Executables":[".exe", ".msi", ".dmg", ".deb", ".rpm", ".apk"],
}

# reverse lookup: extension -> category
EXT_MAP = {}
for cat, exts in FILE_CATEGORIES.items():
    for ext in exts:
        EXT_MAP[ext.lower()] = cat


def categorize_file(filepath: Path) -> str:
    """Return the category name for a given file, or 'Other' if unknown."""
    ext = filepath.suffix.lower()
    return EXT_MAP.get(ext, "Other")


def scan_directory(folder: Path) -> dict:
    """
    Walk through a folder (non-recursive for now, might add option later)
    and return a dict: { category: [list of Path objects] }
    """
    results = defaultdict(list)
    try:
        for entry in folder.iterdir():
            if entry.is_file():
                cat = categorize_file(entry)
                results[cat].append(entry)
    except PermissionError as e:
        print(f"[warn] permission denied: {e}")
    return dict(results)


# ─── worker thread so the UI doesn't freeze during scan/organize ────────────

class ScanWorker(QThread):
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder

    def run(self):
        try:
            result = scan_directory(self.folder)
            self.done.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class OrganizeWorker(QThread):
    progress = pyqtSignal(int, int)   # (current, total)
    done = pyqtSignal(int)            # total files moved
    error = pyqtSignal(str)

    def __init__(self, folder: Path, plan: dict):
        super().__init__()
        self.folder = folder
        self.plan = plan  # { category: [Path, ...] }

    def run(self):
        total = sum(len(v) for v in self.plan.values())
        moved = 0
        try:
            for category, files in self.plan.items():
                dest_dir = self.folder / category
                dest_dir.mkdir(exist_ok=True)
                for f in files:
                    target = dest_dir / f.name
                    # handle name collisions: append _1, _2 etc.
                    counter = 1
                    while target.exists():
                        stem = f.stem + f"_{counter}"
                        target = dest_dir / (stem + f.suffix)
                        counter += 1
                    shutil.move(str(f), str(target))
                    moved += 1
                    self.progress.emit(moved, total)
        except Exception as e:
            self.error.emit(str(e))
            return
        self.done.emit(moved)


# ─── category color coding (just makes the tree nicer to read) ──────────────

CATEGORY_COLORS = {
    "Images":      "#4CAF50",
    "Videos":      "#2196F3",
    "Audio":       "#9C27B0",
    "PDFs":        "#F44336",
    "Docs":        "#FF9800",
    "Code":        "#00BCD4",
    "Archives":    "#795548",
    "Executables": "#607D8B",
    "Other":       "#9E9E9E",
}

CATEGORY_ICONS = {
    "Images":      "🖼️",
    "Videos":      "🎬",
    "Audio":       "🎵",
    "PDFs":        "📄",
    "Docs":        "📝",
    "Code":        "💻",
    "Archives":    "📦",
    "Executables": "⚙️",
    "Other":       "📁",
}


# ─── main window ────────────────────────────────────────────────────────────

class FileOrganizerApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart File Organizer — safouane02")
        self.setMinimumSize(900, 600)
        self.resize(1100, 700)

        self.selected_folder: Path | None = None
        self.scan_results: dict = {}
        self._scan_worker = None
        self._org_worker = None

        self._build_ui()
        self._apply_styles()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(10)

        # top bar: folder picker + action buttons
        top_bar = QHBoxLayout()

        self.folder_label = QLabel("No folder selected")
        self.folder_label.setObjectName("folderLabel")
        self.folder_label.setMinimumWidth(300)

        btn_browse = QPushButton("📂  Browse")
        btn_browse.setObjectName("btnBrowse")
        btn_browse.clicked.connect(self._pick_folder)

        self.btn_scan = QPushButton("🔍  Scan")
        self.btn_scan.setObjectName("btnScan")
        self.btn_scan.setEnabled(False)
        self.btn_scan.clicked.connect(self._run_scan)

        self.btn_organize = QPushButton("✅  Organize")
        self.btn_organize.setObjectName("btnOrganize")
        self.btn_organize.setEnabled(False)
        self.btn_organize.clicked.connect(self._run_organize)

        top_bar.addWidget(self.folder_label, stretch=1)
        top_bar.addWidget(btn_browse)
        top_bar.addWidget(self.btn_scan)
        top_bar.addWidget(self.btn_organize)
        root.addLayout(top_bar)

        # divider line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("divider")
        root.addWidget(line)

        # summary bar
        self.summary_label = QLabel("Scan a folder to see what's inside.")
        self.summary_label.setObjectName("summaryLabel")
        root.addWidget(self.summary_label)

        # splitter: tree (left) + detail panel (right)
        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Type", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setObjectName("fileTree")
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._on_select)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 0, 0, 0)

        right_layout.addWidget(QLabel("Preview", objectName="panelTitle"))

        self.preview_label = QLabel("Select a file to preview info.")
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignTop)
        right_layout.addWidget(self.preview_label, stretch=1)

        splitter.addWidget(self.tree)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

        # progress bar (hidden until organize runs)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        root.addWidget(self.progress_bar)

        # status bar at the bottom
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready.")

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: 'Segoe UI', 'Ubuntu', sans-serif;
                font-size: 13px;
            }
            #folderLabel {
                background: #313244;
                padding: 6px 12px;
                border-radius: 6px;
                color: #a6adc8;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: none;
                border-radius: 6px;
                padding: 7px 18px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton:pressed { background-color: #585b70; }
            QPushButton:disabled { color: #585b70; }
            #btnOrganize {
                background-color: #a6e3a1;
                color: #1e1e2e;
                font-weight: 700;
            }
            #btnOrganize:hover { background-color: #94d49e; }
            #btnOrganize:disabled { background-color: #313244; color: #585b70; }
            #divider { color: #313244; }
            #summaryLabel { color: #89b4fa; font-size: 12px; padding: 2px 0; }
            #panelTitle { font-size: 14px; font-weight: 700; color: #89dceb; margin-bottom: 8px; }
            #previewLabel { color: #a6adc8; line-height: 1.6; }
            QTreeWidget {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
                outline: none;
            }
            QTreeWidget::item { padding: 4px 2px; }
            QTreeWidget::item:selected { background-color: #313244; color: #cdd6f4; }
            QTreeWidget::item:hover { background-color: #2a2a3c; }
            QHeaderView::section {
                background-color: #313244;
                color: #89b4fa;
                padding: 5px;
                border: none;
                font-weight: 600;
            }
            QProgressBar {
                background: #313244;
                border-radius: 6px;
                height: 16px;
                text-align: center;
                color: #1e1e2e;
                font-weight: 600;
            }
            QProgressBar::chunk { background-color: #a6e3a1; border-radius: 6px; }
            QSplitter::handle { background: #313244; width: 2px; }
            QStatusBar { color: #6c7086; font-size: 11px; }
        """)

    # ── folder selection ─────────────────────────────────────────────────────

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder to organize")
        if not path:
            return
        self.selected_folder = Path(path)
        # truncate display if path is too long
        display = str(self.selected_folder)
        if len(display) > 70:
            display = "..." + display[-67:]
        self.folder_label.setText(display)
        self.btn_scan.setEnabled(True)
        self.btn_organize.setEnabled(False)
        self.tree.clear()
        self.scan_results = {}
        self.summary_label.setText("Click Scan to analyze the folder.")
        self.status_bar.showMessage(f"Folder selected: {self.selected_folder}")

    # ── scan ─────────────────────────────────────────────────────────────────

    def _run_scan(self):
        if not self.selected_folder:
            return
        self.btn_scan.setEnabled(False)
        self.btn_organize.setEnabled(False)
        self.tree.clear()
        self.status_bar.showMessage("Scanning...")

        self._scan_worker = ScanWorker(self.selected_folder)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.error.connect(self._on_error)
        self._scan_worker.start()

    def _on_scan_done(self, results: dict):
        self.scan_results = results
        self._populate_tree(results)

        total = sum(len(v) for v in results.values())
        cats = len(results)
        self.summary_label.setText(
            f"Found {total} file(s) across {cats} categor{'y' if cats == 1 else 'ies'}."
        )

        self.btn_scan.setEnabled(True)
        self.btn_organize.setEnabled(total > 0)
        self.status_bar.showMessage(f"Scan complete — {total} files found.")

    def _populate_tree(self, results: dict):
        self.tree.clear()
        for category in sorted(results.keys()):
            files = results[category]
            icon = CATEGORY_ICONS.get(category, "📁")
            color = CATEGORY_COLORS.get(category, "#9E9E9E")

            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, f"{icon}  {category}  ({len(files)} files)")
            cat_item.setForeground(0, QColor(color))
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setData(0, Qt.UserRole, "category")

            for f in sorted(files, key=lambda x: x.name.lower()):
                child = QTreeWidgetItem(cat_item)
                child.setText(0, f.name)
                child.setText(1, f.suffix.lstrip(".").upper() or "—")
                child.setText(2, self._fmt_size(f.stat().st_size))
                child.setData(0, Qt.UserRole, str(f))

            cat_item.setExpanded(True)

    # ── file preview panel ───────────────────────────────────────────────────

    def _on_select(self):
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        path_str = item.data(0, Qt.UserRole)
        if path_str == "category" or not path_str:
            self.preview_label.setText("Select a file for details.")
            return
        try:
            p = Path(path_str)
            stat = p.stat()
            cat = categorize_file(p)
            dest_preview = self.selected_folder / cat / p.name if self.selected_folder else "N/A"
            info = (
                f"<b>Name:</b> {p.name}<br>"
                f"<b>Category:</b> {CATEGORY_ICONS.get(cat, '')} {cat}<br>"
                f"<b>Extension:</b> {p.suffix or '(none)'}<br>"
                f"<b>Size:</b> {self._fmt_size(stat.st_size)}<br><br>"
                f"<b>Will move to:</b><br>"
                f"<span style='color:#a6e3a1;'>{dest_preview}</span>"
            )
            self.preview_label.setText(info)
        except Exception:
            self.preview_label.setText("Could not read file info.")

    # ── organize ─────────────────────────────────────────────────────────────

    def _run_organize(self):
        if not self.scan_results:
            return

        total = sum(len(v) for v in self.scan_results.values())
        reply = QMessageBox.question(
            self,
            "Confirm",
            f"Move {total} files into categorized subfolders inside:\n\n{self.selected_folder}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_organize.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.status_bar.showMessage("Organizing files...")

        self._org_worker = OrganizeWorker(self.selected_folder, self.scan_results)
        self._org_worker.progress.connect(self._on_progress)
        self._org_worker.done.connect(self._on_organize_done)
        self._org_worker.error.connect(self._on_error)
        self._org_worker.start()

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)
        self.status_bar.showMessage(f"Moving files... {current}/{total}")

    def _on_organize_done(self, moved: int):
        self.progress_bar.setVisible(False)
        self.btn_scan.setEnabled(True)
        self.scan_results = {}
        self.tree.clear()
        self.btn_organize.setEnabled(False)
        self.summary_label.setText(f"Done! {moved} file(s) organized successfully.")
        self.status_bar.showMessage(f"Finished — {moved} files moved.")
        QMessageBox.information(self, "Done", f"Successfully organized {moved} file(s)!")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _on_error(self, msg: str):
        self.btn_scan.setEnabled(True)
        self.btn_organize.setEnabled(bool(self.scan_results))
        self.progress_bar.setVisible(False)
        self.status_bar.showMessage(f"Error: {msg}")
        QMessageBox.critical(self, "Error", f"Something went wrong:\n{msg}")

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        """Human readable file size."""
        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


# ─── entry point ────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Smart File Organizer")
    app.setStyle("Fusion")
    window = FileOrganizerApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()