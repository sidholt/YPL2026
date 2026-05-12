'''
Created on May 4, 2020

@author: frederic
'''

import UeiDaq
import numpy


numScans = 512
scanRate = 10000.0

try:
    session = UeiDaq.CUeiSession()

    session.CreateAIChannel("simu://dev0/AI0:7", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeSingleEnded)
    session.ConfigureTimingForBufferedIO(numScans, UeiDaq.UeiTimingClockSourceInternal, scanRate, UeiDaq.UeiDigitalEdgeRising, UeiDaq.UeiTimingDurationContinuous)

    reader = UeiDaq.CUeiAnalogScaledReader(session.GetDataStream())

    session.Start()

    data = numpy.zeros((numScans, session.GetNumberOfChannels()))

    for i in range(0, 100):
        reader.ReadMultipleScans(data)
                
        # calculate FFT on each channel
        for ch in range(0, session.GetNumberOfChannels()):
            freqs = numpy.abs(numpy.fft.rfft(data[:, ch])) 
            print("%d: channel %d peak frequency = %f\n" % (i, ch, numpy.argmax(freqs)*(scanRate/numScans)))
        
    session.Stop()

except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print(e)

