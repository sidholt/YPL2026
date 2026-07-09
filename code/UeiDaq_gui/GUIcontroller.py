import sys
import math
import UeiDaq
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QSizePolicy,
    QDoubleSpinBox, QSlider, QStackedWidget, QStatusBar, QGroupBox,
    QSpinBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — edit these values to match your hardware setup and preferences
# ══════════════════════════════════════════════════════════════════════════════

# DAQ box network address
CUBE_IP = "172.28.2.4"

# Number of output pins per card
NUM_PINS = 8

# Card slot definitions — set available=False for unknown/unused slots
# mode: "voltage" or "current"
# dev:  device string used in the UeiDaq channel URL (e.g. "Dev0")
CARDS = {
    0: {"label": "DEV0  —  CURRENT", "mode": "current", "dev": "Dev0", "available": True},
    1: {"label": "DEV1  —  UNKNOWN", "mode": "current", "dev": "Dev1", "available": True},
    2: {"label": "DEV2  —  VOLTAGE", "mode": "voltage", "dev": "Dev2", "available": True},
}

# Output ranges per mode: (min, max, unit, slider_min, slider_max)
# slider values are scaled by 100 to allow 2 decimal places of resolution
MODE_RANGES = {
    "voltage": (-10.0, 10.0, "V",   -1000, 1000),
    "current": (  0.0, 20.0, "mA",      0, 2000),
}

# Ramp / slew rate control
# SLEW_RATE_V/MA: maximum rate of change in V/s or mA/s
# RAMP_TICK_MS:   how often the ramp timer fires (ms) — 20ms is the practical minimum
# Adjust SLEW_RATE values once hardware specs are confirmed
RAMP_TICK_MS = 20
SLEW_RATE_V  = 5.0    # V/s
SLEW_RATE_MA = 10.0   # mA/s
STEP_V       = SLEW_RATE_V  * (RAMP_TICK_MS / 1000.0)
STEP_MA      = SLEW_RATE_MA * (RAMP_TICK_MS / 1000.0)

# Window dimensions
HOME_WINDOW_W  = 420   # width of home screen
PIN_WINDOW_W   = 560   # width of pin config view
PIN_WINDOW_H   = 580   # height of pin config view

# Sweep defaults
SWEEP_DEFAULT_STEPS    = 10     # number of steps (points) from start to stop
SWEEP_DEFAULT_DWELL_MS = 500    # how long to hold each step (ms)

# ══════════════════════════════════════════════════════════════════════════════


# ── Per-card session ───────────────────────────────────────────────────────────

