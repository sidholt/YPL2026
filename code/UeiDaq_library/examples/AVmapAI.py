import UeiDaq
import numpy
import csv

try:
    session = UeiDaq.CUeiSession()
    scanRate = 1000.0
    numScans = 100

    session.CreateAIChannel("pdna://192.168.100.12/dev6/AI0:2,ts", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeDifferential)
    # Configure AVMap mode with watermark set to half FIFO (1024)
    session.ConfigureTimingForAsyncVMapIO(UeiDaq.UeiTimingClockSourceInternal, 1000.0, UeiDaq.UeiDigitalEdgeRising, 1024, 0)

    reader = UeiDaq.CUeiAnalogScaledReader(session.GetDataStream())

    session.Start()
    
    data = numpy.zeros((numScans, session.GetNumberOfChannels()))
    
    # delete previous file
    f = open("c:\\temp\\data.csv", "wb")
    for i in range(0, 100):
        reader.ReadMultipleScans(data)
        
        print("Acquired buffer #%d (%d scans)" % (i, data.shape[0]))
     
        numpy.savetxt(f, data, delimiter=",")

        #for ch in range(0,session.GetNumberOfChannels()):
        #    print("ch%d = %f" % (session.GetChannel(ch).GetIndex(), data[0,ch]))
    close(f)
    session.Stop()

except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print (e)
