"""
ao333_bridge.py — 32-bit streaming bridge for AO-333 Guardian ADC readback
Run with .venv32 (32-bit Python 3.12 + 32-bit UeiDaq wheel).

Instead of request/response, this bridge streams readings as fast as
DqAdv333ReadADC allows as newline-delimited JSON. The client just reads
lines as fast as it can.

NUM_CH was 8 for a while (the only channels this bridge streamed), timed at
~2-5ms per read. 2026-07-21: bumped to 32 to cover every Dev2 output — the
datasheet's own spec ("all 32 channels read in 2.4 seconds") suggests the
card's ADC mux may take meaningfully longer per read at 32 channels than at
8; watch this bridge's own console output (or the GUI's readback labels)
after starting it to see the real per-read timing on this hardware. If it's
too slow for live feedback, drop NUM_CH back down — nothing else in the
client (gui.py) hardcodes a channel count, it just displays whatever length
array this bridge sends.

Protocol:
  Server streams: "[v0, v1, ..., v31]\n" continuously
  Client sends:   "QUIT\n" to stop
"""

import sys
import socket
import json
import ctypes
import time

# ── config ────────────────────────────────────────────────────────────────────
CUBE_IP = "172.28.2.4"
DEV_NUM     = 2
NUM_CH      = 32   # was 8 — see module docstring; revert to 8 if this proves too slow
BRIDGE_PORT = 57333
PDNA_DLL    = r"C:\Program Files (x86)\UEI\PowerDNA\Shared\PDNALib.dll"
UDP_PORT    = 6334
TIMEOUT_MS  = 1000
# ──────────────────────────────────────────────────────────────────────────────


def setup_dll():
    dll = ctypes.WinDLL(PDNA_DLL)
    dll.DqInitDAQLib.restype  = ctypes.c_int
    dll.DqInitDAQLib.argtypes = []
    dll.DqOpenIOM.restype  = ctypes.c_int
    dll.DqOpenIOM.argtypes = [
        ctypes.c_char_p, ctypes.c_uint16, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_int), ctypes.c_void_p,
    ]
    dll.DqCloseIOM.restype  = ctypes.c_int
    dll.DqCloseIOM.argtypes = [ctypes.c_int]
    dll.DqAdv333ReadADC.restype  = ctypes.c_int
    dll.DqAdv333ReadADC.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_double),
    ]
    return dll


def open_iom(dll):
    dll.DqInitDAQLib()
    handle = ctypes.c_int(0)
    ret = dll.DqOpenIOM(
        CUBE_IP.encode(), ctypes.c_uint16(UDP_PORT),
        ctypes.c_uint32(TIMEOUT_MS), ctypes.byref(handle), None)
    if ret < 0:
        raise RuntimeError(f"DqOpenIOM returned {ret}")
    return handle.value


def read_guardian(dll, handle, cl, bdata, fdata):
    ret = dll.DqAdv333ReadADC(
        ctypes.c_int(handle), ctypes.c_int(DEV_NUM), ctypes.c_int(NUM_CH),
        cl, bdata, fdata)
    if ret < 0:
        raise RuntimeError(f"DqAdv333ReadADC returned {ret}")
    return list(fdata)


def main():
    print(f"[Bridge] Starting streaming AO-333 bridge on port {BRIDGE_PORT}")
    print(f"[Bridge] Architecture: {'32-bit' if sys.maxsize <= 2**32 else '64-bit'}")

    dll    = setup_dll()
    handle = open_iom(dll)
    print(f"[Bridge] Connected to cube, handle={handle}")

    # pre-allocate buffers
    cl    = (ctypes.c_uint32 * NUM_CH)(*range(NUM_CH))
    bdata = (ctypes.c_uint32 * NUM_CH)(*([0] * NUM_CH))
    fdata = (ctypes.c_double  * NUM_CH)(*([0.0] * NUM_CH))

    # test read — timed, so switching NUM_CH (8 -> 32) shows its real cost on
    # this hardware instead of being assumed
    t0   = time.time()
    vals = read_guardian(dll, handle, cl, bdata, fdata)
    dt_ms = (time.time() - t0) * 1000
    print(f"[Bridge] Test read OK ({NUM_CH} ch, {dt_ms:.1f} ms): "
          f"{[f'{v:.6f}' for v in vals]}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", BRIDGE_PORT))
    server.listen(1)
    server.settimeout(1.0)
    print(f"[Bridge] Listening on 127.0.0.1:{BRIDGE_PORT}")

    try:
        while True:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue

            print(f"[Bridge] Client connected: {addr}")
            conn.setblocking(False)   # non-blocking so we don't wait on recv

            # Sustained-rate log (distinct from the one-off test read above)
            # — the real number to judge NUM_CH=32 by, since a single read
            # can be misleadingly fast/slow compared to the streaming loop.
            reads_since_log = 0
            last_log_t = time.time()

            try:
                while True:
                    # check for QUIT without blocking
                    try:
                        data = conn.recv(64).decode("utf-8")
                        if "QUIT" in data:
                            print("[Bridge] QUIT received")
                            break
                    except BlockingIOError:
                        pass  # no data ready — keep streaming
                    except Exception:
                        break

                    # read and stream as fast as hardware allows
                    try:
                        vals  = read_guardian(dll, handle, cl, bdata, fdata)
                        line  = json.dumps(vals) + "\n"
                        conn.sendall(line.encode("utf-8"))
                    except Exception as e:
                        print(f"[Bridge] Read/send error: {e}")
                        break

                    reads_since_log += 1
                    now = time.time()
                    if now - last_log_t >= 2.0:
                        rate = reads_since_log / (now - last_log_t)
                        print(f"[Bridge] Sustained rate: {rate:.1f} reads/sec "
                              f"({NUM_CH} ch/read)")
                        reads_since_log = 0
                        last_log_t = now

            except Exception as e:
                print(f"[Bridge] Connection error: {e}")
            finally:
                conn.close()
                print("[Bridge] Client disconnected")

    except KeyboardInterrupt:
        print("[Bridge] Interrupted")
    finally:
        server.close()
        dll.DqCloseIOM(handle)
        print("[Bridge] Shutdown complete")


if __name__ == "__main__":
    main()