class CardSession:
    """Owns the UeiDaq session for one physical card independently,
    allowing voltage and current sessions to coexist in the future."""

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

        # sweep state
        self._sweep_steps    = []
        self._sweep_pin      = 0
        self._sweep_step_idx = 0
        self._sweep_callback = None
        self._sweep_done_callback = None
        self._sweep_dwell_ms = SWEEP_DEFAULT_DWELL_MS
        self._sweep_timer    = QTimer()
        self._sweep_timer.setSingleShot(True)
        self._sweep_timer.timeout.connect(self._sweep_next_step)

    def connect(self):
        self.disconnect()
        self.session = UeiDaq.CUeiSession()
        url = f"pdna://{CUBE_IP}/{self.dev}/Ao0:{NUM_PINS - 1}"
        print(f"Connecting: {url}, mode: {self.mode}, range: {self.min_val} to {self.max_val}")
        if self.mode == "voltage":
            self.session.CreateAOChannel(
                f"pdna://{CUBE_IP}/{self.dev}/Ao0:{NUM_PINS - 1}",
                self.min_val, self.max_val
            )
        else:
            self.session.CreateAOCurrentChannel(
                f"pdna://{CUBE_IP}/{self.dev}/Ao0:{NUM_PINS - 1}",
                self.min_val, self.max_val
            )
        self.session.ConfigureTimingForSimpleIO()
        self.writer = UeiDaq.CUeiAnalogScaledWriter(self.session.GetDataStream())

    def ramp_to(self, targets: list):
        """Set new targets and start ramping. Interrupts any ramp in progress."""
        self._targets = list(targets)
        if not self._timer.isActive():
            self._timer.start()

    def _ramp_tick(self):
        """Step each pin one tick closer to its target, stop when all arrive."""
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
        if self.mode == "current":
            scaled = [v / 1000.0 for v in values]
        else:
            scaled = values
        self.writer.WriteSingleScan(scaled)
        changed = [i for i, (old, new) in enumerate(zip(self.values, values)) if abs(old - new) > 1e-6]
        if changed:
            pin_strs = "   ".join(f"Pin {i:02d}: {values[i]:8.3f} {self.unit}" for i in changed)
            print(f"[{self.dev}]  {pin_strs}")
        self.values = list(values)

    # ── wave generation ────────────────────────────────────────────────────────

    def start_wave(self, pin: int, waveform: str, freq: float,
                   amplitude: float, offset: float, tick_ms: int,
                   callback=None):
        """
        Output a continuous sin or cos wave on a single pin.
        amplitude and offset are in the card's native unit (mA or V).
        callback(pin, value) called each tick for GUI update.
        """
        self.stop_wave()
        self._wave_pin       = pin
        self._wave_form      = waveform   # "sin" or "cos"
        self._wave_freq      = freq
        self._wave_amplitude = amplitude
        self._wave_offset    = offset
        self._wave_t         = 0.0
        self._wave_tick_ms   = tick_ms
        self._wave_callback  = callback

        self._wave_timer = QTimer()
        self._wave_timer.setInterval(tick_ms)
        self._wave_timer.timeout.connect(self._wave_tick)
        self._wave_timer.start()

    def _wave_tick(self):
        fn = math.sin if self._wave_form == "sin" else math.cos
        val = self._wave_offset + self._wave_amplitude * fn(
            2 * math.pi * self._wave_freq * self._wave_t
        )
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
        """
        Sweep a single pin from start to stop in N steps (points).
        All other pins hold their current values.
        callback(pin, value, step_idx, total_steps) called after each step arrives.
        done_callback() called when sweep completes.
        """
        self.stop_sweep()
        self._sweep_pin           = pin
        self._sweep_dwell_ms      = dwell_ms
        self._sweep_callback      = callback
        self._sweep_done_callback = done_callback
        self._sweep_step_idx      = 0
        if steps < 2:
            steps = 2
        self._sweep_steps = [
            start + (stop - start) * i / (steps - 1)
            for i in range(steps)
        ]
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
            # sweep complete
            done_cb = self._sweep_done_callback
            self.stop_sweep()
            if done_cb:
                done_cb()
            return
        target_val = self._sweep_steps[self._sweep_step_idx]
        targets = list(self.values)
        targets[self._sweep_pin] = target_val
        self._sweep_pending_target = target_val
        self.ramp_to(targets)
        self._sweep_poll = QTimer()
        self._sweep_poll.setInterval(RAMP_TICK_MS)
        self._sweep_poll.timeout.connect(self._sweep_check_arrived)
        self._sweep_poll.start()

    def _sweep_check_arrived(self):
        """Wait for ramp to reach current step, fire callback, then dwell."""
        if abs(self.values[self._sweep_pin] - self._sweep_pending_target) <= self._step:
            self._sweep_poll.stop()
            total = len(self._sweep_steps)
            idx   = self._sweep_step_idx
            # fire callback with current step info before incrementing
            if self._sweep_callback:
                self._sweep_callback(self._sweep_pin, self.values[self._sweep_pin], idx + 1, total)
            self._sweep_step_idx += 1
            self._sweep_timer.start(self._sweep_dwell_ms)

    def zero(self):
        """Ramp all pins to zero."""
        self.stop_sweep()
        self.ramp_to([0.0] * NUM_PINS)

    def zero_immediate(self):
        """Hard zero with no ramp — used on disconnect/close."""
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

            status_lbl = QLabel("○")
            status_lbl.setFixedWidth(14)

            name_lbl = QLabel(info["label"])
            name_lbl.setMinimumWidth(200)
            if not info["available"]:
                name_lbl.setEnabled(False)

            connect_btn = QPushButton("Connect")
            connect_btn.setFixedWidth(70)
            connect_btn.setEnabled(info["available"])

            open_btn = QPushButton("Open")
            open_btn.setFixedWidth(70)
            open_btn.setVisible(False)
            open_btn.setToolTip("Open pin controls for this card")

            x_btn = QPushButton("✕")
            x_btn.setFixedSize(24, 24)
            x_btn.setVisible(False)
            x_btn.setToolTip("Disconnect and zero outputs")

            if info["available"]:
                connect_btn.clicked.connect(lambda _, idx=i: self.card_clicked.emit(idx))
                open_btn.clicked.connect(lambda _, idx=i: self.card_clicked.emit(idx))
                x_btn.clicked.connect(lambda _, idx=i: self.card_disconnected.emit(idx))

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
            if not info["available"]:
                continue
            status_lbl, connect_btn, open_btn, x_btn = self._rows[i]
            connected = self.card_sessions[i].connected
            status_lbl.setText("●" if connected else "○")
            connect_btn.setVisible(not connected)
            open_btn.setVisible(connected)
            x_btn.setVisible(connected)


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

        # header
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

        # scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        pin_container = QWidget()
        self.pin_layout = QVBoxLayout(pin_container)
        self.pin_layout.setSpacing(2)
        self.pin_layout.setContentsMargins(4, 4, 4, 4)

        col_row = QHBoxLayout()
        for text, width in [("Pin", 50), ("Value", 120), ("Slider", -1), ("", 60)]:
            lbl = QLabel(text)
            if width > 0:
                lbl.setFixedWidth(width)
            col_row.addWidget(lbl) if width < 0 else col_row.addWidget(lbl)
        self.pin_layout.addLayout(col_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        self.pin_layout.addWidget(sep2)

        self.spinboxes, self.sliders = [], []

        for i in range(NUM_PINS):
            rl = QHBoxLayout()
            rl.setSpacing(6)

            lbl = QLabel(f"Pin {i:02d}")
            lbl.setFixedWidth(50)

            sb = QDoubleSpinBox()
            sb.setDecimals(3)
            sb.setSingleStep(0.1)
            sb.setValue(0.0)
            sb.setFixedWidth(120)

            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setValue(0)
            sl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            set_btn = QPushButton("Set")
            set_btn.setFixedWidth(60)
            set_btn.clicked.connect(lambda _, idx=i: self._write_all(focused_pin=idx))

            sb.valueChanged.connect(lambda val, idx=i: self._sb_changed(idx, val))
            sl.valueChanged.connect(lambda val, idx=i: self._sl_changed(idx, val))

            rl.addWidget(lbl)
            rl.addWidget(sb)
            rl.addWidget(sl, stretch=1)
            rl.addWidget(set_btn)

            self.spinboxes.append(sb)
            self.sliders.append(sl)
            self.pin_layout.addLayout(rl)

        self.pin_layout.addStretch()
        scroll.setWidget(pin_container)
        root.addWidget(scroll, stretch=1)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep3)

        # bottom bar
        bottom = QHBoxLayout()
        write_btn = QPushButton("Write All")
        zero_btn  = QPushButton("Zero All")
        write_btn.clicked.connect(lambda: self._write_all())
        zero_btn.clicked.connect(self._zero_all)
        bottom.addWidget(write_btn)
        bottom.addWidget(zero_btn)
        bottom.addStretch()
        root.addLayout(bottom)

        # ── sweep panel ──
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.HLine)
        sep4.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep4)

        sweep_group = QGroupBox("Sweep")
        sg = QVBoxLayout(sweep_group)
        sg.setSpacing(6)

        # row 1: pin, start, stop
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

        # row 2: steps vs step size dropdown + active input + derived label
        row2 = QHBoxLayout()

        self._sweep_mode_combo = QComboBox()
        self._sweep_mode_combo.addItem("Steps", "steps")
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

        # row 3: dwell, run/stop
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

        # connect signals that update the derived label
        self.sweep_start.valueChanged.connect(self._update_sweep_derived)
        self.sweep_stop.valueChanged.connect(self._update_sweep_derived)
        self.sweep_steps_sb.valueChanged.connect(self._update_sweep_derived)
        self.sweep_stepsize_sb.valueChanged.connect(self._update_sweep_derived)

        # ── wave panel ──
        sep5 = QFrame()
        sep5.setFrameShape(QFrame.Shape.HLine)
        sep5.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep5)

        wave_group = QGroupBox("Waveform Output")
        wg = QVBoxLayout(wave_group)
        wg.setSpacing(6)

        # row 1: pin, waveform type
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
        self.wave_type_combo.addItem("Sine", "sin")
        self.wave_type_combo.addItem("Cosine", "cos")
        self.wave_type_combo.setFixedWidth(80)
        wrow1.addWidget(self.wave_type_combo)
        wrow1.addStretch()
        wg.addLayout(wrow1)

        # row 2: frequency, amplitude, offset
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

        # row 3: tick rate, run/stop
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

    # ── sweep mode toggle ──────────────────────────────────────────────────────

    def _on_sweep_mode_toggled(self):
        steps_mode = self._sweep_mode_combo.currentData() == "steps"
        self.sweep_steps_sb.setVisible(steps_mode)
        self.sweep_stepsize_sb.setVisible(not steps_mode)
        self._update_sweep_derived()

    def _update_sweep_derived(self):
        start = self.sweep_start.value()
        stop  = self.sweep_stop.value()
        span  = abs(stop - start)
        unit  = self.card_session.unit if self.card_session else ""
        steps_mode = self._sweep_mode_combo.currentData() == "steps"

        if steps_mode:
            steps = self.sweep_steps_sb.value()
            if steps > 1:
                size = span / (steps - 1)
                self.sweep_derived_lbl.setText(f"→ step size: {size:.4f} {unit}")
            else:
                self.sweep_derived_lbl.setText("")
        else:
            size = self.sweep_stepsize_sb.value()
            if size > 0 and span > 0:
                steps = int(round(span / size)) + 1
                self.sweep_derived_lbl.setText(f"→ {steps} steps")
            else:
                self.sweep_derived_lbl.setText("")

    def _compute_steps(self) -> int:
        start = self.sweep_start.value()
        stop  = self.sweep_stop.value()
        if self._sweep_mode_combo.currentData() == "steps":
            return self.sweep_steps_sb.value()
        else:
            size = self.sweep_stepsize_sb.value()
            span = abs(stop - start)
            if size <= 0:
                return 2
            return max(2, int(round(span / size)) + 1)

    # ── card loading ───────────────────────────────────────────────────────────

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

        # wave panel ranges
        half_range = (cs.max_val - cs.min_val) / 2
        self.wave_amp_sb.setRange(0.0, half_range)
        self.wave_amp_sb.setValue(min(1.0, half_range))
        self.wave_amp_sb.setSuffix(f" {cs.unit}")
        self.wave_offset_sb.setRange(cs.min_val, cs.max_val)
        self.wave_offset_sb.setValue((cs.min_val + cs.max_val) / 2)
        self.wave_offset_sb.setSuffix(f" {cs.unit}")

    # ── sweep control ──────────────────────────────────────────────────────────

    def _start_sweep(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected:
                cs.connect()
            pin      = self.sweep_pin_combo.currentData()
            start    = self.sweep_start.value()
            stop     = self.sweep_stop.value()
            steps    = self._compute_steps()
            dwell_ms = self.sweep_dwell_sb.value()
            cs.start_sweep(pin, start, stop, steps, dwell_ms,
                           self._on_sweep_step, self._on_sweep_done)
            self.sweep_run_btn.setEnabled(False)
            self.sweep_stop_btn.setEnabled(True)
            self._status(f"Sweep running — Pin {pin:02d}  {start:.3f} → {stop:.3f} {cs.unit}  {steps} steps")
        except Exception as e:
            self._status(f"Sweep error: {e}")

    def _stop_sweep(self):
        cs = self.card_session
        if cs:
            cs.stop_sweep()
        self.sweep_run_btn.setEnabled(True)
        self.sweep_stop_btn.setEnabled(False)
        self._status("Sweep stopped")

    def _on_sweep_step(self, pin: int, value: float, step: int, total: int):
        """Called after each step arrives — updates spinbox/slider live."""
        self._syncing = True
        self.spinboxes[pin].setValue(value)
        self.sliders[pin].setValue(int(value * 100))
        self._syncing = False
        cs = self.card_session
        self._status(f"Sweep — Pin {pin:02d} at {value:.3f} {cs.unit if cs else ''}  (step {step}/{total})")

    def _on_sweep_done(self):
        self.sweep_run_btn.setEnabled(True)
        self.sweep_stop_btn.setEnabled(False)
        self._status("Sweep complete")

    # ── pin controls ───────────────────────────────────────────────────────────

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

    def _write_all(self, focused_pin=None):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected:
                cs.connect()
            values = [sb.value() for sb in self.spinboxes]
            cs.ramp_to(values)
            if focused_pin is not None:
                msg = f"Ramping pin {focused_pin:02d} → {values[focused_pin]:.3f} {cs.unit}  (all pins ramping)"
            else:
                msg = "Ramping: " + "  ".join(f"P{i}:{v:.2f}" for i, v in enumerate(values)) + f" {cs.unit}"
            self._status(msg)
        except Exception as e:
            self._status(f"Error: {e}")

    def _zero_all(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected:
                cs.connect()
            self._syncing = True
            for sb in self.spinboxes: sb.setValue(0.0)
            for sl in self.sliders:   sl.setValue(0)
            self._syncing = False
            cs.zero()
            self._status("Ramping all pins to zero")
        except Exception as e:
            self._status(f"Error: {e}")

    def _start_wave(self):
        cs = self.card_session
        if cs is None: return
        try:
            if not cs.connected:
                cs.connect()
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
            self._status(f"Wave running — Pin {pin:02d}  {waveform}  {freq}Hz  amp={amplitude} {cs.unit}  offset={offset} {cs.unit}")
        except Exception as e:
            self._status(f"Wave error: {e}")

    def _stop_wave(self):
        cs = self.card_session
        if cs:
            cs.stop_wave()
        self.wave_run_btn.setEnabled(True)
        self.wave_stop_btn.setEnabled(False)
        self._status("Wave stopped")

    def _on_wave_tick(self, pin: int, value: float):
        """Update spinbox/slider live during wave output."""
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
        self.setWindowTitle("DAQ Control")
        self.setMinimumWidth(HOME_WINDOW_W)

        self.card_sessions = {
            i: CardSession(i) for i, info in CARDS.items() if info["available"]
        }

        self.stacked = QStackedWidget()
        self.setCentralWidget(self.stacked)

        # main view
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
        mv.addStretch()

        self.pin_view = PinConfigView()
        self.pin_view.back_clicked.connect(self._show_main)

        self.stacked.addWidget(main_view)
        self.stacked.addWidget(self.pin_view)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _open_card(self, idx: int):
        cs = self.card_sessions[idx]
        try:
            if not cs.connected:
                cs.connect()
            self.status_bar.showMessage(
                f"Connected — {CARDS[idx]['label']} — {cs.min_val} to {cs.max_val} {cs.unit}"
            )
        except Exception as e:
            self.status_bar.showMessage(f"Connection error: {e}")
            return
        self.pin_view.load_card(cs)
        self.stacked.setCurrentIndex(1)
        self.daq_box.refresh()
        self.resize(PIN_WINDOW_W, PIN_WINDOW_H)

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