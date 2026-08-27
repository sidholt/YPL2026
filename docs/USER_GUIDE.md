# YPL Lab Control GUI — User Guide

Day-to-day operating manual for the lab. If you're setting the software up for
the first time on a new machine, start with [README.md](../README.md) instead —
that covers installation. This document assumes it already runs.

**Contents**

1. [Before you touch anything](#1-before-you-touch-anything)
2. [Starting and stopping](#2-starting-and-stopping)
3. [The main window](#3-the-main-window)
4. [DAQ Control](#4-daq-control-uei-powerdna-analog-outputs)
5. [Moku](#5-moku-waveform-generator--oscilloscope)
6. [CoreDAQ Power Meter](#6-coredaq-power-meter)
7. [Santec TSL-550 Laser](#7-santec-tsl-550-laser)
8. [ITLA Laser](#8-itla-laser-emcore-ttx)
9. [HP-8168F Laser](#9-hp-8168f-laser)
10. [CONEX Motor](#10-conex-motor-newport-conex-cc--tra12cc)
11. [Recording data](#11-recording-data)
12. [Where your data goes](#12-where-your-data-goes)
13. [Common workflows](#13-common-workflows)
14. [Troubleshooting](#14-troubleshooting)
15. [Glossary](#15-glossary)

---

## 1. Before you touch anything

Read this section once. The rest of the guide assumes you have.

### Laser safety

Three tabs can emit light into fiber: **Santec**, **ITLA**, and **HP-8168F**.

- Assume any connected laser is **on and emitting** unless you have personally
  confirmed otherwise. The GUI shows output state per tab — check it, don't
  assume it.
- Never disconnect or reconnect fiber with the output on. Turn the output off
  in the GUI first.
- Closing the GUI turns the Santec and HP-8168F off as part of shutdown, but
  *do not* rely on that as your safety procedure — it only helps if the
  software is still responsive.
- **The ITLA is not turned off on exit.** It keeps emitting after the GUI
  closes. Turn it off with the ITLA tab's own **Off** button when you're done.

### Electrical safety on the DAQ

The DAQ Control tab drives real analog outputs into whatever is wired to the
cube.

- **Outputs are not restored on launch, deliberately.** Every pin starts at 0
  and the GUI never auto-writes a saved value on startup. This is a safety
  choice: restoring an old output value into a rig that has been rewired since
  is how you damage a device.
- **Dev2 (AO-333) has dead pins and one dangerous pin.** See
  [Reading the pin colors](#reading-the-pin-colors). In particular **AOut 01
  lands on a digital input (DIn0), not ground** — driving analog voltage into
  it risks damaging the card. It's marked red in the GUI. Don't drive it.
- Use the **Ramp** checkbox (on by default) for anything sensitive. Unchecked
  means the output jumps instantly to the new value.
- **Zero All** is your panic button on that tab.

### One process per instrument

Every instrument here allows exactly one owner at a time. If something won't
connect, the most common reason by far is that *something else already has it*:

- another copy of this GUI still running (check Task Manager for `python.exe`),
- the vendor's own software (CoreConsole, the Moku desktop app, Newport
  utilities),
- `pin_identify_test.py`, which drives DAQ pins directly,
- a previous run that crashed without releasing the port.

The Moku is a special case: **the Moku tab and the Moku panel inside DAQ
Control are two different connections to the same physical box.** Only one can
be connected at a time. See [section 5](#5-moku-waveform-generator--oscilloscope).

---

## 2. Starting and stopping

### Start

From the repo root:

```powershell
uv run code\UeiDaq_gui\gui.py
```

The window opens sized to most of your screen. Every tab is present even if its
hardware is absent — a tab whose Python library failed to import shows a message
saying what's missing rather than crashing the app.

### What connects automatically

**Only the CoreDAQ Power Meter auto-connects on launch.** Everything else waits
for you to click Connect. This is intentional — auto-connecting lasers and
motors on startup was removed because it moves hardware before you've looked at
the rig.

So a normal session is: launch, then connect the specific instruments you need.

### Stop

Close the main window. Shutdown does the following before exiting:

1. Zeroes every DAQ output pin.
2. Turns off Santec and HP-8168F laser emission. **The ITLA is left as-is —
   if it was emitting, it still is after the GUI closes.**
3. Disconnects and releases every port, **including tabs you popped out into
   their own windows**.

`Ctrl+C` in the launching terminal goes through the same shutdown path, so it's
safe. Killing the process from Task Manager is **not** — it skips all of the
above and leaves outputs live and ports locked.

Clicking a tab's own **Disconnect** does the same cleanup for just that
instrument.

---

## 3. The main window

### Tabs

Default left-to-right order:

| Tab | Instrument |
|---|---|
| DAQ Control | UEI PowerDNA analog output cards (Dev0/Dev1/Dev2) |
| Moku | Moku:Go — waveform generator + oscilloscope |
| Dot Product | Measurement tab — Moku bit stream × UEI phase weights |
| 2D Sweep | Measurement tab — drive axis × laser axis heatmap |
| CoreDAQ Power Meter | 4-head USB optical power meter |
| Santec Laser | Santec TSL-550 tunable laser |
| ITLA Laser | Emcore TTX ITLA |
| HP-8168F Laser | HP/Agilent 8168F tunable laser |
| CONEX Motor | Newport CONEX-CC / TRA12CC X+Y stage |

**Reorder:** drag a tab left/right along the bar. The order is saved and comes
back next session.

**Pop out:** drag a tab *vertically* out of the bar (up or down, ~50 px) and it
becomes its own window — useful for watching a power meter while driving a
sweep on another tab. A popped-out window has a **⬅ Reattach to main window**
button at the top; closing it also reattaches. Reattached tabs return to their
correct position in your saved order.

### Global recording bar

The strip above the tabs records **every connected instrument at once** into a
single time-aligned CSV, at 4 Hz, regardless of which tab you're looking at.
See [section 11](#11-recording-data).

### What the GUI remembers between sessions

Saved automatically to `connection_settings.json` and `ao_channel_names.json`
(both next to `gui.py`):

- COM ports, GPIB addresses, the Moku IP
- Sweep ranges, dwell times, set-points, wavelengths, powers
- Moku waveform settings, plot view mode, and capture window
- Per-pin nicknames on the DAQ tab
- Tab order

**Not** saved: DAQ output values (see the safety note in section 1).

To reset any of this, delete the relevant JSON file — it regenerates with
defaults. Don't hand-edit them while the GUI is running; it overwrites them.

---

## 4. DAQ Control (UEI PowerDNA analog outputs)

### Cards

The tab opens on a card-select screen listing three cards:

| Card | Mode | Channels | Range |
|---|---|---|---|
| Dev0 | Current | 16 | 0 – 20 mA |
| Dev1 | Current | 16 | 0 – 20 mA |
| Dev2 | Voltage | 32 | −10 – +10 V |

Click a card to connect it and open its pin view. Connection happens in the
background, so the GUI stays responsive; the status bar reports the result.

Below the card list is an embedded **Moku:Go live readback** panel (read-only
oscilloscope) used to measure what the DAQ is actually putting out. This is a
*different connection* from the Moku tab — see [section 5](#5-moku-waveform-generator--oscilloscope).

### The pin view

Each active channel gets a row:

```
AOut 07   [nickname]   [ 2.500 V ]  [────●────────]   [Set]
```

- **Nickname** — free text (e.g. `BPD 2+`, `PS1`). Saved per channel index and
  shown in the sweep/waveform channel pickers, so you pick "the phase shifter"
  rather than "channel 25".
- **Value box / slider** — stay in sync. Neither writes to hardware on its own.
- **Set** — writes *that* channel.

Bottom row:

- **Write All** — writes every active channel's current box value.
- **Zero All** — writes 0 everywhere. Your panic button.
- **Ramp** (checked by default) — ramps at the slew rate (5 V/s or 10 mA/s,
  20 ms steps) instead of jumping. Uncheck for an instant step.
- **Set All To … / Apply** — fills every active channel's box with one value,
  then writes it.

### Reading the pin colors

On cards whose physical wiring has been mapped (currently **Dev2** only), the
`AOut NN` labels are colour-coded. Cards that haven't been walked get no
colouring at all rather than a guess.

| Colour | Meaning | What to do |
|---|---|---|
| **Green** | Verified working output | Use normally |
| **Gold** — `AOut NN → pin X` | Dead: lands on a ground pin, no reachable output | Don't expect output. `pin X` is the physical DB62 pin it actually reaches, which is usable as a ground tie point |
| **Red** — `AOut 01 → DIn0` | Lands on a **digital input**, not ground | **Do not drive.** Risks damaging the card |

On Dev2 that leaves 21 working channels out of 32. A note under the list also
reports which native ground pins on the DB62 connector are still free.

> The gold labels say "pin X" rather than "gnd X" on purpose: it's a reminder
> that the signal physically arrives somewhere *other than* where the pinout
> says, so you wire to a different physical pin than the channel number implies.

If a channel outputs on the wrong physical pin, **don't fix it by trial and
error** — run `pin_identify_test.py` (close the GUI first) and encode confirmed
pairs into `PIN_REMAP`. An unconfirmed remap entry is more dangerous than none,
because it silently sends voltage somewhere you aren't expecting.

### Sweep

Steps a group of channels through a range together, in lockstep.

1. **AOuts** — tick the channels (or **All**). Every ticked channel sweeps the
   *same* Start→Stop range simultaneously.
2. **Start / Stop** — in the card's units.
3. **Steps or step size** — pick either; the label shows the resulting count.
4. **Dwell (ms)** — settle time per step (20 – 60000).
5. **Log CoreDAQ power (all 4 MZIs)** — on by default; records all four power
   readings at every step. Leave it on unless CoreDAQ isn't part of the run.
6. **Run Sweep** / **Stop**.

**Show: MZI n** picks which head is plotted live; all four are recorded
regardless. **Export CSV…** writes the results, then **📂 Open** opens them.

### Waveform Output

A *software* waveform generator — the CPU writes points on a timer. It is not
the Moku's hardware generator, and it's limited accordingly.

- **AOuts** — every ticked channel plays the same waveform in lockstep.
- **Wave** — Sine or Cosine.
- **Freq** — 0.001 – 1000 Hz.
- **Amplitude / Offset** — in card units.
- **Tick (ms)** — update interval (5 – 1000). This is the real fidelity limit:
  at a 20 ms tick you get 50 points/second, so a 10 Hz sine is only ~5 points
  per cycle. For clean high-frequency waveforms use the [Moku tab](#5-moku-waveform-generator--oscilloscope).
- **Run Wave** / **Stop**.

### Data Recording (per-card)

**Start Recording** logs commanded values plus Moku readback over time;
**Save Data** writes the CSV. **📈 Live Output vs Readback** opens a live
commanded-vs-measured plot with a V-vs-I view toggle.

This is separate from the global recorder in the main window — this one is
DAQ-specific and includes per-pin commanded values.

---

## 5. Moku (waveform generator + oscilloscope)

Drives the Moku:Go in **MultiInstrument mode**: a Waveform Generator and an
Oscilloscope run *simultaneously*, so you can generate a signal and watch it on
the same tab — loop an output back to an input with a cable to see it.

> **Only one Moku connection at a time.** The read-only Moku panel on the DAQ
> Control tab uses a separate single-instrument connection to the same physical
> box. Disconnect one before connecting the other, or the second will fail or
> take the device away from the first.

### Connecting

Enter the IP (remembered between sessions) and click **Connect**. On success the
status shows CONNECTED and the generator controls enable.

### Generating

Per output channel: **Waveform** (Sine / Square / Ramp / Pulse / DC / Off),
**Frequency**, **Amplitude (Vpp)**, **Offset (V)**, **Phase**, plus **Duty %**
(Square/Pulse) or **Symmetry %** (Ramp). Settings persist between sessions.

Nothing reaches the hardware until you click **Apply to Output N**. Select
**Off** and Apply to stop that channel.

> **Output 2 is disabled on this Moku:Go**, with a note explaining why. The
> device's second MultiInstrument slot exposes only one output port, so there's
> no physical connector to route a second generator channel to. This is detected
> at connect time, not hardcoded — if a firmware update ever exposes it, the
> second column enables itself.

### Reading the plot

Two views, selectable in **View**:

- **Scope trace** (default) — plots the captured frame itself: real waveform
  shape and amplitude, like a scope screen. **This is the one you want when
  generating.**
- **Rolling mean** — one averaged point per frame over the last 10 s. Good for
  slow DC drift. **A periodic waveform averages away to roughly its DC offset
  in this mode** — a 1 kHz sine reads as a flat line near 0 V. That's expected,
  not a fault.

**Window** sets the captured time span (100 µs – 1 s), i.e. the horizontal zoom.
Shorter windows also acquire *faster*, so this is your speed control too. Pick a
window showing a few cycles: 10 ms ≈ 10 cycles of a 1 kHz signal.

**frames/s from device** reports the achieved acquisition rate. This is limited
by the Moku's network round trip, not by the GUI — the plot itself redraws in
well under a millisecond. If it feels sluggish, shorten the window; that's the
lever that actually helps.

---

## 6. CoreDAQ Power Meter

Four-head USB optical power meter. **This is the one tab that auto-connects on
launch**, and most sweep features on other tabs log through it.

### Connecting

Leave **Port** blank to auto-detect (recommended), or type `COM16` or just `16`.
Auto-detect finds the right device even if Windows moved it to a different COM
number. After connecting, IDN / Frontend / Detector populate.

### Measurement config

- **Wavelength (nm)** then **SET!** — keeps the InGaAs/Si responsivity
  correction matched to the light you're actually measuring. **Set this before
  trusting absolute power numbers.**
- **Gain** — per head, LINEAR frontends only. **Autogain** steps each head into
  a safe mid-range window automatically, and is usually what you want.

Autogain also runs on its own: every 60 s while connected, and immediately if a
head reads hot enough to be heading for a railed ADC. So readings may adjust
themselves during a long run — that's the gain changing, not the light.

### Live plot

**Show live plot** displays all four heads over the last 30 s; the legend
toggles individual heads. It ticks on automatically when you connect. Unticking
it stops the redraw entirely (the meter keeps reading) — worth doing if you want
every cycle going to a demanding sweep.

---

## 7. Santec TSL-550 Laser

Connects over Prologix GPIB-to-USB. **Manual connect only** — click **Connect
to Laser**.

- **Output ON / OFF.** Output ON also applies whatever wavelength and power are
  currently dialled in, so check those first.
- **Manual Control** — wavelength and power, each with its own **SET!**.
- **Power Sweep** — steps power at a fixed wavelength, logging CoreDAQ at each
  point. The laser must already be **ON**.
- **Fast Sweep (HW triggered)** — the laser sweeps continuously while CoreDAQ
  free-runs, started by a hardware trigger. Set **Start/Stop (nm)**, **Speed
  (nm/s)** (1 – 100), and **Power (mW)**, then **Run Fast Sweep**. This gives far
  denser wavelength resolution than stepping, and saves a **PNG plot alongside
  the CSV** in `data/images/`.

The **Log** box at the bottom is the authoritative record of what the tab
actually did — check it first when a sweep behaves unexpectedly.

---

## 8. ITLA Laser (Emcore TTX)

Connects over Prologix GPIB.

- **Control** — tune by ITU-grid channel or by direct wavelength. Grid spacing
  options are 12.5 / 25 / 50 / 100 GHz. Optional **FTF** applies sub-grid
  detuning in 0.1 GHz steps.
- **Apply Wavelength (live)** and **Apply Power (live)** retune *without* an
  off/on power cycle.
- **Turn Laser On / Off.**
- **Wavelength Sweep** — snaps to grid channels (no FTF), logs CoreDAQ, plots,
  exports CSV.
- **Power Sweep** — wavelength fixed; the laser must already be ON.
- **Dither** — SBS only / TxTrace only / Disable All. The laser must be locked
  to a channel first.
- **Diagnostics** — temperature, fatal status, and similar readback.

---

## 9. HP-8168F Laser

Connects over Prologix GPIB. The simplest of the three laser tabs.

- **Output ON / OFF**
- **Manual Control** — wavelength and power, each with **SET!**
- **Wavelength Sweep** — start/stop/step in nm plus dwell, with CoreDAQ logging,
  a plot, and CSV export
- **Power Sweep** — wavelength fixed; laser must already be ON

---

## 10. CONEX Motor (Newport CONEX-CC / TRA12CC)

Two independent axes (**X** and **Y**), each on its own COM port, as sub-tabs —
plus a **Synchronized XY Move** box for moving both together.

### Startup sequence (per axis)

1. Enter the COM port number (e.g. `4`).
2. **Connect**.
3. **HOME MOTOR** — wait for READY. **Nothing else works until homing
   completes.**

### Moving

- **Absolute** — type a target, **GO!**. The **◀** / **▶** buttons nudge by
  that same distance.
- **Relative** — offset from current position.
- **Hold to jog** — **◀ Hold** / **Hold ▶** move continuously while held.
- **Velocity** — set with **SET!**. Max is 0.4 mm/s.
- **⚠ EMERGENCY STOP ⚠** — stops immediately.

### Reminders (also shown in the tab)

- The motor must be **stationary before disconnecting**.
- Start with small moves (~1 mm) until you trust the travel limits.
- A solid green LED on the controller means READY.

Diagnostics cover state, position, velocity, travel limits, device identity, and
a VISA resource listing (handy when you're unsure which COM port is which).

---

## 11. Recording data

There are three separate recorders. Pick by scope:

| Recorder | Where | Records | Rate |
|---|---|---|---|
| **Global** | Bar above the tabs | Every connected instrument, time-aligned | 4 Hz |
| **DAQ recording** | DAQ Control pin view | Commanded pin values + Moku readback | Moku poll rate |
| **Sweep logs** | Each sweep box | One row per sweep step, incl. CoreDAQ power | Per step |

### Global recording

1. **⏺ Start Recording** — begins sampling every connected instrument.
2. Run your experiment. Switching tabs doesn't interrupt it.
3. **⏺ Stop Recording**.
4. **💾 Save Combined CSV…**, then **📂 Open**.

Columns are discovered from whatever was connected during the run, so connecting
an instrument midway gives you blank cells before that point rather than a
failure.

---

## 12. Where your data goes

Everything lands in **`data/`** at the repo root (created automatically), with
sweep plot images in **`data/images/`**.

Filenames are timestamped `YYYYMMDD_HHMMSS`, e.g.:

```
data/ao_sweep_coredaq_20260731_142530.csv
data/Dev2_voltage_moku_20260731_142530.csv
data/global_recording_20260731_142530.csv
data/sweep2d_20260731_142530.csv
data/images/santec_fast_sweep_20260731_142530.png
```

A 2D Sweep writes its map **twice**: `sweep2d_<stamp>.csv` in long form (one
row per grid point, plus all four CoreDAQ heads) and
`sweep2d_<stamp>_matrix.csv` in matrix form (first row is the drive axis,
first column the laser axis) for dropping straight into Excel/Origin as a
surface. Both carry the same `#` parameter header.

### File format

Sweep and recording CSVs begin with `#` comment lines capturing the run's
parameters, followed by a normal header row:

```
# ao_sweep_unit: V
ao_value_V,coredaq_ch1_W,coredaq_ch2_W,coredaq_ch3_W,coredaq_ch4_W
0.0000,1.234567890e-06,...
```

Those `#` lines are why a sweep is reproducible later — they record the range,
step, dwell, and set-point actually used. Most tools (pandas
`read_csv(comment='#')`, Excel's import) skip them cleanly.

Optical power is always in **watts**; convert to dBm yourself if needed.

### Files do not open automatically

Saving writes the file and enables that box's **📂 Open** button. Nothing pops
up on its own — auto-launching Excel on every export got in the way more than it
helped. Each **📂 Open** opens the most recent file *for that specific box*.

---

## 13. Common workflows

### Measure optical power vs. applied voltage

1. **CoreDAQ** — confirm connected, set the measurement **Wavelength**, run
   **Autogain**.
2. **Laser tab** — set wavelength and power, **Output ON**.
3. **DAQ Control** — click the card, pick your channel(s) in the **Sweep** box.
4. Set Start/Stop, steps, and dwell (long enough for the optics to settle).
5. Leave **Log CoreDAQ power** ticked. **Run Sweep**.
6. **Export CSV…** → **📂 Open**.

### Sweep wavelength and watch a response

1. **CoreDAQ** — connected, wavelength set, autogained.
2. **DAQ Control** — apply any static bias your device needs.
3. **Laser tab** — use **Wavelength Sweep** (ITLA / HP-8168F) for stepped
   points, or Santec's **Fast Sweep** for dense continuous coverage.
4. Export. Santec's fast sweep also drops a PNG in `data/images/`.

### Check what a DAQ channel is really doing

1. **DAQ Control** — connect the card; the Moku readback panel is on that same
   screen. (Disconnect the Moku *tab* first if it's connected.)
2. Connect the Moku panel, set the channel's value, click **Set**.
3. Compare commanded vs. measured. **📈 Live Output vs Readback** plots both
   over time, with a V-vs-I toggle.

If the reading stays at zero on Dev2, check the channel's colour first — gold
and red channels have no reachable output ([section 4](#reading-the-pin-colors)).

### Generate a test signal and view it

1. Disconnect the Moku panel on DAQ Control if connected.
2. **Moku** tab → **Connect**.
3. Cable **Output 1** back to **Input 1** to see your own signal.
4. Set waveform, frequency, amplitude → **Apply to Output 1**.
5. Keep **View: Scope trace** and set **Window** to a few cycles.

### Record everything during a manual experiment

1. Connect every instrument you want captured.
2. **⏺ Start Recording** in the global bar.
3. Work across tabs freely.
4. Stop → **💾 Save Combined CSV…** → **📂 Open**.

---

## 14. Troubleshooting

### Connection

**"A tab shows a 'not found' message instead of controls."**
That library didn't install. Re-run `uv sync` (see the OneDrive note in the
README — it often just needs re-running).

**"Connect fails / port already open / access denied."**
Something else owns it. In order of likelihood: another copy of this GUI, the
vendor software (CoreConsole, Moku app), `pin_identify_test.py`, or a crashed
run that never released the port. Check Task Manager for stray `python.exe`.
For CoreDAQ specifically, leaving the Port field **blank** to auto-detect fixes
the case where Windows moved the device to a new COM number.

**"DAQ card won't connect."**
Confirm `CUBE_IP` in `gui.py` matches the cube and that it responds to `ping`.

**"Moku won't connect / connects then errors."**
Check the other Moku connection isn't already up (tab vs. DAQ Control panel).
Confirm the IP, and that Moku CLI is installed where the README specifies.

### Measurement

**"Moku plot is a flat line while generating."**
You're in **Rolling mean** view, which averages a periodic waveform down to its
DC offset. Switch **View** to **Scope trace**.

**"Moku plot updates slowly."**
The limit is the network round trip, not the GUI. Shorten the **Window**;
check the **frames/s** readout to see the real rate.

**"CoreDAQ readings jump during a run."**
Automatic autogain (every 60 s, plus immediately when a head runs hot). The gain
changed, not the light. Set gains manually if you need a fixed scale.

**"Power numbers look wrong in absolute terms."**
Set the measurement **Wavelength** on the CoreDAQ tab and **SET!** it — the
responsivity correction depends on it.

**"A DAQ channel outputs nothing."**
On Dev2, check the colour: gold = lands on ground (no output), red = AOut 01,
don't drive it. See [section 4](#reading-the-pin-colors).

**"A DAQ channel outputs on the wrong physical pin."**
The cable doesn't wire straight through. Don't guess a correction — close the
GUI, run `pin_identify_test.py`, and encode only *confirmed* pairs into
`PIN_REMAP`.

### Motion

**"CONEX controls do nothing after connecting."**
You haven't homed it. **HOME MOTOR**, wait for READY.

**"Motor won't disconnect cleanly."**
It must be stationary first. Stop the move, then disconnect.

### General

**"The GUI froze."**
Long hardware calls run on background threads, so the window should stay
responsive. If it genuinely locks up, a wedged serial link is the usual cause.
Close via the X if you can — that still zeroes outputs and turns lasers off.
Only kill the process as a last resort, and physically verify laser and DAQ
state afterward.

**"I want to start from a clean slate."**
Close the GUI and delete `connection_settings.json` (ports, addresses, sweep
parameters, tab order) and/or `ao_channel_names.json` (pin nicknames), both next
to `gui.py`. They regenerate with defaults.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **AOut NN** | Analog output channel NN on a DAQ card, as the GUI numbers it (logical, may be remapped to a different physical pin) |
| **Cube** | The UEI PowerDNA chassis holding the DAQ cards, reached over the network at `CUBE_IP` |
| **Dev0 / Dev1 / Dev2** | The three DAQ cards. Dev0/Dev1 are 16-channel current; Dev2 is a 32-channel voltage AO-333 |
| **DB62** | The 62-pin connector on the AO-333 card. "pin X" on a gold label refers to a physical pin here |
| **FTF** | Fine Tune Frequency — sub-grid ITLA detuning, 0.1 GHz steps |
| **Frontend (CoreDAQ)** | The detector amplifier type; LINEAR frontends support gain control and autogain |
| **Head / MZI 1-4** | The four CoreDAQ measurement channels |
| **ITU grid** | Standard optical channel spacing (12.5 / 25 / 50 / 100 GHz) used for ITLA tuning |
| **MiM (MultiInstrument Mode)** | Moku mode running two instruments at once in separate "slots" |
| **PIN_REMAP** | Table in `gui.py` mapping logical AOut index → real physical channel, for miswired cables |
| **Prologix** | GPIB-to-USB adapter used by the three laser tabs |
| **Slew rate** | Ramp speed for DAQ output changes (5 V/s or 10 mA/s) |
