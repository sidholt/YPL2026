import UeiDaq
import numpy
import time

try:
    session = UeiDaq.CUeiSession()

    session.CreateAOChannel("pdna://192.168.100.2/dev0/AO0:7", -10.0, 10.0)
    session.ConfigureTimingForSimpleIO()

    writer = UeiDaq.CUeiAnalogScaledWriter(session.GetDataStream())

    session.Start()

    data = numpy.zeros(session.GetNumberOfChannels())
    for i in range(0, 100):
        for ch in range(0,session.GetNumberOfChannels()):
            data[ch] = 10.0 * (i / 100.0)
            print ("ch%d=%f" % (ch, data[ch]))
        writer.WriteSingleScan(data)
 
        time.sleep(0.1)
        
        
    session.Stop()

except Exception as e:
    print (e)
