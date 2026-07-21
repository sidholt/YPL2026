"""
pin_identify_test.py — Walks each DAQ analog-output pin one at a time so you
can correlate a GUI/software pin number to its physical location, using a
multimeter or by watching a downstream device (e.g. an MZI heater pad)
respond.

Why this script exists: gui.py's write path was audited end to end and
every write — whether triggered by clicking "Set" on one pin or by the new
"Set All To" — goes through the exact same CardSession.write()/ramp_to()
call with the exact same array indexing: values[i] always maps to physical
channel Ao{i} within the Dev{N}/Ao0:{num_pins-1} channel group created at
connect time (see CardSession.connect() in gui.py). No reversal, no offset,
no Set-All-specific code path was found. That makes a pure software
indexing bug unlikely — this script lets you verify pin-by-pin directly
instead of taking that on faith, and for Dev2 channels 0-7 (the only ones
with real Guardian ADC feedback) it cross-checks each write against
hardware readback automatically, so a software bug there would show up
immediately as a mismatch without needing the multimeter at all.

Advances on Enter (not a timer) — probe/observe, type a short note on where
you found the pin (or just hit Enter to skip the note and move on, or 'q'
to stop early), and it moves to the next pin. At the end it prints a full
software-pin -> your-note table and saves it to a timestamped CSV next to
this script, so one guided walk builds the complete diagram.

Deliberately does NOT try to guess the rest of the mapping from wherever
pin 0 turns out to be (e.g. "assume a constant offset" or "assume it's
reversed") — that requires knowing the connector/cable's actual wiring
convention, which isn't visible from this code, and a wrong guess here
could mean applying voltage to a pin you don't think you're touching.
Walking every pin and recording what you actually observe is slower but
can't be wrong.

IMPORTANT — close the main GUI (or at least disconnect the card you're
testing here) before running this. Two processes fighting over the same
AO channels or the same Guardian ADC connection will behave unpredictably.

Edit the CONFIG block below to match what you want to test, then run:
    python pin_identify_test.py
"""

import ctypes
import csv
import os
import time
import UeiDaq

# ── CONFIG ───────────────────────────────────────────────────────────────
CUBE_IP   = "172.28.2.4"   # keep in sync with gui.py's CUBE_IP
DEV       = "Dev2"         # "Dev0"/"Dev1" = current (16 ch), "Dev2" = voltage (32 ch)
MODE      = "voltage"      # "voltage" or "current" — must match DEV above
NUM_CH    = 32             # total channels on this card (16 for Dev0/Dev1, 32 for Dev2)
TEST_VAL  = 3.0            # value to drive each pin to (volts, or mA if MODE="current")
START_PIN = 0              # first pin to test
END_PIN   = 31             # last pin to test (inclusive) — full 32-ch card.
                           # Only physical 0-7 have Guardian ADC readback, so
                           # pins 0-7 auto-confirm; for 8-31 the script drives
                           # them for real but you read them on a multimeter.
                           # Set to 7 for a quick ADC-only check of 0-7.

# Cross-checks Dev2 pins 0-7 against real Guardian ADC hardware feedback —
# the only channels with actual ADC readback (see ao333_bridge.py / gui.py's
# NUM_PINS comment). Set False to skip even for Dev2, or if the bridge DLL
# isn't reachable from this machine.
GUARDIAN_READBACK = True
PDNA_DLL = r"C:\Program Files (x86)\UEI\PowerDNA\Shared\PDNALib.dll"

# VERIFICATION RESULT 2026-07-21 (pin_map_Dev2.csv): the full candidate map
# was walked. 18 pins came out at the right physical pin and were PROMOTED to
# gui.py's PIN_REMAP["Dev2"]. Every one of the 13 rule-inferred routes showed
# nothing ("not seeing anything"), so the involution theory is DISPROVED for
# the inferred pairs — where raw channels 0,1,2,5,8,11,14,17,20,23,26,28
# really land is unknown. One contradiction: logical 27 -> raw 3 showed
# nothing even though the raw walk directly saw raw 3 land on physical 27,
# so raw 3 gets re-checked too.
#
# This script is therefore back in RAW DISCOVERY mode (PIN_REMAP empty):
# pin i drives raw channel i with no correction, and you note the physical
# pin where the voltage actually appears. The places still missing a source
# are physical pins 1, 5, 8, 11, 14, 17, 20, 23, 26, 27, 28, 29, 30, 31 —
# probe those spots for each channel below.
PIN_REMAP = {}

# Walk only these raw channels (overrides START_PIN..END_PIN when non-empty).
# These are exactly the channels whose landing is still unknown after the
# 2026-07-21 verification, plus raw 3 (the logical-27 contradiction).
# Raw 30 is the known-shorted channel (seen driving physical 5/8/11/14/17/20
# at once) — expect it to light up several pins, not one.
PINS_TO_TEST = [0, 1, 2, 3, 5, 8, 11, 14, 17, 20, 23, 26, 28, 30]
# ─────────────────────────────────────────────────────────────────────────


