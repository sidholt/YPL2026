import threading
import time
import UeiDaq

session = UeiDaq.CUeiSession()

# This program uses a write thread and a read thread to continuously write and read from a single
# CAN port. Uses wrapper functions to read and write that are defined and documented in UeiDaqPy.i
# Both threads continuously write and read until the user enters some input into the console.


def ReadThread(canreader):  # canreader is the reader for the port on the 503 board.
    while session.IsRunning():  # if the session ends, stop reading
        try:
            # Read a single frame from the reader
            framesRead = canreader.Read(10)
            numFramesRead = len(framesRead)
            for i in range(numFramesRead):
                # Print the data of the read frames.
                print("     Received frame: Id=%d Type=%s DataSize=%d Data=%s" % (
                      framesRead[i].Id, framesRead[i].Type, framesRead[i].DataSize, str(framesRead[i].Data)))
            time.sleep(0.1001)  # add a delay slightly more than the write thread so a frame has been written.
        except Exception as c:  # The wrapped read method throws exceptions, catch them here.
            if c[0] == UeiDaq.UEIDAQ_TIMEOUT_ERROR:
                print("Reading timed out...")
            else:
                print("Exception in read thread: %s" % c)


def WriteThread(canwriter):  # canwriter is the writer for the port on the 503 board
    numFrames = 10
    count = 1
    try:
        while session.IsRunning():  # if the session ends, stop reading
            # Creation of the CAN frame below.
            frames = []
            for z in range(numFrames):
                frame = UeiDaq.tUeiCANFrame()
                frame.Id = count
                frame.Type = UeiDaq.UeiCANFrameTypeData  # Frame is a data type
                frame.DataSize = 1
                frame.Data = bytearray([count%255, 0, 0, 0, 0, 0, 0 ,0])
                frames.append(frame)
                count += 1
            # Pass the writer, the frame, and number of frames to the wrapper function to be written.
            numFramesWritten = canwriter.Write(frames)
            # Log the written frame to the console
            for i in range(numFramesWritten):
                print("Wrote Frame: Id=%d, Data=%s" % (frames[i].Id, str(frames[i].Data)))
            time.sleep(0.1)  # Add a slight delay to the writing of frames.
    except Exception as c:  # Catch any exceptions thrown
        print("Exception in write thread: %s" % c)


try:
    # Create a new session based off the CAN-503 address and other initialization settings
    session.CreateCANPort("pdna://192.168.101.43/Dev2/CAN0:1",
                          UeiDaq.UeiCANBitsPerSecond100K,
                          UeiDaq.UeiCANFrameExtended,
                          UeiDaq.UeiCANPortModeNormal,
                          0xFFFFFFFF,
                          0)
    session.ConfigureTimingForMessagingIO(1, 0)
    session.GetTiming().SetTimeout(1000)  # Set up max time the reader will go before timing out

    writer = UeiDaq.CUeiCANWriter(session.GetDataStream(), 0)  # Write on port 0
    reader = UeiDaq.CUeiCANReader(session.GetDataStream(), 1)  # Read on port 1

    session.Start()

    writeThread = threading.Thread(target=WriteThread, args=(writer,))  # Set up the write thread with the writer
    readThread = threading.Thread(target=ReadThread, args=(reader,))  # Set up the read thread with the reader

    print("To end the session, hit 'Enter'")  # Let the user know how to close the program

    writeThread.start()  # Begin the writing thread
    time.sleep(0.05)  # Offset the threads
    readThread.start()  # Begin the reading thread

    while 1 == 1:
        if raw_input() == "":  # If the user hits the "enter" key, stop the threads and close the program
            print("Ending session and stopping threads...")
            session.Stop()  # Stop session, thereby stopping the threads
            session.CleanUp()
            print("Session ended, threads cleaned up.")
            break

except Exception as e:  # Catch any exceptions in the main loop
    print("Exception: %s" % e)
