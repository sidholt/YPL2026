import UeiDaq
import numpy
import time

try:
    session = UeiDaq.CUeiSession()

    session.CreateAOChannel("pdna://192.168.100.7/dev2/AO0:7", -10.0, 10.0)
    session.ConfigureTimingForSimpleIO()
    
    # Configure startup values (one per channel)
    # Those values are automatically set on the AO device's channels
    # when the IOM boots up
    supValues = numpy.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    session.SetCustomPropertyDbl1D("startupvalues", supValues)
    
    # read-back startup values
    supValues = numpy.zeros(session.GetDevice().GetNumberOfAOChannels())
    session.GetCustomPropertyDbl1D("startupvalues", supValues)
    print(supValues)
    
    # Access to the output channels is done through a writer object
    writer = UeiDaq.CUeiAnalogScaledWriter(session.GetDataStream())

    # start the session
    session.Start()

    data = numpy.zeros(session.GetNumberOfChannels())
    for i in range(0, 100):
        for ch in range(0,session.GetNumberOfChannels()):
            data[ch] = 10.0 * (i / 100.0)
            print("ch%d=%f" % (ch, data[ch]))
        writer.WriteSingleScan(data)
 
        time.sleep(0.1)
        
        
    session.Stop()

except Exception as e:
    print (e)
