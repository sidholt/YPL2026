"""
itla.py  -  Emcore TTX ITLA driver (OIF-ITLA-MSA-01.3)

Packet format (32-bit, MSB first):
  Inbound  (host -> module): [chk 4b][0][0][RW 1b][register 8b][data 16b]
  Outbound (module -> host): [chk 4b][CE 1b][1][status 2b][register 8b][data 16b]

BIP-4 checksum: XOR of all nibbles of the 28-bit packet with chk field = 0.

Requirements:  pip install pyserial
Usage:
    from itla import ITLA
    it = ITLA()
    it.connect(7, 9600)
    it.nop()
    it.power(0)
    it.channel(1)
    it.resena(8)
"""

import serial, time

# ── Register map ──────────────────────────────────────────────────────────────
REG = {
    "NOP"     : 0x00,
    "DEVTYP"  : 0x01,
    "MFGR"    : 0x02,
    "MODEL"   : 0x03,
    "SERNO"   : 0x04,
    "MFGDATE" : 0x05,
    "RELEASE" : 0x06,
    "STATUSF" : 0x20,
    "STATUSW" : 0x21,
    "CHANNEL" : 0x30,
    "POWER"   : 0x31,
    "RESENA"  : 0x32,
    "GRID"    : 0x34,
    "FCF1"    : 0x35,
    "FCF2"    : 0x36,
    "LF1"     : 0x40,
    "LF2"     : 0x41,
    "OOP"     : 0x42,
    "CTEMP"   : 0x43,
    "OPSL"    : 0x50,
    "OPSH"    : 0x51,
    "LFL1"    : 0x52,
    "LFL2"    : 0x53,
    "LFH1"    : 0x54,
    "LFH2"    : 0x55,
    "LGRID"   : 0x56,
    "CURRENTS": 0x57,
    "TEMPS"   : 0x58,
    "FTF"     : 0x62,
    "DITHERE" : 0x59,   # Master enable: 0x02=on (SBS+TxTrace), 0x00=off
    "DITHERR" : 0x5A,   # SBS dither rate (kHz, 10–200 kHz)
    "DITHERF" : 0x5B,   # FM p-p deviation (0–4, units of GHz*10); 0 disables SBS
    "DITHERA" : 0x5C,   # TxTrace AM amplitude (0–50, 50=5% bias current); 0 disables TxTrace
}

STATUS = {0: "OK", 1: "BUSY", 2: "AEA", 3: "CP"}

# ── Packet helpers ────────────────────────────────────────────────────────────

def _bip4(b0_nochk, b1, b2, b3):
    """BIP-4: XOR all nibbles of the 28-bit word (chk field set to 0)."""
    nibbles = [
        (b0_nochk >> 4) & 0xF, b0_nochk & 0xF,
        (b1 >> 4) & 0xF,       b1 & 0xF,
        (b2 >> 4) & 0xF,       b2 & 0xF,
        (b3 >> 4) & 0xF,       b3 & 0xF,
    ]
    chk = 0
    for n in nibbles:
        chk ^= n
    return chk & 0xF

def _build_read(reg):
    """4-byte read packet for register reg."""
    b0_nochk = 0x00          # RW=0, chk=0
    b1 = reg & 0xFF
    b2 = b3 = 0x00
    chk = _bip4(b0_nochk, b1, b2, b3)
    return bytes([(chk << 4) | 0x00, b1, b2, b3])

def _build_write(reg, data):
    """4-byte write packet for register reg with 16-bit data."""
    b0_nochk = 0x01          # RW=1, chk=0
    b1 = reg & 0xFF
    b2 = (data >> 8) & 0xFF
    b3 = data & 0xFF
    chk = _bip4(b0_nochk, b1, b2, b3)
    return bytes([(chk << 4) | 0x01, b1, b2, b3])

def _parse(resp):
    """Parse 4-byte response. Returns (status, register, data)."""
    if len(resp) < 4:
        raise IOError(f"Short response: {resp.hex() if resp else 'empty'}")
    status = resp[0] & 0x03
    ce     = (resp[0] >> 2) & 0x01
    reg    = resp[1]
    data   = (resp[2] << 8) | resp[3]
    return status, ce, reg, data

