import time
import UeiDaq

# This example uses a for loop to send and receive words from a can board.

session = UeiDaq.CUeiSession()
try:
    # Create a new session based off the CAN-503 address and other initialization settings
    session.CreateCANPort("simu://192.168.100.7/Dev6/CAN0,1",
                          UeiDaq.UeiCANBitsPerSecond250K,
                          UeiDaq.UeiCANFrameExtended,
                          UeiDaq.UeiCANPortModeNormal,
                          0xFFFFFFFF,
                          0)
    session.ConfigureTimingForSimpleIO()
    session.GetTiming().SetTimeout(1000)  # Set up max time the reader will go before timing out

    writer = UeiDaq.CUeiCANWriter(session.GetDataStream(), 0)  # Write on port 0
    reader = UeiDaq.CUeiCANReader(session.GetDataStream(), 1)  # Read on port 1

    session.Start() # Starts the session.
    count = 0
    print("Session starting...")
    # Loop until the user wants to stop
    for i in range(1000):
        # ========================================================================================
        # Creation of the CAN frame below.
        for h in range(10):  # Create 10 CAN frames to send.
            frames = []
            frame = UeiDaq.tUeiCANFrame()  # Create new CAN frame.
            frame.Id = count + 1
            frame.Type = UeiDaq.UeiCANFrameTypeData  # Frame is a data type
            frame.DataSize = 8
            frame.Data = bytearray([1, 2, 3, 4, 5, 6, 7, 8])  

            frames.append(frame)

            numFramesWritten = writer.Write(frames)

            # Log the written frame to the console
            print("Wrote %d Frame: Id=%d, Data=%s" % (numFramesWritten, frames[0].Id, str(frames[0].Data)))
            count += 1

        time.sleep(0.5)  # Add a delay to give CAN frames wnought time to travel from TX port to RX port.

        # ========================================================================================
        # Read 10 frames from the reader. If 10 frames aren't written, a timeout error will be thrown and only
        # received frames will be returned
        try:
            framesRead = reader.Read(10)
        except Exception as e:
            print("Exception: %s" % e)
            if e.args[0] == UeiDaq.UEIDAQ_TIMEOUT_ERROR:
                print("CAN board timed out.")
                continue
            else:
                print(e)
                break
                
        numFramesRead = len(framesRead)
        for s in range(numFramesRead):
            # Print the data of the read frames.
            print("     Received frame: Id=%d Type=%s DataSize=%d Data=%s" % (
                framesRead[s].Id, framesRead[s].Type, framesRead[s].DataSize, str(framesRead[s].Data)))

except Exception as e:
    print("Exception: %s" % e)
