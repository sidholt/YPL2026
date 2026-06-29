"""
unified_lab_gui.py — YPL Lab Control
One window, two tabs:
  • DAQ Control  — UEI PowerDNA cards + Moku:Go + Guardian + Pro Micro
  • ITLA Laser   — Emcore TTX ITLA controller

All-PyQt6 (the old itla_gui.py was PySide6 and has been ported).
Requires: PyQt6, pyqtgraph, numpy; optional: UeiDaq, moku, pyserial, hardware.itla
Run:      python unified_lab_gui.py
"""

import os
os.environ["MOKU_CLI_PATH"] = r"C:\Program Files\Liquid Instruments\Moku CLI\mokucli.exe"

import sys
import math
import time
import subprocess
import socket
import json
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QScrollArea, QFrame, QSizePolicy,
    QDoubleSpinBox, QSlider, QStackedWidget, QStatusBar, QGroupBox,
    QSpinBox, QComboBox, QLineEdit, QCheckBox, QTabWidget, QTextEdit,
    QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QObject
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
    print("[WARNING] pyserial not found — Pro Micro disabled. Run: uv pip install pyserial")

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
# DAQ CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

CUBE_IP = "172.28.2.4"
MOKU_IP = "172.28.5.6"

NUM_PINS = 8

CARDS = {
    0: {"label": "DEV0  —  CURRENT", "mode": "current", "dev": "Dev0", "available": True},
    1: {"label": "DEV1  —  CURRENT", "mode": "current", "dev": "Dev1", "available": True},
    2: {"label": "DEV2  —  VOLTAGE", "mode": "voltage", "dev": "Dev2", "available": True},
}

MODE_RANGES = {
    "voltage": (-10.0, 10.0, "V",   -1000, 1000),
    "current": (  0.0, 20.0, "mA",      0, 2000),
}

RAMP_TICK_MS = 20
SLEW_RATE_V  = 5.0
SLEW_RATE_MA = 10.0
STEP_V       = SLEW_RATE_V  * (RAMP_TICK_MS / 1000.0)
STEP_MA      = SLEW_RATE_MA * (RAMP_TICK_MS / 1000.0)

# Window sizing — computed once at startup, never auto-resized afterwards
MAIN_WINDOW_W     = 800
MAIN_WINDOW_MAX_H = 1000

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
PROMICRO_PLOT_WINDOW_S = 10.0

PROMICRO_PORT = "COM11"
PROMICRO_BAUD = 9600

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


