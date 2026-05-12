import UeiDaq
import numpy
import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as P


numScans=512
scanRate=1000.0

try:
    session = UeiDaq.CUeiSession()

    session.CreateAIChannel("simu://dev0/AI0:7", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeSingleEnded)
    session.ConfigureTimingForBufferedIO(numScans, UeiDaq.UeiTimingClockSourceInternal, scanRate, UeiDaq.UeiDigitalEdgeRising, UeiDaq.UeiTimingDurationContinuous)

    reader = UeiDaq.CUeiAnalogScaledReader(session.GetDataStream())

    session.Start()
    
    P.ion()
    P.show(block=False)
    
    fig = P.figure()
    timeAxe = fig.add_subplot(211)
    spectrumAxe = fig.add_subplot(212)

    time = numpy.arange(0,numScans/scanRate,1/scanRate)
    data = numpy.zeros((numScans, session.GetNumberOfChannels()))
    
    for i in range(0, 100):
        reader.ReadMultipleScans(data)

        timeAxe.cla()
        spectrumAxe.cla()
        
        for ch in range(0,session.GetNumberOfChannels()):
            timeAxe.plot(time, data[:,ch])
            spectrumAxe.magnitude_spectrum(data[:,ch], scanRate)
            
        P.show()
        P.pause(0.001)
        print(i)

    session.Stop()

except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print(e)
