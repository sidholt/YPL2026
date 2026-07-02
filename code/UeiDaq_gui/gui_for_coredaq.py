import sys
import os
import json
import time
import threading
import numpy as np
import scipy.io
from dataclasses import dataclass
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtCore import QThread, Signal, Slot, QTimer
import pyqtgraph as pg
from GUI_format_coredaq import Ui_MainWindow
from hardware.DG4102 import DG4102
from hardware.laser_tsl_550 import TSL550
from hardware.HP3488A import HP3488A
from hardware.laser_hp_8168F import HP8168F
from hardware.KEITH2400 import KEITH2400
from hardware.coredaq import CoreDAQ

from threads import PulseWorker, PulseSequenceWorker, MuxWorker, SweepWorker
from threads.daq_reader_coredaq import DaqReaderWorker


def make_timestamp() -> str:
    """Return a timestamp string with millisecond suffix to prevent filename collisions."""
    t = time.time()
    return time.strftime("%Y%m%d_%H%M%S", time.localtime(t)) + f"_{int((t % 1) * 1000):03d}ms"


EXP_STATIC      = 0   # steady-state snapshot after each pulse
EXP_HISTORY     = 1   # save the 1 kHz circular buffer on stop
EXP_QUAD_STATIC = 2   # 4-device sequential 30 ms snapshot with laser switching

EXP_DESCRIPTIONS = {
    EXP_STATIC: (
        "Static snapshot: 10 steady-state power readings captured ~100 ms after "
        "each pulse. Saved together when experiment stops."
    ),
    EXP_HISTORY: (
        "1 kHz history: the continuous 4-hour circular buffer is saved to file "
        "when the experiment is stopped."
    ),
    EXP_QUAD_STATIC: (
        "Quad snapshot: after each pulse, 30 ms of data is captured for the "
        "active device, then the same-column partner, then both devices in the "
        "other column after switching lasers. Saved on experiment stop. "
        "Data shape: (n_pulses, 4_positions, 4_channels, 30_samples)."
    ),
}


@dataclass
class ActiveDevice:
    
    #each junction has these relavent characteristics that define it
    position: str        # "00", "01", "10", "11"
    heater_type: str     # "pn" or "pin"
    mux_config: list     # relay list from mux_channels
    out_channel: int     # CoreDAQ output photodetector index
    ref_channel: int     # CoreDAQ reference photodetector index


    @property
    def key(self) -> str:
        return f"{self.position}_{self.heater_type}"


# ── Config loading & validation ──────────────────────────────────────────────

def load_device_config(path="device_config.json"):
    """
    Load and validate device_config.json.

    Checks that every device entry has the required pulse parameter fields.
    Raises ValueError at startup (not mid-calibration) if config is malformed.
    """
    with open(path, 'r') as f:
        config = json.load(f)

    for key, dev in config.get("devices", {}).items():
        for pulse_name in ("amorph_reset", "cryst_reset", "amorph_test"):
            if pulse_name not in dev:
                raise ValueError(f"Device '{key}' missing '{pulse_name}' config")
            required = {"rise_us", "fall_us", "width_us", "on_time_us"}
            if pulse_name != "amorph_test":
                required.add("voltage")
            missing = required - set(dev[pulse_name].keys())
            if missing:
                raise ValueError(f"Device '{key}.{pulse_name}' missing: {missing}")
        if "mux" not in dev:
            raise ValueError(f"Device '{key}' missing 'mux' field")

    if "daq_channels" not in config:
        raise ValueError("Config missing 'daq_channels' section")

    print(f"Loaded and validated device config from {path}")
    return config