# ── ITLA class ────────────────────────────────────────────────────────────────

class ITLA:

    def __init__(self):
        self._sp = None

    def connect(self, com_port, baudrate=9600):
        port = f"COM{com_port}" if isinstance(com_port, int) else com_port
        self._sp = serial.Serial(
            port=port, baudrate=baudrate,
            bytesize=8, parity='N', stopbits=1,
            timeout=1.0, rtscts=False,
        )
        # RTS is wired to MS* on the eval board (active low = selected).
        # Set RTS=False (low) to assert module select, then wait for
        # the 5ms TMS-CMD settling time before sending any packets.
        self._sp.rts = False
        time.sleep(0.05)
        self._sp.reset_input_buffer()
        self._sp.reset_output_buffer()
        print(f"Connected to {port} at {baudrate} baud.")

    def disconnect(self):
        if self._sp and self._sp.is_open:
            self._sp.close()
            print("Disconnected.")

    # ── low level ─────────────────────────────────────────────────────────────

    def _xact(self, pkt, label="", verbose=True):
        """Send packet, read 4-byte response, return (status, ce, reg, data)."""
        self._sp.reset_input_buffer()
        self._sp.write(pkt)
        time.sleep(0.05)
        resp = self._sp.read(4)
        status, ce, reg, data = _parse(resp)
        if verbose:
            flag = " CE!" if ce else ""
            print(f"  {label:30s}  raw={resp.hex()}  "
                  f"status={STATUS.get(status,'?')}({status}){flag}  "
                  f"data=0x{data:04X}")
        return status, ce, reg, data

    def read(self, reg, verbose=True):
        status, ce, _, data = self._xact(
            _build_read(reg), f"READ  0x{reg:02X}", verbose)
        return status, data

    def write(self, reg, data, verbose=True):
        status, ce, _, _ = self._xact(
            _build_write(reg, data), f"WRITE 0x{reg:02X} = 0x{data:04X}", verbose)
        return status

    def poll_ready(self, timeout=30.0):
        """Poll NOP until status=OK or timeout. Returns final NOP data."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            status, data = self.read(REG["NOP"], verbose=False)
            if status == 0:
                return data
            time.sleep(0.5)
        raise TimeoutError("ITLA not ready after timeout")

    # ── high level ────────────────────────────────────────────────────────────

    def nop(self):
        status, data = self.read(REG["NOP"])
        mrdy = (data >> 4) & 1
        print(f"    MRDY={mrdy}  pending=0x{(data>>8):02X}  err={data&0xF}")
        return status, data

    def power(self, dbm_x100=0):
        """Set power in dBm*100 (0 = 0 dBm, 1300 = 13 dBm)."""
        return self.write(REG["POWER"], dbm_x100 & 0xFFFF)

    def channel(self, ch):
        """Tune to channel number."""
        return self.write(REG["CHANNEL"], ch)

    def resena(self, val=None):
        """Read or write ResEna. resena(8) enables laser output."""
        if val is None:
            _, data = self.read(REG["RESENA"])
            return data
        return self.write(REG["RESENA"], val)

    def oop(self):
        """Read optical output power (dBm*100)."""
        _, data = self.read(REG["OOP"])
        if data == 0x8000:
            print("    OOP: laser output disabled / not valid")
        else:
            signed = data if data < 0x8000 else data - 0x10000
            print(f"    OOP: {signed/100:.2f} dBm")
        return data

    def lf(self):
        """Read actual laser frequency."""
        _, thz  = self.read(REG["LF1"], verbose=False)
        _, ghz10 = self.read(REG["LF2"], verbose=False)
        freq = thz * 1000 + ghz10 * 0.1
        print(f"    LF: {thz} THz + {ghz10*0.1:.1f} GHz = {freq:.1f} GHz")
        return freq

    def statusf(self):
        _, data = self.read(REG["STATUSF"])
        srq   = (data >> 15) & 1
        alm   = (data >> 14) & 1
        fatal = (data >> 13) & 1
        dis   = (data >> 12) & 1
        print(f"    StatusF: SRQ={srq} ALM={alm} FATAL={fatal} DIS={dis}  raw=0x{data:04X}")
        return data

    def statusw(self):
        _, data = self.read(REG["STATUSW"])
        srq   = (data >> 15) & 1
        wfreq = (data >> 10) & 1
        wpwr  = (data >>  8) & 1
        print(f"    StatusW: SRQ={srq} WFREQ={wfreq} WPWR={wpwr}  raw=0x{data:04X}")
        return data

    def capabilities(self):
        """Read module capability registers (OPSL/OPSH/LFL/LFH/LGrid).
        Returns dict with power range (dBm) and frequency range (GHz)."""
        _, opsl  = self.read(REG["OPSL"],  verbose=False)
        _, opsh  = self.read(REG["OPSH"],  verbose=False)
        _, lfl1  = self.read(REG["LFL1"],  verbose=False)
        _, lfl2  = self.read(REG["LFL2"],  verbose=False)
        _, lfh1  = self.read(REG["LFH1"],  verbose=False)
        _, lfh2  = self.read(REG["LFH2"],  verbose=False)
        _, lgrid = self.read(REG["LGRID"], verbose=False)
        opsl_dbm = (opsl if opsl < 0x8000 else opsl - 0x10000) / 100.0
        opsh_dbm = (opsh if opsh < 0x8000 else opsh - 0x10000) / 100.0
        return {
            "opsl_dbm" : opsl_dbm,
            "opsh_dbm" : opsh_dbm,
            "f_lo_ghz" : lfl1 * 1000.0 + lfl2 * 0.1,
            "f_hi_ghz" : lfh1 * 1000.0 + lfh2 * 0.1,
            "lgrid_ghz": lgrid * 0.1,
        }

    # ── dither ────────────────────────────────────────────────────────────────

    def dither_rate(self, rate_khz=None):
        """Read or write DitherR (0x5A). SBS rate in kHz; hardware range 10–200 kHz."""
        if rate_khz is None:
            _, data = self.read(REG["DITHERR"])
            return data
        if not (10 <= rate_khz <= 200):
            raise ValueError(f"DitherR {rate_khz} kHz out of range 10–200 kHz")
        return self.write(REG["DITHERR"], int(rate_khz))

    def dither_freq(self, deviation=None):
        """Read or write DitherF (0x5B). FM p-p deviation, integer 0–4 (units of GHz×10).
        Write 0 to disable SBS without touching TxTrace."""
        if deviation is None:
            _, data = self.read(REG["DITHERF"])
            return data
        if not (0 <= deviation <= 4):
            raise ValueError(f"DitherF {deviation} out of range 0–4")
        return self.write(REG["DITHERF"], int(deviation))

    def dither_amp(self, amp=None):
        """Read or write DitherA (0x5C). TxTrace AM amplitude 0–50
        (50 = 5% of bias current for 140 mV RMS input).
        Write 0 to disable TxTrace without touching SBS."""
        if amp is None:
            _, data = self.read(REG["DITHERA"])
            return data
        if not (0 <= amp <= 50):
            raise ValueError(f"DitherA {amp} out of range 0–50")
        return self.write(REG["DITHERA"], int(amp))

    def dither_enable(self, enable=None):
        """Read or write DitherE (0x59). True → 0x02 (enables SBS+TxTrace), False → 0x00.
        DitherF=0 suppresses SBS; DitherA=0 suppresses TxTrace."""
        if enable is None:
            _, data = self.read(REG["DITHERE"])
            return bool(data & 0x02)
        val = 0x02 if enable else 0x00
        return self.write(REG["DITHERE"], val)

    def enable_txtrace(self, amp: int = 50, rate_khz: int = 100):
        """
        Enable TxTrace AM modulation via the analog BNC input.

        Disables SBS (DitherF=0), sets TxTrace amplitude (DitherA),
        sets the dither rate (DitherR), then enables (DitherE=0x02).

        The BNC input accepts 10 kHz–1 MHz; amp=50 → 5% AM at 140 mV RMS.
        Requires the laser to be locked to a channel first.

        Parameters
        ----------
        amp : int
            TxTrace amplitude 0–50 (50 = 5% modulation, factory default).
        rate_khz : int
            Dither rate 10–200 kHz (used for SBS; set here as required by firmware).
        """
        self.dither_enable(False)
        self.dither_freq(0)           # disable SBS
        self.dither_amp(amp)
        self.dither_rate(rate_khz)
        self.dither_enable(True)
        print(f"  TxTrace enabled: amp={amp}  ({amp/10:.1f}% modulation at full input)")

    def enable_sbs(self, rate_khz: int, deviation: int = 4):
        """
        Enable SBS suppression FM dither only (TxTrace disabled).

        Parameters
        ----------
        rate_khz : int
            Dither rate 10–200 kHz.
        deviation : int
            FM p-p deviation 0–4 (GHz×10); 4 is the spec-guaranteed value.
        """
        self.dither_enable(False)
        self.dither_amp(0)            # disable TxTrace
        self.dither_rate(rate_khz)
        self.dither_freq(deviation)
        self.dither_enable(True)
        print(f"  SBS dither enabled: rate={rate_khz} kHz  deviation={deviation*0.1:.1f} GHz")

    def disable_dither(self):
        """Disable all dither (SBS + TxTrace). DitherE → 0x00."""
        self.dither_enable(False)
        print("  Dither disabled (SBS + TxTrace off).")

    def diagnostics(self):
        """Read live diagnostic values: temperature, status flags, output power.
        Returns dict."""
        _, ctemp = self.read(REG["CTEMP"],   verbose=False)
        _, statf = self.read(REG["STATUSF"], verbose=False)
        _, statw = self.read(REG["STATUSW"], verbose=False)
        _, oop   = self.read(REG["OOP"],     verbose=False)
        temp_c = (ctemp if ctemp < 0x8000 else ctemp - 0x10000) / 100.0
        pdbm   = (oop   if oop   < 0x8000 else oop   - 0x10000) / 100.0
        return {
            "temp_c"   : temp_c,
            "statf"    : statf,
            "statw"    : statw,
            "oop_dbm"  : pdbm,
            "oop_valid": oop != 0x8000,
        }


# ── Startup sequence ──────────────────────────────────────────────────────────

def startup(com_port=7, baudrate=9600):
    it = ITLA()
    it.connect(com_port, baudrate)

    print("\n── NOP / module ready ───────────────────────────")
    it.nop()

    print("\n── Channel grid ─────────────────────────────────")
    it.read(REG["FCF1"])
    it.read(REG["FCF2"])
    it.read(REG["GRID"])

    print("\n── Set power, tune, enable ──────────────────────")
    it.power(300)
    time.sleep(0.2)

    it.channel(1)
    print("  Waiting up to 25s for frequency lock...")
    for i in range(25):
        _, data = it.read(REG["STATUSW"], verbose=False)
        wfreq = (data >> 10) & 1
        wpwr  = (data >>  8) & 1
        print(f"  t={i+1}s  WFREQ={wfreq}  WPWR={wpwr}  raw=0x{data:04X}")
        if wfreq == 0:
            print("  Frequency locked!")
            break
        time.sleep(1)

    # Clear latched status bits
    it.write(REG["STATUSF"], 0x00FF)
    it.write(REG["STATUSW"], 0x00FF)
    time.sleep(0.3)

    print("\n── Enable laser ─────────────────────────────────")
    it.resena(8)
    time.sleep(1.0)

    print("\n── Status ───────────────────────────────────────")
    it.nop()
    it.statusf()
    it.statusw()
    it.lf()
    it.oop()

    return it


if __name__ == "__main__":
    it = startup(com_port=7, baudrate=9600)

