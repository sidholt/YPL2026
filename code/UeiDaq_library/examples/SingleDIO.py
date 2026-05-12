import UeiDaq
import numpy
import time

# This example demonstrates how to communicate with digital boards.

try:
    diSession = UeiDaq.CUeiSession()  # Create a digital in session
    doSession = UeiDaq.CUeiSession()  # Create a digital out session

    # Use industrial DI channels for MF-101, DIO-448, DIO-449 and DIO-480
    # Use regular DI channels for all other DIO devices
    diPort = diSession.CreateDIIndustrialChannel("pdna://192.168.100.2/dev0/DI0", 1.0, 3.0, 0.0) 
    #diPort = diSession.CreateDIChannel("pdna://192.168.100.2/dev2/DI0") 
    
    # Use protected DO channels for MF-101, DIO-432, DIO-433 and DIO-480
    # Use regular DO channels on all other DIO devices
    doPort = doSession.CreateDOIndustrialChannel("pdna://192.168.100.2/dev0/DO0", UeiDaq.UeiDOPWMDisabled, 0, 0, 0)
    #doPort = doSession.CreateDOProtectedChannel("pdna://192.168.100.2/dev0/DO0", 0.0, 2.0, 0.1, True, 0.1)
    #doPort = doSession.CreateDOChannel("pdna://192.168.100.2/dev0/DO0") 
    
    # Some devices allow configuring different direction for lines in the same port.
    # Set the mask used to select wich digital line will be used as output.
    # When bit x is set to 1, line x is used as output.
    doPort.SetOutputMask(0xF);

    diSession.ConfigureTimingForSimpleIO()  # Set timing for regular IO
    doSession.ConfigureTimingForSimpleIO()

    reader = UeiDaq.CUeiDigitalReader(diSession.GetDataStream())  # Create the reader for the session
    writer = UeiDaq.CUeiDigitalWriter(doSession.GetDataStream())  # Create writer for the session

    diSession.Start()  # Start the sessions
    doSession.Start()

    if doSession.GetDevice().GetDOResolution() <= 16:
        dataOut = numpy.zeros(1, dtype='uint16')  # Create a numpy array of uint16(s) for data going out
        print("DI device uses uint16\n")
    else:
        dataOut = numpy.zeros(1, dtype='uint32')  # Create a numpy array of uint32(s) for data going out
        
    if diSession.GetDevice().GetDIResolution() <= 16:
        dataIn = numpy.zeros(1, dtype='uint16')  # Create an array of uint16(s) for data coming in
        print("DO device uses uint16\n")
    else:
        dataIn = numpy.zeros(1, dtype='uint32')  # Create an array of uint32(s) for data coming in

    for i in range(0, 100):
        dataOut[0] = i % 255
        if doSession.GetDevice().GetDOResolution() <= 16:
            writer.WriteSingleScanUInt16(dataOut)  # Use this function for specifically uint16 data writing
        else:
            writer.WriteSingleScanUInt32(dataOut)  # Use this function for specifically uint32 data writing
        print("Wrote %x" % dataOut[0])

        time.sleep(0.1)

        if diSession.GetDevice().GetDIResolution() <= 16:
            reader.ReadSingleScanUInt16(dataIn)  # Use this function for specifically uint16 data reading
        else:
            reader.ReadSingleScanUInt32(dataIn)  # Use this function for specifically uint32 data reading
        print("Read %x" % dataIn[0])

    diSession.Stop()  # Stop sessions
    doSession.Stop()

except Exception as e:  # Catch any errors thrown by reading/writing
    print ("Error: " + str(e))