#define the main class of the program as an class that inherits from QT's QMainWindow base class
class ExperimentControlApp(QMainWindow):
    #define the software based triggers pulse and sequence send data requiring that there type definitions be included in the intialization 
    trigger_pulse    = Signal(int, float, float, float, float, float, str)
    trigger_mux      = Signal()
    trigger_sweep    = Signal()
    trigger_sequence = Signal(list, object)

    DEVICE_MUX_CONFIGS = {}

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # ── config & device identity ──────────────────────────────────────
        self.device_config      = load_device_config()
        self.DEVICE_MUX_CONFIGS = self.device_config.get("mux_channels", {})
        self._daq_channels      = self.device_config.get("daq_channels", {})

        self._device_type   = "pn"
        self.active_devices = self._build_active_devices() #create instances of all 4 junctions as ActiveDevice objects see the function for more details
        self._cal_device: ActiveDevice = self.active_devices["01"] #this will be the active device 

        #make it so that only one thread can access the following variables at one time 
        self._cal_device_lock = threading.Lock()
        self._experiment_data_lock = threading.Lock()
        self._pulse_lock = threading.Lock()

        #define empty memory to store future experimental data and define variables to describe the state of the experiment 
        self.experiment_type = EXP_STATIC
        self.experiment_on   = False
        self.experiment_data = []

        #these are used to update the display information like turning the active device in the matrix red 
        self._meta = {}
        self._save_folder = ""
        self._selected_table_pos = None

        

        # ── display / experiment state ────────────────────────────────────────
        self.plot_mode       = 'watts'
        self.pd_gains        = [0, 0, 0, 0]   # per-head gains H1..H4 only needed if linear coredaq being used

        print("Starting hardware init…")
        self.init_hardware()
        print("Hardware init done")

        self.init_daq_reader_thread()
        self.start_plotting()

        self.init_pulse_thread()
        self.init_pulse_sequence_thread()
        self.init_mux_thread()
        self.init_sweep_thread()

        self._connect_ui()
        self._init_device_config_dialog()

    # ── device identity management ────────────────────────────────────────

    def _build_active_devices(self) -> dict:
        """Build ActiveDevice objects for all crossbar positions from config."""
        #this is built to scale with higher dimension crossbars hopefully easily by adding more dimensions to the .json file 
        shape = self.device_config.get("crossbar_shape", [2, 2])
        positions = []
        for r in range(2):      
            for c in range(2):  
                positions.append(f"{r}{c}")
        devices = {}
        for pos in positions:
            ch_info = self._daq_channels.get(pos, {"output": 0, "reference": 0})
            devices[pos] = ActiveDevice(
                position=pos,
                heater_type=self._device_type,
                mux_config=list(self.DEVICE_MUX_CONFIGS.get(pos, [])),
                out_channel=ch_info["output"],
                ref_channel=ch_info["reference"],
            )
        return devices

    def get_active_cal_device(self) -> ActiveDevice:
        """getter for device under test. thread safe because wrapped in a with blck dependent on the cal_device_lock"""
        with self._cal_device_lock:
            return self._cal_device


    @Slot(str)
    def set_calibration_device(self, position: str):
        """setter for the device under test."""
        with self._cal_device_lock:
            self._cal_device = self.active_devices[position]
            device = self._cal_device

        print(f"Calibration device → {device.key} "
              f"(DAQ out={device.out_channel}, ref={device.ref_channel})")
        self._sync_filename_hint(device.key)

    # ── UI wiring ─────────────────────────────────────────────────────────────
    def _connect_ui(self):
        ui = self.ui

        ui.Santec_power_on.clicked.connect(self.turn_santec_on)
        ui.Santec_power_off.clicked.connect(self.turn_santec_off)
        ui.HP_power_on.clicked.connect(self.turn_hp_on)
        ui.HP_power_off.clicked.connect(self.turn_hp_off)

        # Device selection table — single cell highlights red, updates active device
        ui.Device_ID_table.cellClicked.connect(self._on_device_table_clicked)
        from PySide6.QtWidgets import QAbstractItemView
        ui.Device_ID_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        ui.Device_ID_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Unified pulse buttons — operate on active device, no MUX check
        ui.send_amorph.clicked.connect(self._on_send_amorph)
        ui.send_cryst.clicked.connect(self._on_send_cryst)
        ui.run_sequence.clicked.connect(self._on_run_sequence)

        # Gain controls — one spinbox per head, each wired independently
        _gain_spinboxes = [
            ui.core_daq_gain_input_1,
            ui.core_daq_gain_input_2,
            ui.core_daq_gain_input_3,
            ui.core_daq_gain_input_4,
        ]
        for head_idx, sb in enumerate(_gain_spinboxes):
            sb.valueChanged.connect(lambda val, h=head_idx: self._on_gain_changed(h, val))
        ui.Core_daq_autogain.clicked.connect(self._on_autogain)
        ui.coredaq_zeroing_button.clicked.connect(self._on_zero_cal)

        if hasattr(ui, 'pushButton'):
            ui.pushButton.clicked.connect(self.save_config_to_json)

        ui.Santec_sweep_power_on.clicked.connect(self.start_laser_sweep)
        ui.start_experimen_push_button.clicked.connect(self.turn_experiment_on)
        ui.stop_experimen_push_button.clicked.connect(self.turn_experiment_off)
        ui.experiment_type_select.currentIndexChanged.connect(self._on_experiment_type_changed)
        if hasattr(ui, 'plot_voltage_update'):
            ui.plot_voltage_update.clicked.connect(self._set_plot_volts)
        if hasattr(ui, 'plot_wattage_rough'):
            ui.plot_wattage_rough.clicked.connect(self._set_plot_watts)

        if hasattr(ui, 'click_save_last_4_seconds_data'):
            ui.click_save_last_4_seconds_data.clicked.connect(self.save_history_data)

    # ── experiment type ───────────────────────────────────────────────────────
    @Slot(int)
    def _on_experiment_type_changed(self, idx: int):
        self.experiment_type = idx
        self.ui.experiemnt_onOff_description_label.setText(
            EXP_DESCRIPTIONS.get(idx, ""))

    def _set_plot_watts(self):
        self.plot_mode = 'watts'
        self.ui.live_transmission_line_chart_2.plotItem.setLabel('left', 'Power', units='W')
        print("Plot: calibrated power (W)")

    # ── PD gain — each spinbox controls its own head independently ───────────
    def _on_gain_changed(self, head_idx: int, val: int):
        """Set gain for a single CoreDAQ head (head_idx 0-based → head 1-4). LINEAR only."""
        self.pd_gains[head_idx] = val
        if self.photoDAQ is not None and self.photoDAQ.frontend_type() == CoreDAQ.FRONTEND_LINEAR:
            try:
                self.photoDAQ.set_gain(head_idx + 1, val)
            except Exception as e:
                print(f"Gain set error H{head_idx + 1}: {e}")

    def _gain_metadata(self) -> dict:
        """Gain fields included in every saved .mat."""
        gain_labels = [
            CoreDAQ.GAIN_LABELS[g] if 0 <= g < 8 else 'unknown'
            for g in self.pd_gains
        ]

        if self.photoDAQ:
            frontend_type = self.photoDAQ.frontend_type()
            detector_type = self.photoDAQ.detector_type()
            wavelength_nm = self.photoDAQ.get_wavelength_nm()
        else:
            frontend_type = 'unknown'
            detector_type = 'unknown'
            wavelength_nm = 0.0

        return {
            'pd_gain_indices': self.pd_gains,   # [H1, H2, H3, H4]
            'gain_labels':     gain_labels,
            'frontend_type':   frontend_type,
            'detector_type':   detector_type,
            'wavelength_nm':   wavelength_nm,
        }

    # ── device table ─────────────────────────────────────────────────────────

    @Slot(int, int)
    def _on_device_table_clicked(self, row: int, col: int):
        """Single-select: highlight clicked cell red; deselect previous; update active device."""
        from PySide6.QtGui import QBrush, QColor
        table = self.ui.Device_ID_table
        new_pos = f"{row}{col}"

        # Reset previous selection to default foreground
        if self._selected_table_pos is not None:
            pr, pc = int(self._selected_table_pos[0]), int(self._selected_table_pos[1])
            prev = table.item(pr, pc)
            if prev:
                prev.setForeground(QBrush(QColor("black")))

        # Highlight new selection
        item = table.item(row, col)
        if item:
            item.setForeground(QBrush(QColor("red")))
        self._selected_table_pos = new_pos

        # Update calibration device if position is in the current 2×2 set
        if new_pos in self.active_devices:
            self.set_calibration_device(new_pos)
            self._load_pulse_params_to_gui(self.active_devices[new_pos].key)

    # ── unified pulse/sequence buttons ────────────────────────────────────────

    def _on_send_amorph(self):
        """Send amorphization pulse for the active device (no MUX check)."""
        device  = self.get_active_cal_device()
        voltage = self.ui.amorph_pulse_character_voltage_input.value()
        self.send_pulse_threaded(source=1, voltage=voltage, device_id=device.key)

    def _on_send_cryst(self):
        """Send crystallization pulse for the active device (no MUX check)."""
        device  = self.get_active_cal_device()
        voltage = self.ui.cryst_pulse_character_voltage_input.value()
        self.send_pulse_threaded(source=2, voltage=voltage, device_id=device.key)

    def _on_run_sequence(self):
        """Run sequence from textEdit for the active device."""
        device = self.get_active_cal_device()
        self.run_sequence(device.position, self.ui.textEdit)

    # ── autogain ──────────────────────────────────────────────────────────────

    def _on_autogain(self):
        """Per-head autogain via snapshot_W(autogain=True, return_debug=True). LINEAR only."""
        if self.photoDAQ is None:
            print("Autogain: CoreDAQ not connected")
            return
        if self.photoDAQ.frontend_type() != CoreDAQ.FRONTEND_LINEAR:
            print("Autogain: not available on LOG frontend (no gain stages)")
            return
        _spinboxes = [
            self.ui.core_daq_gain_input_1,
            self.ui.core_daq_gain_input_2,
            self.ui.core_daq_gain_input_3,
            self.ui.core_daq_gain_input_4,
        ]
        try:
            # Pause only the reader background loop — not stop_plotting — so the
            # display timer keeps running but the serial port is exclusively ours.
            # Without this, concurrent SNAP commands from both threads corrupt
            # autogain's ADC reads, driving every channel to gain 7.
            self.daq_reader.pause()
            try:
                watts, mv, gains = self.photoDAQ.snapshot_W(
                    autogain=True, return_debug=True,
                    n_frames=4, timeout_s=1.0,
                    min_mv=100.0, max_mv=3000.0,
                    max_iters=10, settle_s=0.05,
                )
            finally:
                self.daq_reader.resume()
            gains_int = [int(g) for g in gains]
            self.pd_gains = gains_int
            for sb, g in zip(_spinboxes, gains_int):
                sb.blockSignals(True)
                sb.setValue(g)
                sb.blockSignals(False)
            print(f"Autogain: H1-H4 gains={gains_int}, "
                  f"watts=[{', '.join(f'{w:.2e}' for w in watts)}]")
        except Exception as e:
            import traceback
            print(f"Autogain error: {e}\n{traceback.format_exc()}")

    def _on_zero_cal(self):
        """Soft-zero all channels using a dark snapshot (LINEAR frontend only).

        Calls soft_zero_from_snapshot(): takes 32 frames at the current
        acquisition settings and stores the mean ADC codes as the active
        zero offsets.  Block / turn off all light sources before clicking.
        """
        if self.photoDAQ is None:
            print("Zero cal: CoreDAQ not connected")
            return
        if self.photoDAQ.frontend_type() != CoreDAQ.FRONTEND_LINEAR:
            print("Zero cal: not available on LOG frontend")
            return
        try:
            self.daq_reader.pause()
            try:
                codes, gains = self.photoDAQ.soft_zero_from_snapshot(n_frames=32, settle_s=0.2)
            finally:
                self.daq_reader.resume()
            gains_int = [int(g) for g in gains]
            print(f"Zero cal: codes={[int(c) for c in codes]}, gains={gains_int}")
        except Exception as e:
            import traceback
            print(f"Zero cal error: {e}\n{traceback.format_exc()}")

    # ── device config dialog ──────────────────────────────────────────────────

    def _init_device_config_dialog(self):
        from PySide6.QtUiTools import QUiLoader
        dialog_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "ncr_data", "qt_design_file", "device_config_dialog.ui"
        )
        self._config_dialog = QUiLoader().load(dialog_path, self)
        self._config_dialog.setWindowTitle("Device Config")
        # Sync heater type BEFORE connecting signals to avoid spurious callbacks
        self._config_dialog.HEATER_TYPE_ID.setCurrentText(self._device_type.upper())
        # Wire toolbar action if present
        if hasattr(self.ui, 'actionDevice_Config'):
            self.ui.actionDevice_Config.triggered.connect(self._config_dialog.show)
        # Auto-update folder path when any metadata combo changes
        for combo in [
            self._config_dialog.MPW_RUN_ID_SELECTOR,
            self._config_dialog.CHIP_ID_SELECTOR,
            self._config_dialog.DEVICE_TYPE_SELECTOR,
        ]:
            combo.currentTextChanged.connect(self._auto_update_save_folder)
        self._config_dialog.HEATER_TYPE_ID.currentTextChanged.connect(
            self._on_dialog_heater_type_changed)
        self._config_dialog.FOLDER_BROWSER_PUSHBUTTON.clicked.connect(
            self._browse_save_folder)
        self._config_dialog.accepted.connect(self._apply_device_config)
        # Restore last session's dialog selections, then update save folder
        self._load_session_state()
        self._auto_update_save_folder()
        # Seed the filename hint from the initially active device
        self._sync_filename_hint(self._cal_device.key)

    def _auto_update_save_folder(self):
        """Construct OneDrive save path from dialog metadata and update the path field."""
        data_root = self.device_config.get("data_root", "")
        if not data_root:
            return
        d     = self._config_dialog
        mpw   = d.MPW_RUN_ID_SELECTOR.currentText().strip()
        chip  = d.CHIP_ID_SELECTOR.currentText().strip()
        dtype = d.DEVICE_TYPE_SELECTOR.currentText().strip()
        htype = d.HEATER_TYPE_ID.currentText().strip().upper()
        if not all([mpw, chip, dtype, htype]):
            return
        path = os.path.join(data_root, mpw, chip, dtype, htype)
        d.datafilelocation_DIALOG_CONFIG.setText(path)
        # Keep the main-window folder display in sync
        if hasattr(self.ui, 'folder_path_for_save'):
            self.ui.folder_path_for_save.setPlainText(path)

    def _on_dialog_heater_type_changed(self, heater_type_text: str):
        heater_type = heater_type_text.lower()
        pos = self.get_active_cal_device().position
        self._load_pulse_params_to_gui(f"{pos}_{heater_type}")
        self._auto_update_save_folder()
        self._sync_filename_hint(f"{pos}_{heater_type}")

    def _load_pulse_params_to_gui(self, device_key: str):
        dev = self.device_config.get("devices", {}).get(device_key)
        if dev is None:
            print(f"_load_pulse_params_to_gui: no config for '{device_key}' — clearing fields")
            for w in (self.ui.cryst_pulse_character_voltage_input,
                      self.ui.cryst_pulse_character_leading_input,
                      self.ui.cryst_pulse_character_falling_input,
                      self.ui.cryst_pulse_character_total_time_input,
                      self.ui.amorph_pulse_character_voltage_input,
                      self.ui.amorph_pulse_character_leading_input,
                      self.ui.amorph_pulse_character_falling_input,
                      self.ui.amorph_pulse_character_total_time_input):
                w.setValue(0)
            return
        cr = dev["cryst_reset"]
        ar = dev["amorph_reset"]
        self.ui.cryst_pulse_character_voltage_input.setValue(cr["voltage"])
        self.ui.cryst_pulse_character_leading_input.setValue(cr["rise_us"])
        self.ui.cryst_pulse_character_falling_input.setValue(cr["fall_us"])
        self.ui.cryst_pulse_character_total_time_input.setValue(cr["width_us"])
        self.ui.amorph_pulse_character_voltage_input.setValue(ar["voltage"])
        self.ui.amorph_pulse_character_leading_input.setValue(ar["rise_us"])
        self.ui.amorph_pulse_character_falling_input.setValue(ar["fall_us"])
        self.ui.amorph_pulse_character_total_time_input.setValue(ar["width_us"])

    def _apply_device_config(self):
        d = self._config_dialog
        heater_type = d.HEATER_TYPE_ID.currentText().lower()
        self._device_type   = heater_type
        self.active_devices = self._build_active_devices()
        with self._cal_device_lock:
            self._cal_device = self.active_devices[self._cal_device.position]
        folder = d.datafilelocation_DIALOG_CONFIG.text().strip()
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                print(f"Warning: could not create save folder '{folder}': {e}")
            self._save_folder = folder
        self._meta = {
            'mpw_run_id':  d.MPW_RUN_ID_SELECTOR.currentText(),
            'chip_id':     d.CHIP_ID_SELECTOR.currentText(),
            'device_type': d.DEVICE_TYPE_SELECTOR.currentText(),
            'heater_type': d.HEATER_TYPE_ID.currentText(),
            'pcm_type':    d.PCM_TYPE_SELECTOR.currentText(),
            'notes':       d.NOTES_TEXT_EDIT.toPlainText(),
        }
        for combo in [d.MPW_RUN_ID_SELECTOR, d.CHIP_ID_SELECTOR,
                      d.DEVICE_TYPE_SELECTOR, d.PCM_TYPE_SELECTOR]:
            text = combo.currentText()
            if text and combo.findText(text) == -1:
                combo.addItem(text)
        self._save_session_state()
        print(f"Device config applied: {self._meta}")

    _SESSION_STATE_FILE = "session_state.json"

    def _save_session_state(self):
        """Persist dialog field selections for next session."""
        d = self._config_dialog
        state = {
            'mpw_run_id':  d.MPW_RUN_ID_SELECTOR.currentText(),
            'chip_id':     d.CHIP_ID_SELECTOR.currentText(),
            'device_type': d.DEVICE_TYPE_SELECTOR.currentText(),
            'heater_type': d.HEATER_TYPE_ID.currentText(),
            'pcm_type':    d.PCM_TYPE_SELECTOR.currentText(),
            'notes':       d.NOTES_TEXT_EDIT.toPlainText(),
        }
        try:
            with open(self._SESSION_STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"session_state save error: {e}")

    def _load_session_state(self):
        """Restore dialog fields from the last saved session."""
        try:
            with open(self._SESSION_STATE_FILE, 'r') as f:
                state = json.load(f)
        except FileNotFoundError:
            return
        except Exception as e:
            print(f"session_state load error: {e}")
            return
        d = self._config_dialog
        for combo, key in [
            (d.MPW_RUN_ID_SELECTOR,  'mpw_run_id'),
            (d.CHIP_ID_SELECTOR,     'chip_id'),
            (d.DEVICE_TYPE_SELECTOR, 'device_type'),
            (d.HEATER_TYPE_ID,       'heater_type'),
            (d.PCM_TYPE_SELECTOR,    'pcm_type'),
        ]:
            text = state.get(key, '').strip()
            if text:
                if combo.findText(text) == -1:
                    combo.addItem(text)
                combo.setCurrentText(text)
        notes = state.get('notes', '')
        if notes:
            d.NOTES_TEXT_EDIT.setPlainText(notes)

    def _browse_save_folder(self):
        from PySide6.QtWidgets import QFileDialog
        current = self._config_dialog.datafilelocation_DIALOG_CONFIG.text()
        folder  = QFileDialog.getExistingDirectory(
            self, "Select Save Folder", current or os.getcwd())
        if folder:
            self._config_dialog.datafilelocation_DIALOG_CONFIG.setText(folder)

    def _meta_save_dict(self) -> dict:
        d = {f'meta_{k}': v for k, v in self._meta.items()}
        d['meta_backend'] = 'coredaq'
        try:
            d['meta_laser_wavelength_nm'] = self.ui.HP_wavelength_input.value()
            d['meta_laser_power_mw']      = self.ui.HP_power_input.value()
        except Exception:
            pass
        return d

    def save_config_to_json(self):
        """Write the current cryst/amorph GUI parameter fields back to device_config.json."""
        device = self.get_active_cal_device()
        device_key = device.key
        config_path = "device_config.json"
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            dev = config["devices"].get(device_key)
            if dev is None:
                print(f"save_config_to_json: device '{device_key}' not in config")
                return

            dev["cryst_reset"]["voltage"]  = self.ui.cryst_pulse_character_voltage_input.value()
            dev["cryst_reset"]["rise_us"]  = self.ui.cryst_pulse_character_leading_input.value()
            dev["cryst_reset"]["fall_us"]  = self.ui.cryst_pulse_character_falling_input.value()
            dev["cryst_reset"]["width_us"] = self.ui.cryst_pulse_character_total_time_input.value()

            dev["amorph_reset"]["voltage"]  = self.ui.amorph_pulse_character_voltage_input.value()
            dev["amorph_reset"]["rise_us"]  = self.ui.amorph_pulse_character_leading_input.value()
            dev["amorph_reset"]["fall_us"]  = self.ui.amorph_pulse_character_falling_input.value()
            dev["amorph_reset"]["width_us"] = self.ui.amorph_pulse_character_total_time_input.value()

            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
            print(f"Saved pulse params for '{device_key}' → {config_path}")

        except Exception as e:
            import traceback
            print(f"save_config_to_json error: {e}\n{traceback.format_exc()}")

    # ── thread init ───────────────────────────────────────────────────────────
    def init_pulse_thread(self):
        self.pulse_thread = QThread()
        self.pulse_worker = PulseWorker()
        self.pulse_worker.moveToThread(self.pulse_thread)
        self.trigger_pulse.connect(self.pulse_worker.send_pulse)
        self.pulse_worker.finished.connect(self.handle_pulse_finished)
        self.pulse_worker.error.connect(self.handle_pulse_error)
        self.pulse_worker.pulse_complete.connect(self.capture_experiment_data)
        self.pulse_thread.start()
        self.pulse_worker.set_hardware(
            self.keith1, self.awg, self.MUXER, self,
            pulse_lock=self._pulse_lock,
        )

    def init_pulse_sequence_thread(self):
        self.pulse_sequence_thread = QThread()
        self.pulse_sequence_worker = PulseSequenceWorker()
        self.pulse_sequence_worker.moveToThread(self.pulse_sequence_thread)
        self.trigger_sequence.connect(self.pulse_sequence_worker.run_pulse_sequence)
        self.pulse_sequence_worker.progress.connect(self.handle_sequence_progress)
        self.pulse_sequence_worker.pulse_complete.connect(self.capture_experiment_data)
        self.pulse_sequence_worker.sequence_data_ready.connect(self.save_sequence_daq_data)
        self.pulse_sequence_thread.start()
        self.pulse_sequence_worker.set_hardware(
            self.keith1, self.awg, self.MUXER,
            daq_reader=self.daq_reader,
            pulse_lock=self._pulse_lock,
        )

    def init_mux_thread(self):
        self.mux_thread = QThread()
        self.mux_worker = MuxWorker()
        self.mux_worker.moveToThread(self.mux_thread)
        self.trigger_mux.connect(self.mux_worker.configure_mux)
        self.mux_worker.finished.connect(self.handle_mux_finished)
        self.mux_worker.error.connect(self.handle_mux_error)
        self.mux_thread.start()
        self.mux_worker.set_hardware(self.MUXER, self.awg, pulse_lock=self._pulse_lock)

    def init_sweep_thread(self):
        self.sweep_thread = QThread()
        self.sweep_worker = SweepWorker()
        self.sweep_worker.moveToThread(self.sweep_thread)
        self.trigger_sweep.connect(self.sweep_worker.run_sweep)
        self.sweep_worker.finished.connect(self.handle_sweep_finished)
        self.sweep_worker.error.connect(self.handle_sweep_error)
        self.sweep_worker.progress.connect(self.handle_sweep_progress)
        self.sweep_worker.result.connect(self.handle_sweep_result)
        self.sweep_thread.start()
        self.sweep_worker.set_hardware(self.santec, self.photoDAQ)

    # ── hardware init ─────────────────────────────────────────────────────────
    def init_hardware(self):
        self.santec   = None
        self.hp       = None
        self.MUXER    = None
        self.awg      = None
        self.keith1   = None
        self.photoDAQ = None

        for name, factory, attr in [
            ("Santec",   lambda: TSL550(device_name='Prologix::1::ASRL4::INSTR', force_connect=True),  'santec'),
            ("HP Laser", lambda: HP8168F(device_name='Prologix::9::ASRL4::INSTR', force_connect=True), 'hp'),
            ("MUX",      lambda: HP3488A(device_name='Prologix::10::ASRL4::INSTR', force_connect=True), 'MUXER'),
            ("Keithley", lambda: KEITH2400(device_name='Prologix::3::ASRL4::INSTR', force_connect=True), 'keith1'),
            ("AWG",      lambda: DG4102(device_name='TCPIP0::172.28.5.1::inst0::INSTR'), 'awg'),
        ]:
            try:
                setattr(self, attr, factory())
                print(f"{name} connected.")
                if attr == 'keith1':
                    self.keith1.write('*RST')
                    print("Keithley reset (*RST) sent.")
            except Exception as e:
                print(f"{name} connection failed: {e}")

        try:
            ports = CoreDAQ.find()
            if not ports:
                raise RuntimeError("No CoreDAQ device found")
            self.photoDAQ = CoreDAQ(port=ports[0])
            self.photoDAQ.set_wavelength_nm(1550.0)
            print(f"CoreDAQ connected: {self.photoDAQ.idn()} "
                  f"| {self.photoDAQ.frontend_type()} | {self.photoDAQ.detector_type()}")
            if self.photoDAQ.frontend_type() == CoreDAQ.FRONTEND_LINEAR:
                print("CoreDAQ calibration table (slope mV/W, intercept mV):")
                for h in range(self.photoDAQ.NUM_HEADS):
                    for g in range(self.photoDAQ.NUM_GAINS):
                        s = self.photoDAQ._cal_slope[h][g]
                        i = self.photoDAQ._cal_intercept[h][g]
                        print(f"  H{h+1} G{g}: slope={s:.4g} mV/W  intercept={i:.4g} mV")
            else:
                lut_size = len(self.photoDAQ._loglut_V_V) if self.photoDAQ._loglut_V_V else 0
                print(f"CoreDAQ LOG LUT: {lut_size} points, deadband={self.photoDAQ.get_log_deadband_mV():.0f} mV")
        except Exception as e:
            print(f"CoreDAQ connection failed: {e}")
            self.photoDAQ = None

        print("Hardware initialization complete.")

    def closeEvent(self, event):
        print("Closing GUI…")
        self.turn_santec_off()
        self.turn_hp_off()
        self.stop_plotting()

        for attr in ('pulse_thread','pulse_sequence_thread','mux_thread','sweep_thread'):
            t = getattr(self, attr, None)
            if t:
                t.quit(); t.wait()

        if hasattr(self, 'daq_reader'):
            self.daq_reader.stop()
        if hasattr(self, 'daq_reader_thread'):
            self.daq_reader_thread.quit()
            self.daq_reader_thread.wait()

        time.sleep(0.3)

        for device, name in [(self.santec,'Santec'),(self.hp,'HP'),(self.MUXER,'MUX'),
                              (self.awg,'AWG'),(self.keith1,'Keithley'),(self.photoDAQ,'CoreDAQ')]:
            if device is not None:
                try:
                    device.close(); print(f"{name} closed.")
                except Exception as e:
                    print(f"{name} forced closed ({e})")
        event.accept()

    # ── laser control ─────────────────────────────────────────────────────────
    def turn_santec_on(self):
        try:
            self.santec.power      = self.ui.santec_power_input.value()
            self.santec.wavelength = self.ui.santec_nm_input.value()
            self.santec.shutter    = False
            self.ui.label_laser_status.setText("LASER IS ON")
            self.ui.label_laser_status.setStyleSheet("color: red; font-weight: bold;")
        except Exception as e:
            print(f"Santec on error: {e}")

    def turn_santec_off(self):
        try:
            self.santec.shutter = True
            self.ui.label_laser_status.setText("LASER IS OFF")
            self.ui.label_laser_status.setStyleSheet("color: black;")
        except Exception:
            pass

    def turn_hp_on(self):
        try:
            self.hp.power      = self.ui.HP_power_input.value()
            self.hp.wavelength = self.ui.HP_wavelength_input.value()
            self.hp.on_or_off  = True
            self.ui.label_laser_status_2.setText("LASER IS ON")
            self.ui.label_laser_status_2.setStyleSheet("color: red; font-weight: bold;")
        except Exception as e:
            print(f"HP on error: {e}")

    def turn_hp_off(self):
        try:
            self.hp.on_or_off = False
            self.ui.label_laser_status_2.setText("LASER IS OFF")
            self.ui.label_laser_status_2.setStyleSheet("color: black;")
        except Exception:
            pass

    # ── MUX ──────────────────────────────────────────────────────────────────
    def configure_mux_threaded(self, config):
        self.mux_worker.set_mux_config(config)
        self.trigger_mux.emit()

    # ── pulse helpers ─────────────────────────────────────────────────────────
    def send_pulse_threaded(self, source, voltage, device_id):
        if source == 1:
            rise  = self.ui.amorph_pulse_character_leading_input.value()    * 1e-6
            fall  = self.ui.amorph_pulse_character_falling_input.value()    * 1e-6
            width = self.ui.amorph_pulse_character_total_time_input.value() * 1e-6
        else:
            rise  = self.ui.cryst_pulse_character_leading_input.value()    * 1e-6
            fall  = self.ui.cryst_pulse_character_falling_input.value()    * 1e-6
            width = self.ui.cryst_pulse_character_total_time_input.value() * 1e-6
        on_time = rise + fall + width
        self.trigger_pulse.emit(source, voltage, on_time, rise, fall, width, device_id)

    # ── sequence ──────────────────────────────────────────────────────────────
    def parse_voltage_sequence(self, text_widget):
        try:
            text   = text_widget.toPlainText().replace('\n', ',')
            values = [float(x.strip()) for x in text.split(',') if x.strip()]
            if not values:
                print("Warning: no values in sequence text box")
            return values
        except ValueError:
            QMessageBox.warning(self, "Format Error", "Enter numbers separated by commas or newlines.")
            return []

    def run_sequence(self, mux_channel, text_widget):
        import re
        raw_text   = text_widget.toPlainText().strip()
        active_dev = self.active_devices.get(mux_channel)
        if active_dev is None:
            print(f"No active device for position '{mux_channel}'")
            return
        device_key = active_dev.key

        # Accept "n = x" (case-insensitive, flexible whitespace) as cyclic mode
        m = re.fullmatch(r'n\s*=\s*(\d+)', raw_text, re.IGNORECASE)
        if m:
            n_cycles = int(m.group(1))
            pulse_list = self.build_cycle_sequence(device_key, n_cycles)
            if pulse_list:
                print(f"Running cyclic sequence ({device_key}): {n_cycles} cycles")
                self.trigger_sequence.emit(pulse_list, None)
            return

        values = self.parse_voltage_sequence(text_widget)
        if not values:
            return

        pulse_list = self.build_pulse_sequence(device_key, values)
        if pulse_list:
            print(f"Running sequence ({device_key}): {len(values)} test voltages")
            self.trigger_sequence.emit(pulse_list, None)

    def build_pulse_sequence(self, device_key, test_voltages):
        devices = self.device_config.get("devices", {})
        device  = devices.get(device_key)
        if device is None:
            print(f"No device config for '{device_key}'")
            return []

        ar = device["amorph_reset"]
        cr = device["cryst_reset"]
        at = device["amorph_test"]

        mux_ch     = device["mux"]
        base_mux   = list(self.DEVICE_MUX_CONFIGS[mux_ch])
        cryst_mux  = list(base_mux)
        amorph_mux = list(base_mux)
        amorph_mux[0] = 301

        pulse_list = []
        for voltage in test_voltages:
            t_tgt = 0.0
            pulse_list.append({
                'source': 1, 'voltage': ar['voltage'],
                'on_time': ar['on_time_us']*1e-6,
                'rise_time': ar['rise_us']*1e-6, 'fall_time': ar['fall_us']*1e-6,
                'pulse_width': ar['width_us']*1e-6,
                'name': f"Amorph Reset ({device_key})", 'target_trans': 1.0,
                'mux_config': amorph_mux,
            })
            pulse_list.append({
                'source': 2, 'voltage': cr['voltage'],
                'on_time': cr['on_time_us']*1e-6,
                'rise_time': cr['rise_us']*1e-6, 'fall_time': cr['fall_us']*1e-6,
                'pulse_width': cr['width_us']*1e-6,
                'name': f"Cryst Reset ({device_key})", 'target_trans': 0.0,
                'mux_config': cryst_mux,
            })
            pulse_list.append({
                'source': 1, 'voltage': voltage,
                'on_time': at['on_time_us']*1e-6,
                'rise_time': at['rise_us']*1e-6, 'fall_time': at['fall_us']*1e-6,
                'pulse_width': at['width_us']*1e-6,
                'name': f"Test {voltage:.3f}V ({device_key})", 'target_trans': t_tgt,
                'mux_config': amorph_mux,
            })
        return pulse_list

    def build_cycle_sequence(self, device_key, n_cycles):
        devices = self.device_config.get("devices", {})
        device  = devices.get(device_key)
        if device is None:
            print(f"No device config for '{device_key}'")
            return []

        ar = device["amorph_reset"]
        cr = device["cryst_reset"]

        mux_ch     = device["mux"]
        base_mux   = list(self.DEVICE_MUX_CONFIGS[mux_ch])
        cryst_mux  = list(base_mux)
        amorph_mux = list(base_mux)
        amorph_mux[0] = 301

        pulse_list = []
        for i in range(n_cycles):
            pulse_list.append({
                'source': 2, 'voltage': cr['voltage'],
                'on_time': cr['on_time_us']*1e-6,
                'rise_time': cr['rise_us']*1e-6, 'fall_time': cr['fall_us']*1e-6,
                'pulse_width': cr['width_us']*1e-6,
                'name': f"Cryst ({device_key}) cycle {i+1}", 'target_trans': 0.0,
                'mux_config': cryst_mux,
            })
            pulse_list.append({
                'source': 1, 'voltage': ar['voltage'],
                'on_time': ar['on_time_us']*1e-6,
                'rise_time': ar['rise_us']*1e-6, 'fall_time': ar['fall_us']*1e-6,
                'pulse_width': ar['width_us']*1e-6,
                'name': f"Amorph ({device_key}) cycle {i+1}", 'target_trans': 1.0,
                'mux_config': amorph_mux,
            })
        return pulse_list

    def build_multi_device_pulse_sequence(self, device_voltage_map: dict) -> list:
        """
        Build a concatenated pulse list for multiple devices.

        Parameters
        ----------
        device_voltage_map : dict
            Mapping of device_key → list of voltages, e.g.:
            {"01_pn": [3.5, 5.0, 7.2], "11_pn": [4.0, 6.0]}

        Returns
        -------
        list of pulse dicts — each pulse already carries its own mux_config so
        PulseSequenceWorker handles MUX switching automatically.
        """
        combined = []
        for device_key, voltages in device_voltage_map.items():
            if not voltages:
                continue
            pulses = self.build_pulse_sequence(device_key, voltages)
            combined.extend(pulses)
            print(f"  {device_key}: {len(voltages)} voltages → {len(pulses)} pulses")
        print(f"Multi-device sequence: {len(combined)} total pulses across "
              f"{len(device_voltage_map)} devices")
        return combined


    # ── experiment control ────────────────────────────────────────────────────
    def turn_experiment_on(self):
        if self._save_folder:
            test_file = os.path.join(self._save_folder, ".write_test")
            try:
                with open(test_file, 'w') as f:
                    f.write("ok")
                os.remove(test_file)
            except OSError as e:
                QMessageBox.critical(self, "Save Folder Error",
                    f"Cannot write to save folder:\n{self._save_folder}\n\n{e}\n"
                    "Fix the path in Device Config before starting.")
                return
        with self._experiment_data_lock:
            self.experiment_data = []
        self.experiment_on   = True
        self.ui.experiment_runnin_yes_no.setText("Experiment Running: YES")
        self.ui.experiment_runnin_yes_no.setStyleSheet("color: red; font-weight: bold;")
        self.ui.start_experimen_push_button.setEnabled(False)
        self.ui.experiment_type_select.setEnabled(False)
        print(f"Experiment started — mode: {self.ui.experiment_type_select.currentText()} "
              f"| gains H1-H4: {self.pd_gains}")

    def turn_experiment_off(self):
        self.experiment_on = False
        self.ui.experiment_runnin_yes_no.setText("Experiment Running: no")
        self.ui.experiment_runnin_yes_no.setStyleSheet("color: black;")
        self.ui.start_experimen_push_button.setEnabled(True)
        self.ui.experiment_type_select.setEnabled(True)

        with self._experiment_data_lock:
            has_data = bool(self.experiment_data)

        if self.experiment_type == EXP_STATIC and has_data:
            self.save_experiment_data()
        elif self.experiment_type == EXP_QUAD_STATIC and has_data:
            self.save_quad_static_data()
        elif self.experiment_type == EXP_HISTORY:
            self.save_history_data(auto=True)

    @Slot(dict)
    def capture_experiment_data(self, pulse_params):
        """Dispatch to the appropriate capture method based on experiment type."""
        if not self.experiment_on:
            return
        if self.experiment_type == EXP_STATIC:
            self._capture_static(pulse_params)
        elif self.experiment_type == EXP_QUAD_STATIC:
            self._capture_quad_static(pulse_params)

    def _capture_static(self, pulse_params):
        """EXP_STATIC: steady-state snapshot after each pulse.

        Uses thread-safe request_measurement() — the DAQ thread owns the
        CoreDAQ object; direct cross-thread calls corrupt the serial state machine.
        """
        # Wait 100 ms for transients to settle, then collect 200 samples at ~1 kHz
        # (one per ms) and average — gives 200 ms of steady-state data.
        result = self.daq_reader.request_measurement(n_samples=200, settle_s=0.1)

        if result is None:
            print("capture_experiment_data: measurement request failed or timed out")
            return

        try:
            power_array = result.astype(np.float64)   # (4, 10)
            t_tgt       = pulse_params.get('target_trans', -1.0)

            if pulse_params['source'] == 1:
                pulse_type_str = 'amorph'
            else:
                pulse_type_str = 'cryst'
            entry = {
                'power_data_W':    power_array,
                'pulse_type':      pulse_type_str,
                'device_id':       pulse_params['device_id'],
                'voltage':         pulse_params['voltage'],
                'leading_time_us': pulse_params['leading_time'] * 1e6,
                'falling_time_us': pulse_params['falling_time'] * 1e6,
                'pulse_width_us':  pulse_params['pulse_width']  * 1e6,
                'timestamp':       pulse_params['timestamp'],
                'desired_trans':   t_tgt,
            }
            with self._experiment_data_lock:
                self.experiment_data.append(entry)
                n = len(self.experiment_data)
            print(f"Static snapshot #{n}: {entry['pulse_type']} (T_tgt={t_tgt})")
        except Exception as e:
            import traceback
            print(f"_capture_static error: {e}\n{traceback.format_exc()}")

    def _laser_for_column(self, col: int):
        """Return (turn_on_fn, turn_off_fn) for the laser associated with column col.

        Convention: col 0 → Santec, col 1 → HP.
        """
        if col == 0:
            return self.turn_santec_on, self.turn_santec_off
        else:
            return self.turn_hp_on, self.turn_hp_off

    def _capture_quad_static(self, pulse_params):
        """EXP_QUAD_STATIC: 30 ms snapshot per device across all 4 positions.

        After each pulse:
          1. Settle 100 ms (pulse transient).
          2. 30 ms window for active device          (col c, active laser on).
          3. 30 ms window for same-col other device  (col c, same laser).
          4. Switch laser.
          5. 30 ms window for other-col same-row     (col c', new laser).
          6. 30 ms window for other-col other-row    (col c', same new laser).
          7. Switch laser back to original.

        Saved array shape: (n_pulses, 4_positions, 4_channels, 30_samples).
        Position order: [active, same_col_other_row, other_col_same_row, other_col_other_row].
        """
        try:
            device_id = pulse_params.get('device_id', '')
            pos_str   = device_id.split('_')[0] if '_' in device_id else device_id
            if len(pos_str) < 2:
                print(f"_capture_quad_static: invalid device_id '{device_id}'")
                return

            row       = int(pos_str[0])
            col       = int(pos_str[1])
            other_row = 1 - row
            other_col = 1 - col

            # Ordered positions: active → same-col partner → other-col same-row → other-col other-row
            meas_positions = [
                f"{row}{col}",
                f"{other_row}{col}",
                f"{row}{other_col}",
                f"{other_row}{other_col}",
            ]

            N_SAMPLES = 30   # ~30 ms at the DAQ reader's 1 kHz save rate

            per_device = np.zeros((4, 4, N_SAMPLES), dtype=np.float64)

            # ── Column col measurements (active laser already on) ─────────────
            # First window: include the 100 ms pulse-transient settle
            r0 = self.daq_reader.request_measurement(n_samples=N_SAMPLES, settle_s=0.1)
            if r0 is not None:
                n = min(r0.shape[1], N_SAMPLES)
                per_device[0, :, :n] = r0[:4, :n]

            # Second window: same laser, no additional settle
            r1 = self.daq_reader.request_measurement(n_samples=N_SAMPLES, settle_s=0.0)
            if r1 is not None:
                n = min(r1.shape[1], N_SAMPLES)
                per_device[1, :, :n] = r1[:4, :n]

            # ── Switch laser ──────────────────────────────────────────────────
            on_cur,  off_cur  = self._laser_for_column(col)
            on_next, off_next = self._laser_for_column(other_col)
            off_cur()
            on_next()

            # ── Column other_col measurements (3 second settle for hp laser very slow stabilisation)
            r2 = self.daq_reader.request_measurement(n_samples=N_SAMPLES, settle_s=3)
            if r2 is not None:
                n = min(r2.shape[1], N_SAMPLES)
                per_device[2, :, :n] = r2[:4, :n]

            r3 = self.daq_reader.request_measurement(n_samples=N_SAMPLES, settle_s=0.0)
            if r3 is not None:
                n = min(r3.shape[1], N_SAMPLES)
                per_device[3, :, :n] = r3[:4, :n]

            # ── Restore original laser ────────────────────────────────────────
            off_next()
            on_cur()

            # ── Assemble entry ────────────────────────────────────────────────
            pulse_type_str = 'amorph' if pulse_params['source'] == 1 else 'cryst'
            entry = {
                'per_device_data_W': per_device,           # (4, 4, 30)
                'meas_positions':    meas_positions,        # ["01", "11", "00", "10"]
                'active_position':   pos_str,
                'pulse_type':        pulse_type_str,
                'device_id':         device_id,
                'voltage':           pulse_params['voltage'],
                'leading_time_us':   pulse_params['leading_time'] * 1e6,
                'falling_time_us':   pulse_params['falling_time'] * 1e6,
                'pulse_width_us':    pulse_params['pulse_width']  * 1e6,
                'timestamp':         pulse_params['timestamp'],
            }
            with self._experiment_data_lock:
                self.experiment_data.append(entry)
                n_entries = len(self.experiment_data)
            print(f"Quad snapshot #{n_entries}: {pulse_type_str} @ {pos_str}, "
                  f"positions={meas_positions}")
        except Exception as e:
            import traceback
            print(f"_capture_quad_static error: {e}\n{traceback.format_exc()}")

    # ── save: static ──────────────────────────────────────────────────────────
    def _auto_save_experiment_data(self):
        """Auto-save accumulated static snapshot data after each sequence run."""
        with self._experiment_data_lock:
            if not self.experiment_data:
                return
            d = list(self.experiment_data)
            self.experiment_data = []
        device    = self.get_active_cal_device()
        timestamp = make_timestamp()
        full_path = self.get_save_path(f"{device.key}_static_{timestamp}", ".mat")
        try:
            save_dict = {
                'power_data_W':     np.array([e['power_data_W']    for e in d]),
                'pulse_types':      np.array([e['pulse_type']      for e in d], dtype=object),
                'device_ids':       np.array([e['device_id']       for e in d], dtype=object),
                'voltages':         np.array([e['voltage']         for e in d]),
                'leading_times_us': np.array([e['leading_time_us'] for e in d]),
                'falling_times_us': np.array([e['falling_time_us'] for e in d]),
                'pulse_widths_us':  np.array([e['pulse_width_us']  for e in d]),
                'timestamps':       np.array([e['timestamp']       for e in d]),
                'desired_trans':    np.array([e['desired_trans']   for e in d]),
                'n_pulses':         len(d),
                'experiment_mode':  'static_snapshot',
            }
            save_dict.update(self._gain_metadata())
            save_dict.update(self._meta_save_dict())
            scipy.io.savemat(full_path, save_dict)
            print(f"Auto-saved {len(d)} static snapshots → {full_path}")
        except Exception as e:
            import traceback
            print(f"_auto_save_experiment_data error: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "Save Error",
                f"Could not save {os.path.basename(full_path)}:\n{e}\n\nCheck disk space and permissions.")

    def save_experiment_data(self):
        with self._experiment_data_lock:
            if not self.experiment_data:
                return
            d = list(self.experiment_data)
        device    = self.get_active_cal_device()
        timestamp = make_timestamp()
        full_path = self.get_save_path(f"{device.key}_static_{timestamp}", ".mat")
        try:
            save_dict = {
                'power_data_W':     np.array([e['power_data_W']    for e in d]),
                'pulse_types':      np.array([e['pulse_type']      for e in d], dtype=object),
                'device_ids':       np.array([e['device_id']       for e in d], dtype=object),
                'voltages':         np.array([e['voltage']         for e in d]),
                'leading_times_us': np.array([e['leading_time_us'] for e in d]),
                'falling_times_us': np.array([e['falling_time_us'] for e in d]),
                'pulse_widths_us':  np.array([e['pulse_width_us']  for e in d]),
                'timestamps':       np.array([e['timestamp']       for e in d]),
                'desired_trans':    np.array([e['desired_trans']   for e in d]),
                'n_pulses':         len(d),
                'experiment_mode':  'static_snapshot',
            }
            save_dict.update(self._gain_metadata())
            save_dict.update(self._meta_save_dict())
            scipy.io.savemat(full_path, save_dict)
            print(f"Saved {len(d)} static snapshots → {full_path}")
        except Exception as e:
            import traceback
            print(f"save_experiment_data error: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "Save Error",
                f"Could not save {os.path.basename(full_path)}:\n{e}\n\nCheck disk space and permissions.")

    def save_quad_static_data(self):
        with self._experiment_data_lock:
            if not self.experiment_data:
                return
            d = list(self.experiment_data)
        device    = self.get_active_cal_device()
        timestamp = make_timestamp()
        full_path = self.get_save_path(f"{device.key}_quad_{timestamp}", ".mat")
        try:
            save_dict = {
                'per_device_data_W':  np.array([e['per_device_data_W']  for e in d]),  # (n, 4, 4, 30)
                'meas_positions':     np.array([e['meas_positions']      for e in d], dtype=object),
                'active_positions':   np.array([e['active_position']     for e in d], dtype=object),
                'pulse_types':        np.array([e['pulse_type']          for e in d], dtype=object),
                'device_ids':         np.array([e['device_id']           for e in d], dtype=object),
                'voltages':           np.array([e['voltage']             for e in d]),
                'leading_times_us':   np.array([e['leading_time_us']     for e in d]),
                'falling_times_us':   np.array([e['falling_time_us']     for e in d]),
                'pulse_widths_us':    np.array([e['pulse_width_us']      for e in d]),
                'timestamps':         np.array([e['timestamp']           for e in d]),
                'n_pulses':           len(d),
                'experiment_mode':    'quad_static_snapshot',
            }
            save_dict.update(self._gain_metadata())
            save_dict.update(self._meta_save_dict())
            scipy.io.savemat(full_path, save_dict)
            print(f"Saved {len(d)} quad snapshots → {full_path}")
        except Exception as e:
            import traceback
            print(f"save_quad_static_data error: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "Save Error",
                f"Could not save {os.path.basename(full_path)}:\n{e}\n\nCheck disk space and permissions.")

    @Slot(dict)
    def save_sequence_daq_data(self, seq_result: dict):
        if self.experiment_on and self.experiment_type == EXP_STATIC:
            self._auto_save_experiment_data()

    # ── save: history ─────────────────────────────────────────────────────────
    def save_history_data(self, auto: bool = False):
        device    = self.get_active_cal_device()
        tag       = "history_auto" if auto else "history"
        timestamp = make_timestamp()
        full_path = self.get_save_path(f"{device.key}_{tag}_{timestamp}", ".mat")
        try:
            data = self.daq_reader.get_save_data_ordered()
            rate = self.daq_reader.save_rate_hz
            save_dict = {
                'daq_data_W':      data,
                'sample_rate_hz':  rate,
                'experiment_mode': 'history_1khz',
            }
            save_dict.update(self._gain_metadata())
            save_dict.update(self._meta_save_dict())
            scipy.io.savemat(full_path, save_dict)
            print(f"Saved {data.shape[1] / rate:.1f}s @ {rate}Hz → {full_path}")
        except Exception as e:
            import traceback
            print(f"save_history_data error: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "Save Error",
                f"Could not save {os.path.basename(full_path)}:\n{e}\n\nCheck disk space and permissions.")

    # ── sweep ─────────────────────────────────────────────────────────────────
    def start_laser_sweep(self):
        self.ui.Santec_sweep_power_on.setEnabled(False)
        self.stop_plotting()
        self.sweep_worker.set_sweep_params({
            'start_nm': self.ui.santec_sweep_start_nm_input.value(),
            'stop_nm':  self.ui.santec_sweep_end_nm_input.value(),
            'power':    self.ui.santec__sweep_power_input.value(),
            'speed':    50.0,
        })
        self.trigger_sweep.emit()

    @Slot()
    def handle_sweep_finished(self):
        self.ui.Santec_sweep_power_on.setEnabled(True)
        self.start_plotting()

    @Slot(str)
    def handle_sweep_error(self, msg):
        print(f"Sweep error: {msg}")
        self.ui.Santec_sweep_power_on.setEnabled(True)
        self.start_plotting()
        QMessageBox.warning(self, "Sweep Error", f"Sweep failed: {msg}")

    @Slot(str)
    def handle_sweep_progress(self, msg):
        print(f"Sweep: {msg}")

    @Slot(object)
    def handle_sweep_result(self, result):
        wl       = result['wavelengths']
        ch       = result['data']
        backend  = result.get('backend', 'unknown')
        print(f"Sweep complete: {len(wl)} points ({backend})")

        device    = self.get_active_cal_device()
        timestamp = make_timestamp()
        full_path = self.get_save_path(f"{device.key}_sweep_{timestamp}", ".mat")
        try:
            # CoreDAQ data is already in watts; NI data is raw volts
            if backend == 'coredaq':
                key = 'data_W'
            else:
                key = 'data_raw_volts'
            save_dict = {'wavelengths': wl, key: np.array(ch), 'experiment_mode': 'wavelength_sweep'}
            save_dict.update(self._gain_metadata())
            save_dict.update(self._meta_save_dict())
            scipy.io.savemat(full_path, save_dict)
            print(f"Saved sweep → {full_path}")
        except Exception as e:
            import traceback
            print(f"Sweep save error: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "Save Error",
                f"Could not save {os.path.basename(full_path)}:\n{e}\n\nCheck disk space and permissions.")

    # ── signal handlers ───────────────────────────────────────────────────────
    @Slot()
    def handle_pulse_finished(self):   print("Pulse completed")
    @Slot(str)
    def handle_pulse_error(self, m):   print(f"Pulse error: {m}")
    @Slot()
    def handle_mux_finished(self):     print("MUX configured")
    @Slot(str)
    def handle_mux_error(self, m):     print(f"MUX error: {m}")
    @Slot(str)
    def handle_sequence_progress(self, m): print(f"Sequence: {m}")

    # ── file helpers ──────────────────────────────────────────────────────────
    def _sync_filename_hint(self, device_key: str):
        """Populate name_for_file_input with device_key only when the box is blank
        or still shows the previous auto-generated hint (hasn't been user-edited)."""
        if not hasattr(self.ui, 'name_for_file_input'):
            return
        box = self.ui.name_for_file_input
        current = box.toPlainText().strip()
        last_hint = getattr(self, '_last_filename_hint', None)
        if not current or current == last_hint:
            box.setPlainText(device_key)
            self._last_filename_hint = device_key

    def get_save_path(self, filename, ext=".mat"):
        # Folder: prefer user-edited text box, fall back to _save_folder
        if hasattr(self.ui, 'folder_path_for_save'):
            ui_folder = self.ui.folder_path_for_save.toPlainText().strip()
        else:
            ui_folder = ""
        folder = ui_folder or self._save_folder or os.getcwd()

        # Optional custom label from name_for_file_input, appended to the filename
        if hasattr(self.ui, 'name_for_file_input'):
            label = self.ui.name_for_file_input.toPlainText().strip()
            label = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in label)
            auto_hint = self.get_active_cal_device().key if hasattr(self, '_cal_device') else ''
            if label and label != auto_hint:
                filename = f"{filename}_{label}"

        if not filename.endswith(ext):
            filename += ext
        return os.path.join(folder, filename)

    # ── DAQ reader thread ─────────────────────────────────────────────────────
    def init_daq_reader_thread(self):
        self.daq_reader_thread = QThread()
        self.daq_reader        = DaqReaderWorker()
        self.daq_reader.moveToThread(self.daq_reader_thread)
        self.daq_reader_thread.started.connect(self.daq_reader.run)
        self.daq_reader.error.connect(lambda m: print(f"DAQ error: {m}"))
        self.daq_reader.set_hardware(self.photoDAQ)

    # ── plotting ──────────────────────────────────────────────────────────────
    def start_plotting(self):
        self._setup_plot_vars()
        if not hasattr(self, 'traces') or not self.traces:
            self._configure_plot()
        if not self.daq_reader_thread.isRunning():
            self.daq_reader_thread.start()
        else:
            self.daq_reader.resume()
        self.display_timer.start()

    def stop_plotting(self):
        if hasattr(self, 'display_timer'):
            self.display_timer.stop()
        if hasattr(self, 'daq_reader'):
            self.daq_reader.pause()

    def _setup_plot_vars(self):
        r                    = self.daq_reader
        self.plot_time_span  = r.plot_time_span
        self.plot_buffer_len = r.plot_buffer_len
        self.t_axis          = np.linspace(-self.plot_time_span, 0, self.plot_buffer_len)
        self.t_axis_partial  = None
        self.display_timer   = QTimer()
        self.display_timer.setInterval(16)
        self.display_timer.timeout.connect(self.data_updating)

    def _configure_plot(self):
        pi = self.ui.live_transmission_line_chart_2.plotItem
        pi.setDownsampling(auto=True, mode='peak')
        pi.setClipToView(True)
        pi.addLegend()
        pi.setLabel('bottom', 'Time', units='s')
        pi.setLabel('left',   'Power', units='W')
        pi.setXRange(-self.plot_time_span, 0, padding=0)
        self.traces = [
            pi.plot(pen=pg.mkPen(c, width=1), name=f"port {i+3}", skipFiniteCheck=True)
            for i, c in enumerate(['y', 'b', 'm', 'g'])
        ]

    def data_updating(self):
        """CoreDAQ buffer stores watts — plot_mode 'watts' displays as-is."""
        buf, count = self.daq_reader.get_display_data()
        if count <= 0:
            return

        # 'volts' mode: crude back-conversion to mV for debugging
        if self.plot_mode == 'volts':
            scale = 1000.0
        else:
            scale = 1.0

        N = self.plot_buffer_len
        if count >= N:
            for i, tr in enumerate(self.traces):
                tr.setData(self.t_axis, buf[i] * scale, connect='all')
        else:
            if self.t_axis_partial is None or len(self.t_axis_partial) != count:
                self.t_axis_partial = self.t_axis[-count:]
            for i, tr in enumerate(self.traces):
                tr.setData(self.t_axis_partial, buf[i, :count] * scale, connect='all')



if __name__ == "__main__":
    app    = QApplication(sys.argv)
    window = ExperimentControlApp()
    window.show()
    sys.exit(app.exec())