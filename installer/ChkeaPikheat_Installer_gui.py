"""
ChkeaPikheat Modern Windows Setup Installer Wizard
Provides a streamlined One UI 9 installation experience with desktop shortcut creation,
start menu integration, clean default settings initialization, and uninstaller creation.
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


def get_base_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def create_windows_shortcut(target_exe: Path, shortcut_path: Path, icon_path: Path | None = None, description: str = "ChkeaPikheat"):
    """Creates a Windows .lnk shortcut using PowerShell WScript.Shell without external python dependencies."""
    try:
        ps_cmd = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{str(shortcut_path)}')
$Shortcut.TargetPath = '{str(target_exe)}'
$Shortcut.WorkingDirectory = '{str(target_exe.parent)}'
$Shortcut.Description = '{description}'
"""
        if icon_path and icon_path.exists():
            ps_cmd += f"\n$Shortcut.IconLocation = '{str(icon_path)}'"
        ps_cmd += "\n$Shortcut.Save()"
        
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False, creationflags=creation_flags)
    except Exception as e:
        print(f"Failed to create shortcut {shortcut_path}: {e}")


def init_clean_settings():
    """Initializes clean default settings with Light theme, Khmer language, and empty API key."""
    try:
        from PyQt6.QtCore import QSettings
        # Set for PyQt6DownloadManager and ChkeaPikheat
        for org, app in [("YourOrgName", "PyQt6DownloadManager"), ("ChkeaPikheat", "ChkeaPikheat")]:
            s = QSettings(org, app)
            s.setValue("theme", "light")
            s.setValue("language", "km")
            s.setValue("gemini_api_key", "")
            s.sync()
    except Exception as e:
        print(f"Settings init notice: {e}")


class InstallWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_dir: Path, create_desktop: bool, create_start_menu: bool, parent=None):
        super().__init__(parent)
        self.target_dir = target_dir
        self.create_desktop = create_desktop
        self.create_start_menu = create_start_menu

    def run(self):
        try:
            self.progress_changed.emit(10, "Preparing installation environment...")
            base_dir = get_base_dir()
            
            # Find source payload ChkeaPikheat.exe
            candidates = [
                base_dir / "dist" / "ChkeaPikheat.exe",
                base_dir / "ChkeaPikheat.exe",
                base_dir / "payload" / "ChkeaPikheat.exe",
            ]
            source_exe = None
            for cand in candidates:
                if cand.exists():
                    source_exe = cand
                    break

            if not source_exe:
                self.finished.emit(False, f"Source application executable not found in installer payload.")
                return

            self.target_dir.mkdir(parents=True, exist_ok=True)
            target_exe = self.target_dir / "ChkeaPikheat.exe"

            # 1. Copy Application Executable
            self.progress_changed.emit(30, "Copying application binaries (ChkeaPikheat.exe)...")
            shutil.copy2(source_exe, target_exe)

            # 2. Copy Icons & Resources
            self.progress_changed.emit(50, "Installing application icon and assets...")
            ico_src = base_dir / "app-logo.ico"
            if not ico_src.exists():
                ico_src = base_dir / "downloader_app" / "ui" / "resources" / "app-logo.ico"
            target_ico = self.target_dir / "app-logo.ico"
            if ico_src.exists():
                shutil.copy2(ico_src, target_ico)

            # 3. Initialize Clean Settings
            self.progress_changed.emit(70, "Initializing default settings (Light Theme, Khmer, Clean API Key)...")
            init_clean_settings()

            # 4. Create Shortcuts
            self.progress_changed.emit(85, "Creating Windows shortcuts...")
            if self.create_desktop:
                desktop = Path.home() / "Desktop"
                if desktop.exists():
                    create_windows_shortcut(target_exe, desktop / "ChkeaPikheat.lnk", target_ico, "ChkeaPikheat Video Downloader & Dubbing Studio")

            if self.create_start_menu:
                start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                if start_menu.exists():
                    create_windows_shortcut(target_exe, start_menu / "ChkeaPikheat.lnk", target_ico, "ChkeaPikheat Video Downloader & Dubbing Studio")

            # 5. Create Uninstaller script
            uninstaller_content = f"""@echo off
title Uninstall ChkeaPikheat
echo ========================================================
echo   Are you sure you want to uninstall ChkeaPikheat?
echo ========================================================
choice /C YN /M "Press Y to Uninstall, N to Cancel: "
if errorlevel 2 exit /b

echo Terminating running processes...
taskkill /F /IM ChkeaPikheat.exe >nul 2>&1

echo Removing shortcuts...
del "%USERPROFILE%\\Desktop\\ChkeaPikheat.lnk" >nul 2>&1
del "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\ChkeaPikheat.lnk" >nul 2>&1

echo Removing application directory...
cd /d "%TEMP%"
timeout /t 1 >nul
rmdir /s /q "{str(self.target_dir)}" >nul 2>&1

echo.
echo ChkeaPikheat has been successfully removed from your computer.
pause
"""
            (self.target_dir / "uninstall.bat").write_text(uninstaller_content, encoding="utf-8")

            self.progress_changed.emit(100, "Installation complete!")
            self.finished.emit(True, str(target_exe))

        except Exception as e:
            self.finished.emit(False, str(e))


