"""
unified_lab_gui.py — YPL Lab Control
One window, multiple tabs:
  • DAQ Control    — UEI PowerDNA cards + Moku:Go + Guardian
  • ITLA Laser     — Emcore TTX ITLA controller
  • CONEX Motor    — Newport CONEX-CC / TRA12CC controller
  • HP-8168F Laser — HP/Agilent 8168F tunable laser source (GPIB)

All-PyQt6 (the old itla_gui.py was PySide6 and has been ported).
Requires: PyQt6, pyqtgraph, numpy; optional: UeiDaq, moku, pyserial, hardware.itla, pyvisa
Run:      python unified_lab_gui.py
"""

import os
os.environ["MOKU_CLI_PATH"] = r"C:\Program Files\Liquid Instruments\Moku CLI\mokucli.exe"

import sys
import math
import time
import threading
import subprocess
import socket
import json
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QScrollArea, QFrame, QSizePolicy,
    QDoubleSpinBox, QSlider, QStackedWidget, QStatusBar, QGroupBox,
    QSpinBox, QComboBox, QLineEdit, QCheckBox, QTabWidget, QTextEdit,
    QMessageBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QObject, QEventLoop, QEvent
from PyQt6.QtGui import QPalette, QColor

# ── Optional hardware libraries (each tab degrades gracefully) ────────────────

try:
    import UeiDaq
    HAS_UEIDAQ = True
except ImportError:
    HAS_UEIDAQ = False
    print("[WARNING] UeiDaq not found — DAQ card control disabled.")

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False
    print("[WARNING] pyqtgraph not found — plots disabled. Run: uv pip install pyqtgraph")

try:
    import matplotlib
    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[WARNING] matplotlib not found — Santec Fast Sweep plot disabled. Run: uv pip install matplotlib")

try:
    from moku.instruments import Oscilloscope
    HAS_MOKU = True
except ImportError:
    HAS_MOKU = False
    print("[WARNING] moku library not found — Moku integration disabled.")

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    print("[WARNING] pyserial not found — CoreDAQ optical power meter disabled. Run: uv pip install pyserial")

try:
    from hardware.itla import ITLA, REG
    HAS_ITLA = True
except ImportError:
    HAS_ITLA = False
    print("[WARNING] hardware.itla not found — ITLA Laser tab disabled.")

try:
    import pyvisa
    HAS_PYVISA = True
except ImportError:
    HAS_PYVISA = False
    print("[WARNING] pyvisa not found — CONEX-CC Motor tab disabled. Run: uv pip install pyvisa pyvisa-py")

try:
    from hardware.laser_hp_8168F import HP8168F
    HAS_HP8168F = True
except ImportError:
    HAS_HP8168F = False
    print("[WARNING] hardware.laser_hp_8168F not found — HP-8168F Laser tab disabled.")

try:
    from hardware.coredaq import CoreDAQ
    HAS_COREDAQ = True
except ImportError:
    HAS_COREDAQ = False
    print("[WARNING] hardware.coredaq not found — CoreDAQ Power Meter tab disabled.")

try:
    from hardware.laser_tsl_550 import TSL550
    HAS_SANTEC = True
except ImportError:
    HAS_SANTEC = False
    print("[WARNING] hardware.laser_tsl_550 not found or nidaqmx missing — Santec Laser tab disabled.")

# ══════════════════════════════════════════════════════════════════════════════
# THEME
# ══════════════════════════════════════════════════════════════════════════════

PLOT_BG   = "#15191E"
PLOT_FG   = "#D8DEE9"
C_BLUE    = "#4FC3F7"
C_RED     = "#FF6E6E"
C_GOLD    = "#FFD75E"
C_GREEN   = "#5FD068"
C_ORANGE  = "#FFA836"
C_GRAY    = "#9AA0A6"
C_TEXT    = "#E8E8E8"

def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    bg      = QColor("#1B1F24")
    base    = QColor("#15191E")
    alt     = QColor("#21262C")
    text    = QColor(C_TEXT)
    btn     = QColor("#2A3038")
    hl      = QColor("#3D6FA5")
    p.setColor(QPalette.ColorRole.Window,          bg)
    p.setColor(QPalette.ColorRole.WindowText,      text)
    p.setColor(QPalette.ColorRole.Base,            base)
    p.setColor(QPalette.ColorRole.AlternateBase,   alt)
    p.setColor(QPalette.ColorRole.ToolTipBase,     alt)
    p.setColor(QPalette.ColorRole.ToolTipText,     text)
    p.setColor(QPalette.ColorRole.Text,            text)
    p.setColor(QPalette.ColorRole.Button,          btn)
    p.setColor(QPalette.ColorRole.ButtonText,      text)
    p.setColor(QPalette.ColorRole.Highlight,       hl)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(C_GRAY))
    disabled = QColor("#6A7178")
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    app.setPalette(p)
    app.setStyleSheet(f"""
        QGroupBox {{
            border: 1px solid #343B43;
            border-radius: 6px;
            margin-top: 10px;
            padding-top: 6px;
            font-weight: bold;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: {C_BLUE};
        }}
        QPushButton {{
            border: 1px solid #3A4149;
            border-radius: 4px;
            padding: 4px 10px;
            background: #2A3038;
        }}
        QPushButton:hover    {{ background: #343C46; }}
        QPushButton:pressed  {{ background: #1F252B; }}
        QPushButton:disabled {{ color: #6A7178; border-color: #2A3038; }}
        QTabWidget::pane {{ border: 1px solid #343B43; border-radius: 4px; }}
        QTabBar::tab {{
            padding: 6px 18px;
            background: #21262C;
            border: 1px solid #343B43;
            border-bottom: none;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
        }}
        QTabBar::tab:selected {{ background: #2E3640; color: {C_BLUE}; }}
        QStatusBar {{ border-top: 1px solid #343B43; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            border: 1px solid #3A4149;
            border-radius: 3px;
            padding: 2px 4px;
            background: #15191E;
        }}
    """)
    if HAS_PYQTGRAPH:
        pg.setConfigOption('background', PLOT_BG)
        pg.setConfigOption('foreground', PLOT_FG)

# ══════════════════════════════════════════════════════════════════════════════
# SCROLL-DISABLED SPINBOXES
# ══════════════════════════════════════════════════════════════════════════════

class NoScrollSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event):
        event.ignore()

class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event):
        event.ignore()

# ══════════════════════════════════════════════════════════════════════════════
# MULTI-SELECT PIN PICKER
# ══════════════════════════════════════════════════════════════════════════════

class MultiPinSelector(QPushButton):
    """Button that drops down a checklist popup for picking any subset of
    pins — used for DAQ Control's Sweep/Waveform pin pickers. The button
    label shows "N pins selected" (or the one item's own text, or a
    placeholder) once the popup closes.

    Deliberately NOT a QComboBox with checkable items: that first version
    toggled unreliably because Qt's own item delegate ALSO toggles the
    checkbox when a click lands in its small indicator rect — racing against
    a manual "toggle on any click" handler and canceling it out on roughly
    half of clicks on the checkbox itself, which is exactly where users
    click. A plain QListWidget shown as its own Qt.WindowType.Popup window
    fixes the "closed box doesn't show what's selected" half of that bug
    (this button's text is the only place a "selected" summary gets
    written, so nothing else can silently overwrite it) — but toggling still
    isn't left to Qt's normal item-click signals: measured directly, clicks
    landing inside the checkbox glyph's own small rect (a few pixels wide,
    right where users naturally aim) never reach itemPressed/itemClicked at
    all — something in the view/delegate's own checkbox hit-testing consumes
    them first, even with the item's ItemIsUserCheckable flag left unset.
    So toggling is done via a viewport event filter instead (see
    eventFilter), which sees every raw mouse release before any of that
    view-internal handling gets a chance to swallow it.
    """

    def __init__(self, placeholder: str = "No pins selected", parent=None):
        super().__init__(placeholder, parent)
        self._placeholder = placeholder
        self.clicked.connect(self._toggle_popup)

        self._popup = QListWidget(self)
        self._popup.setWindowFlags(Qt.WindowType.Popup)
        self._popup.viewport().installEventFilter(self)
        self._popup.itemChanged.connect(lambda _item: self._refresh_text())
        self._items: dict = {}   # data -> QListWidgetItem

    def eventFilter(self, obj, event) -> bool:
        if (obj is self._popup.viewport()
                and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton):
            item = self._popup.itemAt(event.pos())
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                    else Qt.CheckState.Checked)
            return True   # consume — don't let the view's own click handling run too
        return super().eventFilter(obj, event)

    def addCheckableItem(self, text: str, data=None) -> None:
        item = QListWidgetItem(text)
        item.setCheckState(Qt.CheckState.Unchecked)
        item.setData(Qt.ItemDataRole.UserRole, data)
        self._popup.addItem(item)
        self._items[data] = item
        self._refresh_text()

    def clear(self) -> None:
        self._popup.clear()
        self._items.clear()
        self._refresh_text()

    def checked_data(self) -> list:
        return [data for data, item in self._items.items()
                if item.checkState() == Qt.CheckState.Checked]

    def set_checked_data(self, values) -> None:
        values = set(values)
        for data, item in self._items.items():
            item.setCheckState(Qt.CheckState.Checked if data in values
                                else Qt.CheckState.Unchecked)
        self._refresh_text()

    def select_all(self) -> None:
        for item in self._items.values():
            item.setCheckState(Qt.CheckState.Checked)
        self._refresh_text()

    def set_item_text_for_data(self, data, text: str) -> None:
        item = self._items.get(data)
        if item is not None:
            item.setText(text)
            self._refresh_text()

    def _toggle_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.setFixedWidth(max(self.width(), 160))
        row_h = self._popup.sizeHintForRow(0) if self._popup.count() else 22
        self._popup.setFixedHeight(min(320, row_h * self._popup.count() + 6))
        self._popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self._popup.show()

    def _refresh_text(self) -> None:
        checked = self.checked_data()
        if not checked:
            text = self._placeholder
        elif len(checked) == 1:
            text = self._items[checked[0]].text()
        else:
            text = f"{len(checked)} pins selected"
        self.setText(text)

# ══════════════════════════════════════════════════════════════════════════════
# DAQ CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

CUBE_IP = "172.28.2.4"
MOKU_IP = "172.28.5.6"

NUM_PINS = 8    # Guardian ADC readback bridge channel count (ao333_bridge.py) — unrelated to AO channel count
MAX_PINS = 32   # widest channel count any single card exposes (Dev2 / AO-333)

CARDS = {
    0: {"label": "DEV0  —  CURRENT", "mode": "current", "dev": "Dev0", "available": True,
        "channels": 16},
    1: {"label": "DEV1  —  CURRENT", "mode": "current", "dev": "Dev1", "available": True,
        "channels": 16},
    2: {"label": "DEV2  —  VOLTAGE", "mode": "voltage", "dev": "Dev2", "available": True,
        "channels": MAX_PINS},
}

# Physical pin remap — maps "GUI/logical pin index" -> "actual physical
# output channel index" for cards whose connector/cable doesn't wire in
# straight sequential order. Keyed by CARDS[...]["dev"]. An empty/missing
# entry means identity (no remap), which MUST stay the default until a
# pin's real mapping has been directly confirmed with pin_identify_test.py
# — do not guess entries here. An unconfirmed remap is more dangerous than
# none at all: it would silently send commanded voltage to a physical pin
# you don't think you're touching. Populate only pins you've verified;
# unlisted pins are assumed correct (identity) until proven otherwise.
#
# Dev2 (AO-333) mapping — completed 2026-07-20 by a full raw walk with
# pin_identify_test.py (PIN_REMAP empty), Guardian ADC + multimeter, recorded
# in pin_map_Dev2.csv. The ribbon cable jumpered off its far end produces a
# SYMMETRIC swap (an involution): driving raw channel a comes out at physical
# pin b, and driving raw channel b comes out at physical pin a. So the same
# dict corrects both the write and the readback direction. The 21 confirmed
# pairs below cover every physical output that has a device wired to it.
#
# NOT a clean i->31-i reversal and NOT a constant offset: pin 15 maps to
# itself while the endpoints swap (0<->31). The pattern is real but irregular,
# so it was walked pin-by-pin rather than extrapolated.
#
# Deliberately UNLISTED (kept identity): logical 1, 5, 8, 11, 14, 17, 20, 23,
# 26, 28, 30. These raw channels could not be pinned to a single physical
# output during the walk — raw channel 30 in particular lit up physical
# 5/8/11/14/17/20 all at once (a short/floating bus, not a 1:1 route). Their
# physical destinations are functional pins that just don't yet have a
# confirmed logical route, so per the standing rule they stay un-remapped
# instead of being guessed. Finish them the same way (raw walk) if/when the
# downstream wiring for those channels is settled, then add the pairs here.
PIN_REMAP = {
    "Dev2": {
        0: 31, 2: 29, 3: 27, 4: 25, 6: 24, 7: 22, 9: 21, 10: 19,
        12: 18, 13: 16, 15: 15, 16: 13, 18: 12, 19: 10, 21: 9,
        22: 7, 24: 6, 25: 4, 27: 3, 29: 2, 31: 0,
    },
}


def remap_pin(dev: str, logical_pin: int) -> int:
    """GUI pin index -> actual physical channel index to write/read for `dev`."""
    return PIN_REMAP.get(dev, {}).get(logical_pin, logical_pin)


AO_CHANNEL_NAMES_FILE = os.path.join(os.path.dirname(__file__), "ao_channel_names.json")

CONNECTION_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "connection_settings.json")

# Saved sweep/recording CSVs go here — anchored to this script's own location
# (gui.py's dir -> code -> project root -> "data") instead of a hardcoded
# absolute path. This file used to live at C:\Users\sih93\Desktop\Sid\GUI and
# a hardcoded data_dir pointed there; after the project moved to the
# OneDrive-synced folder, every save kept silently writing into that old,
# no-longer-visited, unsynced local folder instead of anywhere the user
# looked (or OneDrive backed up). Deriving it from __file__ means it always
# resolves inside wherever the project actually lives.
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")

# Plot images (currently: Santec Fast Sweep results) saved alongside their
# CSV export, so a sweep's picture and data stay next to each other under
# data/ instead of the image being a one-off you'd have to regenerate later.
IMAGES_DIR = os.path.join(DATA_DIR, "images")


def open_saved_file(path: str) -> None:
    """Opens `path` with its default Windows application (e.g. Excel for
    .csv). Wired to each tab's "📂 Open" button, which opens the most
    recently exported/saved file for that button — not auto-launched on
    save itself, since forcing a new Excel window open every export got in
    the way more than it helped."""
    try:
        os.startfile(path)
    except Exception as e:
        print(f"[OpenFile] Failed to open {path}: {e}")


def load_connection_settings() -> dict:
    """Last-used IP/port/address per device, keyed by a short device tag."""
    try:
        with open(CONNECTION_SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_connection_setting(key: str, value) -> None:
    settings = load_connection_settings()
    settings[key] = value
    try:
        tmp = CONNECTION_SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, CONNECTION_SETTINGS_FILE)
    except Exception as e:
        print(f"[Settings] Failed to save {CONNECTION_SETTINGS_FILE}: {e}")


def persist_spinbox(spin, key: str) -> None:
    """Restores `spin`'s value from connection_settings.json under `key` (if
    a value was saved previously) and wires it to auto-save on every change,
    so numeric fields — sweep ranges, set-points, dwell times, etc. — survive
    between sessions without needing their own explicit Set/Run click to
    "commit" them. Deliberately NOT used for the DAQ Control per-pin output
    spinboxes — restoring old output values automatically on launch is a
    hardware-safety footgun in a way a sweep parameter or wavelength
    set-point isn't."""
    settings = load_connection_settings()
    if key in settings:
        try:
            spin.setValue(settings[key])
        except Exception:
            pass
    spin.valueChanged.connect(lambda v: save_connection_setting(key, v))


MODE_RANGES = {
    "voltage": (-10.0, 10.0, "V",   -1000, 1000),
    "current": (  0.0, 20.0, "mA",      0, 2000),
}

RAMP_TICK_MS = 20
SLEW_RATE_V  = 5.0
SLEW_RATE_MA = 10.0
STEP_V       = SLEW_RATE_V  * (RAMP_TICK_MS / 1000.0)
STEP_MA      = SLEW_RATE_MA * (RAMP_TICK_MS / 1000.0)

# Window sizing — computed once at startup, never auto-resized afterwards.
# MAIN_WINDOW_MAX_H is intentionally set well above any real screen height —
# _size_and_center() always clamps to (available screen height - 60), so
# raising this ceiling just means the window uses whatever room the monitor
# actually has instead of stopping short at an arbitrarily small fixed size.
# This mattered most for the DAQ Control pin list (PinConfigView), whose
# scroll area only got ~450px of a 1000px-tall window — most of a 32-channel
# card's pins were then a pin or two per scroll instead of visible at once.
MAIN_WINDOW_W     = 1000
MAIN_WINDOW_MAX_H = 1400

GLOBAL_REC_TICK_MS = 250   # 4 Hz — global cross-device recorder sample rate

SWEEP_DEFAULT_STEPS    = 10
SWEEP_DEFAULT_DWELL_MS = 500

MOKU_PLOT_WINDOW_S     = 10.0
MOKU_POLL_MS           = 100
MOKU_SHUNT_OHMS        = 100.0

AO333_GUARDIAN_POLL_MS = 50

BRIDGE_PORT       = 57333
BRIDGE_PYTHON     = r".venv32\Scripts\python.exe"
BRIDGE_SCRIPT     = r"code\UeiDaq_gui\ao333_bridge.py"

READBACK_DECIMALS      = 6
PLOT_CHUNK_MS          = 100
CMP_PLOT_WINDOW_S      = 10.0
COREDAQ_PLOT_WINDOW_S  = 30.0

# ══════════════════════════════════════════════════════════════════════════════
# DAQ — WORKERS & SESSIONS
# ══════════════════════════════════════════════════════════════════════════════

class MokuSession:
    """Wraps moku Oscilloscope. get_sample() -> (ch1_v, ch2_v) or None."""

    def __init__(self):
        self._osc = None

    def connect(self, ip: str):
        self.disconnect()
        if not HAS_MOKU:
            raise RuntimeError("moku library not installed")
        self._osc = Oscilloscope(ip, force_connect=True)
        self._osc.set_timebase(-0.1, 0.0)
        self._osc.set_frontend(1, impedance='1MOhm', coupling='DC', range='10Vpp')
        self._osc.set_frontend(2, impedance='1MOhm', coupling='DC', range='10Vpp')
        print(f"[Moku] Connected to {ip}")

    def get_sample(self):
        if self._osc is None:
            return None
        try:
            data = self._osc.get_data()
            ch1 = float(np.mean(data['ch1'])) if data.get('ch1') else 0.0
            ch2 = float(np.mean(data['ch2'])) if data.get('ch2') else 0.0
            return (ch1, ch2)
        except Exception as e:
            print(f"[Moku] get_sample error: {e}")
            return None

    def disconnect(self):
        try:
            if self._osc is not None:
                self._osc.relinquish_ownership()
        except Exception:
            pass
        self._osc = None

    @property
    def connected(self):
        return self._osc is not None


class MokuWorker(QObject):
    """
    Runs on a QThread. Handles the blocking Moku network calls
    (connect + periodic get_data) and emits signals back to the GUI thread.
    """
    connected    = pyqtSignal()
    connect_err  = pyqtSignal(str)
    sample_ready = pyqtSignal(float, float)
    lost         = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.session   = MokuSession()
        self._running  = False
        self._timer    = None          # created in start_polling (worker thread)

    def do_connect(self, ip: str):
        try:
            self.session.connect(ip)
            self.connected.emit()
        except Exception as e:
            self.connect_err.emit(str(e))

    def start_polling(self):
        self._running = True
        self._timer   = QTimer()
        self._timer.setInterval(MOKU_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def stop_polling(self):
        self._running = False
        if self._timer:
            self._timer.stop()

    def do_disconnect(self):
        self.stop_polling()
        self.session.disconnect()

    def _poll(self):
        if not self._running:
            return
        sample = self.session.get_sample()
        if sample is None:
            self.stop_polling()
            self.lost.emit()
            return
        self.sample_ready.emit(sample[0], sample[1])


class AO333ReadbackWorker(QObject):
    """
    Runs on a background QThread.
    Connects to ao333_bridge.py which streams JSON lines as fast as the
    Guardian ADC allows. Buffers the latest reading and emits readback_ready
    at AO333_GUARDIAN_POLL_MS for GUI updates.
    """
    readback_ready = pyqtSignal(list)
    error          = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._sock       = None
        self._running    = False
        self._timer      = None
        self._latest     = [0.0] * NUM_PINS
        self._buf        = ""
        self._stream_thread = None

    def start(self):
        self.stop()
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2.0)
            self._sock.connect(("127.0.0.1", BRIDGE_PORT))
            self._sock.settimeout(0.5)
            self._buf    = ""
            self._latest = [0.0] * NUM_PINS
            print("[AO333] Connected to bridge — streaming mode")
        except Exception as e:
            msg = f"Cannot connect to bridge on port {BRIDGE_PORT}: {e}"
            print(f"[AO333] {msg}")
            self.error.emit(msg)
            self._sock = None
            return

        self._running = True

        import threading
        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True)
        self._stream_thread.start()

        self._timer = QTimer()
        self._timer.setInterval(AO333_GUARDIAN_POLL_MS)
        self._timer.timeout.connect(self._emit_latest)
        self._timer.start()

    def _stream_loop(self):
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096).decode("utf-8")
                if not chunk:
                    break
                self._buf += chunk
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("ERROR"):
                        print(f"[AO333] Bridge error: {line}")
                        continue
                    try:
                        self._latest = json.loads(line)
                    except Exception:
                        pass
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[AO333] Stream error: {e}")
                break
        self._running = False

    def _emit_latest(self):
        if self._running:
            self.readback_ready.emit(list(self._latest))
        else:
            self.stop()
            self.error.emit("Bridge stream ended")

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        try:
            if self._sock:
                self._sock.sendall(b"QUIT\n")
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None


# ── Moku live plot widget ──────────────────────────────────────────────────────

class MokuWidget(QGroupBox):
    """
    Home-screen panel. Moku network I/O runs on a background QThread via
    MokuWorker so the GUI never blocks on connect or get_data.
    Emits moku_sample(ch1_v, ch2_v) on every poll for PinConfigView recording.
    """
    moku_sample = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__("Moku:Go — Live Readback", parent)
        self._t   = 0.0
        self._ts1 = []
        self._vs1 = []
        self._ts2 = []
        self._vs2 = []

        self._thread = QThread()
        self._worker = MokuWorker()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        self._worker.connected.connect(self._on_connected)
        self._worker.connect_err.connect(self._on_connect_err)
        self._worker.sample_ready.connect(self._on_sample)
        self._worker.lost.connect(self._on_lost)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        conn_row = QHBoxLayout()
        self._status_lbl = QLabel("○")
        self._status_lbl.setFixedWidth(14)
        conn_row.addWidget(self._status_lbl)
        conn_row.addWidget(QLabel("IP:"))
        self._ip_edit = QLineEdit(load_connection_settings().get("moku_ip", MOKU_IP))
        self._ip_edit.setPlaceholderText("e.g. 192.168.73.1")
        self._ip_edit.setFixedWidth(140)
        conn_row.addWidget(self._ip_edit)
        self._connect_btn    = QPushButton("Connect")
        self._disconnect_btn = QPushButton("✕")
        self._connect_btn.setFixedWidth(80)
        self._disconnect_btn.setFixedSize(24, 24)
        self._disconnect_btn.setVisible(False)
        self._connect_btn.clicked.connect(self._connect)
        self._disconnect_btn.clicked.connect(self._disconnect)
        conn_row.addWidget(self._connect_btn)
        conn_row.addWidget(self._disconnect_btn)
        conn_row.addStretch()
        layout.addLayout(conn_row)

        readout_row = QHBoxLayout()
        self._ch1_v_lbl  = QLabel("Ch1:  — V")
        self._ch1_ma_lbl = QLabel("— mA")
        self._ch2_v_lbl  = QLabel("Ch2:  — V")
        self._ch2_ma_lbl = QLabel("— mA")
        for lbl in (self._ch1_v_lbl, self._ch1_ma_lbl,
                    self._ch2_v_lbl, self._ch2_ma_lbl):
            lbl.setMinimumWidth(90)
        readout_row.addWidget(self._ch1_v_lbl)
        readout_row.addWidget(self._ch1_ma_lbl)
        readout_row.addSpacing(20)
        readout_row.addWidget(self._ch2_v_lbl)
        readout_row.addWidget(self._ch2_ma_lbl)
        readout_row.addStretch()
        layout.addLayout(readout_row)

        if HAS_PYQTGRAPH:
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setLabel('left',   'Voltage', units='V')
            self._plot_widget.setLabel('bottom', 'Time',    units='s')
            self._plot_widget.setMinimumHeight(180)
            self._plot_widget.addLegend()
            self._curve1 = self._plot_widget.plot(
                [], [], pen=pg.mkPen(C_BLUE, width=2), name='Ch1')
            self._curve2 = self._plot_widget.plot(
                [], [], pen=pg.mkPen(C_RED, width=2), name='Ch2')
            layout.addWidget(self._plot_widget)
            note = QLabel(
                f"  I = V / {MOKU_SHUNT_OHMS:.2f} Ω   "
                f"Ch1 (blue),  Ch2 (red)")
            note.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
            layout.addWidget(note)
        else:
            layout.addWidget(QLabel(
                "(install pyqtgraph to enable live plot: uv pip install pyqtgraph)"))

    # ── connect / disconnect ───────────────────────────────────────────────────

    def _connect(self):
        ip = self._ip_edit.text().strip()
        if not ip:
            print("[Moku] Enter an IP address first")
            return
        save_connection_setting("moku_ip", ip)
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Connecting…")
        QTimer.singleShot(0, lambda: self._worker.do_connect(ip))

    def _on_connected(self):
        self._t = 0.0; self._ts1=[]; self._vs1=[]; self._ts2=[]; self._vs2=[]
        self._status_lbl.setText("●")
        self._status_lbl.setStyleSheet(f"color: {C_GREEN};")
        self._connect_btn.setVisible(False)
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")
        self._disconnect_btn.setVisible(True)
        self._ip_edit.setEnabled(False)
        QTimer.singleShot(0, self._worker.start_polling)

    def _on_connect_err(self, msg: str):
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")
        print(f"[Moku] Connect error: {msg}")
        w = self.window()
        if hasattr(w, 'status_bar'):
            w.status_bar.showMessage(f"Moku error: {msg}")

    def _disconnect(self):
        QTimer.singleShot(0, self._worker.do_disconnect)
        self._status_lbl.setText("○")
        self._status_lbl.setStyleSheet("")
        self._connect_btn.setVisible(True)
        self._disconnect_btn.setVisible(False)
        self._ip_edit.setEnabled(True)
        self._ch1_v_lbl.setText("Ch1:  — V");  self._ch1_ma_lbl.setText("— mA")
        self._ch2_v_lbl.setText("Ch2:  — V");  self._ch2_ma_lbl.setText("— mA")

    def _on_lost(self):
        self._disconnect()

    # ── sample received (GUI thread via signal) ────────────────────────────────

    def _on_sample(self, ch1_v: float, ch2_v: float):
        ch1_ma = (ch1_v / MOKU_SHUNT_OHMS) * 1000.0
        ch2_ma = (ch2_v / MOKU_SHUNT_OHMS) * 1000.0

        self._ch1_v_lbl.setText(f"Ch1:  {ch1_v:+.4f} V")
        self._ch1_ma_lbl.setText(f"{ch1_ma:+.3f} mA")
        self._ch2_v_lbl.setText(f"Ch2:  {ch2_v:+.4f} V")
        self._ch2_ma_lbl.setText(f"{ch2_ma:+.3f} mA")

        self.moku_sample.emit(ch1_v, ch2_v)

        if not HAS_PYQTGRAPH:
            return

        self._t += MOKU_POLL_MS / 1000.0
        self._ts1.append(self._t); self._vs1.append(ch1_v)
        self._ts2.append(self._t); self._vs2.append(ch2_v)

        cutoff = self._t - MOKU_PLOT_WINDOW_S
        while self._ts1 and self._ts1[0] < cutoff:
            self._ts1.pop(0); self._vs1.pop(0)
        while self._ts2 and self._ts2[0] < cutoff:
            self._ts2.pop(0); self._vs2.pop(0)

        self._curve1.setData(self._ts1, self._vs1)
        self._curve2.setData(self._ts2, self._vs2)

        if self._ts1:
            x_max = self._ts1[-1]
            self._plot_widget.setXRange(x_max - MOKU_PLOT_WINDOW_S, x_max, padding=0)

    def cleanup(self):
        self._worker.stop_polling()
        self._worker.session.disconnect()
        self._thread.quit()
        self._thread.wait(2000)


# ── Per-card session ───────────────────────────────────────────────────────────

class CardSession:
    def __init__(self, card_index: int):
        self.card_index = card_index
        self.session    = None
        self.writer     = None
        self.mode       = CARDS[card_index]["mode"]
        self.dev        = CARDS[card_index]["dev"]
        self.num_pins   = CARDS[card_index].get("channels", NUM_PINS)
        self.values     = [0.0] * self.num_pins
        self._targets   = [0.0] * self.num_pins
        min_val, max_val, unit, _, _ = MODE_RANGES[self.mode]
        self.min_val, self.max_val, self.unit = min_val, max_val, unit
        self._step = STEP_V if self.mode == "voltage" else STEP_MA

        self._timer = QTimer()
        self._timer.setInterval(RAMP_TICK_MS)
        self._timer.timeout.connect(self._ramp_tick)

        self._sweep_steps         = []
        self._sweep_pins          = []
        self._sweep_step_idx      = 0
        self._sweep_callback      = None
        self._sweep_done_callback = None
        self._sweep_dwell_ms      = SWEEP_DEFAULT_DWELL_MS
        self._sweep_timer         = QTimer()
        self._sweep_timer.setSingleShot(True)
        self._sweep_timer.timeout.connect(self._sweep_next_step)

    def connect(self):
        self.disconnect()
        if not HAS_UEIDAQ:
            raise RuntimeError("UeiDaq library not installed")
        self.session = UeiDaq.CUeiSession()
        print(f"Connecting: pdna://{CUBE_IP}/{self.dev}/Ao0:{self.num_pins-1}, "
              f"mode: {self.mode}, range: {self.min_val} to {self.max_val}")
        if self.mode == "voltage":
            self.session.CreateAOChannel(
                f"pdna://{CUBE_IP}/{self.dev}/Ao0:{self.num_pins-1}",
                self.min_val, self.max_val)
        else:
            self.session.CreateAOCurrentChannel(
                f"pdna://{CUBE_IP}/{self.dev}/Ao0:{self.num_pins-1}",
                self.min_val, self.max_val)
        self.session.ConfigureTimingForSimpleIO()
        self.writer = UeiDaq.CUeiAnalogScaledWriter(self.session.GetDataStream())

    def ramp_to(self, targets: list):
        self._targets = list(targets)
        if not self._timer.isActive():
            self._timer.start()

    def _ramp_tick(self):
        next_vals = []
        for current, target in zip(self.values, self._targets):
            diff = target - current
            if abs(diff) <= self._step:
                next_vals.append(target)
            else:
                next_vals.append(current + self._step * (1 if diff > 0 else -1))
        try:
            self.write(next_vals)
        except Exception as e:
            print(f"[Ramp] write to {self.dev} failed: {e}")
            self._timer.stop()
            return
        if next_vals == self._targets:
            self._timer.stop()

    def write(self, values: list):
        if not self.connected:
            raise RuntimeError("Session not connected")
        # Every write path (Set, Write All, Set All To, ramp, sweep, wave)
        # funnels through here, so this is the one place a confirmed
        # PIN_REMAP entry needs to be applied — `values` stays in GUI/logical
        # pin order for everything else (self.values, the spinboxes, etc.);
        # only what's actually sent to the hardware gets reordered.
        remap = PIN_REMAP.get(self.dev)
        if remap:
            # Build the physical-channel array by placing each logical pin's
            # value onto the physical channel it actually drives. Iterating
            # EVERY logical pin through remap_pin() (identity for unlisted
            # pins) guarantees a complete, leak-free assignment for any
            # bijection. The old loop iterated only the listed swap entries and
            # left every other position holding its stale same-index copy —
            # correct for a clean 0<->31 swap, but silently wrong the moment
            # the map is anything else (which is exactly the situation we're
            # now in). This is the same remap_pin() lookup the Guardian
            # readback path uses, so writes and readbacks stay in agreement.
            physical = list(values)
            for logical_pin in range(len(values)):
                phys = remap_pin(self.dev, logical_pin)
                if 0 <= phys < len(physical):
                    physical[phys] = values[logical_pin]
        else:
            physical = values
        scaled = [v / 1000.0 for v in physical] if self.mode == "current" else physical
        self.writer.WriteSingleScan(scaled)
        self.values = list(values)

    def start_wave(self, pins: list, waveform: str, freq: float,
                   amplitude: float, offset: float, tick_ms: int,
                   callback=None):
        self.stop_wave()
        self._wave_pins      = list(pins)
        self._wave_form      = waveform
        self._wave_freq      = freq
        self._wave_amplitude = amplitude
        self._wave_offset    = offset
        self._wave_t         = 0.0
        self._wave_tick_ms   = tick_ms
        self._wave_callback  = callback
        self._wave_timer     = QTimer()
        self._wave_timer.setInterval(tick_ms)
        self._wave_timer.timeout.connect(self._wave_tick)
        self._wave_timer.start()

    def _wave_tick(self):
        fn  = math.sin if self._wave_form == "sin" else math.cos
        val = self._wave_offset + self._wave_amplitude * fn(
            2 * math.pi * self._wave_freq * self._wave_t)
        val = max(self.min_val, min(self.max_val, val))
        targets = list(self.values)
        for p in self._wave_pins:
            targets[p] = val
        try:
            self.write(targets)
        except Exception:
            self.stop_wave()
            return
        self._wave_t += self._wave_tick_ms / 1000.0
        if self._wave_callback:
            self._wave_callback(list(self._wave_pins), val)

    def stop_wave(self):
        if hasattr(self, '_wave_timer') and self._wave_timer.isActive():
            self._wave_timer.stop()
        self._wave_callback = None

    def start_sweep(self, pins: list, start: float, stop: float,
                    steps: int, dwell_ms: int, callback, done_callback=None):
        self.stop_sweep()
        self._sweep_pins          = list(pins)
        self._sweep_dwell_ms      = dwell_ms
        self._sweep_callback      = callback
        self._sweep_done_callback = done_callback
        self._sweep_step_idx      = 0
        if steps < 2: steps = 2
        self._sweep_steps = [
            start + (stop - start) * i / (steps - 1) for i in range(steps)]
        self._sweep_next_step()

    def stop_sweep(self):
        self._sweep_timer.stop()
        if hasattr(self, '_sweep_poll') and self._sweep_poll.isActive():
            self._sweep_poll.stop()
        self._sweep_steps         = []
        self._sweep_callback      = None
        self._sweep_done_callback = None

    def _sweep_next_step(self):
        if self._sweep_step_idx >= len(self._sweep_steps):
            done_cb = self._sweep_done_callback
            self.stop_sweep()
            if done_cb: done_cb()
            return
        target_val = self._sweep_steps[self._sweep_step_idx]
        targets    = list(self.values)
        for p in self._sweep_pins:
            targets[p] = target_val
        self._sweep_pending_target = target_val
        self.ramp_to(targets)
        self._sweep_poll = QTimer()
        self._sweep_poll.setInterval(RAMP_TICK_MS)
        self._sweep_poll.timeout.connect(self._sweep_check_arrived)
        self._sweep_poll.start()

    def _sweep_check_arrived(self):
        # All swept pins share one target and the same slew rate, so they
        # converge together — only advance once every one of them has
        # actually arrived within tolerance, not just the first.
        if all(abs(self.values[p] - self._sweep_pending_target) <= self._step
               for p in self._sweep_pins):
            self._sweep_poll.stop()
            total = len(self._sweep_steps)
            idx   = self._sweep_step_idx
            if self._sweep_callback:
                self._sweep_callback(
                    list(self._sweep_pins), self._sweep_pending_target, idx + 1, total)
            self._sweep_step_idx += 1
            self._sweep_timer.start(self._sweep_dwell_ms)

    def zero(self):
        self.stop_sweep()
        self.ramp_to([0.0] * self.num_pins)

    def zero_immediate(self):
        self.stop_sweep()
        self.stop_wave()
        self._timer.stop()
        self._targets = [0.0] * self.num_pins
        try:
            self.write([0.0] * self.num_pins)
        except Exception:
            pass

    def disconnect(self):
        self.stop_sweep()
        self.stop_wave()
        self._timer.stop()
        try:
            if self.session:
                self.session.Stop()
                del self.session, self.writer
        except Exception:
            pass
        self.session = self.writer = None

    @property
    def connected(self):
        return self.session is not None


# ── DAQ box widget ─────────────────────────────────────────────────────────────

class DAQBoxWidget(QWidget):
    card_clicked      = pyqtSignal(int)
    card_disconnected = pyqtSignal(int)

    def __init__(self, card_sessions: dict, parent=None):
        super().__init__(parent)
        self.card_sessions = card_sessions
        self._rows = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        for i, info in CARDS.items():
            row = QWidget()
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(0, 2, 0, 2)
            rl.setSpacing(6)

            status_lbl  = QLabel("○")
            status_lbl.setFixedWidth(14)
            name_lbl    = QLabel(info["label"])
            name_lbl.setMinimumWidth(200)
            if not info["available"]:
                name_lbl.setEnabled(False)

            connect_btn = QPushButton("Connect")
            connect_btn.setFixedWidth(80)
            connect_btn.setEnabled(info["available"] and HAS_UEIDAQ)

            open_btn = QPushButton("Open")
            open_btn.setFixedWidth(80)
            open_btn.setVisible(False)
            open_btn.setToolTip("Open pin controls")

            x_btn = QPushButton("✕")
            x_btn.setFixedSize(24, 24)
            x_btn.setVisible(False)
            x_btn.setToolTip("Disconnect and zero outputs")

            if info["available"]:
                connect_btn.clicked.connect(lambda _, idx=i: self.card_clicked.emit(idx))
                open_btn.clicked.connect(   lambda _, idx=i: self.card_clicked.emit(idx))
                x_btn.clicked.connect(      lambda _, idx=i: self.card_disconnected.emit(idx))

            rl.addWidget(status_lbl)
            rl.addWidget(name_lbl, stretch=1)
            rl.addWidget(connect_btn)
            rl.addWidget(open_btn)
            rl.addWidget(x_btn)
            layout.addWidget(row)
            self._rows[i] = (status_lbl, connect_btn, open_btn, x_btn)

        layout.addStretch()

    def refresh(self):
        for i, info in CARDS.items():
            if not info["available"]: continue
            status_lbl, connect_btn, open_btn, x_btn = self._rows[i]
            connected = self.card_sessions[i].connected
            status_lbl.setText("●" if connected else "○")
            status_lbl.setStyleSheet(f"color: {C_GREEN};" if connected else "")
            connect_btn.setVisible(not connected)
            open_btn.setVisible(connected)
            x_btn.setVisible(connected)


