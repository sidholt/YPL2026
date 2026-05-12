import UeiDaq

enum = UeiDaq.CUeiDeviceEnumerator("pdna://172.28.2.4")
count = enum.GetNumberOfDevices()
print(f"Total devices: {count}")
for i in range(count):
    dev = enum.GetDevice(i)
    print(f"Slot {i}: {dev.GetDeviceName()}")