class InstallerWindow(QWidget):
    """One UI 9 Clean Setup Installer Wizard."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChkeaPikheat Setup Wizard")
        self.setFixedSize(620, 480)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        
        base_dir = get_base_dir()
        logo_path = base_dir / "app-logo.png"
        if not logo_path.exists():
            logo_path = base_dir / "downloader_app" / "ui" / "resources" / "app-logo.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.default_install_dir = Path.home() / "AppData" / "Local" / "Programs" / "ChkeaPikheat"
        self.installed_exe_path = ""
        self._init_ui(logo_path)
        self._apply_styles()

    def _init_ui(self, logo_path: Path):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header Banner
        header = QFrame()
        header.setObjectName("headerFrame")
        header.setFixedHeight(95)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(28, 14, 28, 14)
        h_layout.setSpacing(18)

        if logo_path.exists():
            lbl_logo = QLabel()
            lbl_logo.setPixmap(QPixmap(str(logo_path)).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            h_layout.addWidget(lbl_logo)

        h_text_v = QVBoxLayout()
        h_text_v.setSpacing(2)
        lbl_title = QLabel("ChkeaPikheat Setup")
        lbl_title.setObjectName("headerTitle")
        lbl_sub = QLabel("The Ultimate AI Video Downloader, Splitter & Khmer Dubbing Studio")
        lbl_sub.setObjectName("headerSubtitle")
        h_text_v.addWidget(lbl_title)
        h_text_v.addWidget(lbl_sub)
        h_layout.addLayout(h_text_v)
        h_layout.addStretch(1)
        main_layout.addWidget(header)

        # Stacked Pages
        self.pages = QStackedWidget()

        # ── Page 1: Configure & Install ──
        p1 = QWidget()
        p1_layout = QVBoxLayout(p1)
        p1_layout.setContentsMargins(32, 24, 32, 24)
        p1_layout.setSpacing(14)

        lbl_desc = QLabel("Welcome to the ChkeaPikheat installation wizard. This wizard will install ChkeaPikheat on your computer with Google Sans Khmer typography, Light mode defaults, and offline AI dubbing tools.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setObjectName("bodyText")
        p1_layout.addWidget(lbl_desc)

        p1_layout.addSpacing(6)
        lbl_folder = QLabel("Install Destination Folder:")
        lbl_folder.setObjectName("sectionLabel")
        p1_layout.addWidget(lbl_folder)

        dir_box = QHBoxLayout()
        dir_box.setSpacing(8)
        self.txt_dir = QLineEdit(str(self.default_install_dir))
        self.txt_dir.setObjectName("pathInput")
        btn_browse = QPushButton("Browse...")
        btn_browse.setObjectName("btnBrowse")
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self._on_browse_clicked)
        dir_box.addWidget(self.txt_dir, 1)
        dir_box.addWidget(btn_browse)
        p1_layout.addLayout(dir_box)

        p1_layout.addSpacing(6)
        self.chk_desktop = QCheckBox("Create Desktop Shortcut (បង្កើតផ្លូវកាត់លើ Desktop)")
        self.chk_desktop.setChecked(True)
        self.chk_desktop.setObjectName("customCheck")
        p1_layout.addWidget(self.chk_desktop)

        self.chk_start_menu = QCheckBox("Create Start Menu Shortcut (បង្កើតក្នុង Start Menu)")
        self.chk_start_menu.setChecked(True)
        self.chk_start_menu.setObjectName("customCheck")
        p1_layout.addWidget(self.chk_start_menu)

        p1_layout.addStretch(1)

        # Bottom Bar for Page 1
        p1_btn_bar = QHBoxLayout()
        p1_btn_bar.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.close)
        
        self.btn_install = QPushButton("Install Now")
        self.btn_install.setObjectName("btnPrimary")
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install.clicked.connect(self._start_install)

        p1_btn_bar.addWidget(btn_cancel)
        p1_btn_bar.addWidget(self.btn_install)
        p1_layout.addLayout(p1_btn_bar)

        self.pages.addWidget(p1)

        # ── Page 2: Installing Progress ──
        p2 = QWidget()
        p2_layout = QVBoxLayout(p2)
        p2_layout.setContentsMargins(40, 50, 40, 40)
        p2_layout.setSpacing(18)

        self.lbl_installing_title = QLabel("Installing ChkeaPikheat...")
        self.lbl_installing_title.setObjectName("sectionLabelLarge")
        p2_layout.addWidget(self.lbl_installing_title)

        self.lbl_status = QLabel("Extracting and installing files, please wait...")
        self.lbl_status.setObjectName("bodyText")
        p2_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("installProgress")
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        p2_layout.addWidget(self.progress_bar)

        p2_layout.addStretch(1)
        self.pages.addWidget(p2)

        # ── Page 3: Finished ──
        p3 = QWidget()
        p3_layout = QVBoxLayout(p3)
        p3_layout.setContentsMargins(40, 40, 40, 30)
        p3_layout.setSpacing(16)

        lbl_success_title = QLabel("✓ Installation Completed Successfully!")
        lbl_success_title.setObjectName("successTitle")
        p3_layout.addWidget(lbl_success_title)

        lbl_success_desc = QLabel("ChkeaPikheat is now ready to use on your computer. All components, Google Sans typography, FFmpeg engines, and Light mode defaults are configured.")
        lbl_success_desc.setWordWrap(True)
        lbl_success_desc.setObjectName("bodyText")
        p3_layout.addWidget(lbl_success_desc)

        p3_layout.addSpacing(8)
        self.chk_launch = QCheckBox("Launch ChkeaPikheat now (បើកដំណើរការកម្មវិធីភ្លាមៗ)")
        self.chk_launch.setChecked(True)
        self.chk_launch.setObjectName("customCheck")
        p3_layout.addWidget(self.chk_launch)

        p3_layout.addStretch(1)

        p3_btn_bar = QHBoxLayout()
        p3_btn_bar.addStretch(1)
        btn_finish = QPushButton("Finish")
        btn_finish.setObjectName("btnPrimary")
        btn_finish.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_finish.clicked.connect(self._on_finish_clicked)
        p3_btn_bar.addWidget(btn_finish)
        p3_layout.addLayout(p3_btn_bar)

        self.pages.addWidget(p3)

        main_layout.addWidget(self.pages, 1)

    def _on_browse_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Install Destination", self.txt_dir.text())
        if folder:
            self.txt_dir.setText(str(Path(folder) / "ChkeaPikheat"))

    def _start_install(self):
        target_path = Path(self.txt_dir.text().strip())
        self.pages.setCurrentIndex(1)
        
        self.worker = InstallWorker(
            target_dir=target_path,
            create_desktop=self.chk_desktop.isChecked(),
            create_start_menu=self.chk_start_menu.isChecked(),
            parent=self,
        )
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, val: int, msg: str):
        self.progress_bar.setValue(val)
        self.lbl_status.setText(msg)

    def _on_finished(self, success: bool, msg_or_path: str):
        if success:
            self.installed_exe_path = msg_or_path
            self.pages.setCurrentIndex(2)
        else:
            self.lbl_installing_title.setText("Installation Failed")
            self.lbl_status.setText(f"Error: {msg_or_path}")

    def _on_finish_clicked(self):
        if self.chk_launch.isChecked() and self.installed_exe_path and Path(self.installed_exe_path).exists():
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen([str(self.installed_exe_path)], creationflags=creation_flags)
        self.close()

    def _apply_styles(self):
        self.setStyleSheet("""
