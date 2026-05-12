# UeiDaq GUI

A Windows-based DAQ control repository for UEI (United Electronic Industries) analog output hardware.

This project contains a PyQt6 GUI and a command-line script for controlling UEI DAQ cards through the `UeiDaq` Python bindings. It also includes a local UEI library distribution and a set of example files.

## Repository Layout

- `code/`
  - `UeiDaq_gui/`
    - `claudeGUIController.py` — PyQt6-based GUI for analog output control, card configuration, ramping, and sweep operations.
    - `textController.py` — CLI fallback/redundancy for direct DAQ control.
  - `UeiDaq_library/`
    - `UeiDaq-5.2.0-cp312-abi3-win_amd64.whl` — UEI DAQ Python binding wheel for 64-bit Python 3.12.
    - `UeiDaq-5.2.0-cp312-abi3-win32.whl` — UEI DAQ Python binding wheel for 32-bit Python 3.12.
    - `examples/` — UEI example scripts demonstrating various DAQ operations.
    - `ueidaq_framework_user_manual.pdf` — Official UEI DAQ framework documentation.

## Requirements

- Windows
- Python 3.12
- `PyQt6`
- `numpy==1.26.4` (required by the UEI wheel)
- UEI DAQ hardware and a network-accessible DAQ cube
- `UeiDaq` library installed from one of the provided wheels

> Note: The provided UEI wheel requires NumPy 1.26.4 exactly. Install this specific version for compatibility.

## Setup

1. Create and activate a Python virtual environment in your project directory:

```powershell
cd "path\to\FEQ"
python -m venv .venv
& ".venv\Scripts\Activate.ps1"
```

2. Install project dependencies:

```powershell
python -m pip install PyQt6 numpy==1.26.4
```

3. Install UEI bindings using the correct wheel for your Python architecture:

```powershell
python -m pip install code\UeiDaq_library\UeiDaq-5.2.0-cp312-abi3-win_amd64.whl
```

or for 32-bit Python:

```powershell
python -m pip install code\UeiDaq_library\UeiDaq-5.2.0-cp312-abi3-win32.whl
```

## Configuration

The GUI and CLI scripts use a hardcoded DAQ cube IP address and card/channel definitions. Before running, update the following values in each script to match your hardware:

- `code/UeiDaq_gui/claudeGUIController.py`
  - `CUBE_IP` — IP address of your DAQ cube (default: `172.28.2.4`)
  - `CARDS` — card slots, modes, device names, and availability
  - `MODE_RANGES` — voltage/current output limits
  - Ramp/slew and sweep defaults

- `code/UeiDaq_gui/textController.py`
  - `CUBE_IP` — IP address of your DAQ cube (default: `172.28.2.4`)

## Usage

Run the graphical controller:

```powershell
python code\UeiDaq_gui\claudeGUIController.py
```

This opens a PyQt6 interface for controlling analog output channels, including ramped transitions and sweep operations.

## Examples and Documentation

- `code/UeiDaq_library/examples/` contains sample DAQ scripts for tasks such as analog input/output, digital I/O, counters, PWM, MIL-1553, CAN, and more.
- `code/UeiDaq_library/ueidaq_framework_user_manual.pdf` contains the official UEI DAQ framework documentation.

## Notes

- The repository is designed around the UEI DAQ framework and the `UeiDaq` Python API.
- Modify IP, card definitions, and output ranges before use.
- The GUI script includes built-in ramping logic and sweep control for safe analog transitions.
- `textController.py` is a simpler CLI implementation that can be useful as a reference for understanding how the GUI interfaces with the DAQ hardware.