class ProMicroWorker(QObject):
    sample_ready    = pyqtSignal(float)         # A0 voltage (V)
    current_ready   = pyqtSignal(float)         # A1 current (mA)
    error           = pyqtSignal(str)
    connected       = pyqtSignal()
    disconnected    = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._port    = None
        self._running = False

    def start(self, port: str = PROMICRO_PORT):
        self.stop()
        if not HAS_SERIAL:
            self.error.emit("pyserial not installed")
            return
        try:
            self._port = serial.Serial(port, PROMICRO_BAUD, timeout=1.0)
            self._port.reset_input_buffer()
            self._running = True
            self.connected.emit()
            print(f"[ProMicro] Connected on {port}")
        except Exception as e:
            self.error.emit(f"Cannot open {port}: {e}")
            self._port = None
            return
        import threading
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        """Parse lines like: 'A0: 1.2345 V  A1: 8.7654 mA'"""
        while self._running and self._port:
            try:
                line = self._port.readline().decode("utf-8", errors="ignore").strip()
                if not line.startswith("A0:"):
                    continue
                parts = line.split()
                try:
                    self.sample_ready.emit(float(parts[1]))
                except (ValueError, IndexError):
                    pass
                try:
                    a1_idx = parts.index("A1:")
                    self.current_ready.emit(float(parts[a1_idx + 1]))
                except (ValueError, IndexError):
                    pass
            except Exception as e:
                if self._running:
                    self.error.emit(str(e))
                break
        self.disconnected.emit()

    def stop(self):
        self._running = False
        try:
            if self._port: self._port.close()
        except Exception:
            pass
        self._port = None


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
        self._ip_edit = QLineEdit(MOKU_IP)
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
        self.values     = [0.0] * NUM_PINS
        self._targets   = [0.0] * NUM_PINS
        min_val, max_val, unit, _, _ = MODE_RANGES[self.mode]
        self.min_val, self.max_val, self.unit = min_val, max_val, unit
        self._step = STEP_V if self.mode == "voltage" else STEP_MA

        self._timer = QTimer()
        self._timer.setInterval(RAMP_TICK_MS)
        self._timer.timeout.connect(self._ramp_tick)

        self._sweep_steps         = []
        self._sweep_pin           = 0
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
        print(f"Connecting: pdna://{CUBE_IP}/{self.dev}/Ao0:{NUM_PINS-1}, "
              f"mode: {self.mode}, range: {self.min_val} to {self.max_val}")
        if self.mode == "voltage":
            self.session.CreateAOChannel(
                f"pdna://{CUBE_IP}/{self.dev}/Ao0:{NUM_PINS-1}",
                self.min_val, self.max_val)
        else:
            self.session.CreateAOCurrentChannel(
                f"pdna://{CUBE_IP}/{self.dev}/Ao0:{NUM_PINS-1}",
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
        except Exception:
            self._timer.stop()
            return
        if next_vals == self._targets:
            self._timer.stop()

    def write(self, values: list):
        if not self.connected:
            raise RuntimeError("Session not connected")
        scaled = [v / 1000.0 for v in values] if self.mode == "current" else values
        self.writer.WriteSingleScan(scaled)
        self.values = list(values)

    def start_wave(self, pin: int, waveform: str, freq: float,
                   amplitude: float, offset: float, tick_ms: int,
                   callback=None):
        self.stop_wave()
        self._wave_pin       = pin
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
        targets[self._wave_pin] = val
        try:
            self.write(targets)
        except Exception:
            self.stop_wave()
            return
        self._wave_t += self._wave_tick_ms / 1000.0
        if self._wave_callback:
            self._wave_callback(self._wave_pin, val)

    def stop_wave(self):
        if hasattr(self, '_wave_timer') and self._wave_timer.isActive():
            self._wave_timer.stop()
        self._wave_callback = None

    def start_sweep(self, pin: int, start: float, stop: float,
                    steps: int, dwell_ms: int, callback, done_callback=None):
        self.stop_sweep()
        self._sweep_pin           = pin
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
        targets[self._sweep_pin]   = target_val
        self._sweep_pending_target = target_val
        self.ramp_to(targets)
        self._sweep_poll = QTimer()
        self._sweep_poll.setInterval(RAMP_TICK_MS)
        self._sweep_poll.timeout.connect(self._sweep_check_arrived)
        self._sweep_poll.start()

    def _sweep_check_arrived(self):
        if abs(self.values[self._sweep_pin] - self._sweep_pending_target) <= self._step:
            self._sweep_poll.stop()
            total = len(self._sweep_steps)
            idx   = self._sweep_step_idx
            if self._sweep_callback:
                self._sweep_callback(
                    self._sweep_pin, self.values[self._sweep_pin], idx + 1, total)
            self._sweep_step_idx += 1
            self._sweep_timer.start(self._sweep_dwell_ms)

    def zero(self):
        self.stop_sweep()
        self.ramp_to([0.0] * NUM_PINS)

    def zero_immediate(self):
        self.stop_sweep()
        self.stop_wave()
        self._timer.stop()
        self._targets = [0.0] * NUM_PINS
        try:
            self.write([0.0] * NUM_PINS)
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

    def __init__(self, card_label: str, mode: str, parent=None):
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
        for i in range(NUM_PINS):
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        pin_container = QWidget()
        self.pin_layout = QVBoxLayout(pin_container)
        self.pin_layout.setSpacing(2)
        self.pin_layout.setContentsMargins(4, 4, 4, 4)

        col_row = QHBoxLayout()
        for text, width in [("Pin", 50), ("Value", 120), ("Slider", -1), ("", 60), ("Readback", 90)]:
            lbl = QLabel(text)
            if width > 0: lbl.setFixedWidth(width)
            col_row.addWidget(lbl)
        self.pin_layout.addLayout(col_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        self.pin_layout.addWidget(sep2)

        self.spinboxes, self.sliders = [], []
        self._readback_lbls = []

        for i in range(NUM_PINS):
            rl  = QHBoxLayout()
            rl.setSpacing(6)
            lbl = QLabel(f"Pin {i:02d}")
            lbl.setFixedWidth(50)
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
            rb_lbl.setToolTip("Guardian ADC readback (Dev2 only)")
            rb_lbl.setVisible(False)

            rl.addWidget(lbl); rl.addWidget(sb)
            rl.addWidget(sl, stretch=1); rl.addWidget(set_btn)
            rl.addWidget(rb_lbl)
            self.spinboxes.append(sb)
            self.sliders.append(sl)
            self._readback_lbls.append(rb_lbl)
            self.pin_layout.addLayout(rl)

        self.pin_layout.addStretch()
        scroll.setWidget(pin_container)
        root.addWidget(scroll, stretch=1)

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
        row1.addWidget(QLabel("Pin:"))
        self.sweep_pin_combo = QComboBox()
        for i in range(NUM_PINS):
            self.sweep_pin_combo.addItem(f"Pin {i:02d}", i)
        self.sweep_pin_combo.setFixedWidth(80)
        row1.addWidget(self.sweep_pin_combo)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Start:"))
        self.sweep_start = NoScrollDoubleSpinBox()
        self.sweep_start.setDecimals(3)
        self.sweep_start.setFixedWidth(90)
        row1.addWidget(self.sweep_start)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Stop:"))
        self.sweep_stop = NoScrollDoubleSpinBox()
        self.sweep_stop.setDecimals(3)
        self.sweep_stop.setFixedWidth(90)
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
        self.sweep_stepsize_sb = NoScrollDoubleSpinBox()
        self.sweep_stepsize_sb.setDecimals(4)
        self.sweep_stepsize_sb.setRange(0.0001, 100.0)
        self.sweep_stepsize_sb.setValue(1.0)
        self.sweep_stepsize_sb.setFixedWidth(90)
        self.sweep_stepsize_sb.setVisible(False)
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

        root.addWidget(sweep_group)

        self.sweep_start.valueChanged.connect(self._update_sweep_derived)
        self.sweep_stop.valueChanged.connect(self._update_sweep_derived)
        self.sweep_steps_sb.valueChanged.connect(self._update_sweep_derived)
        self.sweep_stepsize_sb.valueChanged.connect(self._update_sweep_derived)

        wave_group = QGroupBox("Waveform Output")
        wg = QVBoxLayout(wave_group)
        wg.setSpacing(6)

        wrow1 = QHBoxLayout()
        wrow1.addWidget(QLabel("Pin:"))
        self.wave_pin_combo = QComboBox()
        for i in range(NUM_PINS):
            self.wave_pin_combo.addItem(f"Pin {i:02d}", i)
        self.wave_pin_combo.setFixedWidth(80)
        wrow1.addWidget(self.wave_pin_combo)
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
        wrow2.addWidget(self.wave_freq_sb)
        wrow2.addSpacing(10)
        wrow2.addWidget(QLabel("Amplitude:"))
        self.wave_amp_sb = NoScrollDoubleSpinBox()
        self.wave_amp_sb.setDecimals(3)
        self.wave_amp_sb.setValue(1.0)
        self.wave_amp_sb.setFixedWidth(90)
        wrow2.addWidget(self.wave_amp_sb)
        wrow2.addSpacing(10)
        wrow2.addWidget(QLabel("Offset:"))
        self.wave_offset_sb = NoScrollDoubleSpinBox()
        self.wave_offset_sb.setDecimals(3)
        self.wave_offset_sb.setValue(0.0)
        self.wave_offset_sb.setFixedWidth(90)
        wrow2.addWidget(self.wave_offset_sb)
        wrow2.addStretch()
        wg.addLayout(wrow2)

        wrow3 = QHBoxLayout()
        wrow3.addWidget(QLabel("Tick (ms):"))
        self.wave_tick_sb = NoScrollSpinBox()
        self.wave_tick_sb.setRange(5, 1000)
        self.wave_tick_sb.setValue(20)
        self.wave_tick_sb.setFixedWidth(70)
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
        self._rec_src_combo.addItem("Pro Micro", "promicro")
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
        self._last_pm_v = 0.0

        # AO-333 Guardian readback worker (Dev2 only)
        self._guardian_thread = QThread()
        self._guardian_worker = AO333ReadbackWorker()
        self._guardian_worker.moveToThread(self._guardian_thread)
        self._guardian_thread.start()
        self._guardian_worker.readback_ready.connect(self._on_guardian_readback)
        self._guardian_worker.error.connect(
            lambda msg: print(f"[AO333] {msg}"))
        self._guardian_values: list = [0.0] * NUM_PINS

        # ── Pro Micro live plot ──
        self._pm_plot_group = QGroupBox("Pro Micro — Live Readback")
        pg2 = QVBoxLayout(self._pm_plot_group)
        pg2.setContentsMargins(4, 4, 4, 4)

        pm_ctrl = QHBoxLayout()
        pm_ctrl.addWidget(QLabel("Port:"))
        self._pm_port_edit = QLineEdit(PROMICRO_PORT)
        self._pm_port_edit.setFixedWidth(80)
        pm_ctrl.addWidget(self._pm_port_edit)
        self._pm_connect_btn    = QPushButton("Connect")
        self._pm_disconnect_btn = QPushButton("✕")
        self._pm_connect_btn.setFixedWidth(80)
        self._pm_disconnect_btn.setFixedSize(24, 24)
        self._pm_disconnect_btn.setVisible(False)
        self._pm_status_lbl = QLabel("○")
        self._pm_status_lbl.setFixedWidth(14)
        self._pm_val_lbl = QLabel("— V")
        self._pm_val_lbl.setMinimumWidth(80)
        self._pm_ma_lbl = QLabel("— mA")
        self._pm_ma_lbl.setMinimumWidth(80)
        self._pm_connect_btn.clicked.connect(self._pm_connect)
        self._pm_disconnect_btn.clicked.connect(self._pm_disconnect)
        pm_ctrl.addWidget(self._pm_status_lbl)
        pm_ctrl.addWidget(self._pm_connect_btn)
        pm_ctrl.addWidget(self._pm_disconnect_btn)
        pm_ctrl.addSpacing(10)
        pm_ctrl.addWidget(self._pm_val_lbl)
        pm_ctrl.addWidget(self._pm_ma_lbl)
        pm_ctrl.addStretch()
        pg2.addLayout(pm_ctrl)

        if HAS_PYQTGRAPH:
            self._pm_plot = pg.PlotWidget()
            self._pm_plot.setLabel('left',   'Voltage', units='V')
            self._pm_plot.setLabel('bottom', 'Time',    units='s')
            self._pm_plot.getAxis('left').enableAutoSIPrefix(False)
            self._pm_plot.setMinimumHeight(140)
            self._pm_curve = self._pm_plot.plot(
                [], [], pen=pg.mkPen('#00FF88', width=2))
            pg2.addWidget(self._pm_plot)

            self._pm_ma_plot = pg.PlotWidget()
            self._pm_ma_plot.setLabel('left',   'Current', units='mA')
            self._pm_ma_plot.setLabel('bottom', 'Time',    units='s')
            self._pm_ma_plot.getAxis('left').enableAutoSIPrefix(False)
            self._pm_ma_plot.setMinimumHeight(140)
            self._pm_ma_curve = self._pm_ma_plot.plot(
                [], [], pen=pg.mkPen(C_RED, width=2))
            pg2.addWidget(self._pm_ma_plot)
        else:
            self._pm_plot     = None
            self._pm_curve    = None
            self._pm_ma_plot  = None
            self._pm_ma_curve = None

        self._pm_plot_group.setVisible(False)
        root.addWidget(self._pm_plot_group)

        self._pm_t   = 0.0
        self._pm_ts  = []
        self._pm_vs  = []
        self._pm_ma_ts = []
        self._pm_ma_vs = []

        # Pro Micro worker + thread
        self._pm_thread = QThread()
        self._pm_worker = ProMicroWorker()
        self._pm_worker.moveToThread(self._pm_thread)
        self._pm_thread.start()
        self._pm_worker.sample_ready.connect(self._on_pm_sample)
        self._pm_worker.current_ready.connect(self._on_pm_current)
        self._pm_worker.connected.connect(self._pm_on_connected)
        self._pm_worker.disconnected.connect(self._pm_on_disconnected)
        self._pm_worker.error.connect(
            lambda msg: print(f"[ProMicro] {msg}"))

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

        if self._pm_curve and self._pm_ts:
            self._pm_curve.setData(self._pm_ts, self._pm_vs)
            x_max = self._pm_ts[-1]
            self._pm_plot.setXRange(
                x_max - PROMICRO_PLOT_WINDOW_S, x_max, padding=0)

        if self._pm_ma_curve and self._pm_ma_ts:
            self._pm_ma_curve.setData(self._pm_ma_ts, self._pm_ma_vs)
            x_max = self._pm_ma_ts[-1]
            self._pm_ma_plot.setXRange(
                x_max - PROMICRO_PLOT_WINDOW_S, x_max, padding=0)

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
        self._cmp_win = LiveComparisonPlot(label, cs.mode)

        src = self._cmp_src_combo.currentData()
        src_names = {"moku": "Moku Ch1", "guardian": "Guardian ADC",
                     "promicro": "Pro Micro"}
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

    def _pm_connect(self):
        port = self._pm_port_edit.text().strip()
        self._pm_connect_btn.setEnabled(False)
        self._pm_connect_btn.setText("…")
        self._pm_t = 0.0
        self._pm_ts = []; self._pm_vs = []
        self._pm_ma_ts = []; self._pm_ma_vs = []
        if HAS_PYQTGRAPH:
            if self._pm_curve:    self._pm_curve.setData([], [])
            if self._pm_ma_curve: self._pm_ma_curve.setData([], [])
        QTimer.singleShot(0, lambda: self._pm_worker.start(port))

    def _pm_disconnect(self):
        QTimer.singleShot(0, self._pm_worker.stop)

    def _pm_on_connected(self):
        self._pm_status_lbl.setText("●")
        self._pm_status_lbl.setStyleSheet(f"color: {C_GREEN};")
        self._pm_connect_btn.setVisible(False)
        self._pm_disconnect_btn.setVisible(True)
        self._pm_port_edit.setEnabled(False)
        self._pm_connect_btn.setEnabled(True)
        self._pm_connect_btn.setText("Connect")

    def _pm_on_disconnected(self):
        self._pm_status_lbl.setText("○")
        self._pm_status_lbl.setStyleSheet("")
        self._pm_connect_btn.setVisible(True)
        self._pm_disconnect_btn.setVisible(False)
        self._pm_port_edit.setEnabled(True)
        self._pm_val_lbl.setText("— V")

    def _on_pm_sample(self, v: float):
        self._last_pm_v = v
        self._pm_val_lbl.setText(f"{v:.4f} V")

        if (self._cmp_src_combo.currentData() == "promicro"
                and self._cmp_win and self._cmp_win.isVisible()
                and self.card_session
                and self.card_session.mode == "voltage"):
            self._push_comparison(v, dt=0.2)

        if (self._recording and self.card_session
                and self._rec_src_combo.currentData() == "promicro"):
            self._append_record(v, dt=0.2)

        if not HAS_PYQTGRAPH or self._pm_curve is None:
            return
        self._pm_t += 0.2
        self._pm_ts.append(self._pm_t)
        self._pm_vs.append(v)
        cutoff = self._pm_t - PROMICRO_PLOT_WINDOW_S
        while self._pm_ts and self._pm_ts[0] < cutoff:
            self._pm_ts.pop(0); self._pm_vs.pop(0)
        self._plot_dirty = True

    def _on_pm_current(self, ma: float):
        self._pm_ma_lbl.setText(f"{ma:.3f} mA")

        if (self._cmp_src_combo.currentData() == "promicro"
                and self._cmp_win and self._cmp_win.isVisible()
                and self.card_session
                and self.card_session.mode == "current"):
            self._push_comparison(ma, dt=0.2)

        if not HAS_PYQTGRAPH or self._pm_ma_curve is None:
            return
        self._pm_ma_ts.append(self._pm_t)
        self._pm_ma_vs.append(ma)
        cutoff = self._pm_t - PROMICRO_PLOT_WINDOW_S
        while self._pm_ma_ts and self._pm_ma_ts[0] < cutoff:
            self._pm_ma_ts.pop(0); self._pm_ma_vs.pop(0)
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

    def load_card(self, cs: CardSession):
        self.card_session = cs
        self.card_title.setText(CARDS[cs.card_index]["label"].split("  —  ")[0])
        self.badge.setText(cs.mode.upper())
        _, _, _, s_min, s_max = MODE_RANGES[cs.mode]
        self._syncing = True
        for i in range(NUM_PINS):
            self.spinboxes[i].setMinimum(cs.min_val)
            self.spinboxes[i].setMaximum(cs.max_val)
            self.spinboxes[i].setSuffix(f" {cs.unit}")
            self.sliders[i].setMinimum(s_min)
            self.sliders[i].setMaximum(s_max)
            self.spinboxes[i].setValue(cs.values[i])
            self.sliders[i].setValue(int(cs.values[i] * 100))
        self._syncing = False
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

        # Guardian readback — only for voltage card (Dev2 / AO-333)
        is_voltage = cs.mode == "voltage"
        for lbl in self._readback_lbls:
            lbl.setVisible(is_voltage)
            lbl.setText("—")
        self._guardian_values = [0.0] * NUM_PINS
        self._pm_plot_group.setVisible(True)
        if HAS_PYQTGRAPH:
            if self._pm_plot:    self._pm_plot.setVisible(is_voltage)
            if self._pm_ma_plot: self._pm_ma_plot.setVisible(not is_voltage)
        self._rec_src_row_widget.setVisible(is_voltage)

        self._cmp_src_combo.blockSignals(True)
        self._cmp_src_combo.clear()
        self._cmp_src_combo.addItem("Moku",      "moku")
        if is_voltage:
            self._cmp_src_combo.addItem("Guardian",  "guardian")
        self._cmp_src_combo.addItem("Pro Micro", "promicro")
        self._cmp_src_combo.blockSignals(False)

        if self._cmp_win and self._cmp_win.isVisible():
            self._cmp_win.close()
        self._cmp_win = None
        self._last_moku_v = 0.0
        self._last_guardian_v = 0.0
        self._last_pm_v = 0.0

        if is_voltage:
            QTimer.singleShot(0, self._guardian_worker.start)
        else:
            QTimer.singleShot(0, self._guardian_worker.stop)

    def _on_guardian_readback(self, values: list):
        self._guardian_values = values
        self._last_guardian_v = float(np.mean(values[:NUM_PINS]))
        for i, v in enumerate(values[:NUM_PINS]):
            self._readback_lbls[i].setText(f"{v:+.{READBACK_DECIMALS}f}V")

        if (self._cmp_src_combo.currentData() == "guardian"
                and self._cmp_win and self._cmp_win.isVisible()
                and self.card_session):
            pin = self._cmp_win.get_pin()
            v   = values[pin] if pin < len(values) else 0.0
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
        data_dir = r"C:\Users\sih93\Desktop\Sid\GUI\data"
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
                "promicro":  "promicro_V",
            }.get(src, "readback_V")

        fname    = os.path.join(data_dir, f"{dev}_{mode}_{src}_{stamp}.csv")
        pin_hdrs = [f"pin{i:02d}_{unit}" for i in range(NUM_PINS)]
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

    def _start_sweep(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            pin      = self.sweep_pin_combo.currentData()
            start    = self.sweep_start.value()
            stop     = self.sweep_stop.value()
            steps    = self._compute_steps()
            dwell_ms = self.sweep_dwell_sb.value()
            cs.start_sweep(pin, start, stop, steps, dwell_ms,
                           self._on_sweep_step, self._on_sweep_done)
            self.sweep_run_btn.setEnabled(False)
            self.sweep_stop_btn.setEnabled(True)
            self._status(f"Sweep running — Pin {pin:02d}  {start:.3f} → "
                         f"{stop:.3f} {cs.unit}  {steps} steps")
        except Exception as e:
            self._status(f"Sweep error: {e}")

    def _stop_sweep(self):
        if self.card_session: self.card_session.stop_sweep()
        self.sweep_run_btn.setEnabled(True)
        self.sweep_stop_btn.setEnabled(False)
        self._status("Sweep stopped")

    def _on_sweep_step(self, pin, value, step, total):
        self._syncing = True
        self.spinboxes[pin].setValue(value)
        self.sliders[pin].setValue(int(value * 100))
        self._syncing = False
        cs = self.card_session
        self._status(f"Sweep — Pin {pin:02d} at {value:.3f} "
                     f"{cs.unit if cs else ''}  (step {step}/{total})")

    def _on_sweep_done(self):
        self.sweep_run_btn.setEnabled(True)
        self.sweep_stop_btn.setEnabled(False)
        self._status("Sweep complete")

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
            values = [sb.value() for sb in self.spinboxes]
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
            for sb in self.spinboxes: sb.setValue(0.0)
            for sl in self.sliders:   sl.setValue(0)
            self._syncing = False
            if self._ramp_chk.isChecked():
                cs.zero()
                self._status("Ramping all pins to zero")
            else:
                def do_zero():
                    try:
                        cs.write([0.0] * NUM_PINS)
                    except Exception as e:
                        print(f"[Zero] {e}")
                t = QThread(self)
                t.run = do_zero
                t.start()
                self._status("Instant zero all pins")
        except Exception as e:
            self._status(f"Error: {e}")

    def _start_wave(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected: cs.connect()
            pin       = self.wave_pin_combo.currentData()
            waveform  = self.wave_type_combo.currentData()
            freq      = self.wave_freq_sb.value()
            amplitude = self.wave_amp_sb.value()
            offset    = self.wave_offset_sb.value()
            tick_ms   = self.wave_tick_sb.value()
            cs.start_wave(pin, waveform, freq, amplitude, offset, tick_ms,
                          self._on_wave_tick)
            self.wave_run_btn.setEnabled(False)
            self.wave_stop_btn.setEnabled(True)
            self._status(f"Wave running — Pin {pin:02d}  {waveform}  {freq}Hz  "
                         f"amp={amplitude} {cs.unit}  offset={offset} {cs.unit}")
        except Exception as e:
            self._status(f"Wave error: {e}")

    def _stop_wave(self):
        if self.card_session: self.card_session.stop_wave()
        self.wave_run_btn.setEnabled(True)
        self.wave_stop_btn.setEnabled(False)
        self._status("Wave stopped")

    def _on_wave_tick(self, pin, value):
        self._syncing = True
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

        self._status(f"Connecting to {CARDS[idx]['label']}…")

        def do_connect():
            try:
                cs.connect()
                QTimer.singleShot(0, lambda: self._card_connected(idx))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._status(
                    f"Connection error: {e}"))

        t = QThread(self)
        self._connect_threads = getattr(self, '_connect_threads', [])
        self._connect_threads.append(t)
        t.run = do_connect        # type: ignore[method-assign]
        t.finished.connect(lambda: self._connect_threads.remove(t)
                           if t in self._connect_threads else None)
        t.start()

    def _card_connected(self, idx: int):
        cs = self.card_sessions[idx]
        self._status(
            f"Connected — {CARDS[idx]['label']} — "
            f"{cs.min_val} to {cs.max_val} {cs.unit}")
        self.pin_view.load_card(cs)
        self.stacked.setCurrentIndex(1)
        self.daq_box.refresh()

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
        self.pin_view._pm_worker.stop()
        self.pin_view._pm_thread.quit()
        self.pin_view._pm_thread.wait(2000)
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
            if   op == "connect":     self._do_connect(**self._args)
            elif op == "on":          self._do_on(**self._args)
            elif op == "off":         self._do_off()
            elif op == "sweep":       self._do_sweep(**self._args)
            elif op == "diagnostics": self._do_diagnostics()
            elif op == "dither":      self._do_dither(**self._args)
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

        f_lo = C_NM_GHZ / max(nm_start, nm_stop)
        f_hi = C_NM_GHZ / min(nm_start, nm_stop)

        targets_ghz = []
        f = f_lo
        while f <= f_hi + 1e-6:
            targets_ghz.append(f)
            f += step_ghz

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
        self.spin_port.setValue(15)
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

        self.btn_on = QPushButton("Turn Laser On")
        self.btn_on.setFixedHeight(32)
        self.btn_on.clicked.connect(self.do_on)
        cg2.addWidget(self.btn_on, 5, 0, 1, 2)

        self.btn_off = QPushButton("Turn Laser Off")
        self.btn_off.setFixedHeight(32)
        self.btn_off.clicked.connect(self.do_off)
        cg2.addWidget(self.btn_off, 5, 2, 1, 2)

        self.lbl_status = QLabel("LASER IS OFF")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.lbl_status.font()
        font.setBold(True)
        font.setPointSize(13)
        self.lbl_status.setFont(font)
        cg2.addWidget(self.lbl_status, 6, 0, 1, 4)

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
        sg.addWidget(self.spin_sw_start, 0, 1)

        sg.addWidget(QLabel("Stop (nm):"), 0, 2)
        self.spin_sw_stop = NoScrollDoubleSpinBox()
        self.spin_sw_stop.setRange(1529.0, 1567.1)
        self.spin_sw_stop.setValue(1554.0)
        self.spin_sw_stop.setDecimals(3)
        self.spin_sw_stop.setSingleStep(1.0)
        sg.addWidget(self.spin_sw_stop, 0, 3)

        sg.addWidget(QLabel("Step (GHz):"), 1, 0)
        self.spin_sw_step = NoScrollDoubleSpinBox()
        self.spin_sw_step.setRange(0.1, 500.0)
        self.spin_sw_step.setValue(100.0)
        self.spin_sw_step.setSingleStep(50.0)
        self.spin_sw_step.setDecimals(1)
        sg.addWidget(self.spin_sw_step, 1, 1)

        sg.addWidget(QLabel("Dwell (s):"), 1, 2)
        self.spin_dwell = NoScrollDoubleSpinBox()
        self.spin_dwell.setRange(0.1, 60.0)
        self.spin_dwell.setValue(1.0)
        self.spin_dwell.setSingleStep(0.5)
        sg.addWidget(self.spin_dwell, 1, 3)

        self.btn_sweep = QPushButton("Start Sweep")
        self.btn_sweep.clicked.connect(self.do_sweep)
        sg.addWidget(self.btn_sweep, 2, 0, 1, 4)

        top.addWidget(sw_box)

        # ── Dither ──────────────────────────────────────────────────────────
        dith_box = QGroupBox("Dither  (laser must be locked to channel first)")
        dg2 = QGridLayout(dith_box)

        dg2.addWidget(QLabel("Rate (kHz):"), 0, 0)
        self.spin_dith_rate = NoScrollSpinBox()
        self.spin_dith_rate.setRange(10, 200)
        self.spin_dith_rate.setValue(100)
        self.spin_dith_rate.setSingleStep(10)
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
        busy      = state in ("warming", "locking")
        if connected and not busy:
            self._diag_timer.start()
        else:
            self._diag_timer.stop()

        self.btn_connect.setEnabled(not connected)
        self.btn_on.setEnabled(connected and not busy and state != "on")
        self.btn_off.setEnabled(connected and not busy and state == "on")
        self.btn_sweep.setEnabled(connected and not busy)
        self.btn_diag.setEnabled(connected and not busy)
        self.btn_dith_sbs.setEnabled(connected and not busy)
        self.btn_dith_txtrace.setEnabled(connected and not busy)
        self.btn_dith_off.setEnabled(connected and not busy)
        self.spin_port.setEnabled(not connected)

        labels = {
            "disconnected": ("NOT CONNECTED",    C_TEXT),
            "warming":      ("WARMING UP...",    C_ORANGE),
            "locking":      ("LOCKING FREQ...",  C_ORANGE),
            "off":          ("LASER IS OFF",     C_TEXT),
            "on":           ("LASER IS ON",      C_RED),
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
        pass

    # ── Button handlers ───────────────────────────────────────────────────────

    def do_connect(self):
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
        self._set_state("locking")
        self.worker.run_op("sweep",
            nm_start=nm_start, nm_stop=nm_stop,
            step_ghz=self.spin_sw_step.value(),
            dwell_s=self.spin_dwell.value(),
            mw=self.spin_mw.value(),
            fcf1=self._fcf1, fcf2=self._fcf2,
            itla_grid=self._grid, ui_grid=self._ui_grid)

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

    def __init__(self):
        super().__init__()
        self._motor = None
        self._rm    = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _query(self, cmd: str) -> str:
        return self._motor.query(cmd)

    def _write(self, cmd: str):
        self._motor.write(cmd)

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
            if self._rm is None:
                self._rm = pyvisa.ResourceManager()
            address = f"ASRL{port}::INSTR"
            self._motor = self._rm.open_resource(address)
            self._motor.baud_rate       = 921600
            self._motor.data_bits       = 8
            self._motor.parity          = pyvisa.constants.Parity.none
            self._motor.stop_bits       = pyvisa.constants.StopBits.one
            self._motor.flow_control    = pyvisa.constants.ControlFlow.xon_xoff
            self._motor.write_termination = '\r\n'
            self._motor.read_termination  = '\r\n'
            self._motor.timeout         = 5000
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
            resources = self._rm.list_resources()
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
                self._motor.close()
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

    def __init__(self, parent=None):
        super().__init__(parent)

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

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Left: Connection ──────────────────────────────────────────────────
        conn_box = QGroupBox("Connection")
        conn_lay = QGridLayout(conn_box)

        conn_lay.addWidget(QLabel("Motor Status:"), 0, 0)
        self._status_lbl = QLabel("DISCONNECTED")
        self._status_lbl.setStyleSheet(f"color: {C_RED}; font-weight: bold;")
        conn_lay.addWidget(self._status_lbl, 0, 1)

        conn_lay.addWidget(QLabel("COM Port #:"), 1, 0)
        self._port_spin = NoScrollSpinBox()
        self._port_spin.setRange(1, 99)
        self._port_spin.setValue(4)
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
        move_lay.addWidget(self._abs_spin, 2, 1)
        self._abs_btn = QPushButton("GO!")
        self._abs_btn.setEnabled(False)
        self._abs_btn.clicked.connect(self._do_move_abs)
        move_lay.addWidget(self._abs_btn, 2, 2)

        move_lay.addWidget(QLabel("Move Relative (mm):"), 3, 0)
        self._rel_spin = NoScrollDoubleSpinBox()
        self._rel_spin.setRange(-12.0, 12.0)
        self._rel_spin.setDecimals(4)
        self._rel_spin.setSingleStep(0.1)
        move_lay.addWidget(self._rel_spin, 3, 1)
        self._rel_btn = QPushButton("GO!")
        self._rel_btn.setEnabled(False)
        self._rel_btn.clicked.connect(self._do_move_rel)
        move_lay.addWidget(self._rel_btn, 3, 2)

        move_lay.addWidget(QLabel("Set Velocity (mm/s):"), 4, 0)
        self._vel_spin = NoScrollDoubleSpinBox()
        self._vel_spin.setRange(0.0001, 0.4)
        self._vel_spin.setDecimals(4)
        self._vel_spin.setValue(0.1)
        self._vel_spin.setSingleStep(0.05)
        move_lay.addWidget(self._vel_spin, 4, 1)
        self._vel_btn = QPushButton("SET!")
        self._vel_btn.setEnabled(False)
        self._vel_btn.clicked.connect(self._do_set_vel)
        move_lay.addWidget(self._vel_btn, 4, 2)

        self._stop_btn = QPushButton("⚠ EMERGENCY STOP ⚠")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet("background: #B71C1C; color: white; font-weight: bold; font-size: 13px;")
        self._stop_btn.clicked.connect(lambda: self._sig_stop.emit())
        move_lay.addWidget(self._stop_btn, 5, 0, 1, 3)

        move_lay.addWidget(QLabel("Diagnostics:"), 6, 0, 1, 3)

        self._pos_limit_btn = QPushButton("Get Positive Limit")
        self._pos_limit_btn.setEnabled(False)
        self._pos_limit_btn.clicked.connect(lambda: self._sig_pos_limit.emit())
        move_lay.addWidget(self._pos_limit_btn, 7, 0)

        self._neg_limit_btn = QPushButton("Get Negative Limit")
        self._neg_limit_btn.setEnabled(False)
        self._neg_limit_btn.clicked.connect(lambda: self._sig_neg_limit.emit())
        move_lay.addWidget(self._neg_limit_btn, 7, 1)

        self._identity_btn = QPushButton("Get Device Info")
        self._identity_btn.setEnabled(False)
        self._identity_btn.clicked.connect(lambda: self._sig_identity.emit())
        move_lay.addWidget(self._identity_btn, 8, 0)

        self._resources_btn = QPushButton("List VISA Resources")
        self._resources_btn.clicked.connect(lambda: self._sig_list_res.emit())
        move_lay.addWidget(self._resources_btn, 8, 1)

        self._config_btn = QPushButton("Dump All Config (1ZT)")
        self._config_btn.setEnabled(False)
        self._config_btn.clicked.connect(lambda: self._sig_dump_config.emit())
        move_lay.addWidget(self._config_btn, 8, 2)

        move_lay.setRowStretch(9, 1)
        root.addWidget(move_box, stretch=1)

        # ── Bottom: Log ───────────────────────────────────────────────────────
        outer = QVBoxLayout()
        outer.addLayout(root)
        log_box = QGroupBox("Log")
        log_lay = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        log_lay.addWidget(self._log)
        outer.addWidget(log_box)

        # Replace root layout with vertical wrapper
        container = QWidget()
        container.setLayout(outer)
        final = QVBoxLayout(self)
        final.setContentsMargins(0, 0, 0, 0)
        final.addWidget(container)

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
                        self._disconnect_btn, self._state_btn, self._stop_btn,
                        self._identity_btn, self._config_btn,
                        self._pos_limit_btn, self._neg_limit_btn,
                        self._vel_check_btn]:
                btn.setEnabled(True)
        elif op == "home":
            for btn in [self._abs_btn, self._rel_btn, self._vel_btn]:
                btn.setEnabled(True)
        elif op == "disconnect":
            for btn in [self._home_btn, self._pos_btn, self._vel_check_btn,
                        self._disconnect_btn, self._state_btn, self._stop_btn,
                        self._identity_btn, self._config_btn,
                        self._pos_limit_btn, self._neg_limit_btn,
                        self._abs_btn, self._rel_btn, self._vel_btn]:
                btn.setEnabled(False)

    # ── Button actions ────────────────────────────────────────────────────────

    def _do_connect(self):
        self._sig_connect.emit(self._port_spin.value())

    def _do_move_abs(self):
        self._sig_move_abs.emit(self._abs_spin.value())

    def _do_move_rel(self):
        self._sig_move_rel.emit(self._rel_spin.value())

    def _do_set_vel(self):
        self._sig_set_vel.emit(self._vel_spin.value())

    def cleanup(self):
        if HAS_PYVISA:
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

        self.daq_panel   = DAQPanel()
        self.itla_panel  = ITLAPanel()
        self.conex_panel = ConexPanel()

        self._detached: dict[str, DetachedWindow] = {}

        self.tabs = QTabWidget()
        self.tabs.setCornerWidget(self._make_popout_btn(), Qt.Corner.TopRightCorner)
        self.setCentralWidget(self.tabs)

        self.tabs.addTab(self.daq_panel,   "DAQ Control")
        self.tabs.addTab(self.itla_panel,  "ITLA Laser")
        self.tabs.addTab(self.conex_panel, "CONEX Motor")

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self._size_and_center()

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
        order = {"DAQ Control": 0, "ITLA Laser": 1, "CONEX Motor": 2}
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