def setup_guardian(cube_ip):
    """Opens a second, low-level connection for Guardian ADC readback —
    only works for Dev2 channels 0-7. Mirrors ao333_bridge.py."""
    dll = ctypes.WinDLL(PDNA_DLL)
    dll.DqInitDAQLib.restype  = ctypes.c_int
    dll.DqOpenIOM.restype     = ctypes.c_int
    dll.DqOpenIOM.argtypes    = [ctypes.c_char_p, ctypes.c_uint16, ctypes.c_uint32,
                                  ctypes.POINTER(ctypes.c_int), ctypes.c_void_p]
    dll.DqAdv333ReadADC.restype  = ctypes.c_int
    dll.DqAdv333ReadADC.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.POINTER(ctypes.c_uint32),
                                     ctypes.POINTER(ctypes.c_uint32),
                                     ctypes.POINTER(ctypes.c_double)]
    dll.DqInitDAQLib()
    handle = ctypes.c_int(0)
    ret = dll.DqOpenIOM(cube_ip.encode(), ctypes.c_uint16(6334), ctypes.c_uint32(1000),
                         ctypes.byref(handle), None)
    if ret < 0:
        raise RuntimeError(f"Guardian DqOpenIOM failed: {ret}")
    return dll, handle.value


def read_guardian(dll, handle):
    n = 8
    cl    = (ctypes.c_uint32 * n)(*range(n))
    bdata = (ctypes.c_uint32 * n)()
    fdata = (ctypes.c_double * n)()
    ret = dll.DqAdv333ReadADC(handle, 2, n, cl, bdata, fdata)
    if ret < 0:
        raise RuntimeError(f"DqAdv333ReadADC failed: {ret}")
    return list(fdata)