QWidget {
    background-color: #F8FAFC;
    color: #0F172A;
    font-family: "Google Sans", "Kantumruy Pro", "Segoe UI", sans-serif;
    font-size: 13px;
}

QFrame#headerFrame {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E2E8F0;
}

QLabel#headerTitle {
    font-size: 19px;
    font-weight: bold;
    color: #0F172A;
}

QLabel#headerSubtitle {
    font-size: 12px;
    color: #64748B;
}

QLabel#sectionLabel {
    font-size: 13px;
    font-weight: 600;
    color: #1E293B;
}

QLabel#sectionLabelLarge {
    font-size: 18px;
    font-weight: 600;
    color: #0F172A;
}

QLabel#successTitle {
    font-size: 18px;
    font-weight: 600;
    color: #10B981;
}

QLabel#bodyText {
    font-size: 12.5px;
    color: #475569;
    line-height: 1.4;
}

QLineEdit#pathInput {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12.5px;
    color: #0F172A;
}

QLineEdit#pathInput:focus {
    border: 1px solid #1259C3;
}

QPushButton#btnBrowse {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
    color: #1E293B;
}

QPushButton#btnBrowse:hover {
    background-color: #F1F5F9;
    border-color: #94A3B8;
}

QCheckBox#customCheck {
    font-size: 13px;
    color: #1E293B;
    spacing: 8px;
}

QCheckBox#customCheck::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #CBD5E1;
    background-color: #FFFFFF;
}

QCheckBox#customCheck::indicator:checked {
    background-color: #1259C3;
    border-color: #1259C3;
}

QProgressBar#installProgress {
    background-color: #E2E8F0;
    border-radius: 6px;
    text-align: center;
}

QProgressBar#installProgress::chunk {
    background-color: #1259C3;
    border-radius: 6px;
}

QPushButton#btnPrimary {
    background-color: #1259C3;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 9px 24px;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#btnPrimary:hover {
    background-color: #0E469C;
}

QPushButton#btnSecondary {
    background-color: #FFFFFF;
    color: #475569;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 9px 20px;
    font-size: 13px;
    font-weight: 500;
}

QPushButton#btnSecondary:hover {
    background-color: #F1F5F9;
}
""")


def main():
    app = QApplication(sys.argv)
    window = InstallerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
