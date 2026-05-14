import os
os.environ["MOKU_CLI_PATH"] = r"C:\Program Files\Liquid Instruments\Moku CLI\mokucli.exe"

import sys
import math
import subprocess
import socket
import json
import numpy as np
import UeiDaq
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QSizePolicy,
    QDoubleSpinBox, QSlider, QStackedWidget, QStatusBar, QGroupBox,
    QSpinBox, QComboBox, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QObject

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False
    print("[WARNING] pyqtgraph not found — Moku plot disabled. Run: uv pip install pyqtgraph")

try:
    from moku.instruments import Oscilloscope
    HAS_MOKU = True
except ImportError:
    HAS_MOKU = False
    print("[WARNING] moku library not found — Moku integration disabled.")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

CUBE_IP = "172.28.2.5"
MOKU_IP = "172.28.5.6"          # set when known, e.g. "192.168.73.1"

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

HOME_WINDOW_W  = 520
PIN_WINDOW_W   = 680
PIN_WINDOW_H   = 950   # tall enough to see all pins + panels without scrolling

SWEEP_DEFAULT_STEPS    = 10
SWEEP_DEFAULT_DWELL_MS = 500

MOKU_PLOT_WINDOW_S = 5.0    # seconds of rolling history shown
MOKU_POLL_MS       = 100    # poll interval ms
MOKU_SHUNT_OHMS    = 505.85    # load resistor (Ohms) — I = V / R

AO333_GUARDIAN_POLL_MS = 50     # GUI update rate from stream (ms) — 20Hz display
AO333_PLOT_WINDOW_S    = 10.0   # seconds of rolling history on Dev2 plot

# Bridge process config
BRIDGE_PORT       = 57333
BRIDGE_PYTHON     = r".venv32\Scripts\python.exe"
BRIDGE_SCRIPT     = r"code\UeiDaq_gui\ao333_bridge.py"

READBACK_DECIMALS = 6

# ══════════════════════════════════════════════════════════════════════════════


# ── Moku session ───────────────────────────────────────────────────────────────

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


# ── Moku background worker ─────────────────────────────────────────────────────

class MokuWorker(QObject):
    """
    Runs on a QThread. Handles the blocking Moku network calls
    (connect + periodic get_data) and emits signals back to the GUI thread.
    """
    # emitted once connect attempt finishes
    connected    = pyqtSignal()
    connect_err  = pyqtSignal(str)

    # emitted every poll with (ch1_v, ch2_v)
    sample_ready = pyqtSignal(float, float)

    # emitted when get_data fails (Moku lost)
    lost         = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.session   = MokuSession()
        self._running  = False
        self._timer    = None          # created in start_polling (must be on worker thread)

    def do_connect(self, ip: str):
        """Called via QMetaObject / signal from GUI thread."""
        try:
            self.session.connect(ip)
            self.connected.emit()
        except Exception as e:
            self.connect_err.emit(str(e))

    def start_polling(self):
        """Start the poll timer — must be called from the worker thread."""
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


# ── AO-333 Guardian streaming bridge client ────────────────────────────────────

class AO333ReadbackWorker(QObject):
    """
    Runs on a background QThread.
    Connects to ao333_bridge.py which streams JSON lines as fast as the
    Guardian ADC allows. Buffers the latest reading and emits readback_ready
    at AO333_GUARDIAN_POLL_MS for GUI updates (decouples hardware rate from
    GUI paint rate).
    """
    readback_ready = pyqtSignal(list)
    error          = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._sock       = None
        self._running    = False
        self._timer      = None   # GUI update timer
        self._latest     = [0.0] * NUM_PINS
        self._buf        = ""
        self._stream_thread = None

    def start(self):
        self.stop()
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2.0)
            self._sock.connect(("127.0.0.1", BRIDGE_PORT))
            self._sock.settimeout(0.5)   # short timeout for stream reads
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

        # background stream reader — runs in its own thread
        import threading
        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True)
        self._stream_thread.start()

        # GUI update timer — emits at display rate
        self._timer = QTimer()
        self._timer.setInterval(AO333_GUARDIAN_POLL_MS)
        self._timer.timeout.connect(self._emit_latest)
        self._timer.start()

    def _stream_loop(self):
        """Runs in a daemon thread — reads bridge stream as fast as possible."""
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096).decode("utf-8")
                if not chunk:
                    break
                self._buf += chunk
                # parse all complete lines
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


