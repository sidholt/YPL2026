"""
VOA Linearization Calibration
------------------------------
Sweeps each specified VOA channel, measures optical power, and builds a
per-channel LUT that maps linear transmission (0=blocked, 1=fully open)
to the required drive voltage.

Supports two DAQ backends:
  'coredaq' — USB optical power meter, returns calibrated watts directly.
              Use when signal power is < ~3 mW.
  'nidaq'   — NI-DAQmx analog input, returns raw photodetector voltage.
              Use for higher power levels. build_lut normalises the signal
              so absolute units do not matter.

Output: voa_lut.json
  {
    "voa_id": 9,
    "lut_size": 256,
    "backend": "nidaq",
    "channels": {
      "0": [6.5, 6.48, ..., 0.0],   # index 0=blocked, 255=fully open
      "1": [...],
      ...
    }
  }

Usage:
  python calibrate_voa.py

Configuration: edit the CONFIGURATION block below.
"""

import json
import time
import numpy as np
from scipy.interpolate import pchip_interpolate
from pathlib import Path
from UsbVoa import UsbVoa

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BACKEND = 'nidaq'           # 'coredaq' or 'nidaq'

VOA_ID       = 9            # board ID of your VOA (from EEPROM)
VOA_CHANNELS = [0]       # which VOA channels to calibrate

# CoreDAQ settings (used when BACKEND = 'coredaq')
COREDAQ_CHANNELS = [1, 2]   # CoreDAQ heads (1-indexed) paired with VOA_CHANNELS
COREDAQ_N_FRAMES = 16       # snapshots averaged per measurement

# NI-DAQ settings (used when BACKEND = 'nidaq')
NIDAQ_DEVICE   = "Dev2"                     # NI device name
NIDAQ_CHANNELS = ["Dev2/ai0"]  # AI channels paired with VOA_CHANNELS
NIDAQ_N_SAMPLES = 256                       # samples averaged per measurement

SWEEP_STEPS = 128           # VOA voltage points across 0–6.5 V (initial sweep)
LUT_SIZE    = 128           # output LUT resolution
REF_SAMPLES = 10            # measurements averaged for open/closed reference levels
OUTPUT_FILE = "voa_lut.json"

# Iterative refinement — each pass probes the largest-gap (least-dense) LUT regions
ITER_ROUNDS     = 2         # refinement passes after initial sweep (0 = off)
REFINE_FRACTION = 0.25      # fraction of LUT gaps to target per pass
REFINE_STEPS    = 64        # new measurement points added per pass

# ---------------------------------------------------------------------------

assert len(VOA_CHANNELS) <= 8, "Max 8 VOA channels supported"
if BACKEND == 'coredaq':
    assert len(VOA_CHANNELS) == len(COREDAQ_CHANNELS), \
        "VOA_CHANNELS and COREDAQ_CHANNELS must be the same length"
elif BACKEND == 'nidaq':
    assert len(VOA_CHANNELS) == len(NIDAQ_CHANNELS), \
        "VOA_CHANNELS and NIDAQ_CHANNELS must be the same length"
else:
    raise ValueError(f"Unknown BACKEND '{BACKEND}' — use 'coredaq' or 'nidaq'")


# ---------------------------------------------------------------------------
# Backend-specific measurement
# ---------------------------------------------------------------------------

def _connect_daq():
    """Connect to the configured DAQ backend. Returns an opaque daq handle."""
    if BACKEND == 'coredaq':
        from hardware.coredaq import CoreDAQ
        ports = CoreDAQ.find()
        if not ports:
            raise RuntimeError("No CoreDAQ device found — check USB connection")
        daq = CoreDAQ(ports[0])
        print(f"  CoreDAQ: {daq.idn()}")
        return daq

    else:  # nidaq
        import nidaqmx.system
        system = nidaqmx.system.System.local()
        if NIDAQ_DEVICE not in system.devices:
            raise RuntimeError(
                f"NI-DAQ device '{NIDAQ_DEVICE}' not found. "
                f"Available: {list(system.devices)}"
            )
        print(f"  NI-DAQ device: {NIDAQ_DEVICE}, channels: {NIDAQ_CHANNELS}")
        return NIDAQ_DEVICE   # just the name — tasks are opened per-read


def _close_daq(daq):
    if BACKEND == 'coredaq':
        try:
            daq.close()
        except Exception:
            pass


