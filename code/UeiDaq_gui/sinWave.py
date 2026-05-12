import UeiDaq
import time
import math
import signal
import sys

s = UeiDaq.CUeiSession()
s.CreateAOCurrentChannel("pdna://172.28.2.4/Dev1/Ao0:7", 0.0, 0.02)
s.ConfigureTimingForSimpleIO()
w = UeiDaq.CUeiAnalogScaledWriter(s.GetDataStream())

FREQ_HZ   = 10000
STEP_MS   = 5      # smoother updates
AMPLITUDE = 0.01
OFFSET    = 0.01

def cleanup(sig=None, frame=None):
    print("\nZeroing and stopping...")
    w.WriteSingleScan([0.0] * 8)
    s.Stop()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)

print("Running sine wave on pin 0 — Ctrl+C to stop")
t = 0.0
while True:
    val = OFFSET + AMPLITUDE * math.sin(2 * math.pi * FREQ_HZ * t)
    w.WriteSingleScan([val, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    time.sleep(STEP_MS / 1000.0)
    t += STEP_MS / 1000.0