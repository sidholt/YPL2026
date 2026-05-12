import ctypes
import ctypes.util
import UeiDaq
import time

# Load the PowerDNA low-level library
pdna = ctypes.CDLL(r"C:\Program Files (x86)\UEI\PowerDNA\Shared\PDNALib.dll")

# Open connection
DqInitDAQLib = pdna.DqInitDAQLib
DqInitDAQLib()

hd = ctypes.c_int(0)
timeout = ctypes.c_int(2000)
DqOpenIOM = pdna.DqOpenIOM
DqOpenIOM.restype = ctypes.c_int
ret = DqOpenIOM(b"172.28.2.4", ctypes.c_int(6334), timeout, ctypes.byref(hd), None)
print(f"OpenIOM ret={ret}, hd={hd.value}")

# Write 5V to pin 0 using UeiDaq as normal
ao = UeiDaq.CUeiSession()
ao.CreateAOChannel("pdna://172.28.2.4/Dev2/Ao0:7", -10.0, 10.0)
ao.ConfigureTimingForSimpleIO()
w = UeiDaq.CUeiAnalogScaledWriter(ao.GetDataStream())
w.WriteSingleScan([5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
print("Wrote 5V to pin 0")
time.sleep(3.0)  # wait for ADC conversion per sample code

# Read back using low-level DqAdv333ReadADC
CHANNELS = 8
rcl  = (ctypes.c_uint32 * CHANNELS)(*range(CHANNELS))
rdata = (ctypes.c_uint32 * CHANNELS)()
afdata = (ctypes.c_double * CHANNELS)()

DqAdv333ReadADC = pdna.DqAdv333ReadADC
DqAdv333ReadADC.restype = ctypes.c_int
ret = DqAdv333ReadADC(hd, ctypes.c_int(2), ctypes.c_int(CHANNELS), rcl, rdata, afdata)
print(f"ReadADC ret={ret}")
print(f"Readback: {list(afdata)}")

ao.Stop()
pdna.DqCloseIOM(hd)
pdna.DqCleanUpDAQLib()