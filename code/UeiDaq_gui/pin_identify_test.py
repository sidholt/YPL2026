"""
pin_identify_test.py — Walks each DAQ analog-output pin one at a time so you
can correlate a GUI/software pin number to its physical location, using a
multimeter or by watching a downstream device (e.g. an MZI heater pad)
respond.

Two walk styles: the classic one-pin-at-a-time walk, and SIGNATURE_MODE
(see CONFIG) which drives every channel under test AT ONCE, each at its own
unique voltage — you probe each candidate physical pin exactly once and the
voltage you read identifies which channel feeds it. Use signature mode when
many channels are unknown; it turns an N-passes-times-M-spots hunt into a
single M-probe pass.

Why this script exists: gui.py's write path was audited end to end and
every write — whether triggered by clicking "Set" on one pin or by the new
"Set All To" — goes through the exact same CardSession.write()/ramp_to()
call with the exact same array indexing: values[i] always maps to physical
channel Ao{i} within the Dev{N}/Ao0:{num_pins-1} channel group created at
connect time (see CardSession.connect() in gui.py). No reversal, no offset,
no Set-All-specific code path was found. That makes a pure software
indexing bug unlikely — this script lets you verify pin-by-pin directly
instead of taking that on faith, and for Dev2 (with real Guardian ADC
feedback across all N_GUARDIAN_CH channels) it cross-checks each write
against hardware readback automatically, so a software bug there would show
up immediately as a mismatch without needing the multimeter at all.

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
                           # All 32 physical pins now have Guardian ADC
                           # readback (N_GUARDIAN_CH — see that constant's
                           # comment re: untested timing at this size), so
                           # every pin should auto-confirm; the multimeter is
                           # now only a fallback if Guardian is unreachable.

# Cross-checks Dev2 pins against real Guardian ADC hardware feedback (see
# ao333_bridge.py / gui.py's NUM_PINS comment). Set False to skip even for
# Dev2, or if the bridge DLL isn't reachable from this machine.
GUARDIAN_READBACK = True
PDNA_DLL = r"C:\Program Files (x86)\UEI\PowerDNA\Shared\PDNALib.dll"

# Channels requested from DqAdv333ReadADC — was 8 (only physical 0-7 had
# readback) until 2026-07-21, now attempting all 32 to cover every Dev2
# output. Untested at this size: watch how long read_guardian() takes to
# return on this hardware (the datasheet's own "all 32 channels read in 2.4
# seconds" spec suggests it may be much slower per-channel than 8 was) —
# drop back to 8 if it makes this walk impractically slow.
N_GUARDIAN_CH = 32

# RESOLVED 2026-07-21: the DNx-AO-333's official pinout (dnx-ao-333.pdf) wires
# its 62-pin connector in 3 physical rows (21/21/20 pins, alternating
# Gnd/AOut). The cable added afterward mirrored each row left-to-right (row
# assignment unchanged). That one rule reproduces every measurement taken —
# 18 pairs from the first verification walk, plus raw 8/20/23/26/28 confirmed
# landing exactly on their predicted Gnd pins by signature voltage, plus raw
# 5/11/14/17/30 confirmed silent (0 V) on their predicted Gnd landings.
# Channels 1 (-> the card's digital input pin DIn0, not analog ground — avoid
# driving it) and 5/8/11/14/17/20/23/26/28/30 (-> Gnd) have no reachable
# output terminal; no remap can fix a wire that doesn't reach a pin. The full
# resolved map is now live in gui.py's PIN_REMAP["Dev2"].
#
# ONE loose end: 27<->3 was directly observed in both directions in the raw
# walk and fits the rule, but one verification attempt failed to reproduce
# it. This script is configured to re-isolate just that pair — PIN_REMAP
# applies gui.py's confirmed map (so if you drive "logical pin 27" here, you
# should see physical terminal 27 light up) and PINS_TO_TEST narrows the walk
# to that single pin.
PIN_REMAP = {
    0: 31, 2: 29, 3: 27, 4: 25, 6: 24, 7: 22, 9: 21, 10: 19,
    12: 18, 13: 16, 15: 15, 16: 13, 18: 12, 19: 10, 21: 9, 22: 7,
    24: 6, 25: 4, 27: 3, 29: 2, 31: 0,
}

# Walk only these raw channels (overrides START_PIN..END_PIN when non-empty).
PINS_TO_TEST = [27]

# SIGNATURE MODE — the fast way to resolve MANY unknown channels at once,
# because probing every candidate spot for every channel one at a time is
# quadratically slow. All PINS_TO_TEST channels are driven SIMULTANEOUSLY,
# each at its own unique voltage, so you walk the DEAD_PHYSICAL pins ONCE:
# the voltage you read on a pin is a fingerprint identifying which raw
# channel feeds it. You type the reading and the script does the lookup.
#   - Requires PINS_TO_TEST (the channels to drive) and DEAD_PHYSICAL (the
#     physical spots to probe). Pins inside Guardian ADC range (0 to
#     N_GUARDIAN_CH-1 — now all 32) identify themselves automatically — no
#     probing needed there, multimeter only as a fallback.
#   - Raw ch 30 (SHORTED_RAW — seen bridging physical 5/8/11/14/17/20) is
#     held at 0 V during the pass so the short can't contaminate readings;
#     it gets a solo pass at the end.
#   - Mind the top voltage: max = SIG_START + (len(PINS_TO_TEST)-1)*SIG_STEP.
# False = the classic one-channel-at-a-time walk — the right choice for the
# single-pin 27<->3 recheck above.
SIGNATURE_MODE = False
SIG_START = 0.5    # lowest signature voltage
SIG_STEP  = 0.25   # spacing between signatures (easy to split on a DMM)
SHORTED_RAW = 30
# Physical pins with no known source — the spots to probe in signature mode.
DEAD_PHYSICAL = []

# HOLD_ONLY: don't prompt pin-by-pin — just energize the signature pattern
# and LEAVE IT ON while you probe every pin at your own pace and write down
# "physical pin -> volts" on paper. Press Enter once when done; the script
# then holds the raw-30 solo pass the same way, then zeroes everything.
# Decode afterwards: the voltage on a pin identifies the raw channel feeding
# it (table printed at start). Nothing is typed in, so nothing is saved to
# the CSV — the written-down readings are the record. Only meaningful with
# SIGNATURE_MODE = True.
HOLD_ONLY = False
# ─────────────────────────────────────────────────────────────────────────


def setup_guardian(cube_ip):
    """Opens a second, low-level connection for Guardian ADC readback —
    Dev2 only, N_GUARDIAN_CH channels. Mirrors ao333_bridge.py."""
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
    n = N_GUARDIAN_CH
    cl    = (ctypes.c_uint32 * n)(*range(n))
    bdata = (ctypes.c_uint32 * n)()
    fdata = (ctypes.c_double * n)()
    t0 = time.time()
    ret = dll.DqAdv333ReadADC(handle, 2, n, cl, bdata, fdata)
    dt_ms = (time.time() - t0) * 1000
    if ret < 0:
        raise RuntimeError(f"DqAdv333ReadADC failed: {ret}")
    if dt_ms > 200:   # only worth printing if it's slow enough to matter
        print(f"   [Guardian] read of {n} channels took {dt_ms:.0f} ms")
    return list(fdata)


def signature_walk(write, zeros, guardian, unit, notes, discovered):
    """The fast walk: drives every PINS_TO_TEST channel AT ONCE, each at its
    own unique voltage, so each dead physical pin needs exactly one probe —
    the voltage read there fingerprints the raw channel feeding it. Fills
    `notes`/`discovered` keyed by raw channel (same shape as the classic
    walk, so the shared table/CSV code just works). Returns True if the
    user stopped early."""
    sig_chans = [c for c in PINS_TO_TEST if c != SHORTED_RAW]
    sig = {c: SIG_START + k * SIG_STEP for k, c in enumerate(sig_chans)}

    def match_sig(volts):
        best = min(sig_chans, key=lambda c: abs(sig[c] - volts))
        return best if abs(sig[best] - volts) <= SIG_STEP / 2 - 0.02 else None

    values = list(zeros)
    for c, v in sig.items():
        values[c] = v
    write(values)

    print("\nSIGNATURE PASS — all unknown channels driven at once:")
    print("   raw ch:" + "".join(f"  {c:>4d}" for c in sig_chans))
    print("   volts :" + "".join(f"  {sig[c]:>4.2f}" for c in sig_chans))
    print(f"   (raw {SHORTED_RAW} held at 0 until its solo pass at the end)")

    remaining = list(DEAD_PHYSICAL)

    # Physical pins inside Guardian range read back automatically — no
    # probing needed there (now all 32, see N_GUARDIAN_CH).
    if guardian is not None:
        time.sleep(0.3)
        vals = read_guardian(*guardian)
        for p in [p for p in remaining if p < len(vals)]:
            r = match_sig(vals[p])
            if r is not None:
                discovered[r] = p
                notes[r] = f"phys {p} @ {vals[p]:+.3f} V (Guardian, signature pass)"
                remaining.remove(p)
                print(f"   [Guardian] physical {p} reads {vals[p]:+.3f} V "
                      f"-> fed by raw ch {r}")
            else:
                print(f"   [Guardian] physical {p} reads {vals[p]:+.3f} V "
                      f"-> no signature match (dead, or on the raw-{SHORTED_RAW} "
                      f"bus — the solo pass will tell)")

    if HOLD_ONLY:
        print("\nHOLD mode — the signature voltages above STAY ON now.")
        print("Probe all the pins at your own pace and write down "
              "physical pin -> volts; nothing to type here.")
        print("   volts -> raw ch:  " +
              ",  ".join(f"{sig[c]:.2f}->{c}"
                         for c in sorted(sig_chans, key=lambda c: sig[c])))
        print(f"   (~0 V means: fed by an already-confirmed channel, fed by "
              f"raw {SHORTED_RAW} — held at 0 until the next step — or dead)")
        input("\n   Press Enter when done probing to switch to the "
              f"raw-{SHORTED_RAW} solo pass... ")
        write(zeros)
        values = list(zeros)
        values[SHORTED_RAW] = TEST_VAL
        write(values)
        print(f"\n   Only raw ch {SHORTED_RAW} is at {TEST_VAL:g} {unit} now "
              f"(known short: several pins may show it). Note which pins are "
              f"live.")
        input("   Press Enter when done to zero everything... ")
        write(zeros)
        return False

    print("\nProbe each pin below ONCE and type the voltage you read "
          "(Enter = nothing/0 there, 'q' = stop):")
    stopped = False
    for p in [p for p in remaining if p >= 8 or guardian is None]:
        ans = input(f"   physical pin {p:2d} reads ({unit}): ").strip().lower()
        if ans == "q":
            stopped = True
            break
        if not ans:
            continue
        try:
            volts = float(ans.rstrip("v").strip())
        except ValueError:
            print("      couldn't parse that as a number — skipping this pin")
            continue
        r = match_sig(volts)
        if r is None:
            print(f"      {volts:g} {unit} matches no signature — leaving pin "
                  f"{p} unidentified")
            continue
        discovered[r] = p
        notes[r] = f"phys {p} @ {volts:g} V (signature pass)"
        remaining.remove(p)
        print(f"      -> physical {p} is fed by raw ch {r} "
              f"(signature {sig[r]:.2f} V)")

    write(zeros)

    if not stopped:
        # Solo pass for the shorted channel: everything else is at 0 now, so
        # any pin that lights up is on the raw-30 bus (or solely fed by it).
        values = list(zeros)
        values[SHORTED_RAW] = TEST_VAL
        write(values)
        print(f"\nSOLO PASS — only raw ch {SHORTED_RAW} at {TEST_VAL:g} {unit} "
              f"(known short: several pins may light up).")
        if remaining:
            print(f"   Physical pins still unidentified: {remaining} — check those.")
        if guardian is not None:
            time.sleep(0.3)
            vals = read_guardian(*guardian)
            hits = [ch for ch, v in enumerate(vals) if abs(v - TEST_VAL) < 0.5]
            if hits:
                print(f"   [Guardian] physical {hits} responding")
        ans = input(f"   physical pins showing ~{TEST_VAL:g} {unit} "
                    "(comma-separated, Enter = none): ").strip()
        if ans:
            notes[SHORTED_RAW] = f"drives phys {ans} (solo pass, known short)"
        write(zeros)

    return stopped


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
            print("Guardian ADC readback connected — will cross-check all pins against hardware.")
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
        if SIGNATURE_MODE and PINS_TO_TEST:
            stopped_early = signature_walk(write, zeros, guardian, unit,
                                           notes, discovered)
        else:
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
                               # physical pin i; in a raw walk (empty remap) this
                               # is still i, so identity wiring reads "as expected"
                prev_note = prior.get(str(i), {}).get("note", "")
                msg = f"  >>> Pin {i:02d} -> {TEST_VAL:g} {unit}  — probe it now"
                if prev_note:
                    msg += f'   [previous note: "{prev_note}"]'
                if guardian is not None:
                    time.sleep(0.3)   # let the ADC settle before reading
                    vals = read_guardian(*guardian)   # N_GUARDIAN_CH physical readback channels
                    # Auto-detect which physical channel actually responded, rather
                    # than only checking the one we EXPECT: the channel(s) that
                    # jumped close to TEST_VAL. With an empty PIN_REMAP this reveals
                    # the true logical->physical landing for every pin whose target
                    # is within Guardian range — no multimeter needed for those.
                    hits = [ch for ch, v in enumerate(vals) if abs(v - TEST_VAL) < 0.5]
                    if len(hits) == 1:
                        found = hits[0]
                        discovered[i] = found
                        tag = "as expected" if found == expected else f"but EXPECTED {expected}"
                        msg += (f"   [Guardian: logical {i} -> physical ch {found} "
                                f"({vals[found]:+.3f} V) — {tag}]")
                    elif not hits:
                        msg += (f"   [Guardian: nothing near {TEST_VAL:g} V within Guardian range "
                                f"({len(vals)} ch) — it lands beyond that or is dead; "
                                f"read it on the multimeter]")
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
    # is already correct. DIRECTION MATTERS now that the map isn't a symmetric
    # involution: `discovered` holds raw/driven channel -> physical landing,
    # while gui.py's PIN_REMAP maps logical pin -> raw channel to DRIVE, so in
    # a raw walk (empty PIN_REMAP) the paste-ready entries are the INVERSE
    # {physical: raw} — the entry that makes GUI pin p come out at physical p.
    nontrivial = {i: p for i, p in discovered.items() if i != p}
    if discovered:
        if PIN_REMAP:
            print("\nAuto-discovered mapping (logical -> physical landing):")
            pairs = ", ".join(f"{i}: {p}" for i, p in sorted(nontrivial.items()))
            print(f'    PIN_REMAP = {{"{DEV}": {{{pairs}}}}}')
        else:
            print("\ngui.py-ready PIN_REMAP entries (logical pin p is fed by "
                  "raw channel r, i.e. {p: r}):")
            pairs = ", ".join(f"{p}: {r}" for p, r in
                              sorted((p, r) for r, p in nontrivial.items()))
            print(f"    {pairs}")
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
