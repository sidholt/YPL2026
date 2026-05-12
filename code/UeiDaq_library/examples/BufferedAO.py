import UeiDaq
import numpy
import time

try:
    session = UeiDaq.CUeiSession()

    session.CreateAOChannel("pdna://192.168.100.2/dev0/AO0:7", -10.0, 10.0)
    session.ConfigureTimingForBufferedIO(100, UeiDaq.UeiTimingClockSourceInternal, 100.0, UeiDaq.UeiDigitalEdgeRising, UeiDaq.UeiTimingDurationContinuous)

    writer = UeiDaq.CUeiAnalogScaledWriter(session.GetDataStream())

    session.Start()
    
    t = numpy.arange(0,session.GetDataStream().GetNumberOfScans(),1)
    
    # create a tuple containing one sine waveform per channel
    waveforms = ()
    for ch in range(0,session.GetNumberOfChannels()):
        channelWaveform = (10.0 * numpy.sin(t))+10.0
        waveforms = waveforms + (channelWaveform,)
        
    # stack waveforms in a 2D array
    data = numpy.column_stack(waveforms)
    
    for i in range(0, 100):        
        writer.WriteMultipleScans(data) 
        
        print("Wrote frame# %d" % i)
        time.sleep(0.5)

    session.Stop()

except Exception as e:
    print(e)