def _measure(daq, ch_index: int) -> float:
    """
    Return a single averaged reading for the given channel index (0-based
    into the VOA_CHANNELS list).

    CoreDAQ → calibrated watts; NI-DAQ → raw volts.
    build_lut normalises either to [0, 1], so the units don't matter.
    """
    if BACKEND == 'coredaq':
        coredaq_ch = COREDAQ_CHANNELS[ch_index]   # 1-indexed head
        power_W = daq.snapshot_W(n_frames=COREDAQ_N_FRAMES, autogain=True)
        return float(power_W[coredaq_ch - 1])

    else:  # nidaq
        import nidaqmx
        from nidaqmx.constants import AcquisitionType
        ch = NIDAQ_CHANNELS[ch_index]
        with nidaqmx.Task() as task:
            task.ai_channels.add_ai_voltage_chan(ch)
            task.timing.cfg_samp_clk_timing(
                rate=1000,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=NIDAQ_N_SAMPLES,
            )
            data = task.read(number_of_samples_per_channel=NIDAQ_N_SAMPLES)
        return float(np.mean(data))


# ---------------------------------------------------------------------------
# Iterative refinement helpers
# ---------------------------------------------------------------------------

def _refine_voltages(voltages: np.ndarray, readings: np.ndarray,
                     n_new: int, refine_frac: float) -> np.ndarray:
    """
    Find the voltage intervals where the measured signal changes most
    between adjacent points (steepest regions of the V→P curve) and
    return new voltages to probe inside those intervals.

    These are the regions where PCHIP interpolation is least accurate
    and additional data points improve the LUT most.
    """
    order  = np.argsort(voltages)
    v      = voltages[order]
    r      = readings[order]

    r_norm  = (r - r.min()) / (r.max() - r.min() + 1e-12)
    d_sig   = np.abs(np.diff(r_norm))          # signal change per interval

    n_tgt   = max(1, round(len(d_sig) * refine_frac))
    top_idx = np.argpartition(d_sig, -n_tgt)[-n_tgt:]

    pts_per = max(1, n_new // n_tgt)
    new_vs  = []
    for i in top_idx:
        lo, hi = v[i], v[i + 1]
        if hi - lo > 1e-4:
            new_vs.append(np.linspace(lo, hi, pts_per + 2)[1:-1])

    return np.sort(np.concatenate(new_vs)) if new_vs else np.array([])


def _drop_near(new_vs: np.ndarray, existing: np.ndarray, tol: float = 0.02) -> np.ndarray:
    """Remove any voltage already within tol V of an existing measurement."""
    if len(new_vs) == 0:
        return new_vs
    return np.array([v for v in new_vs if np.min(np.abs(existing - v)) > tol])


# ---------------------------------------------------------------------------
# Reference calibration
# ---------------------------------------------------------------------------

def calibrate_references(voa: UsbVoa, daq, voa_ch: int, ch_index: int
                         ) -> tuple[float, float]:
    """
    Measure the fully-open (0 V) and fully-closed (max V) power levels.
    Returns (p_open, p_closed).
    """
    print(f"  ch{voa_ch}: measuring fully-open reference (0 V)...")
    voa.set(voa_id=VOA_ID, channel=voa_ch, voltage=0.0)
    time.sleep(0.1)
    p_open = float(np.mean([_measure(daq, ch_index) for _ in range(REF_SAMPLES)]))
    print(f"  ch{voa_ch}: p_open   = {p_open:.6g}")

    print(f"  ch{voa_ch}: measuring fully-closed reference ({voa.max_voltage} V)...")
    voa.set(voa_id=VOA_ID, channel=voa_ch, voltage=voa.max_voltage)
    time.sleep(0.1)
    p_closed = float(np.mean([_measure(daq, ch_index) for _ in range(REF_SAMPLES)]))
    print(f"  ch{voa_ch}: p_closed = {p_closed:.6g}")

    return p_open, p_closed


# ---------------------------------------------------------------------------
# Sweep + LUT
# ---------------------------------------------------------------------------

def sweep_channel(voa: UsbVoa, daq, voa_ch: int, ch_index: int
                  ) -> tuple[np.ndarray, np.ndarray]:
    """
    Sweep voa_ch from 0 V → 6.5 V and record the detector response.
    Returns (voltages, readings) as 1-D arrays.
    """
    voltages = np.linspace(0.0, voa.max_voltage, SWEEP_STEPS)
    readings = np.zeros(SWEEP_STEPS)

    for i, v in enumerate(voltages):
        voa.set(voa_id=VOA_ID, channel=voa_ch, voltage=v)
        time.sleep(0.002)
        readings[i] = _measure(daq, ch_index)
        print(f"  ch{voa_ch}: {v:.3f} V  ->  {readings[i]:.6g}")

    return voltages, readings


def build_lut(voltages: np.ndarray, readings: np.ndarray,
              p_open: float, p_closed: float) -> np.ndarray:
    """
    Given a measured (voltage, reading) sweep and calibrated reference levels,
    return a LUT of length LUT_SIZE where lut[j] is the voltage needed to
    produce j/(LUT_SIZE-1) fractional transmission.

    transmission = (reading - p_closed) / (p_open - p_closed)

    lut[0]          -> 0% transmission (fully blocked)
    lut[LUT_SIZE-1] -> 100% transmission (fully open)
    """
    span = p_open - p_closed
    if np.isclose(span, 0.0):
        raise RuntimeError("No signal variation detected — check fiber connections")
    norm = np.clip((readings - p_closed) / span, 0.0, 1.0)

    order = np.argsort(voltages)
    voltages, norm = voltages[order], norm[order]

    v_fine = np.linspace(0.0, voltages[-1], 2**16)
    p_fine = pchip_interpolate(voltages, norm, v_fine)

    targets = np.linspace(0.0, 1.0, LUT_SIZE)
    lut = np.zeros(LUT_SIZE)
    for j, target in enumerate(targets):
        if j == 0:
            lut[j] = v_fine[np.argmin(p_fine)]
        elif j == LUT_SIZE - 1:
            lut[j] = v_fine[np.argmax(p_fine)]
        else:
            lut[j] = v_fine[np.argmin(np.abs(p_fine - target))]

    return lut


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Connecting to VOA controller...")
    voa = UsbVoa()
    print(f"  Found boards: {voa.ids}")
    if VOA_ID not in voa.ids.values():
        raise RuntimeError(f"Board ID {VOA_ID} not found. Connected IDs: {list(voa.ids.values())}")

    print(f"Connecting to DAQ ({BACKEND})...")
    daq = _connect_daq()

    # Block all channels to start
    voa.set_voa(VOA_ID, voa.volt_zero)
    time.sleep(0.2)

    lut_data = {}
    try:
        for ch_index, voa_ch in enumerate(VOA_CHANNELS):
            label = (f"CoreDAQ head {COREDAQ_CHANNELS[ch_index]}"
                     if BACKEND == 'coredaq'
                     else f"NI-DAQ {NIDAQ_CHANNELS[ch_index]}")
            print(f"\nCalibrating VOA channel {voa_ch} ({label})...")

            # Step 1: calibrate fully-open and fully-closed reference levels
            p_open, p_closed = calibrate_references(voa, daq, voa_ch, ch_index)

            # Step 2: sweep voltage and record detector response
            voa.set_voa(VOA_ID, voa.volt_zero)
            time.sleep(0.1)

            voltages, readings = sweep_channel(voa, daq, voa_ch, ch_index)

            for r in range(ITER_ROUNDS):
                new_vs = _refine_voltages(voltages, readings, REFINE_STEPS, REFINE_FRACTION)
                new_vs = _drop_near(new_vs, voltages)
                if len(new_vs) == 0:
                    print(f"  Pass {r+1}: already converged, no new points needed.")
                    break
                print(f"\n  Refinement pass {r+1}/{ITER_ROUNDS}: {len(new_vs)} new points...")
                new_readings = np.zeros(len(new_vs))
                for i, v in enumerate(new_vs):
                    voa.set(voa_id=VOA_ID, channel=voa_ch, voltage=v)
                    time.sleep(0.002)
                    new_readings[i] = _measure(daq, ch_index)
                    print(f"    [{i+1}/{len(new_vs)}] {v:.4f} V  ->  {new_readings[i]:.6g}")
                voltages = np.concatenate([voltages, new_vs])
                readings = np.concatenate([readings, new_readings])
                order    = np.argsort(voltages)
                voltages, readings = voltages[order], readings[order]

            # Step 3: build LUT anchored to calibrated references
            lut = build_lut(voltages, readings, p_open, p_closed)
            lut_data[str(voa_ch)] = {
                "lut":      [round(float(v), 4) for v in lut],
                "p_open":   round(p_open, 8),
                "p_closed": round(p_closed, 8),
            }
            print(f"  Done. {len(voltages)} total points. "
                  f"Voltage range used: {lut.min():.3f}–{lut.max():.3f} V")
    finally:
        voa.set_voa(VOA_ID, voa.volt_one)
        _close_daq(daq)

    output = {
        "voa_id":   VOA_ID,
        "lut_size": LUT_SIZE,
        "backend":  BACKEND,
        "channels": lut_data,
    }
    Path(OUTPUT_FILE).write_text(json.dumps(output, indent=2))
    print(f"\nSaved LUT to {OUTPUT_FILE}")
    print("\nUsage example:")
    print("  ch = json.load(open('voa_lut.json'))['channels']['0']")
    print("  transmission = 0.7  # 70%")
    print("  idx = round(transmission * (len(ch['lut']) - 1))")
    print("  voa.set(voa_id=9, channel=0, voltage=ch['lut'][idx])")
    print("  # ch['p_open'] and ch['p_closed'] hold the reference power levels")


if __name__ == "__main__":
    main()