# ── Post-recording plot window ─────────────────────────────────────────────────

class RecordingPlotWindow(QWidget):
    """
    Shown after a recording session ends.
    Displays time-series (current or voltage vs time) and optionally V vs I.
    """
    def __init__(self, card_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Recording — {card_label}")
        self.resize(700, 520)
        self._card_label = card_label

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if HAS_PYQTGRAPH:
            self._ts_plot = pg.PlotWidget()
            self._ts_plot.setLabel('bottom', 'Time', units='s')
            self._ts_plot.setMinimumHeight(200)
            self._ts_curve = self._ts_plot.plot([], [], pen=pg.mkPen(C_BLUE, width=2))
            layout.addWidget(self._ts_plot)

            self._vi_plot = pg.PlotWidget()
            self._vi_plot.setMinimumHeight(200)
            self._vi_scatter = self._vi_plot.plot(
                [], [], pen=None,
                symbol='o', symbolSize=5,
                symbolBrush='#00FF88', symbolPen=None)
            self._vi_plot.setVisible(False)
            layout.addWidget(self._vi_plot)
        else:
            layout.addWidget(QLabel("pyqtgraph required for plots"))
            self._ts_plot   = None
            self._vi_plot   = None

        btn_row = QHBoxLayout()
        self._vi_toggle_btn = QPushButton("Show V vs I")
        self._vi_toggle_btn.setFixedWidth(110)
        self._vi_toggle_btn.setCheckable(True)
        self._vi_toggle_btn.toggled.connect(self._toggle_vi)
        btn_row.addWidget(self._vi_toggle_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _toggle_vi(self, checked: bool):
        if self._vi_plot:
            self._vi_plot.setVisible(checked)
        self._vi_toggle_btn.setText("Hide V vs I" if checked else "Show V vs I")
        self.adjustSize()

    def show_data(self, records: list, mode: str, show_vi: bool):
        if not records:
            return

        ts   = [r['t']      for r in records]
        mvs  = [r['moku_v'] for r in records]

        if mode == 'current':
            ys     = [(v / MOKU_SHUNT_OHMS) * 1000.0 for v in mvs]
            y_lbl  = 'Current (mA)'
            color  = C_BLUE
        else:
            ys     = mvs
            y_lbl  = 'Voltage (V)'
            color  = C_GOLD

        if HAS_PYQTGRAPH:
            self._ts_plot.setLabel('left', y_lbl)
            self._ts_curve.setPen(pg.mkPen(color, width=2))
            self._ts_curve.setData(ts, ys)

            src = "Guardian" if mode == "voltage" else "Moku"
            xs_vi = [float(np.mean(r['daq'])) for r in records]
            self._vi_plot.setLabel('bottom',
                'DAQ Output (mA)' if mode == 'current' else 'DAQ Output (V)')
            self._vi_plot.setLabel('left',
                f'{src} Measured (mA)' if mode == 'current' else f'{src} Measured (V)')
            self._vi_scatter.setData(xs_vi, ys)

        if show_vi and HAS_PYQTGRAPH:
            self._vi_toggle_btn.setChecked(True)

        self.show()
        self.raise_()


# ── Live comparison plot window ────────────────────────────────────────────────

class LiveComparisonPlot(QWidget):
    """
    Floating window showing software output vs readback in real time.
    Pin selector lets you choose which pin's commanded value to compare.
    """

    def __init__(self, card_label: str, mode: str, num_pins: int = NUM_PINS, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Output vs Readback — {card_label}")
        self.resize(620, 640)
        self._mode = mode

        self._cmd_ts  = []
        self._cmd_vs  = []
        self._meas_ts = []
        self._meas_vs = []
        self._t       = 0.0
        self._pin     = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        pin_row = QHBoxLayout()
        pin_row.addWidget(QLabel("Pin:"))
        self._pin_combo = QComboBox()
        for i in range(num_pins):
            self._pin_combo.addItem(f"Pin {i:02d}", i)
        self._pin_combo.setFixedWidth(80)
        self._pin_combo.currentIndexChanged.connect(self._on_pin_changed)
        pin_row.addWidget(self._pin_combo)
        pin_row.addSpacing(16)
        self._src_lbl = QLabel("")
        self._src_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        pin_row.addWidget(self._src_lbl)
        pin_row.addStretch()
        layout.addLayout(pin_row)

        y_unit = 'mA' if mode == 'current' else 'V'

        if HAS_PYQTGRAPH:
            self._ts_plot = pg.PlotWidget()
            self._ts_plot.setLabel('left',   f'Value ({y_unit})')
            self._ts_plot.setLabel('bottom', 'Time', units='s')
            self._ts_plot.getAxis('left').enableAutoSIPrefix(False)
            self._ts_plot.setMinimumHeight(200)
            self._ts_plot.addLegend()
            self._cmd_curve  = self._ts_plot.plot(
                [], [], pen=pg.mkPen(C_GOLD, width=2), name='Commanded')
            self._meas_curve = self._ts_plot.plot(
                [], [], pen=pg.mkPen('#00FF88', width=2), name='Measured')
            layout.addWidget(self._ts_plot)

            self._sc_plot = pg.PlotWidget()
            self._sc_plot.getAxis('bottom').enableAutoSIPrefix(False)
            self._sc_plot.getAxis('left').enableAutoSIPrefix(False)
            self._sc_plot.setLabel('bottom', f'Commanded ({y_unit})')
            self._sc_plot.setLabel('left',   f'Measured ({y_unit})')
            self._sc_plot.setMinimumHeight(200)
            self._scatter = self._sc_plot.plot(
                [], [], pen=None, symbol='o', symbolSize=4,
                symbolBrush=C_BLUE, symbolPen=None)
            layout.addWidget(self._sc_plot)
        else:
            layout.addWidget(QLabel("pyqtgraph required"))
            self._ts_plot = self._sc_plot = None

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(70)
        clear_btn.clicked.connect(self.clear)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_source_label(self, txt: str):
        self._src_lbl.setText(txt)

    def _on_pin_changed(self):
        self._pin = self._pin_combo.currentData()
        self.clear()

    def get_pin(self) -> int:
        return self._pin

    def push(self, commanded: float, measured: float, dt: float = 0.1):
        self._t += dt
        self._cmd_ts.append(self._t);  self._cmd_vs.append(commanded)
        self._meas_ts.append(self._t); self._meas_vs.append(measured)

        cutoff = self._t - CMP_PLOT_WINDOW_S
        for ts, vs in [(self._cmd_ts, self._cmd_vs),
                       (self._meas_ts, self._meas_vs)]:
            while ts and ts[0] < cutoff:
                ts.pop(0); vs.pop(0)
        # setData handled by PinConfigView._repaint_plots

    def clear(self):
        self._t = 0.0
        self._cmd_ts=[]; self._cmd_vs=[]
        self._meas_ts=[]; self._meas_vs=[]
        if HAS_PYQTGRAPH:
            self._cmd_curve.setData([], [])
            self._meas_curve.setData([], [])
            self._scatter.setData([], [])


# ── Pin config view ────────────────────────────────────────────────────────────

class PinConfigView(QWidget):
    back_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card_session: CardSession = None
        self._syncing = False
        self._last_recording_csv = None
        self._last_sweep_csv     = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.setFixedWidth(80)
        back_btn.clicked.connect(self.back_clicked.emit)
        self.card_title = QLabel("DEV0")
        f = self.card_title.font(); f.setBold(True); f.setPointSize(12)
        self.card_title.setFont(f)
        self.badge = QLabel("VOLTAGE")
        self.badge.setStyleSheet(
            f"color: {C_BLUE}; border: 1px solid {C_BLUE};"
            "border-radius: 3px; padding: 1px 6px; font-weight: bold;")
        header.addWidget(back_btn)
        header.addSpacing(8)
        header.addWidget(self.card_title)
        header.addStretch()
        header.addWidget(QLabel("Mode:"))
        header.addWidget(self.badge)
        root.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # No inner QScrollArea here on purpose: DAQPanel already wraps this
        # entire PinConfigView in an outer QScrollArea (see pin_scroll in
        # DAQPanel.__init__), so the whole page scrolls together if the
        # window is too short. Nesting a second QScrollArea just for the pin
        # list collapses it to Qt's tiny default sizeHint (~256x192px)
        # instead of its actual content size, which is what made pin
        # adjustment happen inside a cramped little box even on tall
        # windows — the fix is one scroll area, not two.
        #
        # Two side-by-side columns (pins 0-15 / 16-31) instead of one long
        # vertical list — same total row count fits in roughly half the
        # window height, so a 32-channel card needs far less scrolling to
        # see everything at once.
        PIN_COL_SPLIT = MAX_PINS // 2   # 16

        pin_container = QWidget()
        outer_pin_lay = QHBoxLayout(pin_container)
        outer_pin_lay.setSpacing(16)
        outer_pin_lay.setContentsMargins(4, 4, 4, 4)

        self.spinboxes, self.sliders = [], []
        self._readback_lbls = []
        self._name_edits  = []
        self._pin_rows    = []
        self._active_n    = NUM_PINS
        self._channel_names = self._load_channel_names()

        self._group_seps  = []   # [(first_pin_idx_in_group, separator_widget), ...]
        self._pin_columns = []   # column container widgets, hidden when empty

        for col in range(2):
            col_widget = QWidget()
            col_lay = QVBoxLayout(col_widget)
            col_lay.setSpacing(2)
            col_lay.setContentsMargins(0, 0, 0, 0)

            col_row = QHBoxLayout()
            for text, width in [("Pin", 50), ("Name", 90), ("Value", 120), ("Slider", -1), ("", 60), ("Readback", 90)]:
                lbl = QLabel(text)
                if width > 0: lbl.setFixedWidth(width)
                col_row.addWidget(lbl)
            col_lay.addLayout(col_row)

            sep2 = QFrame()
            sep2.setFrameShape(QFrame.Shape.HLine)
            sep2.setFrameShadow(QFrame.Shadow.Sunken)
            col_lay.addWidget(sep2)

            self._pin_columns.append((col_widget, col_lay))
            outer_pin_lay.addWidget(col_widget)

        for i in range(MAX_PINS):
            col_widget, col_lay = self._pin_columns[i // PIN_COL_SPLIT]
            local_i = i % PIN_COL_SPLIT
            if local_i > 0 and local_i % 4 == 0:
                group_sep = QFrame()
                group_sep.setFrameShape(QFrame.Shape.HLine)
                group_sep.setStyleSheet(f"color: {C_GRAY};")
                group_sep.setFixedHeight(1)
                self._group_seps.append((i, group_sep))
                col_lay.addWidget(group_sep)

            row_widget = QWidget()
            row_widget.setStyleSheet(
                f"background-color: {'#1D2127' if (local_i // 4) % 2 else 'transparent'};")
            rl  = QHBoxLayout(row_widget)
            rl.setContentsMargins(4, 1, 4, 1)
            rl.setSpacing(6)
            lbl = QLabel(f"Pin {i:02d}")
            lbl.setFixedWidth(50)
            name_edit = QLineEdit(self._channel_names.get(str(i), ""))
            name_edit.setPlaceholderText("(nickname)")
            name_edit.setFixedWidth(90)
            name_edit.editingFinished.connect(lambda idx=i: self._on_name_edited(idx))
            sb  = NoScrollDoubleSpinBox()
            sb.setDecimals(3)
            sb.setSingleStep(0.1)
            sb.setValue(0.0)
            sb.setFixedWidth(120)
            sl  = QSlider(Qt.Orientation.Horizontal)
            sl.setValue(0)
            sl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            set_btn = QPushButton("Set")
            set_btn.setFixedWidth(60)
            set_btn.clicked.connect(lambda _, idx=i: self._set_pin(idx))
            sb.valueChanged.connect(lambda val, idx=i: self._sb_changed(idx, val))
            sl.valueChanged.connect(lambda val, idx=i: self._sl_changed(idx, val))

            rb_lbl = QLabel("—")
            rb_lbl.setFixedWidth(90)
            rb_lbl.setStyleSheet(f"color: {C_BLUE}; font-size: 10px;")
            rb_lbl.setToolTip("Guardian ADC readback (Dev2 only, first 8 channels)")
            rb_lbl.setVisible(False)

            rl.addWidget(lbl); rl.addWidget(name_edit); rl.addWidget(sb)
            rl.addWidget(sl, stretch=1); rl.addWidget(set_btn)
            rl.addWidget(rb_lbl)
            self.spinboxes.append(sb)
            self.sliders.append(sl)
            self._readback_lbls.append(rb_lbl)
            self._name_edits.append(name_edit)
            self._pin_rows.append(row_widget)
            col_lay.addWidget(row_widget)

        for _, col_lay in self._pin_columns:
            col_lay.addStretch()
        self._set_active_channels(NUM_PINS)
        root.addWidget(pin_container)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep3)

        bottom = QHBoxLayout()
        write_btn  = QPushButton("Write All")
        zero_btn   = QPushButton("Zero All")
        self._ramp_chk = QCheckBox("Ramp")
        self._ramp_chk.setChecked(True)
        self._ramp_chk.setToolTip(
            "Checked = ramp at slew rate\nUnchecked = instant jump")
        write_btn.clicked.connect(lambda: self._write_all())
        zero_btn.clicked.connect(self._zero_all)
        bottom.addWidget(write_btn)
        bottom.addWidget(zero_btn)
        bottom.addSpacing(16)
        bottom.addWidget(self._ramp_chk)
        bottom.addSpacing(16)
        bottom.addWidget(QLabel("Set All To:"))
        self._set_all_spin = NoScrollDoubleSpinBox()
        self._set_all_spin.setDecimals(3)
        self._set_all_spin.setFixedWidth(100)
        bottom.addWidget(self._set_all_spin)
        set_all_btn = QPushButton("Apply")
        set_all_btn.setToolTip("Set every active pin's value box to the amount above, then write it")
        set_all_btn.clicked.connect(self._set_all_to)
        bottom.addWidget(set_all_btn)
        bottom.addStretch()
        root.addLayout(bottom)

        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.HLine)
        sep4.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep4)

        sweep_group = QGroupBox("Sweep")
        sg = QVBoxLayout(sweep_group)
        sg.setSpacing(6)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Pins:"))
        self.sweep_pin_combo = MultiPinSelector("No pins selected")
        for i in range(NUM_PINS):
            self.sweep_pin_combo.addCheckableItem(f"Pin {i:02d}", i)
        self.sweep_pin_combo.setFixedWidth(140)
        self.sweep_pin_combo.setToolTip(
            "Every checked pin sweeps the same Start→Stop range together, "
            "in lockstep")
        row1.addWidget(self.sweep_pin_combo)
        self.sweep_select_all_btn = QPushButton("All")
        self.sweep_select_all_btn.setFixedWidth(36)
        self.sweep_select_all_btn.setToolTip("Check every pin for the sweep")
        self.sweep_select_all_btn.clicked.connect(self.sweep_pin_combo.select_all)
        row1.addWidget(self.sweep_select_all_btn)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Start:"))
        self.sweep_start = NoScrollDoubleSpinBox()
        self.sweep_start.setDecimals(3)
        self.sweep_start.setFixedWidth(90)
        persist_spinbox(self.sweep_start, "daq_sweep_start")
        row1.addWidget(self.sweep_start)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Stop:"))
        self.sweep_stop = NoScrollDoubleSpinBox()
        self.sweep_stop.setDecimals(3)
        self.sweep_stop.setFixedWidth(90)
        persist_spinbox(self.sweep_stop, "daq_sweep_stop")
        row1.addWidget(self.sweep_stop)
        row1.addStretch()
        sg.addLayout(row1)

        row2 = QHBoxLayout()
        self._sweep_mode_combo = QComboBox()
        self._sweep_mode_combo.addItem("Steps",     "steps")
        self._sweep_mode_combo.addItem("Step size", "stepsize")
        self._sweep_mode_combo.setFixedWidth(90)
        self._sweep_mode_combo.currentIndexChanged.connect(self._on_sweep_mode_toggled)
        self.sweep_steps_sb = NoScrollSpinBox()
        self.sweep_steps_sb.setRange(2, 10000)
        self.sweep_steps_sb.setValue(SWEEP_DEFAULT_STEPS)
        self.sweep_steps_sb.setFixedWidth(70)
        persist_spinbox(self.sweep_steps_sb, "daq_sweep_steps")
        self.sweep_stepsize_sb = NoScrollDoubleSpinBox()
        self.sweep_stepsize_sb.setDecimals(4)
        self.sweep_stepsize_sb.setRange(0.0001, 100.0)
        self.sweep_stepsize_sb.setValue(1.0)
        self.sweep_stepsize_sb.setFixedWidth(90)
        self.sweep_stepsize_sb.setVisible(False)
        persist_spinbox(self.sweep_stepsize_sb, "daq_sweep_stepsize")
        self.sweep_derived_lbl = QLabel("")
        self.sweep_derived_lbl.setMinimumWidth(140)
        row2.addWidget(self._sweep_mode_combo)
        row2.addWidget(self.sweep_steps_sb)
        row2.addWidget(self.sweep_stepsize_sb)
        row2.addSpacing(10)
        row2.addWidget(self.sweep_derived_lbl)
        row2.addStretch()
        sg.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Dwell (ms):"))
        self.sweep_dwell_sb = NoScrollSpinBox()
        self.sweep_dwell_sb.setRange(20, 60000)
        self.sweep_dwell_sb.setValue(SWEEP_DEFAULT_DWELL_MS)
        self.sweep_dwell_sb.setFixedWidth(80)
        persist_spinbox(self.sweep_dwell_sb, "daq_sweep_dwell_ms")
        row3.addWidget(self.sweep_dwell_sb)
        row3.addSpacing(10)
        self.sweep_run_btn  = QPushButton("Run Sweep")
        self.sweep_stop_btn = QPushButton("Stop")
        self.sweep_stop_btn.setEnabled(False)
        self.sweep_run_btn.clicked.connect(self._start_sweep)
        self.sweep_stop_btn.clicked.connect(self._stop_sweep)
        row3.addWidget(self.sweep_run_btn)
        row3.addWidget(self.sweep_stop_btn)
        row3.addStretch()
        sg.addLayout(row3)

        row4 = QHBoxLayout()
        self._sweep_log_chk = QCheckBox("Log CoreDAQ power (all 4 MZIs)")
        self._sweep_log_chk.setChecked(True)
        self._sweep_log_chk.setToolTip(
            "Records all 4 CoreDAQ MZI power readings at each sweep step.\n"
            "On by default so sweep data is never silently missing this — "
            "uncheck only if CoreDAQ isn't part of this run.")
        row4.addWidget(self._sweep_log_chk)
        row4.addSpacing(8)
        row4.addWidget(QLabel("Show:"))
        self._sweep_coredaq_head_combo = QComboBox()
        for h in range(1, 5):
            self._sweep_coredaq_head_combo.addItem(f"MZI {h}", h)
        self._sweep_coredaq_head_combo.setFixedWidth(80)
        row4.addWidget(self._sweep_coredaq_head_combo)
        row4.addSpacing(10)
        self._sweep_power_lbl = QLabel("")
        self._sweep_power_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        row4.addWidget(self._sweep_power_lbl)
        row4.addStretch()
        self._sweep_export_btn = QPushButton("Export CSV…")
        self._sweep_export_btn.setEnabled(False)
        self._sweep_export_btn.clicked.connect(self._export_sweep_power_csv)
        row4.addWidget(self._sweep_export_btn)
        self._sweep_open_btn = QPushButton("📂 Open")
        self._sweep_open_btn.setEnabled(False)
        self._sweep_open_btn.setToolTip("Open the last-exported sweep CSV")
        self._sweep_open_btn.clicked.connect(lambda: open_saved_file(self._last_sweep_csv))
        row4.addWidget(self._sweep_open_btn)
        sg.addLayout(row4)

        root.addWidget(sweep_group)

        self._coredaq_panel = None
        self._sweep_power_log: list = []

        self.sweep_start.valueChanged.connect(self._update_sweep_derived)
        self.sweep_stop.valueChanged.connect(self._update_sweep_derived)
        self.sweep_steps_sb.valueChanged.connect(self._update_sweep_derived)
        self.sweep_stepsize_sb.valueChanged.connect(self._update_sweep_derived)

        wave_group = QGroupBox("Waveform Output")
        wg = QVBoxLayout(wave_group)
        wg.setSpacing(6)

        wrow1 = QHBoxLayout()
        wrow1.addWidget(QLabel("Pins:"))
        self.wave_pin_combo = MultiPinSelector("No pins selected")
        for i in range(NUM_PINS):
            self.wave_pin_combo.addCheckableItem(f"Pin {i:02d}", i)
        self.wave_pin_combo.setFixedWidth(140)
        self.wave_pin_combo.setToolTip(
            "Every checked pin plays the same waveform together, in lockstep")
        wrow1.addWidget(self.wave_pin_combo)
        self.wave_select_all_btn = QPushButton("All")
        self.wave_select_all_btn.setFixedWidth(36)
        self.wave_select_all_btn.setToolTip("Check every pin for the waveform")
        self.wave_select_all_btn.clicked.connect(self.wave_pin_combo.select_all)
        wrow1.addWidget(self.wave_select_all_btn)
        wrow1.addSpacing(10)
        wrow1.addWidget(QLabel("Wave:"))
        self.wave_type_combo = QComboBox()
        self.wave_type_combo.addItem("Sine",   "sin")
        self.wave_type_combo.addItem("Cosine", "cos")
        self.wave_type_combo.setFixedWidth(80)
        wrow1.addWidget(self.wave_type_combo)
        wrow1.addStretch()
        wg.addLayout(wrow1)

        wrow2 = QHBoxLayout()
        wrow2.addWidget(QLabel("Freq (Hz):"))
        self.wave_freq_sb = NoScrollDoubleSpinBox()
        self.wave_freq_sb.setDecimals(3)
        self.wave_freq_sb.setRange(0.001, 1000.0)
        self.wave_freq_sb.setValue(1.0)
        self.wave_freq_sb.setFixedWidth(90)
        persist_spinbox(self.wave_freq_sb, "daq_wave_freq_hz")
        wrow2.addWidget(self.wave_freq_sb)
        wrow2.addSpacing(10)
        wrow2.addWidget(QLabel("Amplitude:"))
        self.wave_amp_sb = NoScrollDoubleSpinBox()
        self.wave_amp_sb.setDecimals(3)
        self.wave_amp_sb.setValue(1.0)
        self.wave_amp_sb.setFixedWidth(90)
        persist_spinbox(self.wave_amp_sb, "daq_wave_amplitude")
        wrow2.addWidget(self.wave_amp_sb)
        wrow2.addSpacing(10)
        wrow2.addWidget(QLabel("Offset:"))
        self.wave_offset_sb = NoScrollDoubleSpinBox()
        self.wave_offset_sb.setDecimals(3)
        self.wave_offset_sb.setValue(0.0)
        self.wave_offset_sb.setFixedWidth(90)
        persist_spinbox(self.wave_offset_sb, "daq_wave_offset")
        wrow2.addWidget(self.wave_offset_sb)
        wrow2.addStretch()
        wg.addLayout(wrow2)

        wrow3 = QHBoxLayout()
        wrow3.addWidget(QLabel("Tick (ms):"))
        self.wave_tick_sb = NoScrollSpinBox()
        self.wave_tick_sb.setRange(5, 1000)
        self.wave_tick_sb.setValue(20)
        self.wave_tick_sb.setFixedWidth(70)
        persist_spinbox(self.wave_tick_sb, "daq_wave_tick_ms")
        wrow3.addWidget(self.wave_tick_sb)
        wrow3.addSpacing(10)
        self.wave_run_btn  = QPushButton("Run Wave")
        self.wave_stop_btn = QPushButton("Stop")
        self.wave_stop_btn.setEnabled(False)
        self.wave_run_btn.clicked.connect(self._start_wave)
        self.wave_stop_btn.clicked.connect(self._stop_wave)
        wrow3.addWidget(self.wave_run_btn)
        wrow3.addWidget(self.wave_stop_btn)
        wrow3.addStretch()
        wg.addLayout(wrow3)

        root.addWidget(wave_group)

        # ── recording panel ──
        rec_group = QGroupBox("Data Recording")
        rg = QVBoxLayout(rec_group)
        rg.setSpacing(6)

        rec_row1 = QHBoxLayout()
        self._rec_btn  = QPushButton("⏺  Start Recording")
        self._rec_btn.setFixedWidth(150)
        self._rec_btn.clicked.connect(self._toggle_recording)
        self._rec_status_lbl = QLabel("Idle")
        self._rec_status_lbl.setStyleSheet(f"color: {C_GRAY};")
        self._save_btn = QPushButton("💾  Save Data")
        self._save_btn.setFixedWidth(110)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_csv)
        rec_row1.addWidget(self._rec_btn)
        rec_row1.addSpacing(8)
        rec_row1.addWidget(self._save_btn)
        self._save_open_btn = QPushButton("📂 Open")
        self._save_open_btn.setEnabled(False)
        self._save_open_btn.setToolTip("Open the last-saved recording CSV")
        self._save_open_btn.clicked.connect(lambda: open_saved_file(self._last_recording_csv))
        rec_row1.addWidget(self._save_open_btn)
        rec_row1.addSpacing(10)
        rec_row1.addWidget(self._rec_status_lbl)
        rec_row1.addStretch()
        rg.addLayout(rec_row1)

        rec_row2 = QHBoxLayout()
        self._vi_checkbox = QCheckBox("Also show V vs I after recording")
        rec_row2.addWidget(self._vi_checkbox)
        rec_row2.addStretch()
        rg.addLayout(rec_row2)

        rec_row3 = QHBoxLayout()
        rec_row3.addWidget(QLabel("Readback source:"))
        self._rec_src_combo = QComboBox()
        self._rec_src_combo.addItem("Moku",      "moku")
        self._rec_src_combo.addItem("Guardian",  "guardian")
        self._rec_src_combo.setFixedWidth(110)
        self._rec_src_lbl = QLabel("Readback source:")
        rec_row3.addWidget(self._rec_src_combo)
        rec_row3.addStretch()
        self._rec_src_row_widget = QWidget()
        self._rec_src_row_widget.setLayout(rec_row3)
        self._rec_src_row_widget.setVisible(False)   # shown only for Dev2
        rg.addWidget(self._rec_src_row_widget)

        root.addWidget(rec_group)

        # recording state
        self._recording        = False
        self._rec_records: list = []
        self._rec_t0: float     = 0.0
        self._rec_t: float      = 0.0
        self._rec_plot_win: RecordingPlotWindow = None

        # ── live comparison plot ──
        cmp_row = QHBoxLayout()
        self._cmp_btn = QPushButton("📈  Live Output vs Readback")
        self._cmp_btn.setFixedWidth(200)
        self._cmp_btn.clicked.connect(self._open_comparison_plot)

        self._cmp_src_combo = QComboBox()
        self._cmp_src_combo.setFixedWidth(110)
        self._cmp_src_label = QLabel("Source:")
        self._cmp_src_label.setVisible(True)

        cmp_row.addWidget(self._cmp_btn)
        cmp_row.addSpacing(8)
        cmp_row.addWidget(self._cmp_src_label)
        cmp_row.addWidget(self._cmp_src_combo)
        cmp_row.addStretch()

        sep_cmp = QFrame()
        sep_cmp.setFrameShape(QFrame.Shape.HLine)
        sep_cmp.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep_cmp)
        root.addLayout(cmp_row)

        self._cmp_win: LiveComparisonPlot = None
        self._last_moku_v = 0.0
        self._last_guardian_v = 0.0

        # AO-333 Guardian readback worker (Dev2 only)
        self._guardian_thread = QThread()
        self._guardian_worker = AO333ReadbackWorker()
        self._guardian_worker.moveToThread(self._guardian_thread)
        self._guardian_thread.start()
        self._guardian_worker.readback_ready.connect(self._on_guardian_readback)
        self._guardian_worker.error.connect(
            lambda msg: print(f"[AO333] {msg}"))
        self._guardian_values: list = [0.0] * NUM_PINS

        # ── batch plot repaint timer ──
        self._plot_dirty = False
        self._plot_timer = QTimer()
        self._plot_timer.setInterval(PLOT_CHUNK_MS)
        self._plot_timer.timeout.connect(self._repaint_plots)
        self._plot_timer.start()

    def _repaint_plots(self):
        """Called every PLOT_CHUNK_MS — repaints all plots in one batch."""
        if not self._plot_dirty or not HAS_PYQTGRAPH:
            return
        self._plot_dirty = False

        if self._cmp_win and self._cmp_win.isVisible() and HAS_PYQTGRAPH:
            if self._cmp_win._cmd_ts:
                self._cmp_win._cmd_curve.setData(
                    self._cmp_win._cmd_ts, self._cmp_win._cmd_vs)
                self._cmp_win._meas_curve.setData(
                    self._cmp_win._meas_ts, self._cmp_win._meas_vs)
                x_max = self._cmp_win._cmd_ts[-1]
                self._cmp_win._ts_plot.setXRange(
                    x_max - CMP_PLOT_WINDOW_S, x_max, padding=0)
            if self._cmp_win._cmd_vs:
                self._cmp_win._scatter.setData(
                    self._cmp_win._cmd_vs, self._cmp_win._meas_vs)

    def _open_comparison_plot(self):
        cs = self.card_session
        if cs is None:
            return
        label = CARDS[cs.card_index]["label"]
        self._cmp_win = LiveComparisonPlot(label, cs.mode, cs.num_pins)

        src = self._cmp_src_combo.currentData()
        src_names = {"moku": "Moku Ch1", "guardian": "Guardian ADC"}
        src_name = src_names.get(src, src)
        if cs.mode == "current":
            unit_note = "→ mA via shunt" if src == "moku" else "→ mA via A1"
            self._cmp_win.set_source_label(f"Measured = {src_name} {unit_note}")
        else:
            self._cmp_win.set_source_label(f"Measured = {src_name}")

        # spawn beside the main window instead of on top of it
        mw = self.window()
        self._cmp_win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._cmp_win.show()
        self._cmp_win.raise_()

    def _append_record(self, readback_v: float, dt: float):
        self._rec_t += dt
        self._rec_records.append({
            't':      self._rec_t,
            'moku_v': readback_v,
            'daq':    list(self.card_session.values),
            'mode':   self.card_session.mode,
        })
        self._rec_status_lbl.setText(
            f"● Recording — {len(self._rec_records)} samples")

    def _push_comparison(self, measured: float, dt: float = None):
        if self._cmp_win is None or not self._cmp_win.isVisible():
            return
        cs = self.card_session
        if cs is None:
            return
        pin = self._cmp_win.get_pin()
        commanded = cs.values[pin] if pin < len(cs.values) else 0.0
        if dt is None:
            dt = MOKU_POLL_MS / 1000.0
        self._cmp_win.push(commanded, measured, dt=dt)
        self._plot_dirty = True

    def _on_sweep_mode_toggled(self):
        steps_mode = self._sweep_mode_combo.currentData() == "steps"
        self.sweep_steps_sb.setVisible(steps_mode)
        self.sweep_stepsize_sb.setVisible(not steps_mode)
        self._update_sweep_derived()

    def _update_sweep_derived(self):
        start      = self.sweep_start.value()
        stop       = self.sweep_stop.value()
        span       = abs(stop - start)
        unit       = self.card_session.unit if self.card_session else ""
        steps_mode = self._sweep_mode_combo.currentData() == "steps"
        if steps_mode:
            steps = self.sweep_steps_sb.value()
            self.sweep_derived_lbl.setText(
                f"→ step size: {span / (steps-1):.4f} {unit}" if steps > 1 else "")
        else:
            size = self.sweep_stepsize_sb.value()
            self.sweep_derived_lbl.setText(
                f"→ {int(round(span/size))+1} steps" if size > 0 and span > 0 else "")

    def _compute_steps(self) -> int:
        start = self.sweep_start.value()
        stop  = self.sweep_stop.value()
        if self._sweep_mode_combo.currentData() == "steps":
            return self.sweep_steps_sb.value()
        size = self.sweep_stepsize_sb.value()
        span = abs(stop - start)
        return max(2, int(round(span / size)) + 1) if size > 0 else 2

    # ── Channel naming / active-channel-count helpers ──────────────────────────

    def _load_channel_names(self) -> dict:
        try:
            with open(AO_CHANNEL_NAMES_FILE, "r") as f:
                data = json.load(f)
            return {str(k): str(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_channel_names(self):
        try:
            tmp = AO_CHANNEL_NAMES_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._channel_names, f, indent=2)
            os.replace(tmp, AO_CHANNEL_NAMES_FILE)
        except Exception as e:
            print(f"[AO names] Failed to save {AO_CHANNEL_NAMES_FILE}: {e}")

    def _on_name_edited(self, idx: int):
        name = self._name_edits[idx].text().strip()
        if name:
            self._channel_names[str(idx)] = name
        else:
            self._channel_names.pop(str(idx), None)
        self._save_channel_names()
        if self.card_session and idx < self.card_session.num_pins:
            text = self._pin_display_name(idx)
            for combo in (self.sweep_pin_combo, self.wave_pin_combo):
                combo.set_item_text_for_data(idx, text)

    def _pin_display_name(self, idx: int) -> str:
        name = self._channel_names.get(str(idx), "")
        base = f"Pin {idx:02d}"
        return f"{base} — {name}" if name else base

    def _set_active_channels(self, n: int):
        self._active_n = n
        for i, row in enumerate(self._pin_rows):
            row.setVisible(i < n)
        for first_idx, sep in self._group_seps:
            sep.setVisible(first_idx < n)
        # Hide the second column entirely for a ≤16-channel card instead of
        # showing an empty column with just a header.
        pin_col_split = MAX_PINS // len(self._pin_columns)
        for col_idx, (col_widget, _) in enumerate(self._pin_columns):
            col_widget.setVisible(col_idx * pin_col_split < n)

    def load_card(self, cs: CardSession):
        self.card_session = cs
        self.card_title.setText(CARDS[cs.card_index]["label"].split("  —  ")[0])
        self.badge.setText(cs.mode.upper())
        self._set_active_channels(cs.num_pins)
        _, _, _, s_min, s_max = MODE_RANGES[cs.mode]
        self._syncing = True
        for i in range(cs.num_pins):
            self.spinboxes[i].setMinimum(cs.min_val)
            self.spinboxes[i].setMaximum(cs.max_val)
            self.spinboxes[i].setSuffix(f" {cs.unit}")
            self.sliders[i].setMinimum(s_min)
            self.sliders[i].setMaximum(s_max)
            self.spinboxes[i].setValue(cs.values[i])
            self.sliders[i].setValue(int(cs.values[i] * 100))
        self._syncing = False

        self._set_all_spin.setMinimum(cs.min_val)
        self._set_all_spin.setMaximum(cs.max_val)
        self._set_all_spin.setSuffix(f" {cs.unit}")

        self.sweep_pin_combo.clear()
        self.wave_pin_combo.clear()
        for i in range(cs.num_pins):
            text = self._pin_display_name(i)
            self.sweep_pin_combo.addCheckableItem(text, i)
            self.wave_pin_combo.addCheckableItem(text, i)
        # Default to Pin 0 checked in both, so Run Sweep/Run Wave has
        # something to act on immediately after connecting instead of
        # silently doing nothing until the user opens the dropdown.
        self.sweep_pin_combo.set_checked_data([0])
        self.wave_pin_combo.set_checked_data([0])

        self.sweep_start.setMinimum(cs.min_val)
        self.sweep_start.setMaximum(cs.max_val)
        self.sweep_start.setSuffix(f" {cs.unit}")
        self.sweep_stop.setMinimum(cs.min_val)
        self.sweep_stop.setMaximum(cs.max_val)
        self.sweep_stop.setSuffix(f" {cs.unit}")
        self.sweep_stop.setValue(cs.max_val)
        self.sweep_stepsize_sb.setSuffix(f" {cs.unit}")
        self._update_sweep_derived()
        half_range = (cs.max_val - cs.min_val) / 2
        self.wave_amp_sb.setRange(0.0, half_range)
        self.wave_amp_sb.setValue(min(1.0, half_range))
        self.wave_amp_sb.setSuffix(f" {cs.unit}")
        self.wave_offset_sb.setRange(cs.min_val, cs.max_val)
        self.wave_offset_sb.setValue((cs.min_val + cs.max_val) / 2)
        self.wave_offset_sb.setSuffix(f" {cs.unit}")

        if self._recording:
            self._stop_recording()
        if self._rec_plot_win:
            self._rec_plot_win.close()
            self._rec_plot_win = None

        # Guardian readback — only for voltage card (Dev2 / AO-333), and only
        # for whichever NUM_PINS logical pins actually land on physical
        # channels 0-7: the ao333_bridge.py readback bridge only streams 8
        # monitor channels even though Dev2 now exposes MAX_PINS=32 outputs,
        # and PIN_REMAP means "logical pin i" isn't necessarily "physical
        # channel i" — a pin remapped onto physical 8-31 has no hardware
        # readback even if i < NUM_PINS, and conversely a pin remapped IN
        # from beyond 31 would (there isn't one, but the check stays general).
        is_voltage = cs.mode == "voltage"
        for i, lbl in enumerate(self._readback_lbls):
            lbl.setVisible(is_voltage and remap_pin(cs.dev, i) < NUM_PINS)
            lbl.setText("—")
        self._guardian_values = [0.0] * NUM_PINS
        self._rec_src_row_widget.setVisible(is_voltage)

        self._cmp_src_combo.blockSignals(True)
        self._cmp_src_combo.clear()
        self._cmp_src_combo.addItem("Moku",      "moku")
        if is_voltage:
            self._cmp_src_combo.addItem("Guardian",  "guardian")
        self._cmp_src_combo.blockSignals(False)

        if self._cmp_win and self._cmp_win.isVisible():
            self._cmp_win.close()
        self._cmp_win = None
        self._last_moku_v = 0.0
        self._last_guardian_v = 0.0

        if is_voltage:
            QTimer.singleShot(0, self._guardian_worker.start)
        else:
            QTimer.singleShot(0, self._guardian_worker.stop)

    def _on_guardian_readback(self, values: list):
        # `values` is indexed by PHYSICAL Guardian ADC channel (0-7) — always
        # go through remap_pin() to find which physical channel a given
        # logical pin actually landed on before indexing into it.
        self._guardian_values = values
        dev = self.card_session.dev if self.card_session else None
        self._last_guardian_v = float(np.mean(values[:NUM_PINS]))
        for i, lbl in enumerate(self._readback_lbls):
            phys = remap_pin(dev, i) if dev else i
            if phys < len(values):
                lbl.setText(f"{values[phys]:+.{READBACK_DECIMALS}f}V")

        if (self._cmp_src_combo.currentData() == "guardian"
                and self._cmp_win and self._cmp_win.isVisible()
                and self.card_session):
            pin  = self._cmp_win.get_pin()
            phys = remap_pin(self.card_session.dev, pin)
            v    = values[phys] if phys < len(values) else 0.0
            self._push_comparison(v, dt=AO333_GUARDIAN_POLL_MS / 1000.0)

        if (self._recording and self.card_session
                and self._rec_src_combo.currentData() == "guardian"):
            self._append_record(self._last_guardian_v,
                                dt=AO333_GUARDIAN_POLL_MS / 1000.0)

    def push_moku_sample(self, ch1_v: float, ch2_v: float):
        """Receives every Moku poll tick."""
        self._last_moku_v = ch1_v
        dt = MOKU_POLL_MS / 1000.0

        if self.card_session is None:
            return

        if self.card_session.mode == "current":
            meas_ma = (ch1_v / MOKU_SHUNT_OHMS) * 1000.0
            if self._cmp_src_combo.currentData() == "moku":
                self._push_comparison(meas_ma, dt=dt)
            if self._recording:
                self._append_record(ch1_v, dt)

        elif self.card_session.mode == "voltage":
            if self._cmp_src_combo.currentData() == "moku":
                self._push_comparison(ch1_v, dt=dt)
            if self._recording and self._rec_src_combo.currentData() == "moku":
                self._append_record(ch1_v, dt)

    def _toggle_recording(self):
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        self._recording   = True
        self._rec_records = []
        self._rec_t       = 0.0
        self._rec_btn.setText("⏹  Stop Recording")
        self._rec_btn.setStyleSheet(f"color: {C_RED};")
        self._rec_status_lbl.setText("● Recording — 0 samples")
        self._rec_status_lbl.setStyleSheet(f"color: {C_RED};")
        self._save_btn.setEnabled(False)

    def _stop_recording(self):
        self._recording = False
        self._rec_btn.setText("⏺  Start Recording")
        self._rec_btn.setStyleSheet("")
        n = len(self._rec_records)
        self._rec_status_lbl.setStyleSheet(f"color: {C_GRAY};")
        if n == 0:
            self._rec_status_lbl.setText("Idle — no data recorded")
            self._save_btn.setEnabled(False)
            return
        self._rec_status_lbl.setText(f"Idle — {n} samples recorded")
        self._save_btn.setEnabled(True)
        self._show_plots()

    def _save_csv(self):
        import csv, datetime
        if not self._rec_records or self.card_session is None:
            return
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        mode  = self.card_session.mode
        dev   = self.card_session.dev
        unit  = self.card_session.unit
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if mode == "current":
            src          = "moku"
            readback_col = "moku_mA"
        else:
            src = self._rec_src_combo.currentData()
            readback_col = {
                "moku":      "moku_V",
                "guardian":  "guardian_V",
            }.get(src, "readback_V")

        fname    = os.path.join(data_dir, f"{dev}_{mode}_{src}_{stamp}.csv")
        pin_hdrs = [f"pin{i:02d}_{unit}" for i in range(self.card_session.num_pins)]
        header   = ["time_s", "readback_raw", readback_col] + pin_hdrs

        with open(fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for r in self._rec_records:
                if mode == "current":
                    scaled = (r['moku_v'] / MOKU_SHUNT_OHMS) * 1000.0
                else:
                    scaled = r['moku_v']
                w.writerow([f"{r['t']:.4f}", f"{r['moku_v']:.6f}",
                             f"{scaled:.4f}"] +
                            [f"{v:.4f}" for v in r['daq']])
        print(f"[Recording] Saved {len(self._rec_records)} rows → {fname}")
        self._status(f"Saved {len(self._rec_records)} samples → {fname}")
        self._last_recording_csv = fname
        self._save_open_btn.setEnabled(True)

    def _show_plots(self):
        if not self._rec_records or self.card_session is None:
            return
        label = CARDS[self.card_session.card_index]["label"]
        self._rec_plot_win = RecordingPlotWindow(label)
        mw = self.window()
        self._rec_plot_win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._rec_plot_win.show_data(
            self._rec_records,
            self.card_session.mode,
            show_vi=self._vi_checkbox.isChecked())

    def set_coredaq_panel(self, panel):
        """Wires the CoreDAQ tab in so sweeps can log optical power per step."""
        self._coredaq_panel = panel

    def latest_ao_snapshot(self):
        """(card_label, unit, values) for the active card, or None if none connected."""
        cs = self.card_session
        if cs is None or not cs.connected:
            return None
        label = CARDS[cs.card_index]["label"].split("  —  ")[0]
        return label, cs.unit, list(cs.values)

    def _start_sweep(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            pins = self.sweep_pin_combo.checked_data()
            if not pins:
                self._status("Sweep error: no pins selected")
                return
            start    = self.sweep_start.value()
            stop     = self.sweep_stop.value()
            steps    = self._compute_steps()
            dwell_ms = self.sweep_dwell_sb.value()
            self._sweep_power_log = []
            self._sweep_export_btn.setEnabled(False)
            self._sweep_power_lbl.setText("")
            cs.start_sweep(pins, start, stop, steps, dwell_ms,
                           self._on_sweep_step, self._on_sweep_done)
            self.sweep_run_btn.setEnabled(False)
            self.sweep_stop_btn.setEnabled(True)
            pin_desc = f"Pin {pins[0]:02d}" if len(pins) == 1 else f"{len(pins)} pins"
            self._status(f"Sweep running — {pin_desc}  {start:.3f} → "
                         f"{stop:.3f} {cs.unit}  {steps} steps")
        except Exception as e:
            self._status(f"Sweep error: {e}")

    def _stop_sweep(self):
        if self.card_session: self.card_session.stop_sweep()
        self.sweep_run_btn.setEnabled(True)
        self.sweep_stop_btn.setEnabled(False)
        self._status("Sweep stopped")

    def _on_sweep_step(self, pins, value, step, total):
        self._syncing = True
        for pin in pins:
            self.spinboxes[pin].setValue(value)
            self.sliders[pin].setValue(int(value * 100))
        self._syncing = False
        cs = self.card_session
        pin_desc = f"Pin {pins[0]:02d}" if len(pins) == 1 else f"{len(pins)} pins"
        self._status(f"Sweep — {pin_desc} at {value:.3f} "
                     f"{cs.unit if cs else ''}  (step {step}/{total})")

        if self._sweep_log_chk.isChecked() and self._coredaq_panel is not None:
            powers = self._coredaq_panel.latest_power_w()
            if powers is not None:
                self._sweep_power_log.append((value, *powers))
                head = self._sweep_coredaq_head_combo.currentData()
                self._sweep_power_lbl.setText(
                    f"Step {step}/{total} — MZI {head}: {_fmt_power_w(powers[head - 1])}")
            else:
                self._sweep_power_lbl.setText(
                    "CoreDAQ not connected — power not logged for this step")

    def _on_sweep_done(self):
        self.sweep_run_btn.setEnabled(True)
        self.sweep_stop_btn.setEnabled(False)
        self._status("Sweep complete")
        if self._sweep_power_log:
            self._sweep_export_btn.setEnabled(True)
            self._show_sweep_power_plot()

    def _show_sweep_power_plot(self):
        cs = self.card_session
        unit = cs.unit if cs else ""
        series = {}
        for ch in range(4):
            xs = [row[0] for row in self._sweep_power_log]
            ys = [row[1 + ch] * 1e9 for row in self._sweep_power_log]
            series[f"MZI {ch + 1}"] = (xs, ys, "nW")
        win = MatplotlibPlotWindow("AO Sweep — CoreDAQ Power", "AO value", unit)
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._sweep_plot_win = win

    def _export_sweep_power_csv(self):
        if not self._sweep_power_log:
            return
        import datetime
        cs = self.card_session
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"ao_sweep_coredaq_{stamp}.csv")
        unit  = cs.unit if cs else ""
        comments = [f"ao_sweep_unit: {unit}"]
        header = [f"ao_value_{unit}",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = [[f"{v:.4f}"] + [f"{w:.9e}" for w in powers]
                for v, *powers in self._sweep_power_log]
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[Sweep] Saved {len(rows)} rows → {fname}")
        self._last_sweep_csv = fname
        self._sweep_open_btn.setEnabled(True)

        # Save the matplotlib results plot alongside the CSV — same basename,
        # in data/images/ — same pairing convention as Santec Fast Sweep.
        img_saved = False
        if HAS_MATPLOTLIB and self._sweep_plot_win is not None:
            os.makedirs(IMAGES_DIR, exist_ok=True)
            img_name = os.path.splitext(os.path.basename(fname))[0] + ".png"
            img_path = os.path.join(IMAGES_DIR, img_name)
            self._sweep_plot_win.save_png(img_path)
            print(f"[Sweep] Saved plot image → {img_path}")
            img_saved = True

        self._status(f"Saved {len(rows)} sweep/power rows → {fname}"
                      + ("  (+ image)" if img_saved else ""))

    def _sb_changed(self, idx, val):
        if self._syncing: return
        self._syncing = True
        self.sliders[idx].setValue(int(val * 100))
        self._syncing = False

    def _sl_changed(self, idx, raw):
        if self._syncing: return
        self._syncing = True
        self.spinboxes[idx].setValue(raw / 100.0)
        self._syncing = False

    def _set_pin(self, idx: int):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            val = self.spinboxes[idx].value()
            targets = list(cs.values)
            targets[idx] = val
            if self._ramp_chk.isChecked():
                cs.ramp_to(targets)
                self._status(f"Ramping Pin {idx:02d} → {val:.3f} {cs.unit}")
            else:
                def do_write():
                    try:
                        cs.write(targets)
                    except Exception as e:
                        print(f"[Write] {e}")
                t = QThread(self)
                t.run = do_write
                t.start()
                self._status(f"Instant set Pin {idx:02d} → {val:.3f} {cs.unit}")
        except Exception as e:
            self._status(f"Error: {e}")

    def _write_all(self, focused_pin=None):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            values = [sb.value() for sb in self.spinboxes[:cs.num_pins]]
            if self._ramp_chk.isChecked():
                cs.ramp_to(values)
                if focused_pin is not None:
                    msg = (f"Ramping Pin {focused_pin:02d} → "
                           f"{values[focused_pin]:.3f} {cs.unit}")
                else:
                    msg = ("Ramping all: " +
                           "  ".join(f"P{i}:{v:.2f}" for i, v in enumerate(values)) +
                           f" {cs.unit}")
            else:
                def do_write():
                    try:
                        cs.write(values)
                    except Exception as e:
                        print(f"[Write] {e}")
                t = QThread(self)
                t.run = do_write
                t.start()
                msg = "Instant write all pins"
            self._status(msg)
        except Exception as e:
            self._status(f"Error: {e}")

    def _zero_all(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            self._syncing = True
            for sb in self.spinboxes[:cs.num_pins]: sb.setValue(0.0)
            for sl in self.sliders[:cs.num_pins]:   sl.setValue(0)
            self._syncing = False
            if self._ramp_chk.isChecked():
                cs.zero()
                self._status("Ramping all pins to zero")
            else:
                def do_zero():
                    try:
                        cs.write([0.0] * cs.num_pins)
                    except Exception as e:
                        print(f"[Zero] {e}")
                t = QThread(self)
                t.run = do_zero
                t.start()
                self._status("Instant zero all pins")
        except Exception as e:
            self._status(f"Error: {e}")

    def _set_all_to(self):
        """Sets every active pin's value box (and slider) to the amount in
        "Set All To", then writes it out — same ramp-vs-instant behavior as
        Write All/Zero All, just with a configurable target instead of
        whatever's already dialed into each pin, or a hardcoded zero."""
        cs = self.card_session
        if cs is None: return
        value = self._set_all_spin.value()
        try:
            if not cs.connected: cs.connect()
            self._syncing = True
            for sb in self.spinboxes[:cs.num_pins]: sb.setValue(value)
            for sl in self.sliders[:cs.num_pins]:   sl.setValue(int(value * 100))
            self._syncing = False
            if self._ramp_chk.isChecked():
                cs.ramp_to([value] * cs.num_pins)
                self._status(f"Ramping all pins to {value:.3f} {cs.unit}")
            else:
                def do_set_all():
                    try:
                        cs.write([value] * cs.num_pins)
                    except Exception as e:
                        print(f"[SetAll] {e}")
                t = QThread(self)
                t.run = do_set_all
                t.start()
                self._status(f"Instant set all pins to {value:.3f} {cs.unit}")
        except Exception as e:
            self._status(f"Error: {e}")

    def _start_wave(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            pins = self.wave_pin_combo.checked_data()
            if not pins:
                self._status("Wave error: no pins selected")
                return
            waveform  = self.wave_type_combo.currentData()
            freq      = self.wave_freq_sb.value()
            amplitude = self.wave_amp_sb.value()
            offset    = self.wave_offset_sb.value()
            tick_ms   = self.wave_tick_sb.value()
            cs.start_wave(pins, waveform, freq, amplitude, offset, tick_ms,
                          self._on_wave_tick)
            self.wave_run_btn.setEnabled(False)
            self.wave_stop_btn.setEnabled(True)
            pin_desc = f"Pin {pins[0]:02d}" if len(pins) == 1 else f"{len(pins)} pins"
            self._status(f"Wave running — {pin_desc}  {waveform}  {freq}Hz  "
                         f"amp={amplitude} {cs.unit}  offset={offset} {cs.unit}")
        except Exception as e:
            self._status(f"Wave error: {e}")

    def _stop_wave(self):
        if self.card_session: self.card_session.stop_wave()
        self.wave_run_btn.setEnabled(True)
        self.wave_stop_btn.setEnabled(False)
        self._status("Wave stopped")

    def _on_wave_tick(self, pins, value):
        self._syncing = True
        for pin in pins:
            self.spinboxes[pin].setValue(value)
            self.sliders[pin].setValue(int(value * 100))
        self._syncing = False

    def _status(self, msg):
        w = self.window()
        if hasattr(w, "status_bar"):
            w.status_bar.showMessage(msg)


# ── DAQ panel (former DAQMainWindow, now a tab) ────────────────────────────────

class DAQPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.card_sessions = {
            i: CardSession(i) for i, info in CARDS.items() if info["available"]
        }

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stacked = QStackedWidget()
        outer.addWidget(self.stacked)

        main_view = QWidget()
        mv = QVBoxLayout(main_view)
        mv.setContentsMargins(12, 12, 12, 12)
        mv.setSpacing(8)

        mv.addWidget(QLabel("DAQ Control — Select a card to configure:"))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        mv.addWidget(sep)

        self.daq_box = DAQBoxWidget(self.card_sessions)
        self.daq_box.card_clicked.connect(self._open_card)
        self.daq_box.card_disconnected.connect(self._disconnect_card)
        mv.addWidget(self.daq_box)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        mv.addWidget(sep2)

        self.moku_widget = MokuWidget()
        mv.addWidget(self.moku_widget)

        mv.addStretch()

        self.pin_view = PinConfigView()
        self.pin_view.back_clicked.connect(self._show_main)
        self.moku_widget.moku_sample.connect(self.pin_view.push_moku_sample)

        # Wrap pin view in a scroll area so a fixed window height always works
        pin_scroll = QScrollArea()
        pin_scroll.setWidgetResizable(True)
        pin_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pin_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pin_scroll.setWidget(self.pin_view)

        self.stacked.addWidget(main_view)
        self.stacked.addWidget(pin_scroll)

        # auto-launch the 32-bit Guardian bridge process
        self._bridge_proc = None
        self._launch_bridge()

    def _launch_bridge(self):
        """Start ao333_bridge.py as a subprocess using .venv32."""
        if not (os.path.exists(BRIDGE_PYTHON) and os.path.exists(BRIDGE_SCRIPT)):
            print(f"[Bridge] Not launched — {BRIDGE_PYTHON} or {BRIDGE_SCRIPT} not found")
            return
        try:
            self._bridge_proc = subprocess.Popen(
                [BRIDGE_PYTHON, BRIDGE_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_CONSOLE)
            print(f"[Bridge] Launched PID {self._bridge_proc.pid}")
            QTimer.singleShot(2000, lambda: print("[Bridge] Ready"))
        except Exception as e:
            print(f"[Bridge] Failed to launch: {e}")

    def _status(self, msg: str):
        w = self.window()
        if hasattr(w, "status_bar"):
            w.status_bar.showMessage(msg)

    def _open_card(self, idx: int):
        cs = self.card_sessions[idx]
        if cs.connected:
            self.pin_view.load_card(cs)
            self.stacked.setCurrentIndex(1)
            self.daq_box.refresh()
            return
        self._connect_card(idx, on_connected=lambda: self._show_pin_view(idx))

    def _show_pin_view(self, idx: int):
        cs = self.card_sessions[idx]
        self.pin_view.load_card(cs)
        self.stacked.setCurrentIndex(1)
        self.daq_box.refresh()

    def _connect_card(self, idx: int, on_connected=None):
        """Connect a card in the background. Used both for the manual
        Connect button and for auto-connecting every card on launch."""
        cs = self.card_sessions[idx]
        if cs.connected:
            if on_connected:
                on_connected()
            return

        self._status(f"Connecting to {CARDS[idx]['label']}…")

        def do_connect():
            try:
                cs.connect()
                QTimer.singleShot(0, lambda: self._card_connected(idx, on_connected))
            except Exception as e:
                print(f"[DAQ] FAILED to connect — {CARDS[idx]['label']}: {e}")
                QTimer.singleShot(0, lambda: self._status(
                    f"Connection error: {e}"))

        t = QThread(self)
        self._connect_threads = getattr(self, '_connect_threads', [])
        self._connect_threads.append(t)
        t.run = do_connect        # type: ignore[method-assign]
        t.finished.connect(lambda: self._connect_threads.remove(t)
                           if t in self._connect_threads else None)
        t.start()

    def _card_connected(self, idx: int, on_connected=None):
        cs = self.card_sessions[idx]
        self._status(
            f"Connected — {CARDS[idx]['label']} — "
            f"{cs.min_val} to {cs.max_val} {cs.unit}")
        print(f"[DAQ] Connected — {CARDS[idx]['label']}")
        self.daq_box.refresh()
        if on_connected:
            on_connected()

    def _disconnect_card(self, idx: int):
        cs = self.card_sessions[idx]
        try:
            cs.stop_sweep()
            cs.zero_immediate()
            cs.disconnect()
            self._status(f"Disconnected — {CARDS[idx]['label']}")
        except Exception as e:
            self._status(f"Error disconnecting: {e}")
        self.daq_box.refresh()

    def _show_main(self):
        self.stacked.setCurrentIndex(0)
        self.daq_box.refresh()
        self._status("Ready")

    def cleanup(self):
        for cs in self.card_sessions.values():
            if cs.connected:
                try:
                    cs.zero_immediate()
                    cs.disconnect()
                except Exception:
                    pass
        self.moku_widget.cleanup()
        if self.pin_view._rec_plot_win:
            self.pin_view._rec_plot_win.close()
        if self.pin_view._cmp_win:
            self.pin_view._cmp_win.close()
        self.pin_view._guardian_worker.stop()
        self.pin_view._guardian_thread.quit()
        self.pin_view._guardian_thread.wait(2000)
        if self._bridge_proc and self._bridge_proc.poll() is None:
            self._bridge_proc.terminate()
            print("[Bridge] Terminated")


# ══════════════════════════════════════════════════════════════════════════════
# ITLA LASER (ported PySide6 → PyQt6)
# ══════════════════════════════════════════════════════════════════════════════

C_NM_GHZ    = 299_792_458.0   # c in nm·GHz  (λ_nm = C_NM_GHZ / f_GHz)
ITU_REF_GHZ = 193_100.0       # ITU G.694.1 reference: 193.1 THz

GRID_OPTIONS = {               # display label → GHz
    "50 GHz":   50.0,
    "100 GHz": 100.0,
    "25 GHz":   25.0,
    "12.5 GHz": 12.5,
}

FTF_LIMIT_STEPS = 60          # ±6 GHz in 0.1 GHz steps (OIF-ITLA-MSA-01.3)

def _itu_snap(freq_ghz: float, ui_grid_ghz: float) -> float:
    """Round freq_ghz to the nearest ITU G.694.1 channel on ui_grid_ghz."""
    n = round((freq_ghz - ITU_REF_GHZ) / ui_grid_ghz)
    return ITU_REF_GHZ + n * ui_grid_ghz

def nm_to_itla_ch(nm: float,
                  fcf1_thz: int, fcf2_ghz: float, itla_grid_ghz: float,
                  ui_grid_ghz: float) -> int:
    freq_ghz = C_NM_GHZ / nm
    snapped  = _itu_snap(freq_ghz, ui_grid_ghz)
    fcf_ghz  = fcf1_thz * 1000.0 + fcf2_ghz
    return max(1, round((snapped - fcf_ghz) / itla_grid_ghz) + 1)

def nm_to_itla_ch_ftf(nm: float,
                      fcf1_thz: int, fcf2_ghz: float, itla_grid_ghz: float,
                      ui_grid_ghz: float):
    freq_ghz = C_NM_GHZ / nm
    snapped  = _itu_snap(freq_ghz, ui_grid_ghz)
    fcf_ghz  = fcf1_thz * 1000.0 + fcf2_ghz
    ch       = max(1, round((snapped - fcf_ghz) / itla_grid_ghz) + 1)
    ch_freq  = fcf_ghz + (ch - 1) * itla_grid_ghz
    ftf      = round((freq_ghz - ch_freq) / 0.1)   # signed, 0.1 GHz LSB
    return ch, ftf

def itla_ch_to_nm(ch: int,
                  fcf1_thz: int, fcf2_ghz: float, itla_grid_ghz: float) -> float:
    freq_ghz = (fcf1_thz * 1000.0 + fcf2_ghz) + (ch - 1) * itla_grid_ghz
    return C_NM_GHZ / freq_ghz

def itu_channel_label(ch: int,
                      fcf1_thz: int, fcf2_ghz: float, itla_grid_ghz: float,
                      ui_grid_ghz: float) -> str:
    freq_ghz = (fcf1_thz * 1000.0 + fcf2_ghz) + (ch - 1) * itla_grid_ghz
    n = round((freq_ghz - ITU_REF_GHZ) / ui_grid_ghz)
    return f"ITU {n:+d}  ({freq_ghz/1000:.4f} THz)"

def mw_to_dbm100(mw: float) -> int:
    if mw <= 0:
        return -3000
    return round(10 * math.log10(mw) * 100)


class LaserWorker(QThread):
    status_update      = pyqtSignal(str, str)        # msg, level
    state_changed      = pyqtSignal(str)
    freq_updated       = pyqtSignal(float, float)    # freq_ghz, pdbm
    grid_params        = pyqtSignal(int, float, float)  # fcf1_thz, fcf2_ghz, grid_ghz
    capabilities_ready = pyqtSignal(dict)
    diagnostics_ready  = pyqtSignal(dict)
    done               = pyqtSignal(str)

    def __init__(self, itla):
        super().__init__()
        self.itla  = itla
        self._op   = None
        self._args = {}

    def run_op(self, op, **kwargs):
        if self.isRunning():
            self.wait(5000)
        self._op   = op
        self._args = kwargs
        self.start()

    def run(self):
        op = self._op
        try:
            if   op == "connect":         self._do_connect(**self._args)
            elif op == "on":              self._do_on(**self._args)
            elif op == "off":             self._do_off()
            elif op == "retune":          self._do_retune(**self._args)
            elif op == "set_power_live":  self._do_set_power_live(**self._args)
            elif op == "sweep":           self._do_sweep(**self._args)
            elif op == "power_sweep":     self._do_power_sweep(**self._args)
            elif op == "diagnostics":     self._do_diagnostics()
            elif op == "dither":          self._do_dither(**self._args)
        except Exception as e:
            self.status_update.emit(f"Error: {e}", "error")
            self.state_changed.emit("off")
        self.done.emit(op)

    # ── connect ───────────────────────────────────────────────────────────────

    def _do_connect(self, port, baud):
        self.status_update.emit(f"Connecting to COM{port}...", "info")
        self.itla.connect(port, baud)
        for i in range(60):
            _, data = self.itla.read(REG["NOP"], verbose=False)
            if (data >> 4) & 1:
                _, fcf1 = self.itla.read(REG["FCF1"], verbose=False)
                _, fcf2 = self.itla.read(REG["FCF2"], verbose=False)
                _, grid = self.itla.read(REG["GRID"], verbose=False)
                self.grid_params.emit(int(fcf1), fcf2 * 0.1, grid * 0.1)
                caps = self.itla.capabilities()
                self.capabilities_ready.emit(caps)
                diag = self.itla.diagnostics()
                self.diagnostics_ready.emit(diag)
                self.status_update.emit(
                    f"Ready. FCF={fcf1} THz + {fcf2*0.1:.1f} GHz, "
                    f"grid={grid*0.1:.1f} GHz  |  "
                    f"{caps['f_lo_ghz']/1000:.3f}–{caps['f_hi_ghz']/1000:.3f} THz  "
                    f"|  {caps['opsl_dbm']:.1f}–{caps['opsh_dbm']:.1f} dBm", "ok")
                self.state_changed.emit("off")
                return
            self.status_update.emit(f"Warming up... {i+1}s", "warn")
            self.state_changed.emit("warming")
            time.sleep(1)
        self.status_update.emit("Timeout waiting for MRDY", "error")

    # ── on ────────────────────────────────────────────────────────────────────

    def _do_on(self, ch: int, ftf: int, mw: float, use_ftf: bool):
        dbm100 = mw_to_dbm100(mw)
        self.status_update.emit(
            f"Power → {mw:.1f} mW ({dbm100/100:.2f} dBm)", "info")
        self.itla.power(dbm100)
        time.sleep(0.2)

        self.itla.write(REG["STATUSF"], 0x00FF)
        self.itla.write(REG["STATUSW"], 0x00FF)
        self.itla.write(REG["FTF"],     0x0000, verbose=False)  # clear FTF
        time.sleep(0.2)

        self.status_update.emit(f"Tuning to channel {ch}...", "info")
        self.state_changed.emit("locking")
        self.itla.channel(ch)

        t0 = time.time()
        while time.time() - t0 < 30:
            nop_status, _ = self.itla.read(REG["NOP"], verbose=False)
            self.status_update.emit(
                f"Locking... t={time.time()-t0:.1f}s", "warn")
            if nop_status == 0:
                break
            time.sleep(0.2)

        self.itla.write(REG["STATUSF"], 0x00FF)
        self.itla.write(REG["STATUSW"], 0x00FF)
        time.sleep(0.2)

        self.status_update.emit("Enabling output...", "info")
        self.itla.resena(8)
        time.sleep(0.5)

        # Re-apply power after enable — some modules reset APC setpoint on resena
        self.itla.power(dbm100)

        # Wait for power to stabilize (WPWR bit clears when APC is settled)
        t_pwr = time.time()
        while time.time() - t_pwr < 5.0:
            _, statw = self.itla.read(REG["STATUSW"], verbose=False)
            wpwr = (statw >> 8) & 1
            if wpwr == 0:
                break
            time.sleep(0.1)

        if use_ftf and ftf != 0:
            self.status_update.emit(
                f"Applying FTF {ftf * 0.1:+.2f} GHz...", "info")
            self.itla.write(REG["FTF"], ftf & 0xFFFF, verbose=False)
            time.sleep(0.5)

        self._readback()

    # ── retune / live power (laser stays enabled throughout — no off/on cycle) ──

    def _do_retune(self, ch: int, ftf: int, mw: float, use_ftf: bool):
        dbm100 = mw_to_dbm100(mw)
        self.status_update.emit(
            f"Power → {mw:.1f} mW ({dbm100/100:.2f} dBm)", "info")
        self.itla.power(dbm100)
        time.sleep(0.1)

        self.itla.write(REG["STATUSF"], 0x00FF)
        self.itla.write(REG["STATUSW"], 0x00FF)
        self.itla.write(REG["FTF"],     0x0000, verbose=False)
        time.sleep(0.1)

        self.status_update.emit(f"Retuning to channel {ch}...", "info")
        self.state_changed.emit("locking")
        self.itla.channel(ch)

        t0 = time.time()
        while time.time() - t0 < 30:
            nop_status, _ = self.itla.read(REG["NOP"], verbose=False)
            self.status_update.emit(
                f"Locking... t={time.time()-t0:.1f}s", "warn")
            if nop_status == 0:
                break
            time.sleep(0.2)

        self.itla.write(REG["STATUSF"], 0x00FF)
        self.itla.write(REG["STATUSW"], 0x00FF)

        if use_ftf and ftf != 0:
            self.status_update.emit(
                f"Applying FTF {ftf * 0.1:+.2f} GHz...", "info")
            self.itla.write(REG["FTF"], ftf & 0xFFFF, verbose=False)
            time.sleep(0.5)

        self._readback()

    def _do_set_power_live(self, mw: float):
        dbm100 = mw_to_dbm100(mw)
        self.status_update.emit(
            f"Power → {mw:.1f} mW ({dbm100/100:.2f} dBm)", "info")
        self.itla.power(dbm100)
        time.sleep(0.3)
        self._readback()

    def _do_power_sweep(self, mw_start: float, mw_stop: float, mw_step: float, dwell_s: float):
        """
        Steps output power from mw_start to mw_stop (never touching channel/
        resena — laser must already be locked and ON) so Cal 2-DC can sweep
        power alone at a fixed wavelength.
        """
        if mw_step <= 0:
            self.status_update.emit("Power step must be positive", "error")
            return

        step = abs(mw_step) if mw_stop >= mw_start else -abs(mw_step)
        targets = []
        v = mw_start
        if step >= 0:
            while v <= mw_stop + 1e-9:
                targets.append(round(v, 4))
                v += step
        else:
            while v >= mw_stop - 1e-9:
                targets.append(round(v, 4))
                v += step
        if not targets:
            targets = [mw_start]

        total = len(targets)
        self.status_update.emit(
            f"Power sweep: {total} points, {mw_start:.2f} → {mw_stop:.2f} mW, "
            f"{mw_step:.2f} mW step, {dwell_s:.2f} s dwell", "info")

        for idx, mw in enumerate(targets):
            dbm100 = mw_to_dbm100(mw)
            self.itla.power(dbm100)
            time.sleep(dwell_s)
            self.status_update.emit(f"[{idx+1}/{total}] {mw:.2f} mW", "info")
            self._readback()

        self.status_update.emit("Power sweep complete", "ok")

    def _readback(self):
        _, lf1 = self.itla.read(REG["LF1"], verbose=False)
        _, lf2 = self.itla.read(REG["LF2"], verbose=False)
        _, oop = self.itla.read(REG["OOP"], verbose=False)
        freq_ghz = lf1 * 1000.0 + lf2 * 0.1
        pdbm     = (oop if oop < 0x8000 else oop - 0x10000) / 100.0
        self.freq_updated.emit(freq_ghz, pdbm)
        self.status_update.emit(
            f"Laser ON  {freq_ghz:.1f} GHz  "
            f"({C_NM_GHZ/freq_ghz:.4f} nm)  {pdbm:.2f} dBm", "ok")
        self.state_changed.emit("on")

    # ── off ───────────────────────────────────────────────────────────────────

    def _do_off(self):
        self.status_update.emit("Disabling laser output...", "info")
        self.itla.resena(0)
        self.itla.write(REG["FTF"], 0x0000, verbose=False)
        time.sleep(0.3)
        self.status_update.emit("Laser OFF", "ok")
        self.state_changed.emit("off")

    # ── diagnostics ───────────────────────────────────────────────────────────

    def _do_diagnostics(self):
        diag = self.itla.diagnostics()
        self.diagnostics_ready.emit(diag)

    # ── dither ────────────────────────────────────────────────────────────────

    def _do_dither(self, mode: str, rate_khz: int, deviation: int, amp: int):
        if mode == "sbs":
            self.itla.enable_sbs(rate_khz, deviation)
            self.status_update.emit(
                f"SBS dither ON — {rate_khz} kHz  {deviation * 0.1:.1f} GHz p-p FM", "ok")
        elif mode == "txtrace":
            self.itla.enable_txtrace(amp, rate_khz)
            self.status_update.emit(
                f"TxTrace AM ON — amp={amp} ({amp / 10:.1f}% mod)", "ok")
        else:
            self.itla.disable_dither()
            self.status_update.emit("Dither OFF (SBS + TxTrace disabled)", "ok")

    # ── sweep ─────────────────────────────────────────────────────────────────

    def _do_sweep(self, nm_start, nm_stop, step_ghz, dwell_s,
                  mw, fcf1, fcf2, itla_grid, ui_grid):
        """
        Sweep across wavelengths by stepping step_ghz in frequency.
        Each target is snapped to the nearest ITU channel on ui_grid,
        then mapped to the ITLA's native itla_grid channel.
        No FTF is used — grid channels only.
        """
        dbm100 = mw_to_dbm100(mw)
        self.itla.power(dbm100)
        time.sleep(0.2)
        self.itla.write(REG["FTF"], 0x0000, verbose=False)

        # Walk frequency from nm_start's frequency toward nm_stop's frequency so the
        # wavelength sweep order matches the user's Start → Stop direction (frequency
        # and wavelength are inversely related, so this is NOT simply f_start..f_stop
        # in ascending order).
        f_start = C_NM_GHZ / nm_start
        f_stop  = C_NM_GHZ / nm_stop
        step    = abs(step_ghz) if f_stop >= f_start else -abs(step_ghz)

        targets_ghz = []
        f = f_start
        if step >= 0:
            while f <= f_stop + 1e-6:
                targets_ghz.append(f)
                f += step
        else:
            while f >= f_stop - 1e-6:
                targets_ghz.append(f)
                f += step

        if not targets_ghz:
            self.status_update.emit("No sweep points in range", "error")
            return

        fcf_ghz = fcf1 * 1000.0 + fcf2
        seen, pts = set(), []
        for f_t in targets_ghz:
            snapped = _itu_snap(f_t, ui_grid)
            ch = max(1, round((snapped - fcf_ghz) / itla_grid) + 1)
            if ch not in seen:
                seen.add(ch)
                pts.append(ch)

        self.status_update.emit(
            f"Sweep: {len(pts)} channels, {dwell_s:.1f}s dwell, "
            f"{step_ghz:.1f} GHz step", "info")

        self.itla.write(REG["STATUSF"], 0x00FF)
        self.itla.write(REG["STATUSW"], 0x00FF)
        time.sleep(0.2)
        self.itla.channel(pts[0])
        self.state_changed.emit("locking")

        t0_init = time.time()
        while time.time() - t0_init < 30:
            nop_status, _ = self.itla.read(REG["NOP"], verbose=False)
            if nop_status == 0:
                break
            time.sleep(0.2)

        self.itla.write(REG["STATUSF"], 0x00FF)
        self.itla.write(REG["STATUSW"], 0x00FF)
        self.itla.resena(8)
        time.sleep(0.5)

        for idx, ch in enumerate(pts):
            ch_freq = fcf_ghz + (ch - 1) * itla_grid
            ch_nm   = C_NM_GHZ / ch_freq
            itu_n   = round((ch_freq - ITU_REF_GHZ) / ui_grid)
            self.status_update.emit(
                f"[{idx+1}/{len(pts)}] ch {ch}  {ch_nm:.4f} nm  "
                f"ITU {itu_n:+d} ({ui_grid:.0f} GHz grid)", "info")
            self.state_changed.emit("locking")
            self.itla.write(REG["CHANNEL"], ch)

            t0 = time.time()
            while time.time() - t0 < 15:
                nop_status, _ = self.itla.read(REG["NOP"], verbose=False)
                if nop_status == 0:
                    break
                time.sleep(0.2)

            elapsed = time.time() - t0
            if elapsed < dwell_s:
                time.sleep(dwell_s - elapsed)

            _, lf1 = self.itla.read(REG["LF1"], verbose=False)
            _, lf2 = self.itla.read(REG["LF2"], verbose=False)
            _, oop = self.itla.read(REG["OOP"], verbose=False)
            freq_ghz = lf1 * 1000.0 + lf2 * 0.1
            pdbm     = (oop if oop < 0x8000 else oop - 0x10000) / 100.0
            self.freq_updated.emit(freq_ghz, pdbm)

        self.state_changed.emit("on")
        self.status_update.emit("Sweep complete", "ok")


# ── ITLA panel (former MainWindow, now a tab, PyQt6) ───────────────────────────

class ITLAPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        if not HAS_ITLA:
            lay = QVBoxLayout(self)
            msg = QLabel("hardware.itla module not found —\n"
                         "place hardware/itla.py next to this script to enable the laser tab.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet(f"color: {C_GRAY};")
            lay.addWidget(msg)
            self.itla = None
            self.worker = None
            return

        self.itla   = ITLA()
        self.worker = LaserWorker(self.itla)
        self.worker.status_update.connect(self.on_status)
        self.worker.state_changed.connect(self.on_state)
        self.worker.freq_updated.connect(self.on_freq)
        self.worker.grid_params.connect(self.on_grid_params)
        self.worker.capabilities_ready.connect(self.on_capabilities)
        self.worker.diagnostics_ready.connect(self.on_diagnostics)
        self.worker.done.connect(self.on_done)

        self._diag_timer = QTimer(self)
        self._diag_timer.setInterval(500)   # 2 Hz — max practical at 9600 baud
        self._diag_timer.timeout.connect(self._auto_diagnostics)

        self._laser_state = "disconnected"
        self._fcf1 = 191      # THz  (updated after connect)
        self._fcf2 = 300.0    # GHz
        self._grid = 50.0     # GHz  (ITLA native)

        self._updating = False   # guard against signal loops

        self._last_reading    = None
        self._coredaq_panel   = None
        self._sweep_logging   = False
        self._sweep_power_log = []
        self._power_sweep_logging = False
        self._power_sweep_log     = []
        self._last_sweep_csv       = None
        self._last_power_sweep_csv = None

        self._build_ui()
        self._set_state("disconnected")

    # ── property: current UI grid ──────────────────────────────────────────────

    @property
    def _ui_grid(self) -> float:
        return GRID_OPTIONS.get(self.combo_grid.currentText(), 50.0)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        root = QWidget()
        scroll.setWidget(root)
        top  = QVBoxLayout(root)
        top.setSpacing(8)
        top.setContentsMargins(12, 12, 12, 12)

        # ── Connection ──────────────────────────────────────────────────────
        conn_box = QGroupBox("Connection")
        cg = QHBoxLayout(conn_box)
        cg.addWidget(QLabel("COM port:"))
        self.spin_port = NoScrollSpinBox()
        self.spin_port.setRange(1, 32)
        self.spin_port.setValue(load_connection_settings().get("itla_com_port", 15))
        cg.addWidget(self.spin_port)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.do_connect)
        cg.addWidget(self.btn_connect)
        cg.addStretch()
        top.addWidget(conn_box)

        # ── Laser Capabilities (populated on connect) ────────────────────────
        caps_box = QGroupBox("Laser Capabilities")
        capg = QGridLayout(caps_box)
        capg.addWidget(QLabel("Freq range:"),  0, 0)
        self.lbl_freq_range = QLabel("—")
        capg.addWidget(self.lbl_freq_range,    0, 1)
        capg.addWidget(QLabel("Power range:"), 1, 0)
        self.lbl_pwr_range  = QLabel("—")
        capg.addWidget(self.lbl_pwr_range,     1, 1)
        capg.addWidget(QLabel("Min grid:"),    2, 0)
        self.lbl_min_grid   = QLabel("—")
        capg.addWidget(self.lbl_min_grid,      2, 1)
        top.addWidget(caps_box)

        # ── Control ─────────────────────────────────────────────────────────
        ctrl_box = QGroupBox("Control ITLA Laser")
        cg2 = QGridLayout(ctrl_box)

        cg2.addWidget(QLabel("Power (mW):"), 0, 0)
        self.spin_mw = NoScrollDoubleSpinBox()
        self.spin_mw.setRange(1.0, 22.0)
        self.spin_mw.setValue(5.0)
        self.spin_mw.setSingleStep(0.5)
        self.spin_mw.setDecimals(1)
        persist_spinbox(self.spin_mw, "itla_power_mw")
        cg2.addWidget(self.spin_mw, 0, 1, 1, 3)

        cg2.addWidget(QLabel("Grid spacing:"), 1, 0)
        self.combo_grid = QComboBox()
        for label in GRID_OPTIONS:
            self.combo_grid.addItem(label)
        self.combo_grid.setCurrentText("100 GHz")
        self.combo_grid.currentTextChanged.connect(self._on_grid_combo_changed)
        cg2.addWidget(self.combo_grid, 1, 1, 1, 3)

        cg2.addWidget(QLabel("Wavelength (nm):"), 2, 0)
        self.spin_nm = NoScrollDoubleSpinBox()
        self.spin_nm.setRange(1529.0, 1567.1)
        self.spin_nm.setValue(1550.0)
        self.spin_nm.setSingleStep(0.01)
        self.spin_nm.setDecimals(4)
        self.spin_nm.valueChanged.connect(self._on_nm_changed)
        cg2.addWidget(self.spin_nm, 2, 1, 1, 3)

        cg2.addWidget(QLabel("ITLA channel:"), 3, 0)
        self.spin_ch = NoScrollSpinBox()
        self.spin_ch.setRange(1, 500)
        self.spin_ch.setValue(1)
        self.spin_ch.valueChanged.connect(self._on_ch_changed)
        cg2.addWidget(self.spin_ch, 3, 1)

        self.lbl_ch_info = QLabel("? nm  |  ITU ?")
        self.lbl_ch_info.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        cg2.addWidget(self.lbl_ch_info, 3, 2, 1, 2)

        self.chk_ftf = QCheckBox("Use FTF sub-grid detuning (experimental)")
        self.chk_ftf.setChecked(False)
        self.chk_ftf.stateChanged.connect(lambda _: self._update_preview_from_nm())
        cg2.addWidget(self.chk_ftf, 4, 0, 1, 4)

        # Restored here, not at creation — restoring immediately calls
        # setValue(), which fires _on_nm_changed/_on_ch_changed synchronously,
        # and those touch spin_ch/chk_ftf/lbl_ch_info, all of which must
        # already exist. spin_ch restored last so it "wins" the sync (it's
        # the laser's actual ITU-grid setting; wavelength is the derived
        # display value).
        persist_spinbox(self.spin_nm, "itla_wavelength_nm")
        persist_spinbox(self.spin_ch, "itla_channel")

        live_row = QHBoxLayout()
        self.btn_retune = QPushButton("Apply Wavelength (live)")
        self.btn_retune.setToolTip(
            "Re-tune to the wavelength/channel above while the laser stays on—"
            "no off/on cycle.")
        self.btn_retune.setEnabled(False)
        self.btn_retune.clicked.connect(self.do_retune)
        self.btn_set_power_live = QPushButton("Apply Power (live)")
        self.btn_set_power_live.setToolTip(
            "Update output power while the laser stays on—no off/on cycle.")
        self.btn_set_power_live.setEnabled(False)
        self.btn_set_power_live.clicked.connect(self.do_set_power_live)
        live_row.addWidget(self.btn_retune)
        live_row.addWidget(self.btn_set_power_live)
        cg2.addLayout(live_row, 5, 0, 1, 4)

        self.btn_on = QPushButton("Turn Laser On")
        self.btn_on.setFixedHeight(32)
        self.btn_on.clicked.connect(self.do_on)
        cg2.addWidget(self.btn_on, 6, 0, 1, 2)

        self.btn_off = QPushButton("Turn Laser Off")
        self.btn_off.setFixedHeight(32)
        self.btn_off.clicked.connect(self.do_off)
        cg2.addWidget(self.btn_off, 6, 2, 1, 2)

        self.lbl_status = QLabel("LASER IS OFF")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.lbl_status.font()
        font.setBold(True)
        font.setPointSize(13)
        self.lbl_status.setFont(font)
        cg2.addWidget(self.lbl_status, 7, 0, 1, 4)

        top.addWidget(ctrl_box)

        # ── Readback ────────────────────────────────────────────────────────
        rb_box = QGroupBox("Readback")
        rg = QGridLayout(rb_box)
        rg.addWidget(QLabel("Frequency:"),  0, 0)
        self.lbl_freq = QLabel("—")
        rg.addWidget(self.lbl_freq, 0, 1)
        rg.addWidget(QLabel("Wavelength:"), 1, 0)
        self.lbl_nm_rb = QLabel("—")
        rg.addWidget(self.lbl_nm_rb, 1, 1)
        rg.addWidget(QLabel("Power out:"),  2, 0)
        self.lbl_power = QLabel("—")
        rg.addWidget(self.lbl_power, 2, 1)
        top.addWidget(rb_box)

        # ── Diagnostics ─────────────────────────────────────────────────────
        diag_box = QGroupBox("Diagnostics")
        dg = QGridLayout(diag_box)
        dg.addWidget(QLabel("Temperature:"),    0, 0)
        self.lbl_temp  = QLabel("—")
        dg.addWidget(self.lbl_temp,             0, 1)
        dg.addWidget(QLabel("Fatal status:"),   1, 0)
        self.lbl_statf = QLabel("—")
        dg.addWidget(self.lbl_statf,            1, 1)
        dg.addWidget(QLabel("Warning status:"), 2, 0)
        self.lbl_statw = QLabel("—")
        dg.addWidget(self.lbl_statw,            2, 1)
        self.btn_diag  = QPushButton("Refresh Diagnostics")
        self.btn_diag.clicked.connect(self.do_diagnostics)
        self.btn_diag.setEnabled(False)
        dg.addWidget(self.btn_diag,             3, 0, 1, 2)
        top.addWidget(diag_box)

        # ── Sweep ───────────────────────────────────────────────────────────
        sw_box = QGroupBox("Wavelength Sweep  (snaps to grid channels — no FTF)")
        sg = QGridLayout(sw_box)

        sg.addWidget(QLabel("Start (nm):"), 0, 0)
        self.spin_sw_start = NoScrollDoubleSpinBox()
        self.spin_sw_start.setRange(1529.0, 1567.1)
        self.spin_sw_start.setValue(1548.0)
        self.spin_sw_start.setDecimals(3)
        self.spin_sw_start.setSingleStep(1.0)
        persist_spinbox(self.spin_sw_start, "itla_sweep_start_nm")
        sg.addWidget(self.spin_sw_start, 0, 1)

        sg.addWidget(QLabel("Stop (nm):"), 0, 2)
        self.spin_sw_stop = NoScrollDoubleSpinBox()
        self.spin_sw_stop.setRange(1529.0, 1567.1)
        self.spin_sw_stop.setValue(1554.0)
        self.spin_sw_stop.setDecimals(3)
        self.spin_sw_stop.setSingleStep(1.0)
        persist_spinbox(self.spin_sw_stop, "itla_sweep_stop_nm")
        sg.addWidget(self.spin_sw_stop, 0, 3)

        sg.addWidget(QLabel("Step (GHz):"), 1, 0)
        self.spin_sw_step = NoScrollDoubleSpinBox()
        self.spin_sw_step.setRange(0.1, 500.0)
        self.spin_sw_step.setValue(100.0)
        self.spin_sw_step.setSingleStep(50.0)
        self.spin_sw_step.setDecimals(1)
        persist_spinbox(self.spin_sw_step, "itla_sweep_step_ghz")
        sg.addWidget(self.spin_sw_step, 1, 1)

        sg.addWidget(QLabel("Dwell (s):"), 1, 2)
        self.spin_dwell = NoScrollDoubleSpinBox()
        self.spin_dwell.setRange(0.1, 60.0)
        self.spin_dwell.setValue(1.0)
        self.spin_dwell.setSingleStep(0.5)
        persist_spinbox(self.spin_dwell, "itla_sweep_dwell_s")
        sg.addWidget(self.spin_dwell, 1, 3)

        self.btn_sweep = QPushButton("Start Sweep")
        self.btn_sweep.clicked.connect(self.do_sweep)
        sg.addWidget(self.btn_sweep, 2, 0, 1, 4)

        self._sweep_log_chk = QCheckBox("Log CoreDAQ power (all 4 channels)")
        self._sweep_log_chk.setChecked(True)
        self._sweep_log_chk.setToolTip(
            "Records the CoreDAQ optical power meter at each sweep step. "
            "On by default so sweep data is never silently missing this.")
        sg.addWidget(self._sweep_log_chk, 3, 0, 1, 3)
        self._sweep_export_btn = QPushButton("Export CSV…")
        self._sweep_export_btn.setEnabled(False)
        self._sweep_export_btn.clicked.connect(self._export_sweep_power_csv)
        sg.addWidget(self._sweep_export_btn, 3, 3)
        self._sweep_open_btn = QPushButton("📂 Open")
        self._sweep_open_btn.setEnabled(False)
        self._sweep_open_btn.setToolTip("Open the last-exported sweep CSV")
        self._sweep_open_btn.clicked.connect(lambda: open_saved_file(self._last_sweep_csv))
        sg.addWidget(self._sweep_open_btn, 3, 4)

        top.addWidget(sw_box)

        # ── Power Sweep (Cal 2-DC: power only, wavelength stays fixed) ───────
        pw_box = QGroupBox("Power Sweep  (wavelength stays fixed — laser must already be ON)")
        pwg = QGridLayout(pw_box)

        pwg.addWidget(QLabel("Start (mW):"), 0, 0)
        self.spin_pw_start = NoScrollDoubleSpinBox()
        self.spin_pw_start.setRange(1.0, 22.0)
        self.spin_pw_start.setValue(1.0)
        self.spin_pw_start.setDecimals(2)
        self.spin_pw_start.setSingleStep(0.5)
        persist_spinbox(self.spin_pw_start, "itla_power_sweep_start_mw")
        pwg.addWidget(self.spin_pw_start, 0, 1)

        pwg.addWidget(QLabel("Stop (mW):"), 0, 2)
        self.spin_pw_stop = NoScrollDoubleSpinBox()
        self.spin_pw_stop.setRange(1.0, 22.0)
        self.spin_pw_stop.setValue(10.0)
        self.spin_pw_stop.setDecimals(2)
        self.spin_pw_stop.setSingleStep(0.5)
        persist_spinbox(self.spin_pw_stop, "itla_power_sweep_stop_mw")
        pwg.addWidget(self.spin_pw_stop, 0, 3)

        pwg.addWidget(QLabel("Step (mW):"), 1, 0)
        self.spin_pw_step = NoScrollDoubleSpinBox()
        self.spin_pw_step.setRange(0.01, 10.0)
        self.spin_pw_step.setValue(1.0)
        self.spin_pw_step.setSingleStep(0.5)
        self.spin_pw_step.setDecimals(2)
        persist_spinbox(self.spin_pw_step, "itla_power_sweep_step_mw")
        pwg.addWidget(self.spin_pw_step, 1, 1)

        pwg.addWidget(QLabel("Dwell (s):"), 1, 2)
        self.spin_pw_dwell = NoScrollDoubleSpinBox()
        self.spin_pw_dwell.setRange(0.1, 60.0)
        self.spin_pw_dwell.setValue(1.0)
        self.spin_pw_dwell.setSingleStep(0.5)
        persist_spinbox(self.spin_pw_dwell, "itla_power_sweep_dwell_s")
        pwg.addWidget(self.spin_pw_dwell, 1, 3)

        self.btn_power_sweep = QPushButton("Start Power Sweep")
        self.btn_power_sweep.setEnabled(False)
        self.btn_power_sweep.clicked.connect(self.do_power_sweep)
        pwg.addWidget(self.btn_power_sweep, 2, 0, 1, 4)

        self._power_sweep_log_chk = QCheckBox("Log CoreDAQ power (all 4 channels)")
        self._power_sweep_log_chk.setChecked(True)
        self._power_sweep_log_chk.setToolTip(
            "Records the CoreDAQ optical power meter at each power-sweep step. "
            "On by default so sweep data is never silently missing this.")
        pwg.addWidget(self._power_sweep_log_chk, 3, 0, 1, 3)
        self._power_sweep_export_btn = QPushButton("Export CSV…")
        self._power_sweep_export_btn.setEnabled(False)
        self._power_sweep_export_btn.clicked.connect(self._export_power_sweep_csv)
        pwg.addWidget(self._power_sweep_export_btn, 3, 3)
        self._power_sweep_open_btn = QPushButton("📂 Open")
        self._power_sweep_open_btn.setEnabled(False)
        self._power_sweep_open_btn.setToolTip("Open the last-exported power-sweep CSV")
        self._power_sweep_open_btn.clicked.connect(lambda: open_saved_file(self._last_power_sweep_csv))
        pwg.addWidget(self._power_sweep_open_btn, 3, 4)

        top.addWidget(pw_box)

        # ── Dither ──────────────────────────────────────────────────────────
        dith_box = QGroupBox("Dither  (laser must be locked to channel first)")
        dg2 = QGridLayout(dith_box)

        dg2.addWidget(QLabel("Rate (kHz):"), 0, 0)
        self.spin_dith_rate = NoScrollSpinBox()
        self.spin_dith_rate.setRange(10, 200)
        self.spin_dith_rate.setValue(100)
        self.spin_dith_rate.setSingleStep(10)
        persist_spinbox(self.spin_dith_rate, "itla_dither_rate_khz")
        dg2.addWidget(self.spin_dith_rate, 0, 1, 1, 2)

        dg2.addWidget(QLabel("SBS FM deviation (0–4):"), 1, 0)
        self.spin_dith_dev = NoScrollSpinBox()
        self.spin_dith_dev.setRange(0, 4)
        self.spin_dith_dev.setValue(4)
        self.spin_dith_dev.setSingleStep(1)
        dg2.addWidget(self.spin_dith_dev, 1, 1)
        self.lbl_dith_dev = QLabel("= 0.4 GHz p-p")
        self.lbl_dith_dev.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        dg2.addWidget(self.lbl_dith_dev, 1, 2)
        self.spin_dith_dev.valueChanged.connect(
            lambda v: self.lbl_dith_dev.setText(f"= {v * 0.1:.1f} GHz p-p"))
        persist_spinbox(self.spin_dith_dev, "itla_dither_deviation")

        dg2.addWidget(QLabel("TxTrace AM amplitude (0–50):"), 2, 0)
        self.spin_dith_amp = NoScrollSpinBox()
        self.spin_dith_amp.setRange(0, 50)
        self.spin_dith_amp.setValue(50)
        self.spin_dith_amp.setSingleStep(5)
        dg2.addWidget(self.spin_dith_amp, 2, 1)
        self.lbl_dith_amp = QLabel("= 5.0% modulation")
        self.lbl_dith_amp.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        dg2.addWidget(self.lbl_dith_amp, 2, 2)
        self.spin_dith_amp.valueChanged.connect(
            lambda v: self.lbl_dith_amp.setText(f"= {v / 10:.1f}% modulation"))
        persist_spinbox(self.spin_dith_amp, "itla_dither_amplitude")

        btn_row = QHBoxLayout()
        self.btn_dith_sbs      = QPushButton("Enable SBS only")
        self.btn_dith_txtrace  = QPushButton("Enable TxTrace only")
        self.btn_dith_off      = QPushButton("Disable All")
        for b in (self.btn_dith_sbs, self.btn_dith_txtrace, self.btn_dith_off):
            b.setEnabled(False)
            btn_row.addWidget(b)
        self.btn_dith_sbs.clicked.connect(self._do_dither_sbs)
        self.btn_dith_txtrace.clicked.connect(self._do_dither_txtrace)
        self.btn_dith_off.clicked.connect(self._do_dither_off)
        dg2.addLayout(btn_row, 3, 0, 1, 3)

        top.addWidget(dith_box)

        # ── Log ─────────────────────────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(90)
        self.log.setStyleSheet("font-family: monospace; font-size: 10px;")
        top.addWidget(self.log)

        # Initial preview
        self._update_preview_from_nm()

    # ── State machine ──────────────────────────────────────────────────────────

    def _auto_diagnostics(self):
        if not self.worker.isRunning():
            self.worker.run_op("diagnostics")

    def _set_state(self, state: str):
        self._laser_state = state
        connected = state != "disconnected"
        busy      = state in ("warming", "locking", "power_sweeping")
        if connected and not busy:
            self._diag_timer.start()
        else:
            self._diag_timer.stop()

        self.btn_connect.setEnabled(not connected)
        self.btn_on.setEnabled(connected and not busy and state != "on")
        self.btn_off.setEnabled(connected and not busy and state == "on")
        self.btn_retune.setEnabled(connected and not busy and state == "on")
        self.btn_set_power_live.setEnabled(connected and not busy and state == "on")
        self.btn_sweep.setEnabled(connected and not busy)
        self.btn_power_sweep.setEnabled(connected and not busy and state == "on")
        self.btn_diag.setEnabled(connected and not busy)
        self.btn_dith_sbs.setEnabled(connected and not busy)
        self.btn_dith_txtrace.setEnabled(connected and not busy)
        self.btn_dith_off.setEnabled(connected and not busy)
        self.spin_port.setEnabled(not connected)

        labels = {
            "disconnected":    ("NOT CONNECTED",     C_TEXT),
            "warming":         ("WARMING UP...",     C_ORANGE),
            "locking":         ("LOCKING FREQ...",   C_ORANGE),
            "power_sweeping":  ("SWEEPING POWER...", C_ORANGE),
            "off":             ("LASER IS OFF",      C_TEXT),
            "on":              ("LASER IS ON",       C_RED),
        }
        text, color = labels.get(state, ("?", C_TEXT))
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color};")

    # ── Synced wavelength ↔ channel spin boxes ────────────────────────────────

    def _update_preview_from_nm(self):
        if self._updating:
            return
        self._updating = True
        nm = self.spin_nm.value()
        ch = nm_to_itla_ch(nm, self._fcf1, self._fcf2, self._grid, self._ui_grid)
        self.spin_ch.setValue(ch)
        self._refresh_ch_info(ch)
        self._updating = False

    def _update_preview_from_ch(self):
        if self._updating:
            return
        self._updating = True
        ch = self.spin_ch.value()
        nm = itla_ch_to_nm(ch, self._fcf1, self._fcf2, self._grid)
        self.spin_nm.setValue(nm)
        self._refresh_ch_info(ch)
        self._updating = False

    def _refresh_ch_info(self, ch: int):
        ch_nm   = itla_ch_to_nm(ch, self._fcf1, self._fcf2, self._grid)
        freq    = self._fcf1 * 1000.0 + self._fcf2 + (ch - 1) * self._grid
        itu_n   = round((freq - ITU_REF_GHZ) / self._ui_grid)
        base    = f"{ch_nm:.4f} nm  |  ITU {itu_n:+d} ({self._ui_grid:.0f} GHz grid)"

        if self.chk_ftf.isChecked():
            target_ghz = C_NM_GHZ / self.spin_nm.value()
            ftf_steps  = round((target_ghz - freq) / 0.1)
            if abs(ftf_steps) > FTF_LIMIT_STEPS:
                self.lbl_ch_info.setText(
                    f"FTF out of range ({ftf_steps * 0.1:+.1f} GHz needed, "
                    f"±{FTF_LIMIT_STEPS * 0.1:.0f} GHz max) — "
                    f"will lock to {ch_nm:.4f} nm")
                self.lbl_ch_info.setStyleSheet(f"color: {C_RED}; font-size: 10px;")
                return

        self.lbl_ch_info.setText(base)
        self.lbl_ch_info.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")

    def _on_nm_changed(self, _):
        self._update_preview_from_nm()

    def _on_ch_changed(self, _):
        self._update_preview_from_ch()

    def _on_grid_combo_changed(self, text):
        ghz = GRID_OPTIONS.get(text, 50.0)
        self.spin_sw_step.setValue(ghz)
        self._update_preview_from_nm()

    # ── Worker slots ──────────────────────────────────────────────────────────

    def on_status(self, msg: str, level: str):
        colors = {"info": C_TEXT, "warn": C_ORANGE, "error": C_RED, "ok": C_GREEN}
        self.log.append(f'<span style="color:{colors.get(level, C_TEXT)}">{msg}</span>')
        w = self.window()
        if hasattr(w, "status_bar"):
            w.status_bar.showMessage(msg, 5000)

    def on_state(self, state: str):
        self._set_state(state)

    def on_freq(self, freq_ghz: float, pdbm: float):
        nm = C_NM_GHZ / freq_ghz
        mw = 10 ** (pdbm / 10)
        self.lbl_freq.setText(f"{freq_ghz:.1f} GHz")
        self.lbl_nm_rb.setText(f"{nm:.4f} nm")
        self.lbl_power.setText(f"{pdbm:.2f} dBm  ({mw:.2f} mW)")
        self._last_reading = {"freq_ghz": freq_ghz, "nm": nm,
                               "power_dbm": pdbm, "power_mw": mw}

        if self._sweep_logging and self._coredaq_panel is not None:
            powers = self._coredaq_panel.latest_power_w()
            if powers is not None:
                self._sweep_power_log.append((nm, freq_ghz, pdbm, *powers))

        if self._power_sweep_logging and self._coredaq_panel is not None:
            powers = self._coredaq_panel.latest_power_w()
            if powers is not None:
                self._power_sweep_log.append((mw, freq_ghz, pdbm, *powers))

    def latest_reading(self):
        """Last (freq/wavelength/power) reading dict, or None if not connected."""
        if self._laser_state in ("disconnected",):
            return None
        return self._last_reading

    def on_grid_params(self, fcf1: int, fcf2: float, grid: float):
        self._fcf1 = fcf1
        self._fcf2 = fcf2
        self._grid = grid
        self._update_preview_from_nm()

    def on_capabilities(self, caps: dict):
        f_lo   = caps["f_lo_ghz"]
        f_hi   = caps["f_hi_ghz"]
        nm_min = C_NM_GHZ / f_hi   # high freq → short wavelength
        nm_max = C_NM_GHZ / f_lo   # low freq  → long wavelength
        opsl   = caps["opsl_dbm"]
        opsh   = caps["opsh_dbm"]
        mw_min = 10 ** (opsl / 10)
        mw_max = 10 ** (opsh / 10)
        lgrid  = caps["lgrid_ghz"]

        self.lbl_freq_range.setText(
            f"{f_lo/1000:.4f} \u2013 {f_hi/1000:.4f} THz  "
            f"({nm_max:.3f} \u2013 {nm_min:.3f} nm)")
        self.lbl_pwr_range.setText(
            f"{opsl:.1f} \u2013 {opsh:.1f} dBm  "
            f"({mw_min:.1f} \u2013 {mw_max:.1f} mW)")
        self.lbl_min_grid.setText(f"{lgrid:.1f} GHz")

        self.spin_nm.setRange(nm_min, nm_max)
        self.spin_sw_start.setRange(nm_min, nm_max)
        self.spin_sw_stop.setRange(nm_min, nm_max)
        self.spin_mw.setRange(round(mw_min, 1), round(mw_max, 1))
        self._update_preview_from_nm()

    def on_diagnostics(self, diag: dict):
        self.lbl_temp.setText(f"{diag['temp_c']:.2f} \u00b0C")

        locking = self._laser_state in ("warming", "locking")

        statf = diag["statf"]
        fatal = (statf >> 13) & 1
        alm   = (statf >> 14) & 1
        dis   = (statf >> 12) & 1
        if fatal:
            self.lbl_statf.setText(f"FATAL  (ALM={alm} DIS={dis}  raw=0x{statf:04X})")
            self.lbl_statf.setStyleSheet(f"color: {C_RED}; font-weight: bold;")
        elif alm and not locking:
            self.lbl_statf.setText(f"ALARM  (DIS={dis}  raw=0x{statf:04X})")
            self.lbl_statf.setStyleSheet(f"color: {C_ORANGE}; font-weight: bold;")
        elif alm and locking:
            self.lbl_statf.setText("ALARM — normal during lock acquisition")
            self.lbl_statf.setStyleSheet(f"color: {C_GRAY};")
        else:
            self.lbl_statf.setText("OK")
            self.lbl_statf.setStyleSheet(f"color: {C_GREEN};")

        statw = diag["statw"]
        wfreq = (statw >> 10) & 1
        wpwr  = (statw >>  8) & 1
        warn_flags = " ".join(filter(None, [
            "WFREQ" if wfreq else "", "WPWR" if wpwr else ""]))
        if warn_flags and locking:
            self.lbl_statw.setText(f"{warn_flags} — normal during lock acquisition")
            self.lbl_statw.setStyleSheet(f"color: {C_GRAY};")
        elif warn_flags:
            self.lbl_statw.setText(f"{warn_flags}  (raw=0x{statw:04X})")
            self.lbl_statw.setStyleSheet(f"color: {C_ORANGE}; font-weight: bold;")
        else:
            self.lbl_statw.setText("OK")
            self.lbl_statw.setStyleSheet(f"color: {C_GREEN};")

    def on_done(self, op: str):
        if op == "sweep" and self._sweep_logging:
            self._sweep_logging = False
            if self._sweep_power_log:
                self._sweep_export_btn.setEnabled(True)
                self._show_sweep_power_plot()
        elif op == "power_sweep":
            self._power_sweep_logging = False
            if self._power_sweep_log:
                self._power_sweep_export_btn.setEnabled(True)
                self._show_power_sweep_plot()

    def set_coredaq_panel(self, panel):
        """Wires the CoreDAQ tab in so wavelength sweeps can log optical power."""
        self._coredaq_panel = panel

    def _show_sweep_power_plot(self):
        series = {}
        for ch in range(4):
            xs = [row[0] for row in self._sweep_power_log]
            ys = [row[3 + ch] * 1e9 for row in self._sweep_power_log]
            series[f"MZI {ch + 1}"] = (xs, ys, "nW")
        win = MatplotlibPlotWindow("ITLA Sweep — CoreDAQ Power", "Wavelength", "nm")
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._sweep_plot_win = win

    def _export_sweep_power_csv(self):
        if not self._sweep_power_log:
            return
        import datetime
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"itla_sweep_coredaq_{stamp}.csv")
        comments = [
            f"laser: ITLA",
            f"sweep: {self.spin_sw_start.value():.4f} -> {self.spin_sw_stop.value():.4f} nm, "
            f"step {self.spin_sw_step.value():.1f} GHz, dwell {self.spin_dwell.value():.2f} s",
            f"power_setpoint_mw: {self.spin_mw.value():.2f}",
        ]
        header = ["wavelength_nm", "freq_ghz", "power_dbm",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = [[f"{nm:.4f}", f"{f:.2f}", f"{p:.3f}"] + [f"{w:.9e}" for w in powers]
                for nm, f, p, *powers in self._sweep_power_log]
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[ITLA Sweep] Saved {len(rows)} rows → {fname}")
        self._status(f"Saved {len(rows)} sweep/power rows → {fname}")
        self._last_sweep_csv = fname
        self._sweep_open_btn.setEnabled(True)

    def _show_power_sweep_plot(self):
        series = {}
        for ch in range(4):
            xs = [row[0] for row in self._power_sweep_log]
            ys = [row[3 + ch] * 1e9 for row in self._power_sweep_log]
            series[f"MZI {ch + 1}"] = (xs, ys, "nW")
        win = MatplotlibPlotWindow("ITLA Power Sweep — CoreDAQ Power", "Laser power", "mW")
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._power_sweep_plot_win = win

    def _export_power_sweep_csv(self):
        if not self._power_sweep_log:
            return
        import datetime
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"itla_power_sweep_coredaq_{stamp}.csv")
        comments = [
            "laser: ITLA",
            f"power_sweep: {self.spin_pw_start.value():.2f} -> {self.spin_pw_stop.value():.2f} mW, "
            f"step {self.spin_pw_step.value():.2f} mW, dwell {self.spin_pw_dwell.value():.2f} s",
            f"wavelength_nm: {self.spin_nm.value():.4f}",
        ]
        header = ["power_mw", "freq_ghz", "power_dbm",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = [[f"{mw:.4f}", f"{f:.2f}", f"{p:.3f}"] + [f"{w:.9e}" for w in powers]
                for mw, f, p, *powers in self._power_sweep_log]
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[ITLA Power Sweep] Saved {len(rows)} rows → {fname}")
        self._status(f"Saved {len(rows)} power-sweep rows → {fname}")
        self._last_power_sweep_csv = fname
        self._power_sweep_open_btn.setEnabled(True)

    # ── Button handlers ───────────────────────────────────────────────────────

    def do_connect(self):
        save_connection_setting("itla_com_port", self.spin_port.value())
        self._set_state("warming")
        self.worker.run_op("connect", port=self.spin_port.value(), baud=9600)

    def do_on(self):
        nm      = self.spin_nm.value()
        mw      = self.spin_mw.value()
        use_ftf = self.chk_ftf.isChecked()
        ch, ftf = nm_to_itla_ch_ftf(nm, self._fcf1, self._fcf2,
                                     self._grid, self._ui_grid)
        self.log.append(
            f"<i>Target {nm:.4f} nm → ch {ch} "
            f"({itla_ch_to_nm(ch, self._fcf1, self._fcf2, self._grid):.4f} nm)"
            + (f"  FTF {ftf*0.1:+.2f} GHz" if use_ftf else "") + "</i>")
        self._set_state("locking")
        self.worker.run_op("on", ch=ch, ftf=ftf, mw=mw, use_ftf=use_ftf)

    def do_retune(self):
        nm      = self.spin_nm.value()
        mw      = self.spin_mw.value()
        use_ftf = self.chk_ftf.isChecked()
        ch, ftf = nm_to_itla_ch_ftf(nm, self._fcf1, self._fcf2,
                                     self._grid, self._ui_grid)
        self.log.append(
            f"<i>Live retune → {nm:.4f} nm → ch {ch} "
            f"({itla_ch_to_nm(ch, self._fcf1, self._fcf2, self._grid):.4f} nm)"
            + (f"  FTF {ftf*0.1:+.2f} GHz" if use_ftf else "") + "</i>")
        self._set_state("locking")
        self.worker.run_op("retune", ch=ch, ftf=ftf, mw=mw, use_ftf=use_ftf)

    def do_set_power_live(self):
        mw = self.spin_mw.value()
        self.worker.run_op("set_power_live", mw=mw)

    def do_off(self):
        self.worker.run_op("off")

    def do_diagnostics(self):
        self.worker.run_op("diagnostics")

    def _do_dither_sbs(self):
        self.worker.run_op("dither", mode="sbs",
            rate_khz=self.spin_dith_rate.value(),
            deviation=self.spin_dith_dev.value(),
            amp=0)

    def _do_dither_txtrace(self):
        self.worker.run_op("dither", mode="txtrace",
            rate_khz=self.spin_dith_rate.value(),
            deviation=0,
            amp=self.spin_dith_amp.value())

    def _do_dither_off(self):
        self.worker.run_op("dither", mode="off", rate_khz=10, deviation=0, amp=0)

    def do_sweep(self):
        nm_start = self.spin_sw_start.value()
        nm_stop  = self.spin_sw_stop.value()
        if abs(nm_start - nm_stop) < 0.001:
            QMessageBox.warning(self, "Sweep", "Start and stop must differ.")
            return
        self._sweep_power_log = []
        self._sweep_export_btn.setEnabled(False)
        self._sweep_logging = self._sweep_log_chk.isChecked()
        self._set_state("locking")
        self.worker.run_op("sweep",
            nm_start=nm_start, nm_stop=nm_stop,
            step_ghz=self.spin_sw_step.value(),
            dwell_s=self.spin_dwell.value(),
            mw=self.spin_mw.value(),
            fcf1=self._fcf1, fcf2=self._fcf2,
            itla_grid=self._grid, ui_grid=self._ui_grid)

    def do_power_sweep(self):
        mw_start = self.spin_pw_start.value()
        mw_stop  = self.spin_pw_stop.value()
        if abs(mw_start - mw_stop) < 0.001:
            QMessageBox.warning(self, "Power Sweep", "Start and stop must differ.")
            return
        self._power_sweep_log = []
        self._power_sweep_export_btn.setEnabled(False)
        self._power_sweep_logging = self._power_sweep_log_chk.isChecked()
        self._set_state("power_sweeping")
        self.worker.run_op("power_sweep",
            mw_start=mw_start, mw_stop=mw_stop,
            mw_step=self.spin_pw_step.value(),
            dwell_s=self.spin_pw_dwell.value())

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        if self.itla is None:
            return
        if self._laser_state not in ("disconnected", "off"):
            try:
                if self.worker.isRunning():
                    self.worker.terminate()
                    self.worker.wait(2000)
                self.itla.resena(0)
            except Exception:
                pass
        try:
            self.itla.disconnect()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# CONEX-CC MOTOR CONTROLLER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class ConexWorker(QObject):
    """
    Runs blocking PyVISA calls off the GUI thread.
    All motor I/O goes through here — emit signals back to ConexPanel.
    """
    status_changed  = pyqtSignal(str)          # DISCONNECTED / CONNECTED / HOMING / READY / MOVING / STOPPED
    position_update = pyqtSignal(float)
    velocity_update = pyqtSignal(float)
    log_message     = pyqtSignal(str)
    error           = pyqtSignal(str)
    op_done         = pyqtSignal(str)          # name of finished operation

    # Hard ceiling on any single hardware call, on top of the VISA-level
    # motor.timeout (5000 ms, set in do_connect). That VISA timeout is
    # normally what bounds a query, but — same class of issue as CoreDAQ —
    # a wedged NI-VISA/serial driver can occasionally block underneath it in
    # an uninterruptible kernel wait no VISA-level timeout can preempt.
    # Every _call_with_timeout() call below runs the real call on a
    # throwaway daemon thread so this worker thread (and therefore the app)
    # is never the one stuck.
    HW_TIMEOUT_S = 7.0

    def __init__(self):
        super().__init__()
        self._motor = None
        self._rm    = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _call_with_timeout(self, func, *args, **kwargs):
        """Runs a blocking VISA/serial call on a throwaway daemon thread with a
        hard timeout, so a wedged call can't freeze this worker thread (or the
        whole app) unkillably. NOTE: the CoreDAQ worker deliberately does NOT
        use this pattern — its poll loop ran often enough that the per-call
        thread churn became the freeze, so it calls the hardware directly on
        its own worker thread instead (see CoreDAQWorker._call)."""
        result = {}
        def _run():
            try:
                result['value'] = func(*args, **kwargs)
            except Exception as e:
                result['error'] = e
            finally:
                result['done'] = True
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(self.HW_TIMEOUT_S)
        if not result.get('done'):
            raise TimeoutError(
                f"Conex motor stopped responding (no reply within {self.HW_TIMEOUT_S:.0f}s) "
                "— the serial connection is likely wedged. Unplug/replug the controller.")
        if 'error' in result:
            raise result['error']
        return result['value']

    def _query(self, cmd: str) -> str:
        return self._call_with_timeout(self._motor.query, cmd)

    def _write(self, cmd: str):
        self._call_with_timeout(self._motor.write, cmd)

    def _get_state_code(self) -> str:
        resp = self._query("1TS")
        return resp[-2:]

    def _wait_for_ready(self, timeout: float = 30.0) -> bool:
        self.log_message.emit("Waiting for READY…")
        start = time.time()
        while True:
            code = self._get_state_code()
            if code in ("32", "33", "34"):
                pos_raw = self._query("1TP")
                pos_val = float(pos_raw.replace("1TP", "").strip())
                self.position_update.emit(round(pos_val, 4))
                self.status_changed.emit("READY")
                return True
            if time.time() - start > timeout:
                return False
            time.sleep(0.2)

    def _refresh(self):
        try:
            pos_raw = self._query("1TP")
            vel_raw = self._query("1VA?")
            state   = self._query("1TS")
            self.position_update.emit(round(float(pos_raw.replace("1TP", "").strip()), 4))
            self.velocity_update.emit(round(float(vel_raw.replace("1VA", "").strip()), 4))
            code = state[-2:]
            if code in ("32", "33", "34"):
                self.status_changed.emit("READY")
            elif code == "1E":
                self.status_changed.emit("HOMING")
            elif code == "28":
                self.status_changed.emit("MOVING")
        except Exception:
            pass

    # ── Public slots (called via QMetaObject / direct connection on worker thread) ──

    def do_connect(self, port: int):
        try:
            if self._motor is not None:
                # Reconnecting (e.g. double-clicked Connect, or retry after a
                # failed attempt) — release the old handle first so it can't
                # leak the port open and make this attempt fail as "busy".
                try:
                    self._call_with_timeout(self._motor.close)
                except Exception:
                    pass
                self._motor = None
            if self._rm is None:
                self._rm = pyvisa.ResourceManager()
            address = f"ASRL{port}::INSTR"
            motor = self._call_with_timeout(self._rm.open_resource, address)
            try:
                motor.baud_rate       = 921600
                motor.data_bits       = 8
                motor.parity          = pyvisa.constants.Parity.none
                motor.stop_bits       = pyvisa.constants.StopBits.one
                motor.flow_control    = pyvisa.constants.ControlFlow.xon_xoff
                motor.write_termination = '\r\n'
                motor.read_termination  = '\r\n'
                motor.timeout         = 5000
            except Exception:
                self._call_with_timeout(motor.close)
                raise
            self._motor = motor
            self.log_message.emit(f"Connected to COM{port}")
            self.status_changed.emit("CONNECTED")
            self._refresh()
            self.op_done.emit("connect")
        except Exception as e:
            self.error.emit(f"Connect failed: {e}")

    def do_home(self):
        try:
            self._write("1OR")
            self.status_changed.emit("HOMING")
            self.log_message.emit("Homing motor…")
            ok = self._wait_for_ready()
            if ok:
                self.log_message.emit("Motor is READY")
                self.op_done.emit("home")
            else:
                self.error.emit("Homing timed out")
        except Exception as e:
            self.error.emit(f"Home error: {e}")

    def do_move_absolute(self, pos: float):
        try:
            self._wait_for_ready()
            self._write(f"1PA{pos:.4f}")
            self.status_changed.emit("MOVING")
            self.log_message.emit(f"Moving to {pos:.4f} mm")
            self._wait_for_ready()
            self.op_done.emit("move")
        except Exception as e:
            self.error.emit(f"Move absolute error: {e}")

    def do_move_relative(self, offset: float):
        try:
            self._wait_for_ready()
            self._write(f"1PR{offset:.4f}")
            self.status_changed.emit("MOVING")
            self.log_message.emit(f"Moving {offset:+.4f} mm relative")
            self._wait_for_ready()
            self.op_done.emit("move")
        except Exception as e:
            self.error.emit(f"Move relative error: {e}")

    # Travel limits (mm) for the TRA12CC — jog drives toward these extremes
    # and relies on do_jog_stop() to halt on button-release.
    JOG_MIN = 0.0
    JOG_MAX = 12.0

    def do_jog_start(self, direction: int):
        """Begin a continuous jog toward a travel limit.

        NON-BLOCKING on purpose: unlike do_move_absolute/relative this fires
        the move and returns immediately WITHOUT looping in _wait_for_ready().
        That keeps this worker thread's event loop free so the queued
        do_jog_stop() (sent the instant the button is released) is processed
        right away instead of waiting for a blocking move slot to finish.
        """
        try:
            target = self.JOG_MAX if direction > 0 else self.JOG_MIN
            self._write(f"1PA{target:.4f}")
            self.status_changed.emit("MOVING")
            self.log_message.emit(f"Jogging {'▶ (+)' if direction > 0 else '◀ (–)'}… release to stop")
        except Exception as e:
            self.error.emit(f"Jog start error: {e}")

    def do_jog_stop(self):
        try:
            self._write("ST")
            self.log_message.emit("Jog stopped")
            time.sleep(0.15)          # let the stage finish decelerating
            self._refresh()           # report the real resting position/state
            self.op_done.emit("jog_stop")
        except Exception as e:
            self.error.emit(f"Jog stop error: {e}")

    def do_poll_position(self):
        """Lightweight position read for live jog feedback — no logging, no
        op_done, so it can be fired repeatedly from a timer without spam."""
        try:
            raw = self._query("1TP")
            val = round(float(raw.replace("1TP", "").strip()), 4)
            self.position_update.emit(val)
        except Exception:
            pass

    def do_set_velocity(self, vel: float):
        try:
            capped = min(vel, 0.4)
            if capped != vel:
                self.log_message.emit("Velocity capped at 0.4 mm/s")
            self._write(f"1VA{capped:.4f}")
            self.velocity_update.emit(capped)
            self.log_message.emit(f"Velocity set to {capped:.4f} mm/s")
            self.op_done.emit("velocity")
        except Exception as e:
            self.error.emit(f"Set velocity error: {e}")

    def do_stop(self):
        try:
            self._write("ST")
            self.status_changed.emit("STOPPED")
            self.log_message.emit("⚠ EMERGENCY STOP")
        except Exception as e:
            self.error.emit(f"Stop error: {e}")

    def do_check_position(self):
        try:
            raw = self._query("1TP")
            val = round(float(raw.replace("1TP", "").strip()), 4)
            self.position_update.emit(val)
            self.log_message.emit(f"Position: {val} mm")
            self.op_done.emit("check_pos")
        except Exception as e:
            self.error.emit(f"Position query error: {e}")

    def do_check_velocity(self):
        try:
            raw = self._query("1VA?")
            val = round(float(raw.replace("1VA", "").strip()), 4)
            self.velocity_update.emit(val)
            self.log_message.emit(f"Velocity: {val} mm/s")
            self.op_done.emit("check_vel")
        except Exception as e:
            self.error.emit(f"Velocity query error: {e}")

    def do_check_state(self):
        try:
            resp = self._query("1TS")
            self.log_message.emit(f"State: {resp}  (code: {resp[-2:]})")
            self.op_done.emit("check_state")
        except Exception as e:
            self.error.emit(f"State query error: {e}")

    def do_get_pos_limit(self):
        try:
            resp = self._query("1SR?")
            self.log_message.emit(f"Positive limit: {resp}")
            self.op_done.emit("pos_limit")
        except Exception as e:
            self.error.emit(f"Pos limit error: {e}")

    def do_get_neg_limit(self):
        try:
            resp = self._query("1SL?")
            self.log_message.emit(f"Negative limit: {resp}")
            self.op_done.emit("neg_limit")
        except Exception as e:
            self.error.emit(f"Neg limit error: {e}")

    def do_get_identity(self):
        try:
            resp = self._query("1VE")
            self.log_message.emit(f"Identity: {resp}")
            self.op_done.emit("identity")
        except Exception as e:
            self.error.emit(f"Identity error: {e}")

    def do_list_resources(self):
        try:
            if self._rm is None:
                self._rm = pyvisa.ResourceManager()
            resources = self._call_with_timeout(self._rm.list_resources)
            self.log_message.emit(f"VISA resources: {resources}")
            self.op_done.emit("list_resources")
        except Exception as e:
            self.error.emit(f"List resources error: {e}")

    def do_dump_config(self):
        try:
            resp = self._query("1ZT")
            self.log_message.emit(f"Full config:\n{resp}")
            self.op_done.emit("dump_config")
        except Exception as e:
            self.error.emit(f"Dump config error: {e}")

    def do_disconnect(self):
        try:
            if self._motor:
                self._call_with_timeout(self._motor.close)
                self._motor = None
            self.status_changed.emit("DISCONNECTED")
            self.log_message.emit("Disconnected from motor")
            self.op_done.emit("disconnect")
        except Exception as e:
            self.error.emit(f"Disconnect error: {e}")


class ConexPanel(QWidget):
    """
    PyQt6 port of conex_cc_gui.py — Newport CONEX-CC / TRA12CC controller tab.
    All blocking PyVISA calls run in ConexWorker on a background QThread.
    """

    # Signals to invoke worker slots across threads
    _sig_connect      = pyqtSignal(int)
    _sig_home         = pyqtSignal()
    _sig_move_abs     = pyqtSignal(float)
    _sig_move_rel     = pyqtSignal(float)
    _sig_jog_start    = pyqtSignal(int)
    _sig_jog_stop     = pyqtSignal()
    _sig_poll_pos     = pyqtSignal()
    _sig_set_vel      = pyqtSignal(float)
    _sig_stop         = pyqtSignal()
    _sig_check_pos    = pyqtSignal()
    _sig_check_vel    = pyqtSignal()
    _sig_check_state  = pyqtSignal()
    _sig_pos_limit    = pyqtSignal()
    _sig_neg_limit    = pyqtSignal()
    _sig_identity     = pyqtSignal()
    _sig_list_res     = pyqtSignal()
    _sig_dump_config  = pyqtSignal()
    _sig_disconnect   = pyqtSignal()

    def __init__(self, parent=None, label: str = "", settings_key: str = "conex_com_port",
                 default_port: int = 4):
        super().__init__(parent)
        self._label        = label
        self._settings_key = settings_key
        self._default_port = default_port

        if not HAS_PYVISA:
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(
                "pyvisa is not installed.\n"
                "Run:  uv pip install pyvisa pyvisa-py\n"
                "then restart the GUI."))
            return

        # ── Worker thread ─────────────────────────────────────────────────────
        self._worker = ConexWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        # Connect panel signals → worker slots
        self._sig_connect.connect(self._worker.do_connect)
        self._sig_home.connect(self._worker.do_home)
        self._sig_move_abs.connect(self._worker.do_move_absolute)
        self._sig_move_rel.connect(self._worker.do_move_relative)
        self._sig_jog_start.connect(self._worker.do_jog_start)
        self._sig_jog_stop.connect(self._worker.do_jog_stop)
        self._sig_poll_pos.connect(self._worker.do_poll_position)
        self._sig_set_vel.connect(self._worker.do_set_velocity)
        self._sig_stop.connect(self._worker.do_stop)
        self._sig_check_pos.connect(self._worker.do_check_position)
        self._sig_check_vel.connect(self._worker.do_check_velocity)
        self._sig_check_state.connect(self._worker.do_check_state)
        self._sig_pos_limit.connect(self._worker.do_get_pos_limit)
        self._sig_neg_limit.connect(self._worker.do_get_neg_limit)
        self._sig_identity.connect(self._worker.do_get_identity)
        self._sig_list_res.connect(self._worker.do_list_resources)
        self._sig_dump_config.connect(self._worker.do_dump_config)
        self._sig_disconnect.connect(self._worker.do_disconnect)

        # Connect worker signals → GUI slots
        self._worker.status_changed.connect(self._on_status)
        self._worker.position_update.connect(self._on_position)
        self._worker.velocity_update.connect(self._on_velocity)
        self._worker.log_message.connect(self._on_log)
        self._worker.error.connect(self._on_error)
        self._worker.op_done.connect(self._on_op_done)

        self._build_ui()

        # Polls the position ~4×/s while an arrow is held so the readout
        # tracks the stage during a jog (started/stopped in _start_jog/_stop_jog).
        self._jog_timer = QTimer(self)
        self._jog_timer.setInterval(250)
        self._jog_timer.timeout.connect(lambda: self._sig_poll_pos.emit())

        # Deliberately no auto-connect here (unlike CoreDAQ/Santec) — connect
        # manually via the button.

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        final = QVBoxLayout(self)
        final.setContentsMargins(10, 10, 10, 10)

        root = QHBoxLayout()
        root.setSpacing(12)
        final.addLayout(root)

        # ── Left: Connection ──────────────────────────────────────────────────
        conn_box = QGroupBox(f"Connection — {self._label}" if self._label else "Connection")
        conn_lay = QGridLayout(conn_box)

        conn_lay.addWidget(QLabel("Motor Status:"), 0, 0)
        self._status_lbl = QLabel("DISCONNECTED")
        self._status_lbl.setStyleSheet(f"color: {C_RED}; font-weight: bold;")
        conn_lay.addWidget(self._status_lbl, 0, 1)

        conn_lay.addWidget(QLabel("COM Port #:"), 1, 0)
        self._port_spin = NoScrollSpinBox()
        self._port_spin.setRange(1, 99)
        self._port_spin.setValue(load_connection_settings().get(self._settings_key, self._default_port))
        conn_lay.addWidget(self._port_spin, 1, 1)

        self._connect_btn = QPushButton("Connect to Motor")
        self._connect_btn.clicked.connect(self._do_connect)
        conn_lay.addWidget(self._connect_btn, 2, 0, 1, 2)

        self._home_btn = QPushButton("HOME MOTOR")
        self._home_btn.setEnabled(False)
        self._home_btn.clicked.connect(lambda: self._sig_home.emit())
        conn_lay.addWidget(self._home_btn, 3, 0, 1, 2)

        conn_lay.addWidget(QLabel("Manual Checks:"), 4, 0, 1, 2)

        self._state_btn = QPushButton("Check State")
        self._state_btn.setEnabled(False)
        self._state_btn.clicked.connect(lambda: self._sig_check_state.emit())
        conn_lay.addWidget(self._state_btn, 5, 0, 1, 2)

        self._pos_btn = QPushButton("Check Position")
        self._pos_btn.setEnabled(False)
        self._pos_btn.clicked.connect(lambda: self._sig_check_pos.emit())
        conn_lay.addWidget(self._pos_btn, 6, 0, 1, 2)

        self._vel_check_btn = QPushButton("Check Velocity")
        self._vel_check_btn.setEnabled(False)
        self._vel_check_btn.clicked.connect(lambda: self._sig_check_vel.emit())
        conn_lay.addWidget(self._vel_check_btn, 7, 0, 1, 2)

        self._disconnect_btn = QPushButton("DISCONNECT")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(lambda: self._sig_disconnect.emit())
        conn_lay.addWidget(self._disconnect_btn, 8, 0, 1, 2)

        conn_lay.setRowStretch(9, 1)
        root.addWidget(conn_box)

        # ── Center: Quick-start instructions ─────────────────────────────────
        info_box = QGroupBox("Quick Start")
        info_lay = QVBoxLayout(info_box)
        steps = [
            "① Enter COM port # (e.g. 4)",
            "② Click Connect",
            "③ Click Home Motor\n    and wait for READY",
            "④ All functions now available!",
            "",
            "⚠ Reminders:",
            "• Motor must be STATIONARY\n  before disconnecting",
            "• Start with small moves (1 mm)",
            "• Max velocity is 0.4 mm/s",
            "• LED solid green = READY",
        ]
        for s in steps:
            lbl = QLabel(s)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {C_GRAY};")
            info_lay.addWidget(lbl)
        info_lay.addStretch()
        root.addWidget(info_box)

        # ── Right: Movement ───────────────────────────────────────────────────
        move_box = QGroupBox("Movement")
        move_lay = QGridLayout(move_box)

        move_lay.addWidget(QLabel("Current Velocity (mm/s):"), 0, 0)
        self._vel_lbl = QLabel("---")
        self._vel_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
        move_lay.addWidget(self._vel_lbl, 0, 1)

        move_lay.addWidget(QLabel("Current Position (mm):"), 1, 0)
        self._pos_lbl = QLabel("---")
        self._pos_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
        move_lay.addWidget(self._pos_lbl, 1, 1)

        move_lay.addWidget(QLabel("Move Absolute (mm):"), 2, 0)
        self._abs_spin = NoScrollDoubleSpinBox()
        self._abs_spin.setRange(0.0, 12.0)
        self._abs_spin.setDecimals(4)
        self._abs_spin.setSingleStep(0.1)
        # settings_key is e.g. "conex_x_com_port"/"conex_y_com_port" — reuse
        # its axis prefix so X and Y each get their own saved distance/velocity
        # instead of sharing one (this widget is instantiated once per axis).
        axis_key = self._settings_key.replace("_com_port", "")
        persist_spinbox(self._abs_spin, f"{axis_key}_abs_mm")
        move_lay.addWidget(self._abs_spin, 2, 1)
        # ◀  GO!  ▶ — GO! moves to the absolute position above; the arrows
        # nudge RELATIVE by that same distance in either direction.
        abs_btns = QHBoxLayout()
        abs_btns.setContentsMargins(0, 0, 0, 0)
        abs_btns.setSpacing(3)
        self._abs_left_btn = QPushButton("◀")
        self._abs_left_btn.setEnabled(False)
        self._abs_left_btn.setToolTip("Move left (negative) by the distance above")
        self._abs_left_btn.setFixedWidth(32)
        self._abs_left_btn.clicked.connect(lambda: self._do_abs_arrow(-1))
        self._abs_btn = QPushButton("GO!")
        self._abs_btn.setEnabled(False)
        self._abs_btn.clicked.connect(self._do_move_abs)
        self._abs_right_btn = QPushButton("▶")
        self._abs_right_btn.setEnabled(False)
        self._abs_right_btn.setToolTip("Move right (positive) by the distance above")
        self._abs_right_btn.setFixedWidth(32)
        self._abs_right_btn.clicked.connect(lambda: self._do_abs_arrow(1))
        abs_btns.addWidget(self._abs_left_btn)
        abs_btns.addWidget(self._abs_btn)
        abs_btns.addWidget(self._abs_right_btn)
        move_lay.addLayout(abs_btns, 2, 2)

        move_lay.addWidget(QLabel("Move Relative (mm):"), 3, 0)
        self._rel_spin = NoScrollDoubleSpinBox()
        self._rel_spin.setRange(-12.0, 12.0)
        self._rel_spin.setDecimals(4)
        self._rel_spin.setSingleStep(0.1)
        persist_spinbox(self._rel_spin, f"{axis_key}_rel_mm")
        move_lay.addWidget(self._rel_spin, 3, 1)
        self._rel_btn = QPushButton("GO!")
        self._rel_btn.setEnabled(False)
        self._rel_btn.clicked.connect(self._do_move_rel)
        move_lay.addWidget(self._rel_btn, 3, 2)

        # ── Hold-to-move (jog) ────────────────────────────────────────────────
        # Press and HOLD an arrow to drive continuously at the set velocity;
        # release to stop. Uses pressed/released instead of clicked.
        move_lay.addWidget(QLabel("Hold to Move (Jog):"), 4, 0)
        jog_btns = QHBoxLayout()
        jog_btns.setContentsMargins(0, 0, 0, 0)
        jog_btns.setSpacing(3)
        self._jog_left_btn = QPushButton("◀ Hold")
        self._jog_left_btn.setEnabled(False)
        self._jog_left_btn.setToolTip("Hold to jog left (negative); release to stop")
        self._jog_left_btn.pressed.connect(lambda: self._start_jog(-1))
        self._jog_left_btn.released.connect(self._stop_jog)
        self._jog_right_btn = QPushButton("Hold ▶")
        self._jog_right_btn.setEnabled(False)
        self._jog_right_btn.setToolTip("Hold to jog right (positive); release to stop")
        self._jog_right_btn.pressed.connect(lambda: self._start_jog(1))
        self._jog_right_btn.released.connect(self._stop_jog)
        jog_btns.addWidget(self._jog_left_btn)
        jog_btns.addWidget(self._jog_right_btn)
        move_lay.addLayout(jog_btns, 4, 1, 1, 2)

        move_lay.addWidget(QLabel("Set Velocity (mm/s):"), 5, 0)
        self._vel_spin = NoScrollDoubleSpinBox()
        self._vel_spin.setRange(0.0001, 0.4)
        self._vel_spin.setDecimals(4)
        self._vel_spin.setValue(0.1)
        self._vel_spin.setSingleStep(0.05)
        persist_spinbox(self._vel_spin, f"{axis_key}_vel_mm_s")
        move_lay.addWidget(self._vel_spin, 5, 1)
        self._vel_btn = QPushButton("SET!")
        self._vel_btn.setEnabled(False)
        self._vel_btn.clicked.connect(self._do_set_vel)
        move_lay.addWidget(self._vel_btn, 5, 2)

        self._stop_btn = QPushButton("⚠ EMERGENCY STOP ⚠")
        # Always enabled, independent of connect/disconnect state — an
        # e-stop that's only clickable while the app *thinks* it's connected
        # defeats the purpose. do_stop() is a no-op error (logged, not
        # raised) if there's no motor handle open.
        self._stop_btn.setStyleSheet("background: #B71C1C; color: white; font-weight: bold; font-size: 13px;")
        self._stop_btn.clicked.connect(lambda: self._sig_stop.emit())
        move_lay.addWidget(self._stop_btn, 6, 0, 1, 3)

        move_lay.addWidget(QLabel("Diagnostics:"), 7, 0, 1, 3)

        self._pos_limit_btn = QPushButton("Get Positive Limit")
        self._pos_limit_btn.setEnabled(False)
        self._pos_limit_btn.clicked.connect(lambda: self._sig_pos_limit.emit())
        move_lay.addWidget(self._pos_limit_btn, 8, 0)

        self._neg_limit_btn = QPushButton("Get Negative Limit")
        self._neg_limit_btn.setEnabled(False)
        self._neg_limit_btn.clicked.connect(lambda: self._sig_neg_limit.emit())
        move_lay.addWidget(self._neg_limit_btn, 8, 1)

        self._identity_btn = QPushButton("Get Device Info")
        self._identity_btn.setEnabled(False)
        self._identity_btn.clicked.connect(lambda: self._sig_identity.emit())
        move_lay.addWidget(self._identity_btn, 9, 0)

        self._resources_btn = QPushButton("List VISA Resources")
        self._resources_btn.clicked.connect(lambda: self._sig_list_res.emit())
        move_lay.addWidget(self._resources_btn, 9, 1)

        self._config_btn = QPushButton("Dump All Config (1ZT)")
        self._config_btn.setEnabled(False)
        self._config_btn.clicked.connect(lambda: self._sig_dump_config.emit())
        move_lay.addWidget(self._config_btn, 9, 2)

        move_lay.setRowStretch(10, 1)
        root.addWidget(move_box, stretch=1)

        # ── Bottom: Log ───────────────────────────────────────────────────────
        log_box = QGroupBox("Log")
        log_lay = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        log_lay.addWidget(self._log)
        final.addWidget(log_box)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_status(self, s: str):
        self._status_lbl.setText(s)
        colors = {
            "DISCONNECTED": C_RED,
            "CONNECTED":    C_BLUE,
            "HOMING":       C_ORANGE,
            "READY":        C_GREEN,
            "MOVING":       C_GOLD,
            "STOPPED":      C_RED,
        }
        self._status_lbl.setStyleSheet(
            f"color: {colors.get(s, C_GRAY)}; font-weight: bold;")

    def _on_position(self, val: float):
        self._pos_lbl.setText(f"{val:.4f} mm")

    def _on_velocity(self, val: float):
        self._vel_lbl.setText(f"{val:.4f} mm/s")

    def _on_log(self, msg: str):
        self._log.append(msg)

    def _on_error(self, msg: str):
        self._log.append(f"<span style='color:{C_RED};'>ERROR: {msg}</span>")

    def _on_op_done(self, op: str):
        if op == "connect":
            for btn in [self._home_btn, self._pos_btn, self._vel_check_btn,
                        self._disconnect_btn, self._state_btn,
                        self._identity_btn, self._config_btn,
                        self._pos_limit_btn, self._neg_limit_btn,
                        self._vel_check_btn]:
                btn.setEnabled(True)
        elif op == "home":
            for btn in [self._abs_btn, self._rel_btn, self._vel_btn,
                        self._abs_left_btn, self._abs_right_btn,
                        self._jog_left_btn, self._jog_right_btn]:
                btn.setEnabled(True)
        elif op == "disconnect":
            for btn in [self._home_btn, self._pos_btn, self._vel_check_btn,
                        self._disconnect_btn, self._state_btn,
                        self._identity_btn, self._config_btn,
                        self._pos_limit_btn, self._neg_limit_btn,
                        self._abs_btn, self._rel_btn, self._vel_btn,
                        self._abs_left_btn, self._abs_right_btn,
                        self._jog_left_btn, self._jog_right_btn]:
                btn.setEnabled(False)

    # ── Button actions ────────────────────────────────────────────────────────

    def _do_connect(self):
        save_connection_setting(self._settings_key, self._port_spin.value())
        self._sig_connect.emit(self._port_spin.value())

    def _do_move_abs(self):
        self._sig_move_abs.emit(self._abs_spin.value())

    def _do_move_rel(self):
        self._sig_move_rel.emit(self._rel_spin.value())

    def _do_abs_arrow(self, direction: int):
        """Left/right arrows next to Move Absolute: nudge RELATIVE by the
        distance in the Move Absolute box, in the chosen direction."""
        self._sig_move_rel.emit(direction * self._abs_spin.value())

    def _start_jog(self, direction: int):
        """Button pressed and held — begin a continuous jog and poll the
        position live so the readout tracks the stage while it moves."""
        self._sig_jog_start.emit(direction)
        self._jog_timer.start()

    def _stop_jog(self):
        """Button released — stop polling and halt the stage."""
        self._jog_timer.stop()
        self._sig_jog_stop.emit()

    def _do_set_vel(self):
        self._sig_set_vel.emit(self._vel_spin.value())

    # ── Public API for the dual-axis (XY) container ──────────────────────────

    def move_absolute(self, pos: float):
        """Fire-and-forget move, queued to this motor's own worker thread —
        used by ConexDualPanel to kick off X and Y moves back-to-back so they
        run concurrently instead of one waiting for the other to finish."""
        self._sig_move_abs.emit(pos)

    def home(self):
        self._sig_home.emit()

    def cleanup(self):
        if HAS_PYVISA:
            self._sig_disconnect.emit()
            self._thread.quit()
            self._thread.wait(2000)


class ConexDualPanel(QWidget):
    """
    Two independent CONEX-CC motors (X and Y), each with its own COM port,
    worker thread, and manual controls — plus a synchronized-move box that
    kicks off an absolute move on both at once, so the stage can be driven
    diagonally instead of one axis at a time.

    Each ConexPanel below owns its motor's blocking PyVISA calls on its own
    QThread, so firing move_absolute() on both back-to-back from the GUI
    thread queues two independent moves that actually run concurrently.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.motor_x = ConexPanel(label="X Axis", settings_key="conex_x_com_port", default_port=4)
        self.motor_y = ConexPanel(label="Y Axis", settings_key="conex_y_com_port", default_port=5)

        final = QVBoxLayout(self)
        final.setContentsMargins(10, 10, 10, 10)

        if HAS_PYVISA:
            sync_box = QGroupBox("Synchronized XY Move")
            sync_lay = QGridLayout(sync_box)

            sync_lay.addWidget(QLabel("Target X (mm):"), 0, 0)
            self._x_spin = NoScrollDoubleSpinBox()
            self._x_spin.setRange(0.0, 12.0)
            self._x_spin.setDecimals(4)
            self._x_spin.setSingleStep(0.1)
            persist_spinbox(self._x_spin, "conex_sync_target_x_mm")
            sync_lay.addWidget(self._x_spin, 0, 1)

            sync_lay.addWidget(QLabel("Target Y (mm):"), 0, 2)
            self._y_spin = NoScrollDoubleSpinBox()
            self._y_spin.setRange(0.0, 12.0)
            self._y_spin.setDecimals(4)
            self._y_spin.setSingleStep(0.1)
            persist_spinbox(self._y_spin, "conex_sync_target_y_mm")
            sync_lay.addWidget(self._y_spin, 0, 3)

            self._move_xy_btn = QPushButton("MOVE XY")
            self._move_xy_btn.clicked.connect(self._do_move_xy)
            sync_lay.addWidget(self._move_xy_btn, 0, 4)

            self._home_xy_btn = QPushButton("HOME BOTH")
            self._home_xy_btn.clicked.connect(self._do_home_xy)
            sync_lay.addWidget(self._home_xy_btn, 1, 0, 1, 2)

            final.addWidget(sync_box)

        tabs = QTabWidget()
        tabs.addTab(self.motor_x, "X Axis")
        tabs.addTab(self.motor_y, "Y Axis")
        final.addWidget(tabs, stretch=1)

    def _do_move_xy(self):
        self.motor_x.move_absolute(self._x_spin.value())
        self.motor_y.move_absolute(self._y_spin.value())

    def _do_home_xy(self):
        self.motor_x.home()
        self.motor_y.home()

    def cleanup(self):
        self.motor_x.cleanup()
        self.motor_y.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
# HP 8168F TUNABLE LASER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class HP8168FWorker(QObject):
    """
    Runs blocking PyVISA/GPIB calls off the GUI thread.
    All laser I/O goes through here — emit signals back to HP8168FPanel.
    """
    status_changed    = pyqtSignal(str)          # DISCONNECTED / CONNECTED / SWEEPING
    wavelength_update = pyqtSignal(float)
    power_update      = pyqtSignal(float)
    output_update     = pyqtSignal(bool)
    range_update      = pyqtSignal(float, float, float)   # min_nm, max_nm, max_mw
    sweep_progress    = pyqtSignal(int, int, float)        # idx, total, wavelength_nm
    power_sweep_progress = pyqtSignal(int, int, float)     # idx, total, power_mw
    log_message       = pyqtSignal(str)
    error              = pyqtSignal(str)
    op_done            = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._laser = None
        # threading.Event, not a plain bool: Stop must take effect while do_sweep()
        # is blocking the worker thread's event loop, so it can't wait for a queued
        # cross-thread signal to be delivered — the GUI thread sets this directly.
        self._stop_event = threading.Event()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sleep_interruptible(self, total_s: float):
        remaining = total_s
        while remaining > 0 and not self._stop_event.is_set():
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk

    # ── Public slots (called via signal connections on worker thread) ───────

    def do_connect(self, gpib_addr: int, prologix_port: int):
        try:
            device_name = f"Prologix::{gpib_addr}::ASRL{prologix_port}::INSTR"
            self._laser = HP8168F(device_name=device_name, force_connect=True)
            self.status_changed.emit("CONNECTED")
            self.range_update.emit(self._laser._min_wavelength,
                                    self._laser._max_wavelength,
                                    self._laser._max_power)
            self.wavelength_update.emit(self._laser.wavelength)
            self.power_update.emit(self._laser.power)
            self.output_update.emit(self._laser.on_or_off)
            self.log_message.emit(f"Connected to HP-8168F ({device_name})")
            self.op_done.emit("connect")
        except Exception as e:
            self.error.emit(f"Connect failed: {e}")

    def do_set_wavelength(self, nm: float):
        try:
            self._laser.wavelength = nm
            self.wavelength_update.emit(nm)
            self.log_message.emit(f"Wavelength set to {nm:.4f} nm")
            self.op_done.emit("set_wavelength")
        except Exception as e:
            self.error.emit(f"Set wavelength error: {e}")

    def do_set_power(self, mw: float):
        try:
            self._laser.power = mw
            self.power_update.emit(mw)
            self.log_message.emit(f"Power set to {mw:.3f} mW")
            self.op_done.emit("set_power")
        except Exception as e:
            self.error.emit(f"Set power error: {e}")

    def do_set_output(self, on: bool):
        try:
            self._laser.on_or_off = on
            self.output_update.emit(on)
            self.log_message.emit(f"Output {'ON' if on else 'OFF'}")
            self.op_done.emit("set_output")
        except Exception as e:
            self.error.emit(f"Set output error: {e}")

    def do_sweep(self, nm_start: float, nm_stop: float, nm_step: float, dwell_s: float):
        """
        Step the laser wavelength from nm_start to nm_stop in nm_step increments,
        dwelling dwell_s at each point. Direction follows nm_start → nm_stop
        (i.e. it sweeps in whichever direction the user set, not always ascending).
        """
        try:
            if nm_step <= 0:
                self.error.emit("Step size must be positive")
                return

            self._stop_event.clear()
            step = abs(nm_step) if nm_stop >= nm_start else -abs(nm_step)

            targets = []
            v = nm_start
            if step >= 0:
                while v <= nm_stop + 1e-9:
                    targets.append(round(v, 6))
                    v += step
            else:
                while v >= nm_stop - 1e-9:
                    targets.append(round(v, 6))
                    v += step
            if not targets:
                targets = [nm_start]

            total = len(targets)
            self.status_changed.emit("SWEEPING")
            self.log_message.emit(
                f"Sweep: {total} points, {nm_start:.4f} → {nm_stop:.4f} nm, "
                f"{nm_step:.4f} nm step, {dwell_s:.2f} s dwell")

            for idx, wl in enumerate(targets):
                if self._stop_event.is_set():
                    self.log_message.emit("Sweep stopped by user")
                    break
                self._laser.wavelength = wl
                self.wavelength_update.emit(wl)
                self.sweep_progress.emit(idx + 1, total, wl)
                self._sleep_interruptible(dwell_s)

            self.status_changed.emit("CONNECTED")
            self.log_message.emit("Sweep complete")
            self.op_done.emit("sweep")
        except Exception as e:
            self.error.emit(f"Sweep error: {e}")
            self.status_changed.emit("CONNECTED")

    def do_power_sweep(self, mw_start: float, mw_stop: float, mw_step: float, dwell_s: float):
        """
        Steps output power from mw_start to mw_stop in mw_step increments,
        wavelength held fixed, dwelling dwell_s at each point (Cal 2-DC).
        """
        try:
            if mw_step <= 0:
                self.error.emit("Step size must be positive")
                return

            self._stop_event.clear()
            step = abs(mw_step) if mw_stop >= mw_start else -abs(mw_step)

            targets = []
            v = mw_start
            if step >= 0:
                while v <= mw_stop + 1e-9:
                    targets.append(round(v, 4))
                    v += step
            else:
                while v >= mw_stop - 1e-9:
                    targets.append(round(v, 4))
                    v += step
            if not targets:
                targets = [mw_start]

            total = len(targets)
            self.status_changed.emit("SWEEPING")
            self.log_message.emit(
                f"Power sweep: {total} points, {mw_start:.2f} → {mw_stop:.2f} mW, "
                f"{mw_step:.2f} mW step, {dwell_s:.2f} s dwell")

            for idx, mw in enumerate(targets):
                if self._stop_event.is_set():
                    self.log_message.emit("Power sweep stopped by user")
                    break
                self._laser.power = mw
                self.power_update.emit(mw)
                self.power_sweep_progress.emit(idx + 1, total, mw)
                self._sleep_interruptible(dwell_s)

            self.status_changed.emit("CONNECTED")
            self.log_message.emit("Power sweep complete")
            self.op_done.emit("power_sweep")
        except Exception as e:
            self.error.emit(f"Power sweep error: {e}")
            self.status_changed.emit("CONNECTED")

    def do_stop_sweep(self):
        self._stop_event.set()

    def do_disconnect(self):
        try:
            if self._laser is not None:
                # Turn the laser output off BEFORE dropping the connection.
                # Disconnecting — including on GUI close — must never leave the
                # diode emitting with no software in control. Guarded on its own
                # so a comms hiccup here can't block the actual close().
                try:
                    self._laser.on_or_off = False
                    self.output_update.emit(False)
                    self.log_message.emit("Laser output OFF (auto, before disconnect)")
                except Exception as e:
                    self.log_message.emit(
                        f"Warning: could not turn laser off before disconnect: {e}")
                self._laser.close()
                self._laser = None
            self.status_changed.emit("DISCONNECTED")
            self.log_message.emit("Disconnected from HP-8168F")
            self.op_done.emit("disconnect")
        except Exception as e:
            self.error.emit(f"Disconnect error: {e}")


class HP8168FPanel(QWidget):
    """
    HP/Agilent 8168F tunable laser source — GPIB control via pyvisa.
    All blocking PyVISA calls run in HP8168FWorker on a background QThread.
    """

    # Signals to invoke worker slots across threads
    _sig_connect     = pyqtSignal(int, int)   # gpib_addr, prologix_com_port
    _sig_set_wl      = pyqtSignal(float)
    _sig_set_power   = pyqtSignal(float)
    _sig_set_output  = pyqtSignal(bool)
    _sig_sweep       = pyqtSignal(float, float, float, float)
    _sig_power_sweep = pyqtSignal(float, float, float, float)
    _sig_stop_sweep  = pyqtSignal()
    _sig_disconnect  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        if not HAS_PYVISA or not HAS_HP8168F:
            lay = QVBoxLayout(self)
            msg = []
            if not HAS_PYVISA:
                msg.append("pyvisa is not installed. Run: uv pip install pyvisa pyvisa-py")
            if not HAS_HP8168F:
                msg.append("hardware.laser_hp_8168F module not found —\n"
                            "place hardware/laser_hp_8168F.py next to this script to enable the laser tab.")
            lay.addWidget(QLabel("\n".join(msg) + "\nthen restart the GUI."))
            return

        # ── Worker thread ─────────────────────────────────────────────────────
        self._worker = HP8168FWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        # Connect panel signals → worker slots
        self._sig_connect.connect(self._worker.do_connect)
        self._sig_set_wl.connect(self._worker.do_set_wavelength)
        self._sig_set_power.connect(self._worker.do_set_power)
        self._sig_set_output.connect(self._worker.do_set_output)
        self._sig_sweep.connect(self._worker.do_sweep)
        self._sig_power_sweep.connect(self._worker.do_power_sweep)
        self._sig_stop_sweep.connect(self._worker.do_stop_sweep)
        self._sig_disconnect.connect(self._worker.do_disconnect)

        # Connect worker signals → GUI slots
        self._worker.status_changed.connect(self._on_status)
        self._worker.wavelength_update.connect(self._on_wavelength)
        self._worker.power_update.connect(self._on_power)
        self._worker.output_update.connect(self._on_output)
        self._worker.range_update.connect(self._on_range)
        self._worker.sweep_progress.connect(self._on_sweep_progress)
        self._worker.power_sweep_progress.connect(self._on_power_sweep_progress)
        self._worker.log_message.connect(self._on_log)
        self._worker.error.connect(self._on_error)
        self._worker.op_done.connect(self._on_op_done)

        self._last_wavelength_nm = None
        self._last_power_mw     = None
        self._coredaq_panel     = None
        self._sweep_logging     = False
        self._sweep_power_log   = []
        self._power_sweep_logging = False
        self._power_sweep_log     = []
        self._last_sweep_csv       = None
        self._last_power_sweep_csv = None

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        final = QVBoxLayout(self)
        final.setContentsMargins(10, 10, 10, 10)

        root = QHBoxLayout()
        root.setSpacing(12)
        final.addLayout(root)

        # ── Left: Connection ──────────────────────────────────────────────────
        conn_box = QGroupBox("Connection")
        conn_lay = QGridLayout(conn_box)

        conn_lay.addWidget(QLabel("Laser Status:"), 0, 0)
        self._status_lbl = QLabel("DISCONNECTED")
        self._status_lbl.setStyleSheet(f"color: {C_RED}; font-weight: bold;")
        conn_lay.addWidget(self._status_lbl, 0, 1)

        conn_lay.addWidget(QLabel("GPIB Address:"), 1, 0)
        self._gpib_spin = NoScrollSpinBox()
        self._gpib_spin.setRange(0, 30)
        self._gpib_spin.setValue(load_connection_settings().get("hp8168f_gpib_addr", 9))
        conn_lay.addWidget(self._gpib_spin, 1, 1)

        conn_lay.addWidget(QLabel("Prologix COM Port:"), 2, 0)
        self._prologix_port_spin = NoScrollSpinBox()
        self._prologix_port_spin.setRange(1, 99)
        self._prologix_port_spin.setValue(load_connection_settings().get("prologix_com_port", 4))
        self._prologix_port_spin.setToolTip(
            "COM port of the Prologix GPIB-USB adapter itself (shared by every "
            "GPIB instrument on the bus) — not the instrument's own GPIB address.")
        conn_lay.addWidget(self._prologix_port_spin, 2, 1)

        self._connect_btn = QPushButton("Connect to Laser")
        self._connect_btn.clicked.connect(self._do_connect)
        conn_lay.addWidget(self._connect_btn, 3, 0, 1, 2)

        self._disconnect_btn = QPushButton("DISCONNECT")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(lambda: self._sig_disconnect.emit())
        conn_lay.addWidget(self._disconnect_btn, 4, 0, 1, 2)

        conn_lay.addWidget(QLabel("Output:"), 5, 0)
        self._output_lbl = QLabel("---")
        self._output_lbl.setStyleSheet(f"color: {C_GRAY}; font-weight: bold;")
        conn_lay.addWidget(self._output_lbl, 5, 1)

        out_row = QHBoxLayout()
        self._on_btn  = QPushButton("Output ON")
        self._off_btn = QPushButton("Output OFF")
        self._on_btn.setEnabled(False)
        self._off_btn.setEnabled(False)
        self._on_btn.clicked.connect(lambda: self._sig_set_output.emit(True))
        self._off_btn.clicked.connect(lambda: self._sig_set_output.emit(False))
        out_row.addWidget(self._on_btn)
        out_row.addWidget(self._off_btn)
        conn_lay.addLayout(out_row, 6, 0, 1, 2)

        conn_lay.setRowStretch(7, 1)
        root.addWidget(conn_box)

        # ── Middle: Manual control ───────────────────────────────────────────
        man_box = QGroupBox("Manual Control")
        man_lay = QGridLayout(man_box)

        man_lay.addWidget(QLabel("Current Wavelength (nm):"), 0, 0)
        self._wl_lbl = QLabel("---")
        self._wl_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
        man_lay.addWidget(self._wl_lbl, 0, 1)

        man_lay.addWidget(QLabel("Current Power (mW):"), 1, 0)
        self._pow_lbl = QLabel("---")
        self._pow_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
        man_lay.addWidget(self._pow_lbl, 1, 1)

        man_lay.addWidget(QLabel("Set Wavelength (nm):"), 2, 0)
        self._wl_spin = NoScrollDoubleSpinBox()
        self._wl_spin.setDecimals(4)
        self._wl_spin.setRange(1400.0, 1600.0)   # narrowed to instrument range after connect
        self._wl_spin.setValue(1550.0)
        persist_spinbox(self._wl_spin, "hp8168f_wavelength_nm")
        man_lay.addWidget(self._wl_spin, 2, 1)
        self._wl_btn = QPushButton("SET!")
        self._wl_btn.setEnabled(False)
        self._wl_btn.clicked.connect(lambda: self._sig_set_wl.emit(self._wl_spin.value()))
        man_lay.addWidget(self._wl_btn, 2, 2)

        man_lay.addWidget(QLabel("Set Power (mW):"), 3, 0)
        self._pow_spin = NoScrollDoubleSpinBox()
        self._pow_spin.setDecimals(3)
        self._pow_spin.setRange(0.0, 20.0)       # narrowed to instrument range after connect
        self._pow_spin.setValue(1.0)
        persist_spinbox(self._pow_spin, "hp8168f_power_mw")
        man_lay.addWidget(self._pow_spin, 3, 1)
        self._pow_btn = QPushButton("SET!")
        self._pow_btn.setEnabled(False)
        self._pow_btn.clicked.connect(lambda: self._sig_set_power.emit(self._pow_spin.value()))
        man_lay.addWidget(self._pow_btn, 3, 2)

        man_lay.setRowStretch(4, 1)
        root.addWidget(man_box)

        # ── Right: Wavelength sweep ───────────────────────────────────────────
        sweep_box = QGroupBox("Wavelength Sweep")
        sw_lay = QGridLayout(sweep_box)

        sw_lay.addWidget(QLabel("Start (nm):"), 0, 0)
        self._sw_start = NoScrollDoubleSpinBox()
        self._sw_start.setDecimals(4)
        self._sw_start.setRange(1400.0, 1600.0)
        self._sw_start.setValue(1545.0)
        persist_spinbox(self._sw_start, "hp8168f_sweep_start_nm")
        sw_lay.addWidget(self._sw_start, 0, 1)

        sw_lay.addWidget(QLabel("Stop (nm):"), 1, 0)
        self._sw_stop = NoScrollDoubleSpinBox()
        self._sw_stop.setDecimals(4)
        self._sw_stop.setRange(1400.0, 1600.0)
        self._sw_stop.setValue(1555.0)
        persist_spinbox(self._sw_stop, "hp8168f_sweep_stop_nm")
        sw_lay.addWidget(self._sw_stop, 1, 1)

        sw_lay.addWidget(QLabel("Step (nm):"), 2, 0)
        self._sw_step = NoScrollDoubleSpinBox()
        self._sw_step.setDecimals(4)
        self._sw_step.setRange(0.0001, 100.0)
        self._sw_step.setValue(0.1)
        persist_spinbox(self._sw_step, "hp8168f_sweep_step_nm")
        sw_lay.addWidget(self._sw_step, 2, 1)

        sw_lay.addWidget(QLabel("Dwell (s):"), 3, 0)
        self._sw_dwell = NoScrollDoubleSpinBox()
        self._sw_dwell.setDecimals(2)
        self._sw_dwell.setRange(0.0, 60.0)
        self._sw_dwell.setValue(0.5)
        persist_spinbox(self._sw_dwell, "hp8168f_sweep_dwell_s")
        sw_lay.addWidget(self._sw_dwell, 3, 1)

        self._sw_info_lbl = QLabel("")
        self._sw_info_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        sw_lay.addWidget(self._sw_info_lbl, 4, 0, 1, 2)

        self._sw_run_btn  = QPushButton("Run Sweep")
        self._sw_stop_btn = QPushButton("Stop")
        self._sw_run_btn.setEnabled(False)
        self._sw_stop_btn.setEnabled(False)
        self._sw_run_btn.clicked.connect(self._do_sweep)
        self._sw_stop_btn.clicked.connect(self._do_stop_sweep)
        sw_lay.addWidget(self._sw_run_btn, 5, 0, 1, 2)
        sw_lay.addWidget(self._sw_stop_btn, 6, 0, 1, 2)

        self._sw_progress_lbl = QLabel("")
        self._sw_progress_lbl.setStyleSheet(f"color: {C_GRAY};")
        sw_lay.addWidget(self._sw_progress_lbl, 7, 0, 1, 2)

        self._sweep_log_chk = QCheckBox("Log CoreDAQ power (4 ch)")
        self._sweep_log_chk.setChecked(True)
        self._sweep_log_chk.setToolTip(
            "Records the CoreDAQ optical power meter at each sweep step. "
            "On by default so sweep data is never silently missing this.")
        sw_lay.addWidget(self._sweep_log_chk, 8, 0, 1, 2)
        self._sweep_export_btn = QPushButton("Export CSV…")
        self._sweep_export_btn.setEnabled(False)
        self._sweep_export_btn.clicked.connect(self._export_sweep_power_csv)
        sw_lay.addWidget(self._sweep_export_btn, 9, 0)
        self._sweep_open_btn = QPushButton("📂 Open")
        self._sweep_open_btn.setEnabled(False)
        self._sweep_open_btn.setToolTip("Open the last-exported sweep CSV")
        self._sweep_open_btn.clicked.connect(lambda: open_saved_file(self._last_sweep_csv))
        sw_lay.addWidget(self._sweep_open_btn, 9, 1)

        sw_lay.setRowStretch(10, 1)
        root.addWidget(sweep_box, stretch=1)

        for sb in (self._sw_start, self._sw_stop, self._sw_step, self._sw_dwell):
            sb.valueChanged.connect(self._update_sweep_info)
        self._update_sweep_info()

        # ── Power Sweep (Cal 2-DC: power only, wavelength stays fixed) ───────
        pw_box = QGroupBox("Power Sweep  (wavelength stays fixed — laser must already be ON)")
        pwg = QGridLayout(pw_box)

        pwg.addWidget(QLabel("Start (mW):"), 0, 0)
        self._pw_start = NoScrollDoubleSpinBox()
        self._pw_start.setDecimals(3)
        self._pw_start.setRange(0.0, 20.0)
        self._pw_start.setValue(0.5)
        persist_spinbox(self._pw_start, "hp8168f_power_sweep_start_mw")
        pwg.addWidget(self._pw_start, 0, 1)

        pwg.addWidget(QLabel("Stop (mW):"), 0, 2)
        self._pw_stop = NoScrollDoubleSpinBox()
        self._pw_stop.setDecimals(3)
        self._pw_stop.setRange(0.0, 20.0)
        self._pw_stop.setValue(2.0)
        persist_spinbox(self._pw_stop, "hp8168f_power_sweep_stop_mw")
        pwg.addWidget(self._pw_stop, 0, 3)

        pwg.addWidget(QLabel("Step (mW):"), 1, 0)
        self._pw_step = NoScrollDoubleSpinBox()
        self._pw_step.setDecimals(3)
        self._pw_step.setRange(0.001, 10.0)
        self._pw_step.setValue(0.1)
        persist_spinbox(self._pw_step, "hp8168f_power_sweep_step_mw")
        pwg.addWidget(self._pw_step, 1, 1)

        pwg.addWidget(QLabel("Dwell (s):"), 1, 2)
        self._pw_dwell = NoScrollDoubleSpinBox()
        self._pw_dwell.setDecimals(2)
        self._pw_dwell.setRange(0.0, 60.0)
        self._pw_dwell.setValue(0.5)
        persist_spinbox(self._pw_dwell, "hp8168f_power_sweep_dwell_s")
        pwg.addWidget(self._pw_dwell, 1, 3)

        self._pw_run_btn  = QPushButton("Run Power Sweep")
        self._pw_stop_btn = QPushButton("Stop")
        self._pw_run_btn.setEnabled(False)
        self._pw_stop_btn.setEnabled(False)
        self._pw_run_btn.clicked.connect(self._do_power_sweep)
        self._pw_stop_btn.clicked.connect(self._do_stop_sweep)
        pwg.addWidget(self._pw_run_btn, 2, 0, 1, 2)
        pwg.addWidget(self._pw_stop_btn, 2, 2, 1, 2)

        self._pw_progress_lbl = QLabel("")
        self._pw_progress_lbl.setStyleSheet(f"color: {C_GRAY};")
        pwg.addWidget(self._pw_progress_lbl, 3, 0, 1, 4)

        self._power_sweep_log_chk = QCheckBox("Log CoreDAQ power (4 ch)")
        self._power_sweep_log_chk.setChecked(True)
        self._power_sweep_log_chk.setToolTip(
            "Records the CoreDAQ optical power meter at each power-sweep step. "
            "On by default so sweep data is never silently missing this.")
        pwg.addWidget(self._power_sweep_log_chk, 4, 0, 1, 3)
        self._power_sweep_export_btn = QPushButton("Export CSV…")
        self._power_sweep_export_btn.setEnabled(False)
        self._power_sweep_export_btn.clicked.connect(self._export_power_sweep_csv)
        pwg.addWidget(self._power_sweep_export_btn, 4, 3)
        self._power_sweep_open_btn = QPushButton("📂 Open")
        self._power_sweep_open_btn.setEnabled(False)
        self._power_sweep_open_btn.setToolTip("Open the last-exported power-sweep CSV")
        self._power_sweep_open_btn.clicked.connect(lambda: open_saved_file(self._last_power_sweep_csv))
        pwg.addWidget(self._power_sweep_open_btn, 4, 4)

        final.addWidget(pw_box)

        # ── Bottom: Log ───────────────────────────────────────────────────────
        log_box = QGroupBox("Log")
        log_lay = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        log_lay.addWidget(self._log)
        final.addWidget(log_box)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_status(self, s: str):
        self._status_lbl.setText(s)
        colors = {
            "DISCONNECTED": C_RED,
            "CONNECTED":    C_BLUE,
            "SWEEPING":     C_GOLD,
        }
        self._status_lbl.setStyleSheet(
            f"color: {colors.get(s, C_GRAY)}; font-weight: bold;")

        connected = s != "DISCONNECTED"
        busy      = s == "SWEEPING"
        self._sw_run_btn.setEnabled(connected and not busy)
        self._sw_stop_btn.setEnabled(busy)
        self._pw_run_btn.setEnabled(connected and not busy)
        self._pw_stop_btn.setEnabled(busy)
        self._wl_btn.setEnabled(connected and not busy)
        self._pow_btn.setEnabled(connected and not busy)
        self._on_btn.setEnabled(connected and not busy)
        self._off_btn.setEnabled(connected and not busy)

    def _on_wavelength(self, nm: float):
        self._wl_lbl.setText(f"{nm:.4f} nm")
        self._last_wavelength_nm = nm

    def _on_power(self, mw: float):
        self._pow_lbl.setText(f"{mw:.3f} mW")
        self._last_power_mw = mw

    def latest_reading(self):
        """Last (wavelength, power) reading, or None if not connected."""
        if self._status_lbl.text() == "DISCONNECTED":
            return None
        return {"wavelength_nm": self._last_wavelength_nm, "power_mw": self._last_power_mw}

    def set_coredaq_panel(self, panel):
        """Wires the CoreDAQ tab in so wavelength sweeps can log optical power."""
        self._coredaq_panel = panel

    def _on_output(self, on: bool):
        self._output_lbl.setText("ON" if on else "OFF")
        self._output_lbl.setStyleSheet(f"color: {C_RED if on else C_GRAY}; font-weight: bold;")

    def _on_range(self, min_nm: float, max_nm: float, max_mw: float):
        for spin in (self._wl_spin, self._sw_start, self._sw_stop):
            spin.setRange(min_nm, max_nm)
        self._pow_spin.setRange(0.0, max_mw)
        self._log.append(f"Wavelength range: {min_nm:.3f}–{max_nm:.3f} nm,  max power {max_mw:.3f} mW")

    def _on_log(self, msg: str):
        self._log.append(msg)

    def _on_error(self, msg: str):
        self._log.append(f"<span style='color:{C_RED};'>ERROR: {msg}</span>")

    def _on_op_done(self, op: str):
        if op == "connect":
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._gpib_spin.setEnabled(False)
            self._prologix_port_spin.setEnabled(False)
        elif op == "disconnect":
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)
            self._gpib_spin.setEnabled(True)
            self._prologix_port_spin.setEnabled(True)
        elif op == "sweep" and self._sweep_logging:
            self._sweep_logging = False
            if self._sweep_power_log:
                self._sweep_export_btn.setEnabled(True)
                self._show_sweep_power_plot()
        elif op == "power_sweep":
            self._power_sweep_logging = False
            if self._power_sweep_log:
                self._power_sweep_export_btn.setEnabled(True)
                self._show_power_sweep_plot()

    def _on_sweep_progress(self, idx: int, total: int, wl: float):
        self._sw_progress_lbl.setText(f"[{idx}/{total}]  {wl:.4f} nm")
        if self._sweep_logging and self._coredaq_panel is not None:
            powers = self._coredaq_panel.latest_power_w()
            if powers is not None:
                self._sweep_power_log.append((wl, *powers))

    def _on_power_sweep_progress(self, idx: int, total: int, mw: float):
        self._pw_progress_lbl.setText(f"[{idx}/{total}]  {mw:.3f} mW")
        if self._power_sweep_logging and self._coredaq_panel is not None:
            powers = self._coredaq_panel.latest_power_w()
            if powers is not None:
                self._power_sweep_log.append((mw, *powers))

    def _show_sweep_power_plot(self):
        series = {}
        for ch in range(4):
            xs = [row[0] for row in self._sweep_power_log]
            ys = [row[1 + ch] * 1e9 for row in self._sweep_power_log]
            series[f"MZI {ch + 1}"] = (xs, ys, "nW")
        win = MatplotlibPlotWindow("HP-8168F Sweep — CoreDAQ Power", "Wavelength", "nm")
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._sweep_plot_win = win

    def _export_sweep_power_csv(self):
        if not self._sweep_power_log:
            return
        import datetime
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"hp8168f_sweep_coredaq_{stamp}.csv")
        comments = [
            "laser: HP-8168F",
            f"sweep: {self._sw_start.value():.4f} -> {self._sw_stop.value():.4f} nm, "
            f"step {self._sw_step.value():.4f} nm, dwell {self._sw_dwell.value():.2f} s",
            f"power_setpoint_mw: {self._pow_spin.value():.3f}",
        ]
        header = ["wavelength_nm",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = [[f"{wl:.4f}"] + [f"{w:.9e}" for w in powers]
                for wl, *powers in self._sweep_power_log]
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[HP-8168F Sweep] Saved {len(rows)} rows → {fname}")
        self._log.append(f"Saved {len(rows)} sweep/power rows → {fname}")
        self._last_sweep_csv = fname
        self._sweep_open_btn.setEnabled(True)

    def _show_power_sweep_plot(self):
        series = {}
        for ch in range(4):
            xs = [row[0] for row in self._power_sweep_log]
            ys = [row[1 + ch] * 1e9 for row in self._power_sweep_log]
            series[f"MZI {ch + 1}"] = (xs, ys, "nW")
        win = MatplotlibPlotWindow("HP-8168F Power Sweep — CoreDAQ Power", "Laser power", "mW")
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._power_sweep_plot_win = win

    def _export_power_sweep_csv(self):
        if not self._power_sweep_log:
            return
        import datetime
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"hp8168f_power_sweep_coredaq_{stamp}.csv")
        comments = [
            "laser: HP-8168F",
            f"power_sweep: {self._pw_start.value():.3f} -> {self._pw_stop.value():.3f} mW, "
            f"step {self._pw_step.value():.3f} mW, dwell {self._pw_dwell.value():.2f} s",
            f"wavelength_nm: {self._wl_spin.value():.4f}",
        ]
        header = ["power_mw",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = [[f"{mw:.4f}"] + [f"{w:.9e}" for w in powers]
                for mw, *powers in self._power_sweep_log]
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[HP-8168F Power Sweep] Saved {len(rows)} rows → {fname}")
        self._log.append(f"Saved {len(rows)} power-sweep rows → {fname}")
        self._last_power_sweep_csv = fname
        self._power_sweep_open_btn.setEnabled(True)

    # ── Button actions ────────────────────────────────────────────────────────

    def _update_sweep_info(self):
        start = self._sw_start.value()
        stop  = self._sw_stop.value()
        step  = self._sw_step.value()
        dwell = self._sw_dwell.value()
        if step <= 0:
            self._sw_info_lbl.setText("")
            return
        npts = int(abs(stop - start) / step) + 1
        self._sw_info_lbl.setText(
            f"{npts} points · ~{npts * dwell:.1f} s total")

    def _do_connect(self):
        save_connection_setting("hp8168f_gpib_addr", self._gpib_spin.value())
        save_connection_setting("prologix_com_port", self._prologix_port_spin.value())
        self._sig_connect.emit(self._gpib_spin.value(), self._prologix_port_spin.value())

    def _do_sweep(self):
        start = self._sw_start.value()
        stop  = self._sw_stop.value()
        step  = self._sw_step.value()
        dwell = self._sw_dwell.value()
        if abs(start - stop) < 1e-9:
            QMessageBox.warning(self, "Sweep", "Start and stop must differ.")
            return
        self._sw_progress_lbl.setText("")
        self._sweep_power_log = []
        self._sweep_export_btn.setEnabled(False)
        self._sweep_logging = self._sweep_log_chk.isChecked()
        self._sig_sweep.emit(start, stop, step, dwell)

    def _do_power_sweep(self):
        start = self._pw_start.value()
        stop  = self._pw_stop.value()
        step  = self._pw_step.value()
        dwell = self._pw_dwell.value()
        if abs(start - stop) < 1e-9:
            QMessageBox.warning(self, "Power Sweep", "Start and stop must differ.")
            return
        self._pw_progress_lbl.setText("")
        self._power_sweep_log = []
        self._power_sweep_export_btn.setEnabled(False)
        self._power_sweep_logging = self._power_sweep_log_chk.isChecked()
        self._sig_power_sweep.emit(start, stop, step, dwell)

    def _do_stop_sweep(self):
        # Set the worker's threading.Event directly from this (GUI) thread — a
        # queued _sig_stop_sweep signal would just sit behind the sweep loop's
        # own blocking call on the worker thread and never get delivered in time.
        self._worker._stop_event.set()
        self._sig_stop_sweep.emit()

    def cleanup(self):
        if HAS_PYVISA and HAS_HP8168F:
            self._sig_disconnect.emit()
            self._thread.quit()
            self._thread.wait(2000)


# ══════════════════════════════════════════════════════════════════════════════
# SANTEC TSL-550 TUNABLE LASER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class FastSweepWorker(QObject):
    """
    Runs one full hardware-triggered wavelength sweep on its own thread — holds
    direct references to the raw TSL550 laser and CoreDAQ objects for the
    duration of the sweep. Mirrors the lab's threads/laser_sweep_worker.py: one
    thread, one blocking method owning both hardware objects, so no cross-thread
    handshake is needed mid-sweep (unlike SantecWorker/CoreDAQWorker, which each
    own their device privately behind a queued-signal API for everyday use).

    Trigger scheme: the laser fires a single rising-edge trigger pulse at the
    start of its native continuous sweep (TRIG:OUTP 2 / TRIG:OUTP:ACT 1).
    CoreDAQ is armed on that one edge and free-runs its own ADC clock at
    SWEEP_RATE_HZ for a precomputed sample count — the wavelength axis is
    reconstructed from elapsed time and the sweep's constant speed, not from
    per-point synchronization.
    """
    progress = pyqtSignal(str)
    error    = pyqtSignal(str)
    result   = pyqtSignal(object)   # dict: {"wavelengths": [...], "power_ch": [[4 lists]]}
    finished = pyqtSignal()

    SWEEP_RATE_HZ = 50_000

    def __init__(self):
        super().__init__()
        self._laser  = None
        self._daq    = None
        self._params = {}

    def set_hardware(self, laser, daq):
        self._laser = laser
        self._daq   = daq

    def set_sweep_params(self, params: dict):
        self._params = params

    def _configure_laser(self, start_nm, stop_nm, speed_nm_s, power_mw):
        laser = self._laser
        laser.write('WAV:UNIT 0')       # nm
        laser.write('POW:UNIT 1')       # mW
        laser.write('TRIG:INP 0')       # no external trigger IN to laser
        laser.write('TRIG:OUTP 2')      # output mode 2 = start trigger pulse
        laser.write('TRIG:OUTP:ACT 1')  # active-high: rising edge = sweep start

        laser.wavelength = start_nm
        time.sleep(0.5)
        laser.power = power_mw
        laser.on()
        laser.shutter = False
        time.sleep(0.3)

        laser.write(f'WAV:SWE:STAR {start_nm}')
        laser.write(f'WAV:SWE:STOP {stop_nm}')
        laser.write(f'WAV:SWE:SPE {speed_nm_s}')
        laser.write('WAV:SWE:MOD 1')    # one-way continuous
        laser.write('WAV:SWE:CYCL 1')   # single cycle
        time.sleep(0.3)

    def _build_wavelength_axis(self, start_nm, stop_nm, speed_nm_s, n_samples):
        span = abs(stop_nm - start_nm)
        dur  = span / speed_nm_s
        t    = np.arange(n_samples, dtype=float) / float(self.SWEEP_RATE_HZ)
        wl   = start_nm + (stop_nm - start_nm) * (t / dur)
        return np.clip(wl, min(start_nm, stop_nm), max(start_nm, stop_nm))

    def run_sweep(self):
        start_nm   = self._params.get('start_nm', 1500.0)
        stop_nm    = self._params.get('stop_nm',  1560.0)
        speed_nm_s = self._params.get('speed',    50.0)
        power_mw   = self._params.get('power',    1.0)

        if speed_nm_s <= 0:
            self.error.emit("Sweep speed must be > 0 nm/s")
            self.finished.emit()
            return
        if self._laser is None or self._daq is None:
            self.error.emit("Laser or CoreDAQ not connected")
            self.finished.emit()
            return

        self.progress.emit(
            f"Fast sweep: {start_nm:.3f} → {stop_nm:.3f} nm @ {speed_nm_s:.1f} nm/s, "
            f"P={power_mw:.3f} mW")

        try:
            span  = abs(stop_nm - start_nm)
            dur_s = span / speed_nm_s
            n     = int(round(dur_s * self.SWEEP_RATE_HZ))
            if n <= 0:
                raise ValueError("Zero samples — check sweep parameters")

            self.progress.emit(f"CoreDAQ: setting {self.SWEEP_RATE_HZ // 1000} kHz sample rate")
            self._daq.set_oversampling(0)
            self._daq.set_freq(self.SWEEP_RATE_HZ)

            self._configure_laser(start_nm, stop_nm, speed_nm_s, power_mw)

            self.progress.emit(f"CoreDAQ: arming {n} samples on rising trigger edge")
            self._daq.arm_acquisition(n, use_trigger=True, trigger_rising=True)

            self.progress.emit("Starting sweep (trigger fires DAQ)...")
            t0 = time.time()
            self._laser.write('WAV:SWE 1')

            timeout_s = dur_s + 30.0
            while True:
                if self._daq.state_enum() == 4:   # READY — data available
                    break
                if (time.time() - t0) > timeout_s:
                    raise TimeoutError(f"CoreDAQ timeout after {time.time() - t0:.1f}s")
                try:
                    wl = self._laser.query('WAV?').strip()
                    self.progress.emit(f"  λ={wl} nm  ({time.time() - t0:.1f}s)")
                except Exception:
                    pass
                time.sleep(0.5)

            self.progress.emit(f"Data ready in {time.time() - t0:.1f}s — transferring...")
            time.sleep(0.2)
            power_ch = self._daq.transfer_frames_W(n)   # list of 4 lists, already watts

            wl_axis = self._build_wavelength_axis(start_nm, stop_nm, speed_nm_s, n)

            self._laser.shutter = True
            self.progress.emit(f"Fast sweep complete: {len(wl_axis)} points")
            self.result.emit({"wavelengths": wl_axis.tolist(), "power_ch": power_ch})
            self.finished.emit()

        except Exception as e:
            try:
                self._laser.shutter = True
            except Exception:
                pass
            self.error.emit(str(e))
            self.finished.emit()


class SantecWorker(QObject):
    """
    Runs blocking PyVISA/GPIB calls off the GUI thread.
    All laser I/O goes through here — emit signals back to SantecPanel.
    """
    status_changed    = pyqtSignal(str)          # DISCONNECTED / CONNECTED / SWEEPING
    wavelength_update = pyqtSignal(float)
    power_update      = pyqtSignal(float)
    output_update     = pyqtSignal(bool)
    range_update      = pyqtSignal(float, float, float)   # min_nm, max_nm, max_mw
    power_sweep_progress = pyqtSignal(int, int, float)     # idx, total, power_mw
    log_message       = pyqtSignal(str)
    error              = pyqtSignal(str)
    op_done            = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._laser = None
        # threading.Event, not a plain bool: Stop must take effect while do_power_sweep()
        # is blocking the worker thread's event loop, so it can't wait for a queued
        # cross-thread signal to be delivered — the GUI thread sets this directly.
        self._stop_event = threading.Event()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sleep_interruptible(self, total_s: float):
        remaining = total_s
        while remaining > 0 and not self._stop_event.is_set():
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk

    # ── Public slots (called via signal connections on worker thread) ───────

    def do_connect(self, gpib_addr: int, prologix_port: int):
        try:
            if self._laser is not None:
                # Reconnecting — release the old handle first so it can't
                # leak the port open and make this attempt fail as "busy".
                try:
                    self._laser.close()
                except Exception:
                    pass
                self._laser = None
            device_name = f"Prologix::{gpib_addr}::ASRL{prologix_port}::INSTR"
            self._laser = TSL550(device_name=device_name, force_connect=True)
            self.status_changed.emit("CONNECTED")
            self.range_update.emit(self._laser._min_wavelength,
                                    self._laser._max_wavelength,
                                    self._laser._max_power)
            self.wavelength_update.emit(self._laser.wavelength)
            self.power_update.emit(self._laser.power)
            self.output_update.emit(not self._laser.shutter)
            self.log_message.emit(f"Connected to Santec TSL-550 ({device_name})")
            self.op_done.emit("connect")
        except Exception as e:
            self.error.emit(f"Connect failed: {e}")

    def do_refresh_status(self):
        """Re-queries the laser's actual current wavelength/power/output so the
        GUI keeps reflecting reality rather than just whatever was last
        commanded from this panel — e.g. if the laser drifted, or someone
        adjusted it from the front panel. Called on a periodic timer while
        idle (not mid-sweep, where the sweep loop itself is already the
        source of truth for wavelength progress)."""
        if self._laser is None:
            return
        try:
            self.wavelength_update.emit(self._laser.wavelength)
            self.power_update.emit(self._laser.power)
            self.output_update.emit(not self._laser.shutter)
        except Exception:
            pass

    def do_set_wavelength(self, nm: float):
        try:
            self._laser.wavelength = nm
            self.wavelength_update.emit(nm)
            self.log_message.emit(f"Wavelength set to {nm:.4f} nm")
            self.op_done.emit("set_wavelength")
        except Exception as e:
            self.error.emit(f"Set wavelength error: {e}")

    def do_set_power(self, mw: float):
        try:
            self._laser.power = mw
            self.power_update.emit(mw)
            self.log_message.emit(f"Power set to {mw:.3f} mW")
            self.op_done.emit("set_power")
        except Exception as e:
            self.error.emit(f"Set power error: {e}")

    def do_set_output(self, on: bool, nm: float = 0.0, mw: float = 0.0):
        # Leaves the laser diode itself running either way — only the shutter
        # is toggled, so this never forces a warm-up/re-lock cycle. Turning
        # the diode fully on/off only ever happens once, right after connect.
        try:
            if on:
                # Apply the currently-dialed-in wavelength/power BEFORE
                # opening the shutter, so "Output ON" always starts the
                # laser emitting at the settings shown on screen instead of
                # whatever it was last left at.
                self._laser.wavelength = nm
                self.wavelength_update.emit(nm)
                self._laser.power = mw
                self.power_update.emit(mw)
                self._laser.on()
                self._laser.shutter = False
                self.log_message.emit(f"Wavelength set to {nm:.4f} nm, power set to {mw:.3f} mW")
            else:
                self._laser.shutter = True
            self.output_update.emit(on)
            self.log_message.emit(f"Output {'ON' if on else 'OFF'}")
            self.op_done.emit("set_output")
        except Exception as e:
            self.error.emit(f"Set output error: {e}")

    def do_power_sweep(self, mw_start: float, mw_stop: float, mw_step: float, dwell_s: float):
        """
        Steps output power from mw_start to mw_stop in mw_step increments,
        wavelength held fixed, dwelling dwell_s at each point (Cal 2-DC).
        """
        try:
            if mw_step <= 0:
                self.error.emit("Step size must be positive")
                return

            self._stop_event.clear()
            step = abs(mw_step) if mw_stop >= mw_start else -abs(mw_step)

            targets = []
            v = mw_start
            if step >= 0:
                while v <= mw_stop + 1e-9:
                    targets.append(round(v, 4))
                    v += step
            else:
                while v >= mw_stop - 1e-9:
                    targets.append(round(v, 4))
                    v += step
            if not targets:
                targets = [mw_start]

            total = len(targets)
            self.status_changed.emit("SWEEPING")
            self.log_message.emit(
                f"Power sweep: {total} points, {mw_start:.2f} → {mw_stop:.2f} mW, "
                f"{mw_step:.2f} mW step, {dwell_s:.2f} s dwell")

            for idx, mw in enumerate(targets):
                if self._stop_event.is_set():
                    self.log_message.emit("Power sweep stopped by user")
                    break
                self._laser.power = mw
                self.power_update.emit(mw)
                self.power_sweep_progress.emit(idx + 1, total, mw)
                self._sleep_interruptible(dwell_s)

            self.status_changed.emit("CONNECTED")
            self.log_message.emit("Power sweep complete")
            self.op_done.emit("power_sweep")
        except Exception as e:
            self.error.emit(f"Power sweep error: {e}")
            self.status_changed.emit("CONNECTED")

    def do_stop_sweep(self):
        self._stop_event.set()

    def do_disconnect(self):
        try:
            if self._laser is not None:
                # Close the shutter (output OFF) BEFORE dropping the connection.
                # Disconnecting — including on GUI close — must never leave the
                # laser emitting with no software in control. Guarded on its own
                # so a comms hiccup here can't block the actual close().
                try:
                    self._laser.shutter = True
                    self.output_update.emit(False)
                    self.log_message.emit("Laser output OFF (auto, before disconnect)")
                except Exception as e:
                    self.log_message.emit(
                        f"Warning: could not close shutter before disconnect: {e}")
                self._laser.close()
                self._laser = None
            self.status_changed.emit("DISCONNECTED")
            self.log_message.emit("Disconnected from Santec TSL-550")
            self.op_done.emit("disconnect")
        except Exception as e:
            self.error.emit(f"Disconnect error: {e}")


class SantecPanel(QWidget):
    """
    Santec TSL-550 tunable laser source — GPIB control via pyvisa.
    All blocking PyVISA calls run in SantecWorker on a background QThread.
    """

    # Signals to invoke worker slots across threads
    _sig_connect     = pyqtSignal(int, int)   # gpib_addr, prologix_com_port
    _sig_set_wl      = pyqtSignal(float)
    _sig_set_power   = pyqtSignal(float)
    _sig_set_output  = pyqtSignal(bool, float, float)   # on, wavelength_nm, power_mw
    _sig_power_sweep = pyqtSignal(float, float, float, float)
    _sig_stop_sweep  = pyqtSignal()
    _sig_disconnect  = pyqtSignal()
    _sig_run_fast_sweep  = pyqtSignal()
    _sig_refresh_status  = pyqtSignal()

    STATUS_POLL_MS = 1000   # periodic re-read of actual laser wavelength/power/output

    def __init__(self, parent=None):
        super().__init__(parent)

        if not HAS_PYVISA or not HAS_SANTEC:
            lay = QVBoxLayout(self)
            msg = []
            if not HAS_PYVISA:
                msg.append("pyvisa is not installed. Run: uv pip install pyvisa pyvisa-py")
            if not HAS_SANTEC:
                msg.append("hardware.laser_tsl_550 not found, or its 'nidaqmx' dependency is "
                            "missing —\nrun: uv pip install nidaqmx")
            lay.addWidget(QLabel("\n".join(msg) + "\nthen restart the GUI."))
            return

        # ── Worker thread ─────────────────────────────────────────────────────
        self._worker = SantecWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        # Connect panel signals → worker slots
        self._sig_connect.connect(self._worker.do_connect)
        self._sig_set_wl.connect(self._worker.do_set_wavelength)
        self._sig_set_power.connect(self._worker.do_set_power)
        self._sig_set_output.connect(self._worker.do_set_output)
        self._sig_power_sweep.connect(self._worker.do_power_sweep)
        self._sig_stop_sweep.connect(self._worker.do_stop_sweep)
        self._sig_disconnect.connect(self._worker.do_disconnect)
        self._sig_refresh_status.connect(self._worker.do_refresh_status)

        # Connect worker signals → GUI slots
        self._worker.status_changed.connect(self._on_status)
        self._worker.wavelength_update.connect(self._on_wavelength)
        self._worker.power_update.connect(self._on_power)
        self._worker.output_update.connect(self._on_output)
        self._worker.range_update.connect(self._on_range)
        self._worker.power_sweep_progress.connect(self._on_power_sweep_progress)
        self._worker.log_message.connect(self._on_log)
        self._worker.error.connect(self._on_error)
        self._worker.op_done.connect(self._on_op_done)

        # Periodic re-read of actual laser state — keeps the "Current
        # Wavelength/Power" labels honest even between explicit set/sweep
        # actions (e.g. front-panel adjustments, or just to reflect reality
        # rather than a stale value from whenever it was last written).
        self._status_poll_timer = QTimer()
        self._status_poll_timer.setInterval(self.STATUS_POLL_MS)
        self._status_poll_timer.timeout.connect(self._poll_status)
        self._status_poll_timer.start()

        # ── Fast Sweep worker thread — direct laser+DAQ refs, single blocking
        # method arms the DAQ, fires the laser's one-shot start trigger, and
        # transfers the result. Mirrors the lab's laser_sweep_worker.py pattern:
        # one thread owns both hardware objects for the duration of the sweep,
        # no cross-thread handshake needed mid-sweep. ────────────────────────
        self._fast_sweep_worker = FastSweepWorker()
        self._fast_sweep_thread = QThread()
        self._fast_sweep_worker.moveToThread(self._fast_sweep_thread)
        self._fast_sweep_thread.start()
        self._sig_run_fast_sweep.connect(self._fast_sweep_worker.run_sweep)
        self._fast_sweep_worker.progress.connect(self._on_fast_sweep_progress)
        self._fast_sweep_worker.error.connect(self._on_fast_sweep_error)
        self._fast_sweep_worker.result.connect(self._on_fast_sweep_result)
        self._fast_sweep_worker.finished.connect(self._on_fast_sweep_finished)

        self._last_wavelength_nm = None
        self._last_power_mw     = None
        self._coredaq_panel     = None
        self._power_sweep_logging = False
        self._power_sweep_log     = []
        self._fast_sweep_running  = False
        self._fast_sweep_result   = None   # (wavelengths[], [ch1_W..ch4_W])
        self._fast_sweep_plot_win = None
        self._last_power_sweep_csv = None
        self._last_fast_sweep_csv  = None

        self._build_ui()

        # auto-connect on launch using the saved GPIB/COM settings
        self._do_connect()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        final = QVBoxLayout(self)
        final.setContentsMargins(10, 10, 10, 10)

        root = QHBoxLayout()
        root.setSpacing(12)
        final.addLayout(root)

        # ── Left: Connection ──────────────────────────────────────────────────
        conn_box = QGroupBox("Connection")
        conn_lay = QGridLayout(conn_box)

        conn_lay.addWidget(QLabel("Laser Status:"), 0, 0)
        self._status_lbl = QLabel("DISCONNECTED")
        self._status_lbl.setStyleSheet(f"color: {C_RED}; font-weight: bold;")
        conn_lay.addWidget(self._status_lbl, 0, 1)

        conn_lay.addWidget(QLabel("GPIB Address:"), 1, 0)
        self._gpib_spin = NoScrollSpinBox()
        self._gpib_spin.setRange(0, 30)
        self._gpib_spin.setValue(load_connection_settings().get("santec_gpib_addr", 1))
        conn_lay.addWidget(self._gpib_spin, 1, 1)

        conn_lay.addWidget(QLabel("Prologix COM Port:"), 2, 0)
        self._prologix_port_spin = NoScrollSpinBox()
        self._prologix_port_spin.setRange(1, 99)
        self._prologix_port_spin.setValue(load_connection_settings().get("prologix_com_port", 4))
        self._prologix_port_spin.setToolTip(
            "COM port of the Prologix GPIB-USB adapter itself (shared by every "
            "GPIB instrument on the bus) — not the instrument's own GPIB address.")
        conn_lay.addWidget(self._prologix_port_spin, 2, 1)

        self._connect_btn = QPushButton("Connect to Laser")
        self._connect_btn.clicked.connect(self._do_connect)
        conn_lay.addWidget(self._connect_btn, 3, 0, 1, 2)

        self._disconnect_btn = QPushButton("DISCONNECT")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(lambda: self._sig_disconnect.emit())
        conn_lay.addWidget(self._disconnect_btn, 4, 0, 1, 2)

        conn_lay.addWidget(QLabel("Output:"), 5, 0)
        self._output_lbl = QLabel("---")
        self._output_lbl.setStyleSheet(f"color: {C_GRAY}; font-weight: bold;")
        conn_lay.addWidget(self._output_lbl, 5, 1)

        out_row = QHBoxLayout()
        self._on_btn  = QPushButton("Output ON")
        self._off_btn = QPushButton("Output OFF")
        self._on_btn.setEnabled(False)
        self._off_btn.setEnabled(False)
        self._on_btn.clicked.connect(self._do_output_on)
        self._off_btn.clicked.connect(lambda: self._sig_set_output.emit(False, 0.0, 0.0))
        out_row.addWidget(self._on_btn)
        out_row.addWidget(self._off_btn)
        conn_lay.addLayout(out_row, 6, 0, 1, 2)

        conn_lay.setRowStretch(7, 1)
        root.addWidget(conn_box)

        # ── Middle: Manual control ───────────────────────────────────────────
        man_box = QGroupBox("Manual Control")
        man_lay = QGridLayout(man_box)

        man_lay.addWidget(QLabel("Current Wavelength (nm):"), 0, 0)
        self._wl_lbl = QLabel("---")
        self._wl_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
        man_lay.addWidget(self._wl_lbl, 0, 1)

        man_lay.addWidget(QLabel("Current Power (mW):"), 1, 0)
        self._pow_lbl = QLabel("---")
        self._pow_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
        man_lay.addWidget(self._pow_lbl, 1, 1)

        man_lay.addWidget(QLabel("Set Wavelength (nm):"), 2, 0)
        self._wl_spin = NoScrollDoubleSpinBox()
        self._wl_spin.setDecimals(4)
        self._wl_spin.setRange(1400.0, 1700.0)   # narrowed to instrument range after connect
        self._wl_spin.setValue(1550.0)
        # Same key _do_set_wl/_do_output_on already save on click — persist_spinbox
        # additionally saves on every change, so the value survives a session even
        # if SET!/Output ON was never clicked.
        persist_spinbox(self._wl_spin, "santec_last_wavelength_nm")
        man_lay.addWidget(self._wl_spin, 2, 1)
        self._wl_btn = QPushButton("SET!")
        self._wl_btn.setEnabled(False)
        self._wl_btn.clicked.connect(self._do_set_wl)
        man_lay.addWidget(self._wl_btn, 2, 2)

        man_lay.addWidget(QLabel("Set Power (mW):"), 3, 0)
        self._pow_spin = NoScrollDoubleSpinBox()
        self._pow_spin.setDecimals(3)
        self._pow_spin.setRange(0.0, 20.0)       # narrowed to instrument range after connect
        self._pow_spin.setValue(1.0)
        persist_spinbox(self._pow_spin, "santec_last_power_mw")
        man_lay.addWidget(self._pow_spin, 3, 1)
        self._pow_btn = QPushButton("SET!")
        self._pow_btn.setEnabled(False)
        self._pow_btn.clicked.connect(self._do_set_power)
        man_lay.addWidget(self._pow_btn, 3, 2)

        man_lay.setRowStretch(4, 1)
        root.addWidget(man_box)

        # ── Power Sweep (Cal 2-DC: power only, wavelength stays fixed) ───────
        pw_box = QGroupBox("Power Sweep  (wavelength stays fixed — laser must already be ON)")
        pwg = QGridLayout(pw_box)

        pwg.addWidget(QLabel("Start (mW):"), 0, 0)
        self._pw_start = NoScrollDoubleSpinBox()
        self._pw_start.setDecimals(3)
        self._pw_start.setRange(0.0, 20.0)
        self._pw_start.setValue(0.5)
        persist_spinbox(self._pw_start, "santec_power_sweep_start_mw")
        pwg.addWidget(self._pw_start, 0, 1)

        pwg.addWidget(QLabel("Stop (mW):"), 0, 2)
        self._pw_stop = NoScrollDoubleSpinBox()
        self._pw_stop.setDecimals(3)
        self._pw_stop.setRange(0.0, 20.0)
        self._pw_stop.setValue(2.0)
        persist_spinbox(self._pw_stop, "santec_power_sweep_stop_mw")
        pwg.addWidget(self._pw_stop, 0, 3)

        pwg.addWidget(QLabel("Step (mW):"), 1, 0)
        self._pw_step = NoScrollDoubleSpinBox()
        self._pw_step.setDecimals(3)
        self._pw_step.setRange(0.001, 10.0)
        self._pw_step.setValue(0.1)
        persist_spinbox(self._pw_step, "santec_power_sweep_step_mw")
        pwg.addWidget(self._pw_step, 1, 1)

        pwg.addWidget(QLabel("Dwell (s):"), 1, 2)
        self._pw_dwell = NoScrollDoubleSpinBox()
        self._pw_dwell.setDecimals(2)
        self._pw_dwell.setRange(0.0, 60.0)
        self._pw_dwell.setValue(0.5)
        persist_spinbox(self._pw_dwell, "santec_power_sweep_dwell_s")
        pwg.addWidget(self._pw_dwell, 1, 3)

        self._pw_run_btn  = QPushButton("Run Power Sweep")
        self._pw_stop_btn = QPushButton("Stop")
        self._pw_run_btn.setEnabled(False)
        self._pw_stop_btn.setEnabled(False)
        self._pw_run_btn.clicked.connect(self._do_power_sweep)
        self._pw_stop_btn.clicked.connect(self._do_stop_sweep)
        pwg.addWidget(self._pw_run_btn, 2, 0, 1, 2)
        pwg.addWidget(self._pw_stop_btn, 2, 2, 1, 2)

        self._pw_progress_lbl = QLabel("")
        self._pw_progress_lbl.setStyleSheet(f"color: {C_GRAY};")
        pwg.addWidget(self._pw_progress_lbl, 3, 0, 1, 4)

        self._power_sweep_log_chk = QCheckBox("Log CoreDAQ power (4 ch)")
        self._power_sweep_log_chk.setChecked(True)
        self._power_sweep_log_chk.setToolTip(
            "Records the CoreDAQ optical power meter at each power-sweep step. "
            "On by default so sweep data is never silently missing this.")
        pwg.addWidget(self._power_sweep_log_chk, 4, 0, 1, 3)
        self._power_sweep_export_btn = QPushButton("Export CSV…")
        self._power_sweep_export_btn.setEnabled(False)
        self._power_sweep_export_btn.clicked.connect(self._export_power_sweep_csv)
        pwg.addWidget(self._power_sweep_export_btn, 4, 3)
        self._power_sweep_open_btn = QPushButton("📂 Open")
        self._power_sweep_open_btn.setEnabled(False)
        self._power_sweep_open_btn.setToolTip("Open the last-exported power-sweep CSV")
        self._power_sweep_open_btn.clicked.connect(lambda: open_saved_file(self._last_power_sweep_csv))
        pwg.addWidget(self._power_sweep_open_btn, 4, 4)

        final.addWidget(pw_box)

        # ── Fast Sweep (hardware-triggered, laser drives CoreDAQ directly) ────
        fs_box = QGroupBox("Fast Sweep (HW Triggered) \u2014 laser start-trigger \u2192 CoreDAQ free-run capture")
        fsg = QGridLayout(fs_box)

        fsg.addWidget(QLabel("Start (nm):"), 0, 0)
        self._fs_start = NoScrollDoubleSpinBox()
        self._fs_start.setDecimals(4)
        self._fs_start.setRange(1400.0, 1700.0)
        self._fs_start.setValue(1545.0)
        persist_spinbox(self._fs_start, "santec_fast_sweep_start_nm")
        fsg.addWidget(self._fs_start, 0, 1)

        fsg.addWidget(QLabel("Stop (nm):"), 0, 2)
        self._fs_stop = NoScrollDoubleSpinBox()
        self._fs_stop.setDecimals(4)
        self._fs_stop.setRange(1400.0, 1700.0)
        self._fs_stop.setValue(1555.0)
        persist_spinbox(self._fs_stop, "santec_fast_sweep_stop_nm")
        fsg.addWidget(self._fs_stop, 0, 3)

        fsg.addWidget(QLabel("Speed (nm/s):"), 1, 0)
        self._fs_speed = NoScrollDoubleSpinBox()
        self._fs_speed.setDecimals(2)
        self._fs_speed.setRange(1.0, 100.0)
        self._fs_speed.setValue(50.0)
        persist_spinbox(self._fs_speed, "santec_fast_sweep_speed_nm_s")
        fsg.addWidget(self._fs_speed, 1, 1)

        fsg.addWidget(QLabel("Power (mW):"), 1, 2)
        self._fs_power = NoScrollDoubleSpinBox()
        self._fs_power.setDecimals(3)
        self._fs_power.setRange(0.0, 20.0)
        self._fs_power.setValue(1.0)
        persist_spinbox(self._fs_power, "santec_fast_sweep_power_mw")
        fsg.addWidget(self._fs_power, 1, 3)

        self._fs_info_lbl = QLabel("")
        self._fs_info_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
        fsg.addWidget(self._fs_info_lbl, 2, 0, 1, 4)

        self._fs_run_btn = QPushButton("Run Fast Sweep")
        self._fs_run_btn.setEnabled(False)
        self._fs_run_btn.clicked.connect(self._do_fast_sweep)
        fsg.addWidget(self._fs_run_btn, 3, 0, 1, 4)

        self._fs_progress_lbl = QLabel("")
        self._fs_progress_lbl.setStyleSheet(f"color: {C_GRAY};")
        fsg.addWidget(self._fs_progress_lbl, 4, 0, 1, 4)

        self._fs_export_btn = QPushButton("Export CSV\u2026")
        self._fs_export_btn.setEnabled(False)
        self._fs_export_btn.clicked.connect(self._export_fast_sweep_csv)
        fsg.addWidget(self._fs_export_btn, 5, 0, 1, 3)
        self._fs_open_btn = QPushButton("📂 Open")
        self._fs_open_btn.setEnabled(False)
        self._fs_open_btn.setToolTip("Open the last-exported fast-sweep CSV")
        self._fs_open_btn.clicked.connect(lambda: open_saved_file(self._last_fast_sweep_csv))
        fsg.addWidget(self._fs_open_btn, 5, 3)

        for sb in (self._fs_start, self._fs_stop, self._fs_speed):
            sb.valueChanged.connect(self._update_fast_sweep_info)
        self._update_fast_sweep_info()

        root.addWidget(fs_box, stretch=1)

        # ── Bottom: Log ───────────────────────────────────────────────────────
        log_box = QGroupBox("Log")
        log_lay = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        log_lay.addWidget(self._log)
        final.addWidget(log_box)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _poll_status(self):
        """Fired every STATUS_POLL_MS — only queries the laser while idle and
        connected. Mid-sweep the worker thread is already busy running the
        blocking sweep loop (which emits its own wavelength updates), so a
        queued refresh here would just pile up behind it for no benefit."""
        if self._status_lbl.text() == "CONNECTED" and not self._fast_sweep_running:
            self._sig_refresh_status.emit()

    def _on_status(self, s: str):
        self._status_lbl.setText(s)
        colors = {
            "DISCONNECTED": C_RED,
            "CONNECTED":    C_BLUE,
            "SWEEPING":     C_GOLD,
        }
        self._status_lbl.setStyleSheet(
            f"color: {colors.get(s, C_GRAY)}; font-weight: bold;")

        connected = s != "DISCONNECTED"
        # Fast Sweep drives the raw laser object directly from its own thread,
        # so it counts as "busy" for every control that would otherwise also
        # touch that object concurrently — same lockout as a regular SWEEPING.
        busy      = s == "SWEEPING" or self._fast_sweep_running
        self._pw_run_btn.setEnabled(connected and not busy)
        self._pw_stop_btn.setEnabled(s == "SWEEPING")
        self._wl_btn.setEnabled(connected and not busy)
        self._pow_btn.setEnabled(connected and not busy)
        self._on_btn.setEnabled(connected and not busy)
        self._off_btn.setEnabled(connected and not busy)
        self._fs_run_btn.setEnabled(connected and not busy)

    def _on_wavelength(self, nm: float):
        self._wl_lbl.setText(f"{nm:.4f} nm")
        self._last_wavelength_nm = nm

    def _on_power(self, mw: float):
        self._pow_lbl.setText(f"{mw:.3f} mW")
        self._last_power_mw = mw

    def latest_reading(self):
        """Last (wavelength, power) reading, or None if not connected."""
        if self._status_lbl.text() == "DISCONNECTED":
            return None
        return {"wavelength_nm": self._last_wavelength_nm, "power_mw": self._last_power_mw}

    def set_coredaq_panel(self, panel):
        """Wires the CoreDAQ tab in so wavelength sweeps can log optical power."""
        self._coredaq_panel = panel

    def _on_output(self, on: bool):
        self._output_lbl.setText("ON" if on else "OFF")
        self._output_lbl.setStyleSheet(f"color: {C_RED if on else C_GRAY}; font-weight: bold;")

    def _on_range(self, min_nm: float, max_nm: float, max_mw: float):
        self._wl_spin.setRange(min_nm, max_nm)
        self._pow_spin.setRange(0.0, max_mw)
        self._log.append(f"Wavelength range: {min_nm:.3f}–{max_nm:.3f} nm,  max power {max_mw:.3f} mW")

    def _on_log(self, msg: str):
        self._log.append(msg)

    def _on_error(self, msg: str):
        self._log.append(f"<span style='color:{C_RED};'>ERROR: {msg}</span>")
        connected = self._status_lbl.text() != "DISCONNECTED"
        print(f"[Santec] ERROR: {msg}" if connected
              else f"[Santec] FAILED to connect: {msg}")

    def _on_op_done(self, op: str):
        if op == "connect":
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._gpib_spin.setEnabled(False)
            self._prologix_port_spin.setEnabled(False)
            print(f"[Santec] Connected — GPIB {self._gpib_spin.value()} "
                  f"via Prologix COM{self._prologix_port_spin.value()}")
        elif op == "disconnect":
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)
            self._gpib_spin.setEnabled(True)
            self._prologix_port_spin.setEnabled(True)
        elif op == "power_sweep":
            self._power_sweep_logging = False
            if self._power_sweep_log:
                self._power_sweep_export_btn.setEnabled(True)
                self._show_power_sweep_plot()

    def _on_power_sweep_progress(self, idx: int, total: int, mw: float):
        self._pw_progress_lbl.setText(f"[{idx}/{total}]  {mw:.3f} mW")
        if self._power_sweep_logging and self._coredaq_panel is not None:
            powers = self._coredaq_panel.latest_power_w()
            if powers is not None:
                self._power_sweep_log.append((mw, *powers))

    def _show_power_sweep_plot(self):
        series = {}
        for ch in range(4):
            xs = [row[0] for row in self._power_sweep_log]
            ys = [row[1 + ch] * 1e9 for row in self._power_sweep_log]
            series[f"MZI {ch + 1}"] = (xs, ys, "nW")
        win = MatplotlibPlotWindow("Santec Power Sweep — CoreDAQ Power", "Laser power", "mW")
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._power_sweep_plot_win = win

    def _export_power_sweep_csv(self):
        if not self._power_sweep_log:
            return
        import datetime
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"santec_power_sweep_coredaq_{stamp}.csv")
        comments = [
            "laser: Santec TSL-550",
            f"power_sweep: {self._pw_start.value():.3f} -> {self._pw_stop.value():.3f} mW, "
            f"step {self._pw_step.value():.3f} mW, dwell {self._pw_dwell.value():.2f} s",
            f"wavelength_nm: {self._wl_spin.value():.4f}",
        ]
        header = ["power_mw",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = [[f"{mw:.4f}"] + [f"{w:.9e}" for w in powers]
                for mw, *powers in self._power_sweep_log]
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[Santec Power Sweep] Saved {len(rows)} rows → {fname}")
        self._log.append(f"Saved {len(rows)} power-sweep rows → {fname}")
        self._last_power_sweep_csv = fname
        self._power_sweep_open_btn.setEnabled(True)

    # ── Button actions ────────────────────────────────────────────────────────

    def _do_connect(self):
        save_connection_setting("santec_gpib_addr", self._gpib_spin.value())
        save_connection_setting("prologix_com_port", self._prologix_port_spin.value())
        self._sig_connect.emit(self._gpib_spin.value(), self._prologix_port_spin.value())

    def _do_set_wl(self):
        nm = self._wl_spin.value()
        save_connection_setting("santec_last_wavelength_nm", nm)
        self._sig_set_wl.emit(nm)

    def _do_set_power(self):
        mw = self._pow_spin.value()
        save_connection_setting("santec_last_power_mw", mw)
        self._sig_set_power.emit(mw)

    def _do_output_on(self):
        """Output ON also (re-)applies whatever wavelength/power are
        currently dialed into Manual Control, so turning the laser on
        always reflects what's set on screen instead of requiring two
        separate SET! clicks first."""
        nm = self._wl_spin.value()
        mw = self._pow_spin.value()
        save_connection_setting("santec_last_wavelength_nm", nm)
        save_connection_setting("santec_last_power_mw", mw)
        self._sig_set_output.emit(True, nm, mw)

    def _do_power_sweep(self):
        start = self._pw_start.value()
        stop  = self._pw_stop.value()
        step  = self._pw_step.value()
        dwell = self._pw_dwell.value()
        if abs(start - stop) < 1e-9:
            QMessageBox.warning(self, "Power Sweep", "Start and stop must differ.")
            return
        self._pw_progress_lbl.setText("")
        self._power_sweep_log = []
        self._power_sweep_export_btn.setEnabled(False)
        self._power_sweep_logging = self._power_sweep_log_chk.isChecked()
        self._sig_power_sweep.emit(start, stop, step, dwell)

    def _do_stop_sweep(self):
        # Set the worker's threading.Event directly from this (GUI) thread — a
        # queued _sig_stop_sweep signal would just sit behind the sweep loop's
        # own blocking call on the worker thread and never get delivered in time.
        self._worker._stop_event.set()
        self._sig_stop_sweep.emit()

    def _update_fast_sweep_info(self):
        start = self._fs_start.value()
        stop  = self._fs_stop.value()
        speed = self._fs_speed.value()
        if speed <= 0:
            self._fs_info_lbl.setText("")
            return
        duration_s = abs(stop - start) / speed
        npts = int(round(duration_s * FastSweepWorker.SWEEP_RATE_HZ))
        self._fs_info_lbl.setText(f"~{npts} pts \u00b7 ~{duration_s:.1f} s")

    def _set_fast_sweep_controls_enabled(self, enabled: bool):
        # The fast sweep drives the raw laser/DAQ objects directly from its own
        # thread \u2014 anything else that could also touch them concurrently
        # (manual wavelength/power/output, the power sweep) must be locked
        # out for the duration, same as SWEEPING already locks them out for
        # do_power_sweep().
        for w in (self._fs_run_btn, self._pw_run_btn,
                  self._wl_btn, self._pow_btn, self._on_btn, self._off_btn,
                  self._disconnect_btn):
            w.setEnabled(enabled)

    def _do_fast_sweep(self):
        start = self._fs_start.value()
        stop  = self._fs_stop.value()
        speed = self._fs_speed.value()
        power = self._fs_power.value()
        if abs(start - stop) < 1e-9:
            QMessageBox.warning(self, "Fast Sweep", "Start and stop must differ.")
            return
        if self._coredaq_panel is None or not self._coredaq_panel._connected:
            QMessageBox.warning(self, "Fast Sweep", "CoreDAQ must be connected first.")
            return

        # Pause CoreDAQ's own ~5 Hz poll loop \u2014 it shares the same serial
        # connection the sweep worker is about to drive directly.
        if not self._coredaq_panel.pause_polling():
            QMessageBox.warning(
                self, "Fast Sweep",
                "CoreDAQ isn't responding (a poll call may be stuck on a "
                "hardware read) \u2014 refusing to start Fast Sweep since it "
                "would touch the same serial connection concurrently. "
                "Try reconnecting the CoreDAQ panel.")
            return

        self._fast_sweep_result  = None
        self._fast_sweep_running = True
        self._fs_export_btn.setEnabled(False)
        self._fs_progress_lbl.setText("Starting...")
        self._set_fast_sweep_controls_enabled(False)

        self._fast_sweep_worker.set_hardware(self._worker._laser, self._coredaq_panel._worker._daq)
        self._fast_sweep_worker.set_sweep_params({
            "start_nm": start, "stop_nm": stop, "speed": speed, "power": power,
        })
        self._sig_run_fast_sweep.emit()

    def _on_fast_sweep_progress(self, msg: str):
        self._fs_progress_lbl.setText(msg)

    def _on_fast_sweep_result(self, result: dict):
        self._fast_sweep_result = (result["wavelengths"], result["power_ch"])
        self._log.append(f"Fast sweep captured {len(result['wavelengths'])} points")
        self._fs_export_btn.setEnabled(True)
        self._show_fast_sweep_plot()

    def _on_fast_sweep_error(self, msg: str):
        self._log.append(f"<span style='color:{C_RED};'>Fast sweep ERROR: {msg}</span>")
        QMessageBox.warning(self, "Fast Sweep Error", f"Fast sweep failed:\n{msg}")

    def _on_fast_sweep_finished(self):
        self._fast_sweep_running = False
        connected = self._status_lbl.text() != "DISCONNECTED"
        self._set_fast_sweep_controls_enabled(connected)
        if self._coredaq_panel is not None:
            self._coredaq_panel.resume_polling()

    def _show_fast_sweep_plot(self):
        if not self._fast_sweep_result:
            return
        if not HAS_MATPLOTLIB:
            self._log.append(
                f"<span style='color:{C_RED};'>matplotlib not installed \u2014 "
                "can't show Fast Sweep plot. Run: uv pip install matplotlib</span>")
            return
        wavelengths, power_ch = self._fast_sweep_result
        series = {}
        for ch in range(min(4, len(power_ch))):
            ys_nw = [w * 1e9 for w in power_ch[ch]]
            series[f"MZI {ch + 1}"] = (wavelengths, ys_nw, "nW")
        win = MatplotlibPlotWindow("Santec Fast Sweep \u2014 CoreDAQ Power", "Wavelength", "nm")
        win.show_data(series)
        mw = self.window()
        win.move(mw.x() + mw.width() + 16, mw.y() + 40)
        self._fast_sweep_plot_win = win

    def _export_fast_sweep_csv(self):
        if not self._fast_sweep_result:
            return
        import datetime
        wavelengths, power_ch = self._fast_sweep_result
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"santec_fast_sweep_coredaq_{stamp}.csv")
        comments = [
            "laser: Santec TSL-550 (HW-triggered continuous sweep)",
            f"sweep: {self._fs_start.value():.4f} -> {self._fs_stop.value():.4f} nm, "
            f"speed {self._fs_speed.value():.2f} nm/s, power {self._fs_power.value():.3f} mW",
        ]
        header = ["wavelength_nm",
                  "coredaq_ch1_W", "coredaq_ch2_W", "coredaq_ch3_W", "coredaq_ch4_W"]
        rows = []
        for i, wl in enumerate(wavelengths):
            rows.append([f"{wl:.4f}"] + [f"{power_ch[ch][i]:.9e}" for ch in range(4)])
        write_csv_with_metadata(fname, comments, header, rows)
        print(f"[Santec Fast Sweep] Saved {len(rows)} rows \u2192 {fname}")
        self._log.append(f"Saved {len(rows)} fast-sweep rows \u2192 {fname}")
        self._last_fast_sweep_csv = fname
        self._fs_open_btn.setEnabled(True)

        # Save the matplotlib results plot alongside the CSV \u2014 same basename,
        # in data/images/ \u2014 so the picture and the data it came from stay
        # paired. self._fast_sweep_plot_win survives even if the user closed
        # that window (we still hold the Python reference), so this reuses
        # the exact figure already rendered instead of re-plotting from scratch.
        if HAS_MATPLOTLIB and self._fast_sweep_plot_win is not None:
            os.makedirs(IMAGES_DIR, exist_ok=True)
            img_name = os.path.splitext(os.path.basename(fname))[0] + ".png"
            img_path = os.path.join(IMAGES_DIR, img_name)
            self._fast_sweep_plot_win.save_png(img_path)
            print(f"[Santec Fast Sweep] Saved plot image \u2192 {img_path}")
            self._log.append(f"Saved plot image \u2192 {img_path}")

    def cleanup(self):
        if HAS_PYVISA and HAS_SANTEC:
            self._status_poll_timer.stop()
            self._sig_disconnect.emit()
            self._thread.quit()
            self._thread.wait(2000)
            self._fast_sweep_thread.quit()
            self._fast_sweep_thread.wait(2000)


# ══════════════════════════════════════════════════════════════════════════════
# COREDAQ OPTICAL POWER METER PANEL
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_power_w(p_w: float) -> str:
    """Auto-scale a watts value to a readable string (mW/µW/nW/pW)."""
    a = abs(p_w)
    if a >= 1e-3:
        return f"{p_w * 1e3:.4f} mW"
    if a >= 1e-6:
        return f"{p_w * 1e6:.4f} µW"
    if a >= 1e-9:
        return f"{p_w * 1e9:.4f} nW"
    return f"{p_w * 1e12:.4f} pW"


def write_csv_with_metadata(path: str, comments: list, header: list, rows: list):
    """
    Writes '# comment' lines followed by a normal CSV body — mirrors the
    metadata-header convention used by the reference CoreConsole sweep tab.
    """
    import csv
    with open(path, "w", newline="") as f:
        for c in comments:
            f.write(f"# {c}\n")
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


if HAS_PYQTGRAPH:
    class _DecimalAxisItem(pg.AxisItem):
        """AxisItem that always renders tick labels in plain decimal notation.
        pyqtgraph's default tickStrings() falls back to scientific notation
        ("%g") for values below 0.001 or at/above 10000 — unreadable for the
        tiny (sub-µW) CoreDAQ power readings on the Santec sweep plots."""
        def tickStrings(self, values, scale, spacing):
            eff = spacing * scale
            places = max(0, math.ceil(-math.log10(eff))) if eff > 0 else 0
            return [("%%0.%df" % places) % (v * scale) for v in values]


class MultiSeriesPlotWindow(QWidget):
    """
    Generic 2-column grid of pyqtgraph plots, one per named series — mirrors
    the reference CoreConsole app's plotter/sweep tab layout. Sparse-tolerant:
    each series supplies its own (x, y) arrays, so devices that weren't
    connected the whole time just produce a shorter curve.
    """

    _COLORS = (C_BLUE, C_GOLD, C_GREEN, C_RED, "#B388FF", "#00FF88", "#FFA836", "#4FC3F7")

    def __init__(self, title: str, x_label: str, x_unit: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 640)
        self._x_label = x_label
        self._x_unit  = x_unit
        self._grid = QGridLayout(self)
        self._plots = {}   # name -> (PlotWidget, curve)

    def show_data(self, series_data: dict):
        """series_data: {name: (xs, ys, y_unit)}"""
        if not HAS_PYQTGRAPH:
            self._grid.addWidget(QLabel("pyqtgraph required for plots"), 0, 0)
            return
        for i, (name, (xs, ys, y_unit)) in enumerate(series_data.items()):
            if name not in self._plots:
                pw = pg.PlotWidget(axisItems={
                    'bottom': _DecimalAxisItem(orientation='bottom'),
                    'left':   _DecimalAxisItem(orientation='left'),
                })
                pw.setLabel('bottom', self._x_label, units=self._x_unit)
                pw.setLabel('left', name, units=y_unit)
                pw.getAxis('left').enableAutoSIPrefix(False)
                pw.setMinimumHeight(220)
                color = self._COLORS[len(self._plots) % len(self._COLORS)]
                curve = pw.plot([], [], pen=pg.mkPen(color, width=2), symbol='o', symbolSize=4)
                row, col = divmod(len(self._plots), 2)
                self._grid.addWidget(pw, row, col)
                self._plots[name] = (pw, curve)
            _, curve = self._plots[name]
            curve.setData(xs, ys)
        self.show()
        self.raise_()


class MatplotlibPlotWindow(QWidget):
    """
    Matplotlib results window for sweep/run results across every device tab
    (DAQ Control, ITLA, HP-8168F, Santec regular + fast sweep) — all series
    overlaid on one white-background axes with a legend you can click to
    toggle each one, plus the standard Matplotlib pan/zoom/save toolbar. A
    print/report-friendly look, and the PNG this saves (see save_png) is what
    ends up paired with each sweep's exported CSV.
    Deliberately separate from MultiSeriesPlotWindow (pyqtgraph, dark theme,
    one-subplot-per-series grid), which stays in use for the live/continuous
    recording plots — those redraw at high frequency, where matplotlib's
    full-redraw-per-frame cost doesn't fit the way a single sweep-end plot does.
    """

    _COLORS = ("#1f77b4", "#d62728", "#2ca02c", "#ff7f0e",
               "#9467bd", "#17becf", "#8c564b", "#e377c2")

    def __init__(self, title: str, x_label: str, x_unit: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1400, 900)
        self._x_label = x_label
        self._x_unit  = x_unit

        layout = QVBoxLayout(self)
        if not HAS_MATPLOTLIB:
            layout.addWidget(QLabel("matplotlib required for plots — "
                                     "run: uv pip install matplotlib"))
            self._fig = self._canvas = self._ax = None
            return

        self.setStyleSheet("background-color: white;")
        # Bigger figure + higher on-screen DPI than matplotlib's default so
        # sweep lines are easier to read at a glance; save_png() renders the
        # exported PNG at an even higher DPI on top of this for print-quality
        # output.
        self._fig = Figure(figsize=(13, 8), dpi=120, facecolor="white")
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._ax = self._fig.add_subplot(111, facecolor="white")
        layout.addWidget(self._canvas)
        try:
            from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
            layout.addWidget(NavigationToolbar2QT(self._canvas, self))
        except Exception:
            pass

    def show_data(self, series_data: dict):
        """series_data: {name: (xs, ys, y_unit)}"""
        if not HAS_MATPLOTLIB:
            self.show()
            self.raise_()
            return
        self._ax.clear()
        self._ax.set_facecolor("white")
        y_unit = ""
        for i, (name, (xs, ys, unit)) in enumerate(series_data.items()):
            y_unit = unit or y_unit
            self._ax.plot(xs, ys, label=name, color=self._COLORS[i % len(self._COLORS)],
                           linewidth=2.2)
        x_label = f"{self._x_label} ({self._x_unit})" if self._x_unit else self._x_label
        y_label = f"Power ({y_unit})" if y_unit else "Power"
        self._ax.set_xlabel(x_label, fontsize=12)
        self._ax.set_ylabel(y_label, fontsize=12)
        self._ax.set_title(self.windowTitle(), fontsize=14)
        self._ax.tick_params(axis="both", labelsize=11)
        # Data is pre-scaled into a sane unit (e.g. nW) by the caller, so the
        # axis should show plain numbers in that unit — not matplotlib's own
        # sci-notation/offset rescaling on top of it, which would just make
        # the axis unit ambiguous again (e.g. "1e-9" next to a "nW" label).
        self._ax.ticklabel_format(style="plain", axis="y")
        self._ax.yaxis.get_major_formatter().set_useOffset(False)
        self._ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.5, color="#cccccc")
        self._ax.legend(loc="best", frameon=True, fontsize=11)
        for side in ("top", "right"):
            self._ax.spines[side].set_visible(False)
        self._fig.tight_layout()
        self._canvas.draw()
        self.show()
        self.raise_()

    def save_png(self, path: str) -> None:
        """Saves the currently-rendered figure exactly as shown — works even
        if this window has since been closed/hidden, since closing a QWidget
        we still hold a Python reference to doesn't destroy its Figure.
        Rendered at a higher DPI than the on-screen figure so the exported
        PNG stays sharp when zoomed in or printed."""
        self._fig.savefig(path, facecolor="white", dpi=200)


class CoreDAQWorker(QObject):
    """
    Runs blocking serial calls to the CoreDAQ optical power meter off the GUI
    thread. All I/O still goes through this one worker thread via queued
    slots (do_connect/do_poll/do_set_gain/do_set_wavelength/do_disconnect),
    preserving strict single-owner access to the serial connection.

    The plot data path is restructured to match the lab's
    threads/daq_reader_coredaq.py DaqReaderWorker for speed: each do_poll()
    tick is one snapshot_W() round trip (not two), decimated writes into a
    pre-allocated numpy ring buffer (O(1) circular write, no Python-list
    .pop(0) reshuffling), and a zero-allocation chronological read via
    get_display_data() for the GUI's independent ~30 Hz redraw timer. The
    numeric mV/gain labels and latest_power_w() are refreshed on a much
    slower wall-clock throttle (LABEL_HZ) since they don't need per-sample
    freshness.

    Poll loop is self-pacing, not a fixed-interval timer: do_poll() only
    schedules the next tick (via QTimer.singleShot(0, ...), fired on this
    same worker thread — no cross-thread signal) after the current one
    finishes. A fixed-rate timer firing faster than the serial round trip
    would queue up an ever-growing backlog of pending polls, which is what
    made the live plots stutter/freeze under load.
    """
    status_changed = pyqtSignal(str)             # DISCONNECTED / CONNECTED
    info_update     = pyqtSignal(str, str, str)   # idn, frontend_type, detector_type
    raw_update      = pyqtSignal(list, list, list)  # power_w(4), mV(4), gains(4) — throttled
    log_message     = pyqtSignal(str)
    error           = pyqtSignal(str)
    op_done         = pyqtSignal(str)
    poll_paused     = pyqtSignal()
    autogain_done   = pyqtSignal(list)   # gains(4), after an autogain pass

    LABEL_HZ = 10.0   # wall-clock throttle for numeric-label refresh + extra snapshot_mV() call

    # Minimum spacing between poll ticks. The poll loop is self-chained (the
    # next tick is scheduled only after the current one finishes), so this is
    # a floor, not a fixed rate — the real cadence is whatever the slower of
    # this interval and the serial round-trip time works out to. A small
    # non-zero floor (vs. the old singleShot(0) "as fast as possible") keeps
    # the worker thread from pegging a core and starving the GUI thread of
    # the GIL, which is what made the whole app feel frozen while connected.
    POLL_INTERVAL_MS = 15

    # Only used by do_connect() (see _call_with_timeout below) — NOT do_poll's
    # hot path, which is exactly why this can't just reuse the old
    # every-call-gets-a-thread pattern _call()'s docstring describes moving
    # away from.
    CONNECT_TIMEOUT_S = 5.0

    def __init__(self):
        super().__init__()
        self._daq = None
        self._last_power_w = None
        self._polling = False

        # ── Plot ring buffer: pre-allocated, fixed-size, circular ───────────
        # Sized generously for COREDAQ_PLOT_WINDOW_S at up to ~1 kHz — actual
        # achieved poll rate (capped by serial round-trip time) just fills a
        # smaller fraction of the window, which is fine.
        self.plot_buffer_len  = max(2, int(COREDAQ_PLOT_WINDOW_S * 1000))
        self.plot_buffer      = np.zeros((4, self.plot_buffer_len), dtype=np.float32)
        # Actual wall-clock time of each sample — the real poll rate is capped
        # by serial round-trip time and runs nowhere near the 1 kHz the buffer
        # is sized for, so the display side needs real timestamps (not an
        # assumed-rate linspace) to know which samples actually fall within
        # the last COREDAQ_PLOT_WINDOW_S seconds.
        self.plot_time_buffer = np.zeros(self.plot_buffer_len, dtype=np.float64)
        self.plot_write_index = 0
        self.plot_filled      = 0
        self._display_buf     = np.zeros((4, self.plot_buffer_len), dtype=np.float32)
        self._display_time_buf = np.zeros(self.plot_buffer_len, dtype=np.float64)

        self._last_label_emit_t = 0.0
        self._err_count = 0

    def _call(self, func, *args, **kwargs):
        """Invoke a blocking CoreDAQ serial call directly on this worker thread.

        This used to run every call on a throwaway daemon thread with a hard
        timeout, so a wedged read could never block the worker. That backfired
        badly: the poll loop spawned hundreds of short-lived daemon threads per
        second, and the resulting GIL contention/thread churn made the whole
        GUI unresponsive. Worse, a timed-out call abandoned a live daemon
        thread that still held the serial port open, so the COM port stayed
        locked until a reboot.

        CoreDAQ's own pyserial read timeout (0.15 s) already bounds normal
        calls, and because this runs on the worker QThread (not the GUI
        thread), even a rare hard wedge only stalls this one background thread
        and stops the tab updating — the rest of the app stays usable. This is
        the same direct-call model the reliable reference GUI uses."""
        return func(*args, **kwargs)

    def _call_with_timeout(self, func, *args, **kwargs):
        """Same bounded-timeout pattern as ConexWorker: runs `func` on a
        throwaway daemon thread so a wedged call can't hang this worker
        thread forever, and raises TimeoutError instead. Reserved for
        do_connect() specifically — a one-time call, not the hot poll loop
        — so it can't reintroduce the GIL-contention/thread-churn problem
        that made _call() above stop doing this for every call. This is
        what lets auto-connect-on-launch be safe: previously a wedged
        serial-port open here froze the whole GUI unrecoverably; now it
        times out and reports an error instead."""
        result = {}
        def _run():
            try:
                result['value'] = func(*args, **kwargs)
            except Exception as e:
                result['error'] = e
            finally:
                result['done'] = True
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(self.CONNECT_TIMEOUT_S)
        if not result.get('done'):
            raise TimeoutError(
                f"CoreDAQ stopped responding (no reply within {self.CONNECT_TIMEOUT_S:.0f}s) "
                "— the serial connection is likely wedged. Unplug/replug the device.")
        if 'error' in result:
            raise result['error']
        return result['value']

    def do_connect(self, port: str):
        # Defensive: release any handle we're still holding from a prior
        # attempt before opening a new one, so we're never the reason a
        # retry fails with "port already open". Bounded like every other
        # hardware call — close() can itself block on a wedged port.
        if self._daq is not None:
            try:
                self._call_with_timeout(self._daq.close)
            except Exception:
                pass
            self._daq = None
        try:
            port = port.strip()
            # Accept bare numbers ("16") as shorthand for the Windows device
            # name pyserial actually needs ("COM16") — same convention the
            # vendor's own CoreConsole-style tooling expects.
            if port.isdigit():
                port = f"COM{port}"
            if port:
                daq = self._call_with_timeout(CoreDAQ, port)
            else:
                ports = self._call_with_timeout(CoreDAQ.find)
                if not ports:
                    self.error.emit("No CoreDAQ device found — check USB connection")
                    return
                self.log_message.emit(f"Auto-detected CoreDAQ on {ports[0]}")
                daq = self._call_with_timeout(CoreDAQ, ports[0])
            self._daq = daq
            idn       = self._call_with_timeout(self._daq.idn)
            frontend  = self._call_with_timeout(self._daq.frontend_type)
            detector  = self._call_with_timeout(self._daq.detector_type)
            # Fresh connection: drop any stale samples from a previous device
            # so the plot window doesn't briefly show old data.
            self.plot_write_index   = 0
            self.plot_filled        = 0
            self._last_label_emit_t = 0.0
            self._err_count         = 0
            self.status_changed.emit("CONNECTED")
            self.info_update.emit(idn, frontend, detector)
            self.log_message.emit(f"Connected — {idn}")
            self.op_done.emit("connect")
            self._polling = True
            QTimer.singleShot(self.POLL_INTERVAL_MS, self.do_poll)
        except PermissionError as e:
            self.error.emit(
                f"Connect failed: {e} — port is already open elsewhere "
                "(another program such as CoreConsole, a leftover instance "
                "of this GUI, or a previous unclosed connection). Close "
                "whatever else has it open, or leave the Port field blank "
                "to auto-detect — the right device, even if it's enumerated "
                "on a different COM port.")
        except Exception as e:
            self.error.emit(f"Connect failed: {e}")

    def do_poll(self):
        if not self._polling or self._daq is None:
            return
        try:
            power_w = self._call(self._daq.snapshot_W)
            data = np.asarray(power_w[:4], dtype=np.float32)
            self._last_power_w = tuple(float(x) for x in power_w[:4])

            now = time.monotonic()
            self.plot_buffer[:, self.plot_write_index] = data
            self.plot_time_buffer[self.plot_write_index] = now
            self.plot_write_index = (self.plot_write_index + 1) % self.plot_buffer_len
            if self.plot_filled < self.plot_buffer_len:
                self.plot_filled += 1

            if (now - self._last_label_emit_t) >= (1.0 / self.LABEL_HZ):
                self._last_label_emit_t = now
                mv, gains = self._call(self._daq.snapshot_mV)
                self.raw_update.emit(list(power_w[:4]), list(mv[:4]), list(gains[:4]))
        except Exception as e:
            self._err_count += 1
            if self._err_count % 200 == 1:
                self.error.emit(f"Poll error (×{self._err_count}): {e}")
        finally:
            # Chain the next tick only once this one is done, paced by
            # POLL_INTERVAL_MS so the loop never busy-spins the worker thread.
            if self._polling:
                QTimer.singleShot(self.POLL_INTERVAL_MS, self.do_poll)

    def do_pause_poll(self):
        """Stops the self-pacing loop and confirms via poll_paused so the
        caller (Fast Sweep, which is about to touch the raw CoreDAQ handle
        from a different thread) knows no poll is in flight. Queued
        (non-blocking) — if a poll call is currently wedged in a hardware
        read, this request simply waits behind it in this thread's own
        queue instead of also blocking the GUI thread."""
        self._polling = False
        self.poll_paused.emit()

    def do_resume_poll(self):
        if self._daq is not None and not self._polling:
            self._polling = True
            QTimer.singleShot(self.POLL_INTERVAL_MS, self.do_poll)

    def get_display_data(self):
        """
        Returns (data, times, count): the plot ring buffer stitched
        chronologically (oldest first) into pre-allocated scratch buffers —
        no allocation on this hot path, called directly (not via a queued
        signal) by the GUI's independent display-refresh timer. `times` are
        time.monotonic() wall-clock timestamps for each sample, so the
        caller can plot against actual elapsed time instead of an assumed
        sample rate.
        """
        count = self.plot_filled
        if count == 0:
            return self._display_buf, self._display_time_buf, 0

        N    = self.plot_buffer_len
        widx = self.plot_write_index

        if count >= N:
            if widx == 0:
                np.copyto(self._display_buf, self.plot_buffer)
                np.copyto(self._display_time_buf, self.plot_time_buffer)
            else:
                self._display_buf[:, :N - widx] = self.plot_buffer[:, widx:]
                self._display_buf[:, N - widx:] = self.plot_buffer[:, :widx]
                self._display_time_buf[:N - widx] = self.plot_time_buffer[widx:]
                self._display_time_buf[N - widx:] = self.plot_time_buffer[:widx]
        else:
            np.copyto(self._display_buf[:, :count], self.plot_buffer[:, :count])
            np.copyto(self._display_time_buf[:count], self.plot_time_buffer[:count])

        return self._display_buf, self._display_time_buf, count

    def do_set_gain(self, head: int, value: int):
        try:
            self._call(self._daq.set_gain, head, value)
            self.log_message.emit(f"Head {head} gain set to G{value}")
            self.op_done.emit("set_gain")
        except Exception as e:
            self.error.emit(f"Set gain error: {e}")

    def do_autogain(self):
        """Runs on this worker thread, same as do_poll — no need to pause
        polling here (unlike the older reference GUI) since both share one
        QThread event loop and Qt serializes queued calls onto it, so a poll
        tick can never interleave with autogain's own SNAP reads."""
        try:
            _watts, _mv, gains = self._call(
                self._daq.snapshot_W, autogain=True, return_debug=True,
                n_frames=4, timeout_s=1.0,
                min_mv=100.0, max_mv=3000.0,
                max_iters=10, settle_s=0.05,
            )
            gains_int = [int(g) for g in gains]
            self.log_message.emit(f"Autogain complete — gains={gains_int}")
            self.autogain_done.emit(gains_int)
            self.op_done.emit("autogain")
        except Exception as e:
            self.error.emit(f"Autogain error: {e}")

    def do_set_wavelength(self, nm: float):
        try:
            self._call(self._daq.set_wavelength_nm, nm)
            self.log_message.emit(f"Measurement wavelength set to {nm:.2f} nm")
            self.op_done.emit("set_wavelength")
        except Exception as e:
            self.error.emit(f"Set wavelength error: {e}")

    def do_disconnect(self):
        self._polling = False
        daq = self._daq
        self._daq = None
        # Reflect the disconnect in the UI first, then do the (possibly slow)
        # port close. That way the GUI flips to DISCONNECTED immediately even
        # if close() blocks briefly on a sluggish link, instead of looking
        # like the button did nothing.
        self.status_changed.emit("DISCONNECTED")
        self.op_done.emit("disconnect")
        try:
            if daq is not None:
                self._call(daq.close)
            self.log_message.emit("Disconnected from CoreDAQ")
        except Exception as e:
            self.error.emit(f"Disconnect error: {e}")


class CoreDAQPanel(QWidget):
    """
    CoreDAQ 4-channel USB optical power meter — wraps hardware/coredaq.py.
    All blocking serial calls run in CoreDAQWorker on a background QThread.
    """

    _sig_connect       = pyqtSignal(str)
    _sig_pause_poll    = pyqtSignal()
    _sig_resume_poll   = pyqtSignal()
    _sig_set_gain      = pyqtSignal(int, int)
    _sig_autogain      = pyqtSignal()
    _sig_set_wl        = pyqtSignal(float)
    _sig_disconnect    = pyqtSignal()

    DISPLAY_MS = 33   # ~30 Hz plot redraw, decoupled from the poll/acquire rate
    MAX_PLOT_POINTS = 1500   # cap points handed to pyqtgraph per curve per redraw —
                              # a fast poll rate can fill the 5s window with several
                              # thousand samples/channel, and re-rendering all of them
                              # 30x/sec was enough GUI-thread work to make the tab feel
                              # frozen even though nothing was actually stuck

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected     = False
        self._frontend_type = None

        if not HAS_SERIAL or not HAS_COREDAQ:
            lay = QVBoxLayout(self)
            msg = []
            if not HAS_SERIAL:
                msg.append("pyserial is not installed. Run: uv pip install pyserial")
            if not HAS_COREDAQ:
                msg.append("hardware.coredaq module not found —\n"
                            "place hardware/coredaq.py next to this script to enable this tab.")
            lay.addWidget(QLabel("\n".join(msg) + "\nthen restart the GUI."))
            return

        # ── Worker thread ─────────────────────────────────────────────────────
        self._worker = CoreDAQWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        self._sig_connect.connect(self._worker.do_connect)
        # Queued (not blocking): pause_polling() below waits for poll_paused
        # itself, via a QEventLoop with a timeout, so a poll call wedged in
        # a hardware read can never freeze the GUI thread — see pause_polling().
        self._sig_pause_poll.connect(self._worker.do_pause_poll)
        self._sig_resume_poll.connect(self._worker.do_resume_poll)
        self._sig_set_gain.connect(self._worker.do_set_gain)
        self._sig_autogain.connect(self._worker.do_autogain)
        self._sig_set_wl.connect(self._worker.do_set_wavelength)
        self._sig_disconnect.connect(self._worker.do_disconnect)

        self._worker.status_changed.connect(self._on_status)
        self._worker.info_update.connect(self._on_info)
        self._worker.raw_update.connect(self._on_raw)
        self._worker.log_message.connect(self._on_log)
        self._worker.error.connect(self._on_error)
        self._worker.op_done.connect(self._on_op_done)
        self._worker.autogain_done.connect(self._on_autogain_done)

        # Independent redraw timer — reads the worker's ring buffer directly
        # (get_display_data() is a plain, allocation-free method call, not a
        # queued signal) so plot refresh rate never depends on how fast the
        # serial link can actually sustain do_poll() ticks. Left stopped here:
        # the live plot is hidden by default and only starts redrawing when the
        # user ticks "Show live plot" (see _on_show_plot_toggled). Keeping it
        # off by default removes a continuous 30 Hz GUI-thread render load.
        self._display_timer = QTimer()
        self._display_timer.setInterval(self.DISPLAY_MS)
        self._display_timer.timeout.connect(self._update_live_plot)

        self._build_ui()

        # Auto-connect on launch. This used to be unsafe — a wedged/blocking
        # serial open here froze the whole GUI at startup, unrecoverable
        # short of a reboot — but do_connect() now runs its hardware calls
        # through _call_with_timeout() (see CoreDAQWorker), which can't hang
        # past CONNECT_TIMEOUT_S. Deferred via singleShot(0, ...) so it fires
        # once the event loop is actually pumping rather than synchronously
        # mid-construction.
        QTimer.singleShot(0, self._do_connect)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        final = QVBoxLayout(self)
        final.setContentsMargins(10, 10, 10, 10)

        root = QHBoxLayout()
        root.setSpacing(12)
        final.addLayout(root)

        # ── Left: Connection ──────────────────────────────────────────────────
        conn_box = QGroupBox("Connection")
        conn_lay = QGridLayout(conn_box)

        conn_lay.addWidget(QLabel("Status:"), 0, 0)
        self._status_lbl = QLabel("DISCONNECTED")
        self._status_lbl.setStyleSheet(f"color: {C_RED}; font-weight: bold;")
        conn_lay.addWidget(self._status_lbl, 0, 1)

        conn_lay.addWidget(QLabel("Port:"), 1, 0)
        self._port_edit = QLineEdit(load_connection_settings().get("coredaq_port", ""))
        self._port_edit.setPlaceholderText("blank = auto-detect, or COM16 / 16")
        conn_lay.addWidget(self._port_edit, 1, 1)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._do_connect)
        conn_lay.addWidget(self._connect_btn, 2, 0, 1, 2)

        self._disconnect_btn = QPushButton("DISCONNECT")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._do_disconnect)
        conn_lay.addWidget(self._disconnect_btn, 3, 0, 1, 2)

        conn_lay.addWidget(QLabel("IDN:"), 4, 0)
        self._idn_lbl = QLabel("—")
        self._idn_lbl.setWordWrap(True)
        conn_lay.addWidget(self._idn_lbl, 4, 1)

        conn_lay.addWidget(QLabel("Frontend:"), 5, 0)
        self._frontend_lbl = QLabel("—")
        conn_lay.addWidget(self._frontend_lbl, 5, 1)

        conn_lay.addWidget(QLabel("Detector:"), 6, 0)
        self._detector_lbl = QLabel("—")
        conn_lay.addWidget(self._detector_lbl, 6, 1)

        conn_lay.setRowStretch(7, 1)
        root.addWidget(conn_box)

        # ── Middle: Measurement config ───────────────────────────────────────
        cfg_box = QGroupBox("Measurement Config")
        cfg_lay = QGridLayout(cfg_box)

        cfg_lay.addWidget(QLabel("Wavelength (nm):"), 0, 0)
        self._wl_spin = NoScrollDoubleSpinBox()
        self._wl_spin.setDecimals(1)
        self._wl_spin.setRange(400.0, 1700.0)
        self._wl_spin.setValue(1550.0)
        persist_spinbox(self._wl_spin, "coredaq_wavelength_nm")
        cfg_lay.addWidget(self._wl_spin, 0, 1)
        self._wl_btn = QPushButton("SET!")
        self._wl_btn.setEnabled(False)
        self._wl_btn.clicked.connect(lambda: self._sig_set_wl.emit(self._wl_spin.value()))
        cfg_lay.addWidget(self._wl_btn, 0, 2)
        cfg_lay.addWidget(QLabel(
            "Keeps the InGaAs/Si responsivity correction in sync\n"
            "with the wavelength actually being measured."), 1, 0, 1, 3)

        cfg_lay.addWidget(QLabel("Gain (LINEAR heads only):"), 2, 0, 1, 3)
        self._gain_combos = []
        self._gain_btns    = []
        for h in range(1, 5):
            cfg_lay.addWidget(QLabel(f"Head {h}:"), 2 + h, 0)
            combo = QComboBox()
            for g, label in enumerate(CoreDAQ.GAIN_LABELS):
                combo.addItem(f"G{g} ({label})", g)
            combo.setEnabled(False)
            cfg_lay.addWidget(combo, 2 + h, 1)
            btn = QPushButton("Set")
            btn.setEnabled(False)
            btn.clicked.connect(lambda _, hh=h: self._sig_set_gain.emit(
                hh, self._gain_combos[hh - 1].currentData()))
            cfg_lay.addWidget(btn, 2 + h, 2)
            self._gain_combos.append(combo)
            self._gain_btns.append(btn)

        cfg_lay.addWidget(QLabel("Set All To:"), 7, 0)
        self._gain_set_all_combo = QComboBox()
        for g, label in enumerate(CoreDAQ.GAIN_LABELS):
            self._gain_set_all_combo.addItem(f"G{g} ({label})", g)
        self._gain_set_all_combo.setEnabled(False)
        cfg_lay.addWidget(self._gain_set_all_combo, 7, 1)
        self._gain_set_all_btn = QPushButton("Set All")
        self._gain_set_all_btn.setEnabled(False)
        self._gain_set_all_btn.clicked.connect(self._set_all_gains)
        cfg_lay.addWidget(self._gain_set_all_btn, 7, 2)

        self._autogain_btn = QPushButton("Autogain")
        self._autogain_btn.setEnabled(False)
        self._autogain_btn.setToolTip(
            "Automatically steps each head's gain so its reading lands\n"
            "within a safe mid-range window, then reads back the result")
        self._autogain_btn.clicked.connect(self._do_autogain)
        cfg_lay.addWidget(self._autogain_btn, 8, 0, 1, 3)

        cfg_lay.setRowStretch(9, 1)
        root.addWidget(cfg_box)

        # ── Right: Channel readouts ──────────────────────────────────────────
        ch_box = QGroupBox("Channels")
        ch_lay = QGridLayout(ch_box)
        self._power_lbls = []
        self._raw_lbls   = []
        for ch in range(4):
            ch_lay.addWidget(QLabel(f"Head {ch + 1}:"), ch, 0)
            p_lbl = QLabel("—")
            p_lbl.setStyleSheet(f"color: {C_BLUE}; font-family: monospace; font-size: 13px;")
            p_lbl.setMinimumWidth(110)
            ch_lay.addWidget(p_lbl, ch, 1)
            raw_lbl = QLabel("—")
            raw_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 10px;")
            ch_lay.addWidget(raw_lbl, ch, 2)
            self._power_lbls.append(p_lbl)
            self._raw_lbls.append(raw_lbl)
        ch_lay.setRowStretch(4, 1)
        root.addWidget(ch_box, stretch=1)

        # ── Live plot toggle — OFF by default ────────────────────────────────
        # The live plot is the single most expensive thing this tab does
        # (a 30 Hz GUI-thread redraw of up to 4×1500 points). It stays hidden
        # and un-timed until the user opts in, so simply connecting and reading
        # the numeric channel values never pays that cost.
        self._show_plot_chk = QCheckBox("Show live plot")
        self._show_plot_chk.setChecked(False)
        self._show_plot_chk.setToolTip(
            "Off by default. The rolling per-channel plot is CPU-heavy; enable "
            "it only when you need to watch the waveform.")
        self._show_plot_chk.toggled.connect(self._on_show_plot_toggled)
        final.addWidget(self._show_plot_chk)

        # ── Live plot — all 4 heads on one shared plot ───────────────────────
        plot_box = QGroupBox(f"Live Plot  (last {COREDAQ_PLOT_WINDOW_S:.0f} s)")
        self._plot_box = plot_box
        plot_lay = QVBoxLayout(plot_box)
        self._live_curves = []
        if HAS_PYQTGRAPH:
            colors = (C_BLUE, C_GOLD, C_GREEN, C_RED)
            pw = pg.PlotWidget()
            self._plot_widget = pw
            pw.setLabel('left', 'Power', units='nW')
            pw.setLabel('bottom', 'Time', units='s')
            pw.getAxis('left').enableAutoSIPrefix(False)
            pw.setMinimumHeight(320)
            # Render-side speedups: downsample large point counts to the
            # visible pixel width, clip off-screen data, and skip the
            # per-point NaN/Inf check (our ring-buffer data is always
            # finite) — mirrors the lab's assembled_gui.py live-plot setup.
            pw.plotItem.setDownsampling(auto=True, mode='peak')
            pw.plotItem.setClipToView(True)
            pw.setXRange(-COREDAQ_PLOT_WINDOW_S, 0.0, padding=0)
            # Autorange Y: with all 4 heads sharing one axis, their power
            # levels can differ a lot (e.g. different gains/detectors), so a
            # fixed per-channel span no longer makes sense — let pyqtgraph
            # fit the axis to whatever is currently visible/enabled.
            pw.enableAutoRange(axis='y', enable=True)
            # Legend entries are clickable in pyqtgraph — clicking a head's
            # swatch toggles that curve's visibility, giving show/hide per
            # head for free (pyqtgraph.LegendItem.ItemSample.mouseClickEvent).
            legend = pw.addLegend(offset=(10, 10))
            for ch in range(4):
                curve = pw.plot([], [], pen=pg.mkPen(colors[ch], width=2),
                                 name=f'MZI {ch + 1}', skipFiniteCheck=True)
                self._live_curves.append(curve)
            plot_lay.addWidget(pw)
        else:
            plot_lay.addWidget(QLabel("pyqtgraph required for live plots"))
        plot_box.setVisible(False)   # hidden until connected / "Show live plot" ticked
        final.addWidget(plot_box)

        # ── Bottom: Log ───────────────────────────────────────────────────────
        log_box = QGroupBox("Log")
        log_lay = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(100)
        log_lay.addWidget(self._log)
        final.addWidget(log_box)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_status(self, s: str):
        self._connected = s == "CONNECTED"
        self._status_lbl.setText(s)
        self._status_lbl.setStyleSheet(
            f"color: {C_BLUE if self._connected else C_RED}; font-weight: bold;")
        self._wl_btn.setEnabled(self._connected)
        if self._connected:
            if HAS_PYQTGRAPH:
                for curve in self._live_curves:
                    curve.setData([], [])
            # Re-sync the redraw timer to the checkbox: on a reconnect the plot
            # should resume automatically if "Show live plot" is still ticked.
            if self._show_plot_chk.isChecked() and not self._display_timer.isActive():
                self._display_timer.start()
            # Polling itself is started/stopped by the worker (do_connect /
            # do_disconnect) — it lives entirely on the worker thread now.
        else:
            for lbl in self._power_lbls: lbl.setText("—")
            for lbl in self._raw_lbls:   lbl.setText("—")
            for combo, btn in zip(self._gain_combos, self._gain_btns):
                combo.setEnabled(False); btn.setEnabled(False)
            self._gain_set_all_combo.setEnabled(False)
            self._gain_set_all_btn.setEnabled(False)
            self._autogain_btn.setEnabled(False)

    def _on_info(self, idn: str, frontend: str, detector: str):
        self._idn_lbl.setText(idn)
        self._frontend_lbl.setText(frontend)
        self._detector_lbl.setText(detector)
        self._frontend_type = frontend
        is_linear = frontend == CoreDAQ.FRONTEND_LINEAR
        for combo, btn in zip(self._gain_combos, self._gain_btns):
            combo.setEnabled(is_linear); btn.setEnabled(is_linear)
        self._gain_set_all_combo.setEnabled(is_linear)
        self._gain_set_all_btn.setEnabled(is_linear)
        self._autogain_btn.setEnabled(is_linear)

    def _set_all_gains(self):
        value = self._gain_set_all_combo.currentData()
        for h, combo in enumerate(self._gain_combos, start=1):
            combo.setCurrentIndex(combo.findData(value))
            self._sig_set_gain.emit(h, value)

    def _do_autogain(self):
        self._autogain_btn.setEnabled(False)
        self._autogain_btn.setText("Autogain…")
        self._sig_autogain.emit()

    def _on_autogain_done(self, gains: list):
        self._autogain_btn.setText("Autogain")
        self._autogain_btn.setEnabled(self._frontend_type == CoreDAQ.FRONTEND_LINEAR)
        for combo, g in zip(self._gain_combos, gains):
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(g))
            combo.blockSignals(False)

    def _on_raw(self, power_w: list, mv: list, gains: list):
        """Throttled (~CoreDAQWorker.LABEL_HZ) numeric-label refresh — the fast
        per-sample data goes straight into the worker's ring buffer instead
        and is picked up by _update_live_plot() on its own timer."""
        for i, v in enumerate(power_w[:4]):
            self._power_lbls[i].setText(_fmt_power_w(v))
        for i in range(min(4, len(mv))):
            g = gains[i] if i < len(gains) else 0
            self._raw_lbls[i].setText(f"{mv[i]:.2f} mV  (G{g})")

    def _on_show_plot_toggled(self, checked: bool):
        """Show/hide the live plot and start/stop its redraw timer. While
        hidden, the timer is stopped so the tab does zero plotting work —
        polling and the numeric readouts keep running regardless."""
        self._plot_box.setVisible(checked)
        if checked:
            # Clear any stale curve left from a previous session so the
            # first frame starts clean, then begin redrawing.
            if HAS_PYQTGRAPH:
                for curve in self._live_curves:
                    curve.setData([], [])
            self._display_timer.start()
        else:
            self._display_timer.stop()

    def _update_live_plot(self):
        """Called by the independent ~30 Hz display timer — pulls whatever the
        worker's ring buffer currently holds. Decoupled from the acquisition
        rate: a slow serial link just means fewer new points per redraw, not
        a slower UI.

        The buffer is sized for up to ~1 kHz sampling, but the real poll rate
        is capped by serial round-trip time and is usually far slower — so we
        can't assume samples are 1 ms apart. Instead each sample carries its
        own time.monotonic() timestamp, and here we convert to "seconds ago"
        and drop anything older than the window so stale samples can't linger
        on screen mislabeled as recent.
        """
        if not HAS_PYQTGRAPH or not self._connected:
            return
        data, times, count = self._worker.get_display_data()
        if count <= 0:
            return
        times = times[:count]
        rel = times - time.monotonic()
        mask = rel >= -COREDAQ_PLOT_WINDOW_S
        rel = rel[mask]
        if rel.size == 0:
            return
        # Decimate before handing anything to pyqtgraph — a fast poll rate
        # can put several thousand points/channel in the window, and
        # setData() on the full array every redraw is real GUI-thread work
        # that scales with point count regardless of how fast the plot
        # itself renders.
        mask_idx = np.nonzero(mask)[0]
        if rel.size > self.MAX_PLOT_POINTS:
            step = rel.size // self.MAX_PLOT_POINTS
            rel = rel[::step]
            mask_idx = mask_idx[::step]
        for ch, curve in enumerate(self._live_curves):
            y_nw = data[ch, :count][mask_idx] * 1e9   # W -> nW
            curve.setData(rel, y_nw, connect='all')

    def _on_log(self, msg: str):
        self._log.append(msg)

    def _on_error(self, msg: str):
        self._log.append(f"<span style='color:{C_RED};'>ERROR: {msg}</span>")
        print(f"[CoreDAQ] FAILED to connect: {msg}" if not self._connected
              else f"[CoreDAQ] ERROR: {msg}")
        if self._autogain_btn.text() == "Autogain…":
            self._autogain_btn.setText("Autogain")
            self._autogain_btn.setEnabled(self._frontend_type == CoreDAQ.FRONTEND_LINEAR)

    def _on_op_done(self, op: str):
        if op == "connect":
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._port_edit.setEnabled(False)
            # Auto-show the live plot on every successful connect. setChecked
            # only fires _on_show_plot_toggled (which shows the box + starts
            # the redraw timer) when the box wasn't already checked; if it
            # was, _on_status (fired just before this) already resumed the
            # timer, so there's no gap either way.
            self._show_plot_chk.setChecked(True)
            print(f"[CoreDAQ] Connected — {self._idn_lbl.text()}")
        elif op == "disconnect":
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)
            self._port_edit.setEnabled(True)

    # ── Button actions ────────────────────────────────────────────────────────

    def _do_connect(self):
        port = self._port_edit.text().strip()
        save_connection_setting("coredaq_port", port)
        self._sig_connect.emit(port)

    def _do_disconnect(self):
        """Disconnect with instant UI feedback. Flipping the worker's
        `_polling` flag off here (a plain bool the worker thread also reads)
        stops the poll loop from re-arming right away, and updating the UI on
        this GUI thread means the button always responds immediately — even if
        the worker is momentarily busy in a serial call and can't process the
        queued do_disconnect for a few ms. The worker still performs the real
        port close() when it picks up the signal."""
        if hasattr(self, "_worker"):
            self._worker._polling = False
        self._on_status("DISCONNECTED")
        self._on_op_done("disconnect")
        self._sig_disconnect.emit()

    # ── Public API (used by DAQPanel sweep↔power logging) ──────────────────

    def latest_power_w(self):
        """Last cached (head1..head4) watts snapshot, or None if not connected."""
        return self._worker._last_power_w if self._connected else None

    def pause_polling(self, timeout_ms: int = 3000) -> bool:
        """Stops the live poll loop — must not run concurrently with a Fast
        Sweep's direct hardware access, since they share one serial
        connection. Waits (pumping the GUI event loop, not freezing it) for
        the worker thread to confirm polling has actually stopped, up to
        timeout_ms. Returns False on timeout — e.g. a poll call is wedged
        in a hardware read — in which case the caller must NOT touch the
        raw CoreDAQ handle, since the worker thread still owns it.
        Previously this used Qt.ConnectionType.BlockingQueuedConnection,
        which blocked the GUI thread with no timeout — a single stuck
        serial read froze the entire application, unrecoverable even via
        Task Manager (the thread was wedged in uninterruptible kernel I/O)."""
        if not self._connected:
            return True
        loop = QEventLoop()
        confirmed = False
        def _on_confirmed():
            nonlocal confirmed
            confirmed = True
            loop.quit()
        self._worker.poll_paused.connect(_on_confirmed)
        QTimer.singleShot(timeout_ms, loop.quit)
        self._sig_pause_poll.emit()
        loop.exec()
        self._worker.poll_paused.disconnect(_on_confirmed)
        return confirmed

    def resume_polling(self):
        if self._connected:
            self._sig_resume_poll.emit()

    def cleanup(self):
        if HAS_SERIAL and HAS_COREDAQ:
            self._sig_disconnect.emit()
            self._thread.quit()
            self._thread.wait(2000)


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class DetachedWindow(QMainWindow):
    """A panel popped out of the main tab bar into its own window."""

    def __init__(self, panel: QWidget, title: str, reattach_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"YPL — {title}")
        self._panel       = panel
        self._reattach_cb = reattach_cb

        # Give it its own status bar so panel status messages still work
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        btn = QPushButton("⬅  Reattach to main window")
        btn.setFixedHeight(26)
        btn.clicked.connect(self._do_reattach)
        lay.addWidget(btn)
        lay.addWidget(panel)

        # QTabWidget.removeTab() hides the page it removes (it's leaving the
        # internal QStackedWidget); that explicit-hidden state survives the
        # reparent into this window's layout, so the panel must be shown again.
        panel.setVisible(True)

        self.setCentralWidget(container)
        self._size_and_center()

    def _size_and_center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(MAIN_WINDOW_W, screen.width() - 40)
        h = min(MAIN_WINDOW_MAX_H, screen.height() - 60)
        self.resize(w, h)
        # Offset slightly so it doesn't sit exactly on top of the main window
        self.move(screen.center().x() - w // 2 + 40,
                  screen.top() + (screen.height() - h) // 2 + 40)

    def _do_reattach(self):
        self._reattach_cb(self._panel)
        self.close()

    def closeEvent(self, event):
        # Closing via X reattaches so cleanup always runs from the main window
        self._reattach_cb(self._panel)
        event.accept()


class UnifiedMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YPL Lab Control")

        self.daq_panel     = DAQPanel()
        self.itla_panel    = ITLAPanel()
        self.conex_panel   = ConexDualPanel()
        self.hp8168f_panel = HP8168FPanel()
        self.santec_panel  = SantecPanel()
        self.coredaq_panel = CoreDAQPanel()
        self.daq_panel.pin_view.set_coredaq_panel(self.coredaq_panel)
        self.itla_panel.set_coredaq_panel(self.coredaq_panel)
        self.hp8168f_panel.set_coredaq_panel(self.coredaq_panel)
        self.santec_panel.set_coredaq_panel(self.coredaq_panel)

        self._detached: dict[str, DetachedWindow] = {}

        self.tabs = QTabWidget()
        self.tabs.setCornerWidget(self._make_popout_btn(), Qt.Corner.TopRightCorner)

        self.tabs.addTab(self.daq_panel,     "DAQ Control")
        self.tabs.addTab(self.coredaq_panel, "CoreDAQ Power Meter")
        self.tabs.addTab(self.santec_panel,  "Santec Laser")
        self.tabs.addTab(self.conex_panel,   "CONEX Motor")
        self.tabs.addTab(self.itla_panel,    "ITLA Laser")
        self.tabs.addTab(self.hp8168f_panel, "HP-8168F Laser")

        # Recording bar sits above the tabs so it's visible no matter which
        # tab is active — recording spans every connected device, not just
        # the one currently in view.
        central = QWidget()
        central_lay = QVBoxLayout(central)
        central_lay.setContentsMargins(0, 0, 0, 0)
        central_lay.setSpacing(0)
        central_lay.addWidget(self._build_recorder_bar())
        central_lay.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self._recording    = False
        self._rec_t0       = 0.0
        self._rec_records  = []
        self._rec_plot_win = None
        self._last_global_csv = None
        self._rec_timer = QTimer()
        self._rec_timer.setInterval(GLOBAL_REC_TICK_MS)
        self._rec_timer.timeout.connect(self._global_record_tick)

        self._size_and_center()

    # ── Global combined recorder ────────────────────────────────────────────────

    def _build_recorder_bar(self):
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel("Global Recording (all connected devices):")
        lbl.setStyleSheet(f"color: {C_GRAY};")
        self._rec_btn = QPushButton("⏺  Start Recording")
        self._rec_btn.clicked.connect(self._toggle_global_recording)
        self._rec_status_lbl = QLabel("Idle")
        self._rec_status_lbl.setStyleSheet(f"color: {C_GRAY};")
        self._rec_save_btn = QPushButton("💾  Save Combined CSV…")
        self._rec_save_btn.setEnabled(False)
        self._rec_save_btn.clicked.connect(self._save_global_csv)
        lay.addWidget(lbl)
        lay.addWidget(self._rec_btn)
        lay.addSpacing(10)
        lay.addWidget(self._rec_status_lbl)
        lay.addStretch()
        lay.addWidget(self._rec_save_btn)
        self._rec_open_btn = QPushButton("📂 Open")
        self._rec_open_btn.setEnabled(False)
        self._rec_open_btn.setToolTip("Open the last-saved combined recording CSV")
        self._rec_open_btn.clicked.connect(lambda: open_saved_file(self._last_global_csv))
        lay.addWidget(self._rec_open_btn)
        return bar

    def _toggle_global_recording(self):
        if not self._recording:
            self._start_global_recording()
        else:
            self._stop_global_recording()

    def _start_global_recording(self):
        self._recording   = True
        self._rec_records = []
        self._rec_t0      = time.time()
        self._rec_btn.setText("⏹  Stop Recording")
        self._rec_btn.setStyleSheet(f"color: {C_RED};")
        self._rec_status_lbl.setText("● Recording — 0 samples")
        self._rec_status_lbl.setStyleSheet(f"color: {C_RED};")
        self._rec_save_btn.setEnabled(False)
        if self._rec_plot_win:
            self._rec_plot_win.close()
            self._rec_plot_win = None
        self._rec_timer.start()

    def _stop_global_recording(self):
        self._recording = False
        self._rec_timer.stop()
        self._rec_btn.setText("⏺  Start Recording")
        self._rec_btn.setStyleSheet("")
        n = len(self._rec_records)
        self._rec_status_lbl.setStyleSheet(f"color: {C_GRAY};")
        if n == 0:
            self._rec_status_lbl.setText("Idle — no data recorded (nothing was connected)")
            return
        self._rec_status_lbl.setText(f"Idle — {n} samples recorded")
        self._rec_save_btn.setEnabled(True)
        self._show_global_plot()

    def _global_record_tick(self):
        t = time.time() - self._rec_t0
        row = {"t": t}

        ao = self.daq_panel.pin_view.latest_ao_snapshot()
        if ao:
            label, unit, values = ao
            for i, v in enumerate(values):
                row[f"AO_{label}_pin{i:02d}_{unit}"] = v

        powers = self.coredaq_panel.latest_power_w()
        if powers:
            for i, p in enumerate(powers):
                row[f"CoreDAQ_head{i+1}_W"] = p

        itla = self.itla_panel.latest_reading()
        if itla:
            row["ITLA_wavelength_nm"] = itla["nm"]
            row["ITLA_power_mW"]     = itla["power_mw"]

        hp = self.hp8168f_panel.latest_reading()
        if hp and hp["wavelength_nm"] is not None:
            row["HP8168F_wavelength_nm"] = hp["wavelength_nm"]
            row["HP8168F_power_mW"]     = hp["power_mw"]

        santec = self.santec_panel.latest_reading()
        if santec and santec["wavelength_nm"] is not None:
            row["Santec_wavelength_nm"] = santec["wavelength_nm"]
            row["Santec_power_mW"]     = santec["power_mw"]

        self._rec_records.append(row)
        self._rec_status_lbl.setText(f"● Recording — {len(self._rec_records)} samples")

    def _series_keys(self):
        keys = set()
        for row in self._rec_records:
            keys.update(k for k in row.keys() if k != "t")
        return sorted(keys)

    def _show_global_plot(self):
        keys = self._series_keys()
        if not keys:
            return
        series = {}
        for k in keys:
            xs = [r["t"] for r in self._rec_records if k in r]
            ys = [r[k]   for r in self._rec_records if k in r]
            unit = k.rsplit("_", 1)[-1] if "_" in k else ""
            series[k] = (xs, ys, unit)
        win = MultiSeriesPlotWindow("Combined Recording", "Time", "s")
        win.show_data(series)
        win.move(self.x() + self.width() + 16, self.y() + 40)
        self._rec_plot_win = win

    def _save_global_csv(self):
        if not self._rec_records:
            return
        import datetime
        data_dir = DATA_DIR
        os.makedirs(data_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(data_dir, f"global_recording_{stamp}.csv")
        keys   = self._series_keys()
        header = ["t"] + keys
        rows = []
        for r in self._rec_records:
            rows.append([f"{r['t']:.3f}"] + [
                (f"{r[k]:.6g}" if k in r else "") for k in keys
            ])
        write_csv_with_metadata(
            fname, [f"global combined recording, {len(self._rec_records)} samples"],
            header, rows)
        print(f"[Global Recording] Saved {len(rows)} rows → {fname}")
        self.status_bar.showMessage(f"Saved {len(rows)} rows → {fname}", 5000)
        self._last_global_csv = fname
        self._rec_open_btn.setEnabled(True)

    # ── Pop-out ────────────────────────────────────────────────────────────────

    def _make_popout_btn(self):
        btn = QPushButton("⬡  Pop out tab")
        btn.setFixedHeight(24)
        btn.setToolTip("Open the active tab in its own window")
        btn.clicked.connect(self._popout_current)
        return btn

    def _popout_current(self):
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
        title = self.tabs.tabText(idx)

        # If already detached, just focus that window
        if title in self._detached:
            self._detached[title].raise_()
            self._detached[title].activateWindow()
            return

        panel = self.tabs.widget(idx)

        # Snapshot the DAQ stacked page so it survives reparenting
        daq_page = None
        if isinstance(panel, DAQPanel):
            daq_page = panel.stacked.currentIndex()

        self.tabs.removeTab(idx)

        win = DetachedWindow(panel, title,
                             reattach_cb=lambda p: self._reattach(p, title))

        # Restore stacked page after reparent (Qt resets it to 0)
        if daq_page is not None:
            panel.stacked.setCurrentIndex(daq_page)

        win.show()
        self._detached[title] = win

        if self.tabs.count() == 0:
            self.status_bar.showMessage(
                "All tabs detached — use Reattach to bring them back")

    def _reattach(self, panel: QWidget, title: str):
        self._detached.pop(title, None)
        order = {"DAQ Control": 0, "CoreDAQ Power Meter": 1, "Santec Laser": 2,
                  "CONEX Motor": 3, "ITLA Laser": 4, "HP-8168F Laser": 5}
        slot = order.get(title, self.tabs.count())
        self.tabs.insertTab(slot, panel, title)
        self.tabs.setCurrentIndex(slot)
        self.raise_()
        self.activateWindow()

    # ── Sizing ─────────────────────────────────────────────────────────────────

    def _size_and_center(self):
        """Open at a fixed sensible size — fits both tabs, never auto-resizes."""
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(MAIN_WINDOW_W, screen.width() - 40)
        h = min(MAIN_WINDOW_MAX_H, screen.height() - 60)
        self.resize(w, h)
        self.move(screen.center().x() - w // 2,
                  screen.top() + (screen.height() - h) // 2)

    def closeEvent(self, event):
        # Pull detached windows back in so cleanup runs cleanly
        for win in list(self._detached.values()):
            win.close()
        self.daq_panel.cleanup()
        self.itla_panel.cleanup()
        self.conex_panel.cleanup()
        self.hp8168f_panel.cleanup()
        self.santec_panel.cleanup()
        self.coredaq_panel.cleanup()
        event.accept()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = UnifiedMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()