PROMICRO_PORT          = "COM11"
PROMICRO_BAUD          = 9600
PROMICRO_PLOT_WINDOW_S = 10.0

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    print("[WARNING] pyserial not found — Pro Micro disabled. Run: uv pip install pyserial")


# ── Pro Micro serial worker ────────────────────────────────────────────────────

class ProMicroWorker(QObject):
    sample_ready = pyqtSignal(float)
    error        = pyqtSignal(str)
    connected    = pyqtSignal()
    disconnected = pyqtSignal()

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
        while self._running and self._port:
            try:
                line = self._port.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("A0:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            self.sample_ready.emit(float(parts[1]))
                        except ValueError:
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

        # ── worker + thread ──
        self._thread = QThread()
        self._worker = MokuWorker()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        self._worker.connected.connect(self._on_connected)
        self._worker.connect_err.connect(self._on_connect_err)
        self._worker.sample_ready.connect(self._on_sample)
        self._worker.lost.connect(self._on_lost)

        # ── UI ──
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
        self._connect_btn.setFixedWidth(70)
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
            pg.setConfigOption('background', 'k')
            pg.setConfigOption('foreground', 'w')
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setLabel('left',   'Voltage', units='V')
            self._plot_widget.setLabel('bottom', 'Time',    units='s')
            self._plot_widget.setMinimumHeight(180)
            self._plot_widget.addLegend()
            self._curve1 = self._plot_widget.plot(
                [], [], pen=pg.mkPen('#00BFFF', width=2), name='Ch1')
            self._curve2 = self._plot_widget.plot(
                [], [], pen=pg.mkPen('#FF6347', width=2), name='Ch2')
            layout.addWidget(self._plot_widget)
            note = QLabel(
                f"  I = V / {MOKU_SHUNT_OHMS:.2f} Ω   "
                f"Ch1 (blue),  Ch2 (red)")
            note.setStyleSheet("color: gray; font-size: 10px;")
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
        # run blocking connect on the worker thread
        QTimer.singleShot(0, lambda: self._worker.do_connect(ip))

    def _on_connected(self):
        self._t = 0.0; self._ts1=[]; self._vs1=[]; self._ts2=[]; self._vs2=[]
        self._status_lbl.setText("●")
        self._connect_btn.setVisible(False)
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")
        self._disconnect_btn.setVisible(True)
        self._ip_edit.setEnabled(False)
        # start polling on the worker thread
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
        self._connect_btn.setVisible(True)
        self._disconnect_btn.setVisible(False)
        self._ip_edit.setEnabled(True)
        self._ch1_v_lbl.setText("Ch1:  — V");  self._ch1_ma_lbl.setText("— mA")
        self._ch2_v_lbl.setText("Ch2:  — V");  self._ch2_ma_lbl.setText("— mA")

    def _on_lost(self):
        """Worker thread lost the Moku — update UI from GUI thread."""
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
        changed = [i for i, (old, new) in enumerate(zip(self.values, values))
                   if abs(old - new) > 1e-6]
        if changed:
            print(f"[{self.dev}]  " +
                  "   ".join(f"Pin {i:02d}: {values[i]:8.3f} {self.unit}"
                             for i in changed))
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
            connect_btn.setFixedWidth(70)
            connect_btn.setEnabled(info["available"])

            open_btn = QPushButton("Open")
            open_btn.setFixedWidth(70)
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
            connect_btn.setVisible(not connected)
            open_btn.setVisible(connected)
            x_btn.setVisible(connected)


# ── Post-recording plot window ─────────────────────────────────────────────────

class RecordingPlotWindow(QWidget):
    """
    Shown after a recording session ends.
    Displays time-series (current or voltage vs time) and optionally V vs I.
    Receives the completed record list on show_data().
    Each record: {'t': float, 'moku_v': float, 'daq': list[float], 'mode': str}
    """
    def __init__(self, card_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Recording — {card_label}")
        self.resize(700, 500)
        self._card_label = card_label

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if HAS_PYQTGRAPH:
            pg.setConfigOption('background', 'k')
            pg.setConfigOption('foreground', 'w')

            # time series plot
            self._ts_plot = pg.PlotWidget()
            self._ts_plot.setLabel('bottom', 'Time', units='s')
            self._ts_plot.setMinimumHeight(200)
            self._ts_curve = self._ts_plot.plot([], [], pen=pg.mkPen('#00BFFF', width=2))
            layout.addWidget(self._ts_plot)

            # V vs I plot (hidden until toggled)
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
        """Populate plots from a completed record list."""
        if not records:
            return

        ts   = [r['t']      for r in records]
        mvs  = [r['moku_v'] for r in records]

        if mode == 'current':
            ys     = [(v / MOKU_SHUNT_OHMS) * 1000.0 for v in mvs]
            y_lbl  = 'Current (mA)'
            color  = '#00BFFF'
        else:
            ys     = mvs
            y_lbl  = 'Voltage (V)'
            color  = '#FFD700'

        if HAS_PYQTGRAPH:
            self._ts_plot.setLabel('left', y_lbl)
            self._ts_curve.setPen(pg.mkPen(color, width=2))
            self._ts_curve.setData(ts, ys)

            # V vs I: X = mean DAQ output, Y = readback scaled
            src = "Guardian" if mode == "voltage" else "Moku"
            xs_vi = [float(np.mean(r['daq'])) for r in records]
            self._vi_plot.setLabel('bottom',
                'DAQ Output (mA)' if mode == 'current' else 'DAQ Output (V)')
            self._vi_plot.setLabel('left',
                f'{src} Measured (mA)' if mode == 'current' else f'{src} Measured (V)')
            self._vi_scatter.setData(xs_vi, ys)

        # pre-set VI visibility based on checkbox
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
        self._pin     = 0    # which pin's commanded value to track

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ── pin selector row ──
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
        self._src_lbl.setStyleSheet("color: gray; font-size: 10px;")
        pin_row.addWidget(self._src_lbl)
        pin_row.addStretch()
        layout.addLayout(pin_row)

        y_unit = 'mA' if mode == 'current' else 'V'

        if HAS_PYQTGRAPH:
            pg.setConfigOption('background', 'k')
            pg.setConfigOption('foreground', 'w')

            # time series
            self._ts_plot = pg.PlotWidget()
            self._ts_plot.setLabel('left',   f'Value ({y_unit})')
            self._ts_plot.setLabel('bottom', 'Time', units='s')
            self._ts_plot.getAxis('left').enableAutoSIPrefix(False)
            self._ts_plot.setMinimumHeight(200)
            self._ts_plot.addLegend()
            self._cmd_curve  = self._ts_plot.plot(
                [], [], pen=pg.mkPen('#FFD700', width=2), name='Commanded')
            self._meas_curve = self._ts_plot.plot(
                [], [], pen=pg.mkPen('#00FF88', width=2), name='Measured')
            layout.addWidget(self._ts_plot)

            # scatter
            self._sc_plot = pg.PlotWidget()
            self._sc_plot.getAxis('bottom').enableAutoSIPrefix(False)
            self._sc_plot.getAxis('left').enableAutoSIPrefix(False)
            self._sc_plot.setLabel('bottom', f'Commanded ({y_unit})')
            self._sc_plot.setLabel('left',   f'Measured ({y_unit})')
            self._sc_plot.setMinimumHeight(200)
            self._scatter = self._sc_plot.plot(
                [], [], pen=None, symbol='o', symbolSize=4,
                symbolBrush='#00BFFF', symbolPen=None)
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

        window = 30.0
        cutoff = self._t - window
        for ts, vs in [(self._cmd_ts, self._cmd_vs),
                       (self._meas_ts, self._meas_vs)]:
            while ts and ts[0] < cutoff:
                ts.pop(0); vs.pop(0)

        if not HAS_PYQTGRAPH:
            return

        self._cmd_curve.setData(self._cmd_ts,  self._cmd_vs)
        self._meas_curve.setData(self._meas_ts, self._meas_vs)
        if self._cmd_ts:
            x_max = self._cmd_ts[-1]
            self._ts_plot.setXRange(x_max - window, x_max, padding=0)
        self._scatter.setData(self._cmd_vs, self._meas_vs)

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
        back_btn.setFixedWidth(70)
        back_btn.clicked.connect(self.back_clicked.emit)
        self.card_title = QLabel("DEV0")
        self.badge      = QLabel("VOLTAGE")
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
            sb  = QDoubleSpinBox()
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
            rb_lbl.setStyleSheet("color: #00BFFF; font-size: 10px;")
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
        self.sweep_start = QDoubleSpinBox()
        self.sweep_start.setDecimals(3)
        self.sweep_start.setFixedWidth(90)
        row1.addWidget(self.sweep_start)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Stop:"))
        self.sweep_stop = QDoubleSpinBox()
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
        self.sweep_steps_sb = QSpinBox()
        self.sweep_steps_sb.setRange(2, 10000)
        self.sweep_steps_sb.setValue(SWEEP_DEFAULT_STEPS)
        self.sweep_steps_sb.setFixedWidth(70)
        self.sweep_stepsize_sb = QDoubleSpinBox()
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
        self.sweep_dwell_sb = QSpinBox()
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

        sep5 = QFrame()
        sep5.setFrameShape(QFrame.Shape.HLine)
        sep5.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep5)

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
        self.wave_freq_sb = QDoubleSpinBox()
        self.wave_freq_sb.setDecimals(3)
        self.wave_freq_sb.setRange(0.001, 1000.0)
        self.wave_freq_sb.setValue(1.0)
        self.wave_freq_sb.setFixedWidth(90)
        wrow2.addWidget(self.wave_freq_sb)
        wrow2.addSpacing(10)
        wrow2.addWidget(QLabel("Amplitude:"))
        self.wave_amp_sb = QDoubleSpinBox()
        self.wave_amp_sb.setDecimals(3)
        self.wave_amp_sb.setValue(1.0)
        self.wave_amp_sb.setFixedWidth(90)
        wrow2.addWidget(self.wave_amp_sb)
        wrow2.addSpacing(10)
        wrow2.addWidget(QLabel("Offset:"))
        self.wave_offset_sb = QDoubleSpinBox()
        self.wave_offset_sb.setDecimals(3)
        self.wave_offset_sb.setValue(0.0)
        self.wave_offset_sb.setFixedWidth(90)
        wrow2.addWidget(self.wave_offset_sb)
        wrow2.addStretch()
        wg.addLayout(wrow2)

        wrow3 = QHBoxLayout()
        wrow3.addWidget(QLabel("Tick (ms):"))
        self.wave_tick_sb = QSpinBox()
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
        sep6 = QFrame()
        sep6.setFrameShape(QFrame.Shape.HLine)
        sep6.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep6)

        rec_group = QGroupBox("Data Recording")
        rg = QVBoxLayout(rec_group)
        rg.setSpacing(6)

        rec_row1 = QHBoxLayout()
        self._rec_btn  = QPushButton("⏺  Start Recording")
        self._rec_btn.setFixedWidth(150)
        self._rec_btn.clicked.connect(self._toggle_recording)
        self._rec_status_lbl = QLabel("Idle")
        self._rec_status_lbl.setStyleSheet("color: gray;")
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

        # source selector for recording readback (Dev2 only, hidden for current cards)
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

        # Dev2 source selector (only visible for voltage card)
        self._cmp_src_combo = QComboBox()
        self._cmp_src_combo.addItem("Moku",     "moku")
        self._cmp_src_combo.addItem("Guardian", "guardian")
        self._cmp_src_combo.addItem("Pro Micro","promicro")
        self._cmp_src_combo.setFixedWidth(100)
        self._cmp_src_combo.setVisible(False)
        self._cmp_src_label = QLabel("Source:")
        self._cmp_src_label.setVisible(False)

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

        # ── Dev2 live rolling plot ──
        self._dev2_plot_group = QGroupBox("Dev2 Live Voltage Readback")
        dg = QVBoxLayout(self._dev2_plot_group)
        dg.setContentsMargins(4, 4, 4, 4)

        if HAS_PYQTGRAPH:
            pg.setConfigOption('background', 'k')
            pg.setConfigOption('foreground', 'w')
            self._dev2_plot = pg.PlotWidget()
            self._dev2_plot.setLabel('left',   'Voltage', units='V')
            self._dev2_plot.setLabel('bottom', 'Time',    units='s')
            self._dev2_plot.setMinimumHeight(200)
            self._dev2_plot.addLegend()
            colors = ['#FFD700','#00BFFF','#FF6347','#00FF88',
                      '#FF69B4','#FFA500','#7B68EE','#00CED1']
            self._dev2_curves = []
            for i in range(NUM_PINS):
                c = self._dev2_plot.plot(
                    [], [], pen=pg.mkPen(colors[i], width=1),
                    name=f'Pin {i}')
                self._dev2_curves.append(c)
            dg.addWidget(self._dev2_plot)
        else:
            dg.addWidget(QLabel("(pyqtgraph required)"))
            self._dev2_plot   = None
            self._dev2_curves = []

        self._dev2_plot_group.setVisible(False)
        root.addWidget(self._dev2_plot_group)

        # rolling buffers for Dev2 plot
        self._dev2_t   = 0.0
        self._dev2_ts  = []
        self._dev2_vs  = [[] for _ in range(NUM_PINS)]

        # ── Pro Micro live plot ──
        self._pm_plot_group = QGroupBox("Pro Micro — Live Voltage")
        pg2 = QVBoxLayout(self._pm_plot_group)
        pg2.setContentsMargins(4, 4, 4, 4)

        pm_ctrl = QHBoxLayout()
        pm_ctrl.addWidget(QLabel("Port:"))
        self._pm_port_edit = QLineEdit(PROMICRO_PORT)
        self._pm_port_edit.setFixedWidth(80)
        pm_ctrl.addWidget(self._pm_port_edit)
        self._pm_connect_btn    = QPushButton("Connect")
        self._pm_disconnect_btn = QPushButton("✕")
        self._pm_connect_btn.setFixedWidth(70)
        self._pm_disconnect_btn.setFixedSize(24, 24)
        self._pm_disconnect_btn.setVisible(False)
        self._pm_status_lbl = QLabel("○")
        self._pm_status_lbl.setFixedWidth(14)
        self._pm_val_lbl = QLabel("— V")
        self._pm_val_lbl.setMinimumWidth(80)
        self._pm_connect_btn.clicked.connect(self._pm_connect)
        self._pm_disconnect_btn.clicked.connect(self._pm_disconnect)
        pm_ctrl.addWidget(self._pm_status_lbl)
        pm_ctrl.addWidget(self._pm_connect_btn)
        pm_ctrl.addWidget(self._pm_disconnect_btn)
        pm_ctrl.addSpacing(10)
        pm_ctrl.addWidget(self._pm_val_lbl)
        pm_ctrl.addStretch()
        pg2.addLayout(pm_ctrl)

        if HAS_PYQTGRAPH:
            self._pm_plot = pg.PlotWidget()
            self._pm_plot.setLabel('left',   'Voltage', units='V')
            self._pm_plot.setLabel('bottom', 'Time',    units='s')
            self._pm_plot.setMinimumHeight(160)
            self._pm_curve = self._pm_plot.plot(
                [], [], pen=pg.mkPen('#00FF88', width=2))
            pg2.addWidget(self._pm_plot)
        else:
            self._pm_plot  = None
            self._pm_curve = None

        self._pm_plot_group.setVisible(False)
        root.addWidget(self._pm_plot_group)

        self._pm_t  = 0.0
        self._pm_ts = []
        self._pm_vs = []

        # Pro Micro worker + thread
        self._pm_thread = QThread()
        self._pm_worker = ProMicroWorker()
        self._pm_worker.moveToThread(self._pm_thread)
        self._pm_thread.start()
        self._pm_worker.sample_ready.connect(self._on_pm_sample)
        self._pm_worker.connected.connect(self._pm_on_connected)
        self._pm_worker.disconnected.connect(self._pm_on_disconnected)
        self._pm_worker.error.connect(
            lambda msg: print(f"[ProMicro] {msg}"))

    def _open_comparison_plot(self):
        cs = self.card_session
        if cs is None:
            return
        label = CARDS[cs.card_index]["label"]
        self._cmp_win = LiveComparisonPlot(label, cs.mode)

        if cs.mode == "current":
            self._cmp_win.set_source_label("Measured = Moku Ch1 → mA via shunt")
        else:
            src = self._cmp_src_combo.currentData()
            src_names = {"moku": "Moku Ch1", "guardian": "Guardian ADC",
                         "promicro": "Pro Micro"}
            self._cmp_win.set_source_label(
                f"Measured = {src_names.get(src, src)}")

        self._cmp_win.show()
        self._cmp_win.raise_()

    def _append_record(self, readback_v: float, dt: float):
        """Append one sample to the recording buffer."""
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
        """Push a commanded/measured pair to the live comparison window."""
        if self._cmp_win is None or not self._cmp_win.isVisible():
            return
        cs = self.card_session
        if cs is None:
            return
        # use the selected pin's commanded value
        pin = self._cmp_win.get_pin()
        commanded = cs.values[pin] if pin < len(cs.values) else 0.0
        if dt is None:
            dt = MOKU_POLL_MS / 1000.0
        self._cmp_win.push(commanded, measured, dt=dt)

    def _pm_connect(self):
        port = self._pm_port_edit.text().strip()
        self._pm_connect_btn.setEnabled(False)
        self._pm_connect_btn.setText("…")
        self._pm_t = 0.0; self._pm_ts = []; self._pm_vs = []
        if HAS_PYQTGRAPH and self._pm_curve:
            self._pm_curve.setData([], [])
        QTimer.singleShot(0, lambda: self._pm_worker.start(port))

    def _pm_disconnect(self):
        QTimer.singleShot(0, self._pm_worker.stop)

    def _pm_on_connected(self):
        self._pm_status_lbl.setText("●")
        self._pm_connect_btn.setVisible(False)
        self._pm_disconnect_btn.setVisible(True)
        self._pm_port_edit.setEnabled(False)
        self._pm_connect_btn.setEnabled(True)
        self._pm_connect_btn.setText("Connect")

    def _pm_on_disconnected(self):
        self._pm_status_lbl.setText("○")
        self._pm_connect_btn.setVisible(True)
        self._pm_disconnect_btn.setVisible(False)
        self._pm_port_edit.setEnabled(True)
        self._pm_val_lbl.setText("— V")

    def _on_pm_sample(self, v: float):
        self._last_pm_v = v
        self._pm_val_lbl.setText(f"{v:.4f} V")

        # push to comparison only when Pro Micro is the selected source
        if (self._cmp_src_combo.currentData() == "promicro"
                and self._cmp_win and self._cmp_win.isVisible()
                and self.card_session):
            self._push_comparison(v, dt=0.2)

        # append to recording when Pro Micro is the selected recording source
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
        self._pm_curve.setData(self._pm_ts, self._pm_vs)
        if self._pm_ts:
            x_max = self._pm_ts[-1]
            self._pm_plot.setXRange(x_max - PROMICRO_PLOT_WINDOW_S, x_max, padding=0)

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

        # stop any running recording when switching cards
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
        self._dev2_plot_group.setVisible(is_voltage)
        self._pm_plot_group.setVisible(is_voltage)
        self._cmp_src_combo.setVisible(is_voltage)
        self._cmp_src_label.setVisible(is_voltage)
        self._rec_src_row_widget.setVisible(is_voltage)

        # close stale comparison window when switching cards
        if self._cmp_win and self._cmp_win.isVisible():
            self._cmp_win.close()
        self._cmp_win = None
        self._last_moku_v = 0.0
        self._last_guardian_v = 0.0
        self._last_pm_v = 0.0

        # reset Dev2 rolling plot buffers
        self._dev2_t  = 0.0
        self._dev2_ts = []
        self._dev2_vs = [[] for _ in range(NUM_PINS)]
        if HAS_PYQTGRAPH and self._dev2_curves:
            for c in self._dev2_curves:
                c.setData([], [])

        if is_voltage:
            QTimer.singleShot(0, self._guardian_worker.start)
        else:
            QTimer.singleShot(0, self._guardian_worker.stop)

    def _on_guardian_readback(self, values: list):
        """Called on GUI thread at AO333_GUARDIAN_POLL_MS rate from stream."""
        self._guardian_values = values
        self._last_guardian_v = float(np.mean(values[:NUM_PINS]))
        for i, v in enumerate(values[:NUM_PINS]):
            self._readback_lbls[i].setText(f"{v:+.{READBACK_DECIMALS}f}V")

        # push to comparison only when Guardian is the selected source
        if (self._cmp_src_combo.currentData() == "guardian"
                and self._cmp_win and self._cmp_win.isVisible()
                and self.card_session):
            pin = self._cmp_win.get_pin()
            v   = values[pin] if pin < len(values) else 0.0
            self._push_comparison(v, dt=AO333_GUARDIAN_POLL_MS / 1000.0)

        # append to recording when Guardian is the selected recording source
        if (self._recording and self.card_session
                and self._rec_src_combo.currentData() == "guardian"):
            self._append_record(self._last_guardian_v,
                                dt=AO333_GUARDIAN_POLL_MS / 1000.0)

        # update rolling plot
        if not HAS_PYQTGRAPH or not self._dev2_curves:
            return
        self._dev2_t += AO333_GUARDIAN_POLL_MS / 1000.0
        self._dev2_ts.append(self._dev2_t)
        for i, v in enumerate(values[:NUM_PINS]):
            self._dev2_vs[i].append(v)

        cutoff = self._dev2_t - AO333_PLOT_WINDOW_S
        while self._dev2_ts and self._dev2_ts[0] < cutoff:
            self._dev2_ts.pop(0)
            for buf in self._dev2_vs:
                if buf: buf.pop(0)

        for i, curve in enumerate(self._dev2_curves):
            curve.setData(self._dev2_ts, self._dev2_vs[i])
        if self._dev2_ts:
            x_max = self._dev2_ts[-1]
            self._dev2_plot.setXRange(
                x_max - AO333_PLOT_WINDOW_S, x_max, padding=0)

    def push_moku_sample(self, ch1_v: float, ch2_v: float):
        """Receives every Moku poll tick."""
        self._last_moku_v = ch1_v
        dt = MOKU_POLL_MS / 1000.0

        if self.card_session is None:
            return

        if self.card_session.mode == "current":
            meas_ma = (ch1_v / MOKU_SHUNT_OHMS) * 1000.0
            self._push_comparison(meas_ma, dt=dt)
            # current cards always record from Moku
            if self._recording:
                self._append_record(ch1_v, dt)

        elif self.card_session.mode == "voltage":
            if self._cmp_src_combo.currentData() == "moku":
                self._push_comparison(ch1_v, dt=dt)
            # record from Moku only if Moku is the selected recording source
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
        self._rec_btn.setStyleSheet("color: red;")
        self._rec_status_lbl.setText("● Recording — 0 samples")
        self._rec_status_lbl.setStyleSheet("color: red;")
        self._save_btn.setEnabled(False)

    def _stop_recording(self):
        self._recording = False
        self._rec_btn.setText("⏺  Start Recording")
        self._rec_btn.setStyleSheet("")
        n = len(self._rec_records)
        self._rec_status_lbl.setStyleSheet("color: gray;")
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

        # label readback column by actual source used
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
                    scaled = r['moku_v']   # already in volts for all Dev2 sources
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
        """Set button handler — respects Ramp checkbox for single pin."""
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
                # instant: write immediately on a thread to avoid blocking GUI
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


