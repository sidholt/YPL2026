import UeiDaq
import time

try:
    vrSession = UeiDaq.CUeiSession()

    vrSession.CreateVRChannel("pdna://192.168.100.11/Dev3/vr0,1,2,3", UeiDaq.UeiVRModeCounterTimed)
    vrSession.ConfigureTimingForSimpleIO()
    
    readers = []
    
    # We need one reader per channel because they can be configured independantly
    # and return data at a different rate
    for ch in range(0, vrSession.GetNumberOfChannels()):
        channel = vrSession.GetChannel(ch).GetIndex()

        readers.append(UeiDaq.CUeiVRReader(vrSession.GetDataStream(), channel))

    vrSession.Start()

    for i in range(0, 100):
        for ch in range(0, vrSession.GetNumberOfChannels()):
            channel = vrSession.GetChannel(ch).GetIndex()
            
            vrData = readers[ch].ReadVRData(1)

            print("Ch%d: velocity=%f" % (channel, vrData[0].velocity))
            print("Ch%d: position=%d" % (channel, vrData[0].position))
            print("Ch%d: teeth count=%d" % (channel, vrData[0].teethCount))

        time.sleep(0.5)

    vrSession.Stop()

except KeyboardInterrupt:
    if vrSession.IsRunning():
        vrSession.Stop()

except Exception as e:
    print (e)
