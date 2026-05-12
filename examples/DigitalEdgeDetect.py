import UeiDaq
import numpy
import time

# This example demonstrates how to communicate with digital boards.

try:
    diSession = UeiDaq.CUeiSession()  # Create a digital in session
    

    # Use industrial DI channels for MF-101, DIO-448, DIO-449 and DIO-480
    # Use regular DI channels for all other DIO devices
    diSession.CreateDIChannel("pdna://192.168.100.11/dev9/DI0") 

    # Set the mask that specifies the input lines that can trigger change of state events
    diPort = diSession.GetDIChannel(0) 
    diPort.SetEdgeMask(0xFF, UeiDaq.UeiDigitalEdgeRising);

    diSession.ConfigureTimingForEdgeDetection(UeiDaq.UeiDigitalEdgeRising)  # Set timing for edge detection IO

    reader = UeiDaq.CUeiDigitalReader(diSession.GetDataStream())  # Create the reader for the session
    
    diSession.Start()  # Start the sessions
        
    while True:
        try:
            # read edge detect data. It is a list of two values per DI port [ rising edge, falling edge]
            edgeData = reader.ReadEdgeDetectData(2)  
            
            print(edgeData)
        except Exception as e:
            # ignore timeout errors
            if e.args[0] == UeiDaq.UEIDAQ_TIMEOUT_ERROR:
                continue
            raise e

except KeyboardInterrupt:
    diSession.Stop()

except Exception as e:  # Catch any errors thrown by reading/writing
    print ("Error: " + str(e))
