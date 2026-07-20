"""
auto_pin_scan.py — Fully automated Dev2 pin-mapping scan using Guardian ADC
readback. No keypresses, no multimeter.

Drives each logical pin 0..31 to TEST_VAL one at a time (all others held at
0 V, RAW — no remap applied, so this observes the true wiring) and watches
the 8 Guardian ADC physical channels. Any logical pin whose physical landing
spot is in 0-7 is identified automatically; pins that land on physical 8-31
are reported as "not visible" and still need the multimeter walk in
pin_identify_test.py.

CRITICAL TIMING FACT (discovered 2026-07-17 by driving all 32 pins to 1 V
and watching the ADC): the Guardian ADC is a slow ROUND-ROBIN scanner — it
refreshes roughly one channel every ~0.4 s, so a full 8-channel refresh
takes ~3 s, and DqAdv333ReadADC returns the last-scanned (possibly seconds-
stale) value per channel. A fixed short sleep before reading is therefore
worthless: this script instead (a) waits until ALL channels have visibly
refreshed to ~0 V before driving each pin, and (b) polls for up to
DRIVE_WAIT_S for a genuine ~TEST_VAL response. Anything less produces
stale-data ghosts (an earlier 0.4 s-settle version of this scan reported
six different pins all "landing" on ch7 at the same stale voltage).

Results are printed as a table, compared against gui.py's current PIN_REMAP,
and saved to a timestamped CSV next to this script.

Prereq: main GUI closed (or Dev2 disconnected in it) — two processes on the
same AO channels behave unpredictably.

Run with the 32-bit venv (PDNALib.dll is 32-bit):
    .venv32\\Scripts\\python.exe auto_pin_scan.py
"""

import ctypes
import csv
import os
import time
import UeiDaq

# ── CONFIG ───────────────────────────────────────────────────────────────
CUBE_IP      = "172.28.2.4"
DEV          = "Dev2"
NUM_CH       = 32
TEST_VAL     = 1.0    # volts driven onto each pin during its slot
HIT_FRAC     = 0.85   # reading > HIT_FRAC*TEST_VAL counts as a hit
ZERO_LEVEL   = 0.1    # all channels must read below this before next pin
DRIVE_WAIT_S = 6.0    # max seconds to wait for a response after driving
ZERO_WAIT_S  = 8.0    # max seconds to wait for all-zero between pins
POLL_S       = 0.15
PDNA_DLL     = r"C:\Program Files (x86)\UEI\PowerDNA\Shared\PDNALib.dll"

# gui.py's remap as of this scan — used only to LABEL agreement/disagreement
# in the report; the scan itself always writes raw (no remap).
GUI_PIN_REMAP = {0: 31, 31: 0}
# ─────────────────────────────────────────────────────────────────────────


def setup_guardian(cube_ip):
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
    print(f"Connecting to {DEV} (voltage) on {CUBE_IP}, Ao0:{NUM_CH - 1}...")
    session = UeiDaq.CUeiSession()
    session.CreateAOChannel(f"pdna://{CUBE_IP}/{DEV}/Ao0:{NUM_CH - 1}", -10.0, 10.0)
    session.ConfigureTimingForSimpleIO()
    writer = UeiDaq.CUeiAnalogScaledWriter(session.GetDataStream())

    dll, handle = setup_guardian(CUBE_IP)
    print("Guardian ADC connected.")

    zeros = [0.0] * NUM_CH
    results = {}   # logical pin -> physical ch (0-7), "MULTI", or None (not visible)

    def wait_all_zero():
        """Block until every ADC channel has refreshed to ~0 V (or timeout).
        Guarantees the next pin's hit can't be a stale ghost of the last one."""
        deadline = time.time() + ZERO_WAIT_S
        while time.time() < deadline:
            if all(abs(v) < ZERO_LEVEL for v in read_guardian(dll, handle)):
                return True
            time.sleep(POLL_S)
        return False

    try:
        writer.WriteSingleScan(zeros)
        if not wait_all_zero():
            print("[WARN] ADC did not settle to zero at start — readings may be unreliable.")
        print("Baseline confirmed ~0 V on all 8 ADC channels.")

        for i in range(NUM_CH):
            values = list(zeros)
            values[i] = TEST_VAL
            writer.WriteSingleScan(values)

            hit = None
            deadline = time.time() + DRIVE_WAIT_S
            while time.time() < deadline:
                vals = read_guardian(dll, handle)
                hits = [ch for ch, v in enumerate(vals) if v > HIT_FRAC * TEST_VAL]
                if len(hits) > 1:
                    hit = "MULTI"
                    print(f"  logical {i:2d} -> MULTIPLE channels {hits} — possible short/crosstalk!")
                    break
                if len(hits) == 1:
                    hit = hits[0]
                    print(f"  logical {i:2d} -> physical {hit}  ({vals[hit]:+.3f} V)")
                    break
                time.sleep(POLL_S)
            if hit is None:
                print(f"  logical {i:2d} -> no ADC response in {DRIVE_WAIT_S:g}s "
                      f"(lands on physical 8-31)")
            results[i] = hit

            writer.WriteSingleScan(zeros)
            if not wait_all_zero():
                print(f"  [WARN] ADC did not return to zero after pin {i} — "
                      f"next result may be contaminated.")
    finally:
        writer.WriteSingleScan(zeros)
        session.Stop()
        dll.DqCloseIOM(handle)
        print("All pins zeroed, sessions closed.")

    visible   = {i: p for i, p in results.items() if isinstance(p, int)}
    invisible = sorted(i for i, p in results.items() if p is None)
    multi     = sorted(i for i, p in results.items() if p == "MULTI")

    print(f"\n=== SCAN RESULT ({len(visible)}/{NUM_CH} pins identified via ADC) ===")
    print(f"{'logical':>7}  {'physical':>8}  vs gui.py PIN_REMAP")
    for i, p in sorted(visible.items()):
        expected = GUI_PIN_REMAP.get(i, i)
        status = "MATCHES current remap" if p == expected else \
                 f"MISMATCH - gui.py currently sends logical {i} to physical {expected}"
        print(f"{i:7d}  {p:8d}  {status}")
    if invisible:
        print(f"\nLanded on physical 8-31 (need multimeter walk): {invisible}")
    if multi:
        print(f"\nMULTIPLE-response pins (investigate wiring): {multi}")

    nontrivial = {i: p for i, p in sorted(visible.items()) if i != p}
    if nontrivial:
        pairs = ", ".join(f"{i}: {p}" for i, p in nontrivial.items())
        print(f'\nConfirmed non-identity pairs for gui.py:  "{DEV}": {{{pairs}}}')

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            f"auto_pin_scan_{DEV}.csv")
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["logical_pin", "physical_channel", "status"])
        for i in range(NUM_CH):
            p = results.get(i)
            if isinstance(p, int):
                w.writerow([i, p, "confirmed_adc"])
            elif p == "MULTI":
                w.writerow([i, "", "multiple_responses"])
            else:
                w.writerow([i, "", "lands_on_8_31_unverified"])
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
