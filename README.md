# YPL Lab Control GUI

> This project is part of my work during my Summer 2026 internship at the
> Youngblood Photonics Lab (YPL), University of Pittsburgh.

A Windows PyQt6 application for controlling the lab's optical/DAQ hardware
from one window: UEI PowerDNA analog output cards, a CoreDAQ USB optical
power meter, a Santec TSL-550 tunable laser, a Newport CONEX-CC motor stage,
an Emcore ITLA laser controller, and an HP/Agilent 8168F tunable laser —
each on its own tab, each degrading gracefully (tab stays visible with a
message instead of crashing the app) if its hardware library isn't installed
or its instrument isn't connected.

## Repository Layout

- `code/UeiDaq_gui/`
  - `gui.py` — **current entry point.** The unified, multi-tab GUI described
    above.
  - `ao333_bridge.py` — optional 32-bit helper process that streams Guardian
    ADC readback for the AO-333 card; `gui.py` auto-launches it if a 32-bit
    venv is set up (see [Optional: AO-333 Guardian ADC bridge](#optional-ao-333-guardian-adc-bridge)).
  - `hardware/` — one module per instrument (`coredaq.py`, `itla.py`,
    `laser_hp_8168F.py`, `laser_tsl_550.py`, plus a shared `visa_module/` for
    GPIB-over-Prologix support).
  - `connection_settings.json`, `ao_channel_names.json` — **auto-generated**
    by the GUI itself (last-used COM ports/GPIB addresses/wavelengths, pin
    nicknames). Don't hand-edit; delete either to reset to defaults.
  - `GUIcontroller.py`, `GUIControllerNew.py`, `GUIControllerOriginal.py`,
    `textController.py` — earlier/reference versions, not actively
    maintained. Use `gui.py`.
- `code/UeiDaq_library/` — UEI's official wheels/examples/docs, bundled as a
  fallback (see [Prerequisites](#prerequisites) — the primary source is the
  UEI Framework installer, not this folder).
- `data/` — where every sweep/recording CSV gets saved (auto-created,
  auto-opens the file after saving).
- `pyproject.toml` / `uv.lock` — dependency manifest for the `uv` package
  manager (see [Setup](#setup)).

## Prerequisites

**Software:**
- Windows 10/11
- Python 3.12 (pinned in `.python-version` / `pyproject.toml`)
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — this
  project's package/environment manager. Install with:
  ```powershell
  winget install --id=astral-sh.uv -e
  ```
- **UEI Framework software** installed to its default location
  (`C:\Program Files (x86)\UEI\Framework\...` and `...\PowerDNA\...`). This
  is UEI's own Windows installer (comes with the DAQ hardware / from UEI
  support) — it provides both the `UeiDaq` Python bindings `uv sync` links
  against and `PDNALib.dll`, which the optional Guardian ADC bridge needs.
  Not something `uv`/pip can install for you.
- *(Optional)* [NI-DAQmx runtime](https://www.ni.com/en/support/downloads/drivers/download.ni-daqmx.html) —
  only needed for the Santec TSL-550 tab to actually talk to hardware (the
  `nidaqmx` Python package itself installs fine without it; you'll only hit
  this if you try to connect).
- *(Optional)* [Moku CLI](https://www.liquidinstruments.com/) installed to
  `C:\Program Files\Liquid Instruments\Moku CLI\` — only needed for the
  Moku:Go oscilloscope panel inside the DAQ Control tab.

**Hardware / network**, as applicable to what you're using:
- A UEI DAQ cube reachable on the network (see `CUBE_IP` in
  [Configuration](#configuration))
- A Prologix GPIB-USB adapter for the ITLA, Santec, and HP-8168F laser tabs
  (each just needs its GPIB address + the adapter's COM port)
- CONEX-CC/TRA12CC controller and CoreDAQ power meter connect over USB-serial
  directly — no adapter needed

## Setup

1. **Install `uv`** (see above) if you don't already have it.

2. **Install the UEI Framework software** if this machine hasn't had it
   installed before — get it from UEI / whoever set up the DAQ hardware.
   Confirm afterward that this file exists:
   ```
   C:\Program Files (x86)\UEI\Framework\Python\UeiDaq_np1-5.2.0-cp312-abi3-win_amd64.whl
   ```

3. **From the repo root, sync the environment:**
   ```powershell
   cd "path\to\GUI"
   uv sync
   ```
   This creates `.venv` and installs everything declared in
   `pyproject.toml`/`uv.lock` — PyQt6, numpy, the UEI bindings, pyqtgraph,
   matplotlib, pyserial, pyvisa/pyvisa-py, moku, and nidaqmx. One command,
   nothing to install by hand.

   > **If this folder lives inside OneDrive** (as this one does), `uv sync`
   > can intermittently fail with `Access is denied` while OneDrive has a
   > file in `.venv` locked for syncing. This is harmless — it isn't a
   > broken environment, just OneDrive racing the installer. Just re-run
   > `uv sync` (usually 1–5 tries clears it). If it keeps happening, exclude
   > `.venv` and `.venv32` from OneDrive sync (OneDrive Settings → Account →
   > Choose folders) — they're build artifacts, not something you need
   > backed up.

4. **Run it:**
   ```powershell
   uv run code\UeiDaq_gui\gui.py
   ```
   (or activate `.venv` yourself and run
   `python code\UeiDaq_gui\gui.py`)

That's it for the software side — every tab should open. Tabs whose hardware
library failed to import show a message explaining what's missing instead of
a blank/crashed tab; if you see one after `uv sync` succeeded, something in
step 2 or 3 didn't take (see [Troubleshooting](#troubleshooting)).

### Optional: AO-333 Guardian ADC bridge

The DAQ Control tab's live Guardian ADC readback for the AO-333 card
(Dev2) needs a **separate 32-bit** Python environment — the UEI wheel for
that particular DLL path is 32-bit only. This is optional: without it, the
GUI still runs and controls outputs normally, it just won't show live
readback for that card.

```powershell
uv venv --python cpython-3.12.13-windows-x86-none .venv32
uv pip install --python .venv32\Scripts\python.exe numpy==1.26.4 pywin32 `
  "C:\Program Files (x86)\UEI\Framework\Python\UeiDaq_np1-5.2.0-cp312-abi3-win32.whl"
```

`gui.py` looks for `.venv32\Scripts\python.exe` at startup and auto-launches
`ao333_bridge.py` as a subprocess if it's there — nothing else to configure.

## Configuration

Hardware-specific constants live at the top of `code/UeiDaq_gui/gui.py` and
need to match your actual setup:

- `CUBE_IP` — IP address of the UEI DAQ cube
- `MOKU_IP` — IP address of the Moku:Go, if used
- `CARDS` — which device slots exist, their mode (`voltage`/`current`), and
  channel counts
- `MODE_RANGES` — output voltage/current limits per mode
- `RAMP_TICK_MS` / `SLEW_RATE_V` / `SLEW_RATE_MA` — ramping behavior for
  analog output changes

Everything else — COM ports, GPIB addresses, last-used wavelength/power,
per-pin nicknames — is set from within the GUI itself and persisted
automatically to `connection_settings.json` / `ao_channel_names.json`.

## Data Output

Sweep results and recordings save as CSV to `data/` at the repo root
(auto-created if missing) and open automatically in their default
application (e.g. Excel) right after saving, so there's no need to go
hunting for the file afterward.

## Troubleshooting

- **A tab shows "X not found" instead of its controls** — the corresponding
  optional dependency didn't install. Re-run `uv sync`; if a specific
  package is still missing, `uv pip install <package>` gets you unblocked
  immediately, but track down why `uv sync` didn't install it (see the
  OneDrive note above).
- **`uv sync` fails with `Access is denied`** — see the OneDrive note in
  step 3 above. Re-running it (a few times, if needed) resolves it.
- **DAQ Control tab can't connect** — check `CUBE_IP` matches your cube and
  that it's reachable on the network (`ping <CUBE_IP>`).
- **A laser/motor tab can't connect** — check the COM port and (for GPIB
  instruments) the GPIB address match what's set in that tab; these are
  editable directly in the GUI and get saved for next time.
