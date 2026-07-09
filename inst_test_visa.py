"""Ask the Santec TSL-550 for its identity, using the GUI's own VISA layer.

The TSL is NOT on the network -- it's on the Prologix GPIB-USB adapter at
GPIB address 1, which enumerates as serial port ASRL4 (COM4). That's the
"Prologix::1::ASRL4::INSTR" address the GUI's init_hardware() uses. (The AWG
is the TCPIP/network instrument, not the laser.)

We reuse VisaInterface so the Prologix ++mode/++addr/++read handshake is done
for us -- the same tested path the running GUI uses.
"""
import os
import sys

# Make "from hardware..." importable no matter where this is run from.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "code", "UeiDaq_gui"))

from hardware.visa_module.visa_interface import VisaInterface

DEVICE = "Prologix::1::ASRL6::INSTR"   # Santec = GPIB addr 1 on the Prologix at COM6

dev = VisaInterface(device_name=DEVICE, force_connect=True)
dev.open()
try:
    print("Connected to:", dev.device_name)
    print("IDN:", dev.query("*IDN?"))
finally:
    dev.close()