def main():
    if PINS_TO_TEST:
        assert all(0 <= p < NUM_CH for p in PINS_TO_TEST), "PINS_TO_TEST out of range for NUM_CH"
        pins = list(PINS_TO_TEST)
    else:
        assert 0 <= START_PIN <= END_PIN < NUM_CH, "START_PIN/END_PIN out of range for NUM_CH"
        pins = list(range(START_PIN, END_PIN + 1))

    print(f"Connecting to {DEV} ({MODE}) on {CUBE_IP}, channels Ao0:{NUM_CH - 1}...")
    session = UeiDaq.CUeiSession()
    addr = f"pdna://{CUBE_IP}/{DEV}/Ao0:{NUM_CH - 1}"
    if MODE == "voltage":
        session.CreateAOChannel(addr, -10.0, 10.0)
    else:
        session.CreateAOCurrentChannel(addr, 0.0, 20.0)
    session.ConfigureTimingForSimpleIO()
    writer = UeiDaq.CUeiAnalogScaledWriter(session.GetDataStream())

    guardian = None
    if GUARDIAN_READBACK and DEV == "Dev2":
        try:
            guardian = setup_guardian(CUBE_IP)
            print("Guardian ADC readback connected — will cross-check pins 0-7 against hardware.")
        except Exception as e:
            print(f"[WARN] Guardian readback unavailable ({e}) — continuing without it.")

    zeros = [0.0] * NUM_CH
    unit  = "V" if MODE == "voltage" else "mA"
    notes = {}       # logical pin -> whatever the user typed about where they found it
    discovered = {}  # logical pin -> physical channel the Guardian auto-scan saw it on

    # Load whatever this pin was already noted as from a prior run, so the
    # walk can show it instead of starting blind each time.
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"pin_map_{DEV}.csv")
    prior = {}   # logical_pin (str) -> {"physical_channel": ..., "note": ...}
    if os.path.exists(out_path):
        with open(out_path, newline="") as f:
            for row in csv.DictReader(f):
                prior[row["logical_pin"]] = row
        n_notes = sum(1 for row in prior.values() if row.get("note"))
        if n_notes:
            print(f"Loaded {n_notes} existing note(s) from {out_path}.")

    def write(values):
        if PIN_REMAP:
            physical = list(values)
            for logical_pin, physical_pin in PIN_REMAP.items():
                if logical_pin < len(values):
                    physical[physical_pin] = values[logical_pin]
        else:
            physical = values
        scaled = [v / 1000.0 for v in physical] if MODE == "current" else physical
        writer.WriteSingleScan(scaled)

    stopped_early = False
    try:
        write(zeros)
        print(f"\nAll {DEV} pins zeroed.")
        pins_desc = (", ".join(str(p) for p in pins) if PINS_TO_TEST
                     else f"{START_PIN}..{END_PIN}")
        print(f"Walking pins {pins_desc}, {TEST_VAL:g} {unit} each.")
        print("Probe/observe, then Enter to advance — type a short note first "
              "if you want it recorded (e.g. \"top-left screw terminal\"), "
              "or 'q' + Enter to stop early.\n")
        for i in pins:
            values = list(zeros)
            values[i] = TEST_VAL
            write(values)
            expected = i   # a correct remap makes logical pin i come out at
                           # physical pin i; in a raw walk (empty remap) this is
                           # still i, so identity wiring reads "as expected"
            prev_note = prior.get(str(i), {}).get("note", "")
            msg = f"  >>> Pin {i:02d} -> {TEST_VAL:g} {unit}  — probe it now"
            if prev_note:
                msg += f'   [previous note: "{prev_note}"]'
            if guardian is not None:
                time.sleep(0.3)   # let the ADC settle before reading
                vals = read_guardian(*guardian)   # 8 physical readback channels
                # Auto-detect which physical channel actually responded, rather
                # than only checking the one we EXPECT: the channel(s) that
                # jumped close to TEST_VAL. With an empty PIN_REMAP this reveals
                # the true logical->physical landing for every pin whose target
                # is in physical 0-7 — no multimeter needed for those.
                hits = [ch for ch, v in enumerate(vals) if abs(v - TEST_VAL) < 0.5]
                if len(hits) == 1:
                    found = hits[0]
                    discovered[i] = found
                    tag = "as expected" if found == expected else f"but EXPECTED {expected}"
                    msg += (f"   [Guardian: logical {i} -> physical ch {found} "
                            f"({vals[found]:+.3f} V) — {tag}]")
                elif not hits:
                    msg += (f"   [Guardian: nothing near {TEST_VAL:g} V on physical 0-7 "
                            f"— it lands on physical 8-31; read it on the multimeter]")
                else:
                    msg += (f"   [Guardian: MULTIPLE channels responded {hits} "
                            f"— possible short/crosstalk, investigate]")
            print(msg)
            prompt = f"      note for Pin {i:02d} "
            prompt += f'(Enter to keep "{prev_note}", ' if prev_note else "(Enter to skip, "
            prompt += "'q' to stop): "
            note = input(prompt).strip()
            write(zeros)
            if note.lower() == "q":
                stopped_early = True
                break
            if note:
                notes[i] = note
    except KeyboardInterrupt:
        stopped_early = True
        print("\nStopped early.")
    finally:
        write(zeros)
        session.Stop()
        if guardian is not None:
            dll, handle = guardian
            dll.DqCloseIOM(handle)
        print("All pins zeroed, session closed.")

    print(f"\n{'Pin':>5}  {'PhysCh':>6}  Note")
    print(f"{'---':>5}  {'------':>6}  ----")
    for i in pins:
        prior_row = prior.get(str(i), {})
        phys = discovered.get(i)
        if phys is None and prior_row.get("physical_channel"):
            phys = int(prior_row["physical_channel"])
        phys_s = f"{phys:6d}" if phys is not None else "     ?"
        note = notes.get(i) or prior_row.get("note") or "(not recorded)"
        print(f"{i:5d}  {phys_s}  {note}")

    # Auto-discovered pairs, ready to paste into gui.py's PIN_REMAP. Only the
    # non-identity pairs are worth encoding; a pin that landed on its own index
    # is already correct. Pins that landed on physical 8-31 aren't here (no
    # ADC readback) — add those from your multimeter notes by hand.
    nontrivial = {i: p for i, p in discovered.items() if i != p}
    if discovered:
        print("\nAuto-discovered mapping (Guardian ADC, physical 0-7 only):")
        pairs = ", ".join(f"{i}: {p}" for i, p in sorted(nontrivial.items()))
        print(f'    PIN_REMAP = {{"{DEV}": {{{pairs}}}}}')
        identity = sorted(i for i, p in discovered.items() if i == p)
        if identity:
            print(f"    (already-correct/identity pins seen: {identity})")

    if notes or discovered:
        # Merge onto whatever prior (loaded above) already has, so a
        # partial/resumed walk doesn't blow away notes recorded earlier.
        for i in pins:
            phys = discovered.get(i)
            row = prior.get(str(i), {"physical_channel": "", "note": ""})
            if phys is not None:
                row["physical_channel"] = phys
            if i in notes:
                row["note"] = notes[i]
            prior[str(i)] = row

        with open(out_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["logical_pin", "physical_channel", "note"])
            for i in sorted(prior, key=int):
                row = prior[i]
                w.writerow([i, row.get("physical_channel", ""), row.get("note", "")])
        print(f"\nSaved diagram to {out_path} (merged with any existing entries)")
    if stopped_early:
        print("(Stopped before reaching the last pin — re-run with PINS_TO_TEST "
              "trimmed to the ones you haven't done (or START_PIN moved up) "
              "to continue; the CSV merge keeps everything already recorded.)")


if __name__ == "__main__":
    main()
