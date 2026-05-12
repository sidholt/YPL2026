import UeiDaq
import time
RECV_SIZE = 64

try:
    session = UeiDaq.CUeiSession()
    port = session.CreateSerialPort("pdna://192.168.101.43/Dev0/com0,1",
                                    UeiDaq.UeiSerialModeRS485FullDuplex,
                                    UeiDaq.UeiSerialBitsPerSecond57600,
                                    UeiDaq.UeiSerialDataBits8,
                                    UeiDaq.UeiSerialParityNone,
                                    UeiDaq.UeiSerialStopBits1,
                                    "")
    session.ConfigureTimingForMessagingIO(500, 100.0)
    session.GetTiming().SetTimeout(1000)

    writers = [UeiDaq.CUeiSerialWriter(session.GetDataStream()) for i in range(session.GetNumberOfChannels())]
    readers = [UeiDaq.CUeiSerialReader(session.GetDataStream()) for i in range(session.GetNumberOfChannels())]

    for p in range(session.GetNumberOfChannels()):
        tempPort = session.GetChannel(p).GetIndex()
        writers[p] = UeiDaq.CUeiSerialWriter(session.GetDataStream(), tempPort)
        readers[p] = UeiDaq.CUeiSerialReader(session.GetDataStream(), tempPort)

    session.Start()

    sendBuffer = [0, 0, 0, 0, 0]

    count = 0
    while count < 10:
        for i in range(session.GetNumberOfChannels()):
            tempPort = session.GetChannel(i).GetIndex()
            sendBuffer[0] = count
            numBytesWritten = writers[i].WriteInt16(sendBuffer)
            print("Sent %d bytes: %s to port %d" % (numBytesWritten, str(sendBuffer), tempPort))

        time.sleep(0.1)
        for i in range(session.GetNumberOfChannels()):
            tempPort = session.GetChannel(i).GetIndex()
            recvBuffer = readers[i].Read(RECV_SIZE)
            print("Received %d bytes: %s from port %d" % (len(recvBuffer), str(recvBuffer), tempPort))
        count += 1

except Exception as e:  # Global error catching.
    print("Exception: %s" % e)  # Print any errors caught.
