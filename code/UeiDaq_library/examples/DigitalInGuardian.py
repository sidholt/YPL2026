import UeiDaq
import numpy
import time

# This example demonstrates how to communicate with digital boards.

try:
    diSession = UeiDaq.CUeiSession()  # Create a digital in session
    diSession.CreateDIIndustrialChannel("pdna://192.168.100.2/dev6/DI0", 2.0, 4.0, 0.0) 
    diSession.ConfigureTimingForSimpleIO()  # Set timing for regular IO

    aiSession = UeiDaq.CUeiSession()  # Create a digital in session
    aiSession.CreateAIChannel("pdna://192.168.100.2/dev6/AI0:47", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeSingleEnded)
    aiSession.ConfigureTimingForSimpleIO()  # Set timing for regular IO

    diReader = UeiDaq.CUeiDigitalReader(diSession.GetDataStream())  # Create the reader for the DI session
    aiReader = UeiDaq.CUeiAnalogScaledReader(aiSession.GetDataStream())  # Create the reader for the AI session

    diSession.Start()  # Start the sessions
    aiSession.Start()

    # AI and DI sessions are using numpy arrays/vectors to store measurements
    diData = numpy.zeros(1, dtype='uint32')  # Create an array of uint32's for data coming in
    aiData = numpy.zeros(aiSession.GetNumberOfChannels())

    for i in range(0, 100):
        diReader.ReadSingleScanUInt32(diData)  # Use this function for specifically uint32 data reading
        aiReader.ReadSingleScan(aiData)

        print("DI lines state: 0x%x" % diData[0])

        diag = "DI lines voltage: "
        for i in range(0, aiSession.GetNumberOfChannels()):
            diag = diag + ", " + str(aiData[i])
        print(diag)

        time.sleep(0.2)

    diSession.Stop()  # Stop sessions
    aiSession.Stop()

except KeyboardInterrupt:
    diSession.Stop()
    aiSession.Stop()

except Exception as e:  # Catch any errors thrown by reading/writing
    print ("Error: " + str(e))