# ── Main window ────────────────────────────────────────────────────────────────

class DAQMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YPL DAQ Control")
        self.setMinimumWidth(HOME_WINDOW_W)

        self.card_sessions = {
            i: CardSession(i) for i, info in CARDS.items() if info["available"]
        }

        self.stacked = QStackedWidget()
        self.setCentralWidget(self.stacked)

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

        self.stacked.addWidget(main_view)
        self.stacked.addWidget(self.pin_view)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # auto-launch the 32-bit Guardian bridge process
        self._bridge_proc = None
        self._launch_bridge()

    def _launch_bridge(self):
        """Start ao333_bridge.py as a subprocess using .venv32."""
        try:
            self._bridge_proc = subprocess.Popen(
                [BRIDGE_PYTHON, BRIDGE_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_CONSOLE)
            print(f"[Bridge] Launched PID {self._bridge_proc.pid}")
            # give it a moment to start listening
            QTimer.singleShot(2000, lambda: print("[Bridge] Ready"))
        except Exception as e:
            print(f"[Bridge] Failed to launch: {e}")

    def _open_card(self, idx: int):
        cs = self.card_sessions[idx]
        if cs.connected:
            self.pin_view.load_card(cs)
            self.stacked.setCurrentIndex(1)
            self.daq_box.refresh()
            screen_h = QApplication.primaryScreen().availableGeometry().height()
            self.resize(PIN_WINDOW_W, min(PIN_WINDOW_H, screen_h - 40))
            return

        self.status_bar.showMessage(f"Connecting to {CARDS[idx]['label']}…")

        def do_connect():
            try:
                cs.connect()
                # schedule GUI update back on main thread
                QTimer.singleShot(0, lambda: self._card_connected(idx))
            except Exception as e:
                QTimer.singleShot(0, lambda: self.status_bar.showMessage(
                    f"Connection error: {e}"))

        t = QThread(self)
        # keep reference so it isn't GC'd
        self._connect_threads = getattr(self, '_connect_threads', [])
        self._connect_threads.append(t)
        t.run = do_connect        # type: ignore[method-assign]
        t.finished.connect(lambda: self._connect_threads.remove(t)
                           if t in self._connect_threads else None)
        t.start()

    def _card_connected(self, idx: int):
        cs = self.card_sessions[idx]
        self.status_bar.showMessage(
            f"Connected — {CARDS[idx]['label']} — "
            f"{cs.min_val} to {cs.max_val} {cs.unit}")
        self.pin_view.load_card(cs)
        self.stacked.setCurrentIndex(1)
        self.daq_box.refresh()
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        self.resize(PIN_WINDOW_W, min(PIN_WINDOW_H, screen_h - 40))

    def _disconnect_card(self, idx: int):
        cs = self.card_sessions[idx]
        try:
            cs.stop_sweep()
            cs.zero_immediate()
            cs.disconnect()
            self.status_bar.showMessage(f"Disconnected — {CARDS[idx]['label']}")
        except Exception as e:
            self.status_bar.showMessage(f"Error disconnecting: {e}")
        self.daq_box.refresh()

    def _show_main(self):
        self.stacked.setCurrentIndex(0)
        self.daq_box.refresh()
        self.status_bar.showMessage("Ready")
        self.adjustSize()

    def closeEvent(self, event):
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
        self.pin_view._guardian_worker.stop()
        self.pin_view._guardian_thread.quit()
        self.pin_view._guardian_thread.wait(2000)
        self.pin_view._pm_worker.stop()
        self.pin_view._pm_thread.quit()
        self.pin_view._pm_thread.wait(2000)
        if self._bridge_proc and self._bridge_proc.poll() is None:
            self._bridge_proc.terminate()
            print("[Bridge] Terminated")
        event.accept()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = DAQMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()