import UeiDaq
import numpy

try:
    session = UeiDaq.CUeiSession()
    numScans = 100

    session.CreateAIChannel("pdna://192.168.100.2/dev5/AI0:7", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeDifferential)
    session.ConfigureTimingForBufferedIO(numScans, UeiDaq.UeiTimingClockSourceInternal, 1000.0, UeiDaq.UeiDigitalEdgeRising, UeiDaq.UeiTimingDurationContinuous)

    reader = UeiDaq.CUeiAnalogScaledReader(session.GetDataStream())

    session.Start()
    
    data = numpy.zeros((numScans, session.GetNumberOfChannels()))
    
    for i in range(0, 100):
        reader.ReadMultipleScans(data)

        for ch in range(0,session.GetNumberOfChannels()):
            print("ch%d = %f" % (session.GetChannel(ch).GetIndex(), data[0,ch]))

    session.Stop()

except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print (e)
