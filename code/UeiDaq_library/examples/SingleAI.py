import UeiDaq
import numpy
import time

try:
    session = UeiDaq.CUeiSession()

    session.CreateAIChannel("simu://dev0/AI0:15", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeSingleEnded)
    session.ConfigureTimingForSimpleIO()

    reader = UeiDaq.CUeiAnalogScaledReader(session.GetDataStream())
    
    # Individual channel attributes can be accessed if needed
    for ch in range(0,session.GetNumberOfChannels()):
        aichannel = session.GetAIChannel(ch)
        aichannel.SetAliasName("Channel %d" % aichannel.GetIndex())
        print("%s: AZ=%d" % (aichannel.GetAliasName(), aichannel.IsAutoZeroEnabled()))

    session.Start()

    data = numpy.zeros(session.GetNumberOfChannels())
    for i in range(0, 100):
        reader.ReadSingleScan(data)

        for ch in range(0,session.GetNumberOfChannels()):
            val = data[ch]
            print ("ch%d=%f" % (ch, val))

        time.sleep(0.1)

    session.Stop()
    
except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print("Exception: %s" % e)
