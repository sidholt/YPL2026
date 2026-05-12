import UeiDaq
import time
import copy

try:
    startRt = 4
    startSa = 7
    wordCount = 10
    rt_chan = 1
    frames = 2
   
    # Create resource string for 1553 device and port
    rtResource = "simu://192.168.100.2/dev7"
    #rtResource = "pdna://192.168.100.2/dev9"
    rtResource += "/milb" + str(rt_chan)

    # Configure port as remote terminal
    session = UeiDaq.CUeiSession()
    session.CreateMIL1553Port(rtResource, UeiDaq.UeiMIL1553CouplingTransformer, UeiDaq.UeiMIL1553OpModeRemoteTerminal)

    session.ConfigureTimingForSimpleIO()
    session.GetTiming().SetTimeout(100)

    # Get device status information
    status = session.GetDevice().GetStatus()
    print("1553 device status: %s" % status)

    # create one reader and one writer for RT port
    reader = UeiDaq.CUeiMIL1553Reader(session.GetDataStream(), rt_chan)
    writer = UeiDaq.CUeiMIL1553Writer(session.GetDataStream(), rt_chan)

    session.Start()

    # output RT frames are read as list
    outFrms = []

    # RT needs "dummy" input frames to specify the Rt, Sa, block and datasize of the
    # receive area to be read
    inFrms = []
      
    for j in range(0, frames):
        inFrm = UeiDaq.CUeiMIL1553RTFrame(startRt+j, startSa+j, 0, wordCount).GetFrame()
        inFrms.append(inFrm)
        
        outRtFrm = UeiDaq.CUeiMIL1553RTFrame(startRt+j, startSa+j, 0, wordCount).GetFrame()
        data = [0] * 36
        for i in range(0, wordCount):
            data[i] = j + i + 1
        outRtFrm.RxTxData = data
        outFrms.append(outRtFrm)

    # Start RTs - all SAs will be started at this time
    for j in range(0, frames):
        writer.WriteRTFrame([outFrms[j]])
        
    c=1
    while True:  
        # Change and retreive RT data at each iteration
        # Store data to RT "transmit" area
        for j in range(0, frames):
            data = [0] * 36
            for i in range(0, wordCount):
              data[i] = j * 10 + i + c
            outFrms[j].RxTxData = data
            
            writer.WriteRTFrame([outFrms[j]])   
            print("Wrote RT=%d Sa=%d Data=%s" % (outFrms[j].Rt,  outFrms[j].Sa, outFrms[j].RxTxData[0:outFrms[j].DataSize]))
            
        # Read data from RT "receive" area
        for j in range(0, frames):
            rtFrms = reader.ReadRTFrame([inFrms[j]])
            #rtFrms = []
            if len(rtFrms) > 0:
                rtFrm = UeiDaq.CUeiMIL1553RTFrame(rtFrms[0])
                print("Read RT frame=%s Data=%s" % (rtFrm.GetFrameStr(),  rtFrm.GetDataStr()))
                print("Read RT=%d Sa=%d Data=%s" % (rtFrms[0].Rt,  rtFrms[0].Sa, rtFrms[0].RxTxData[0:rtFrms[0].DataSize]))
                
         
        time.sleep(0.1)

        # Read bus monitor and display bus activity
        while True:
            bmFrm = reader.ReadBMFrame(1)
            if not len(bmFrm): 
                break
                   
            print("RT:%d SA:%d WC:%d DS:%d CMD:%s DATA:%s\n" % \
                  (bmFrm[0].Rt, \
                  bmFrm[0].Sa, \
                  bmFrm[0].WordCount, \
                  bmFrm[0].DataSize , \
                  bmFrm[0].Command, \
                  bmFrm[0].BmData[0:bmFrm[0].DataSize]))
            
            # CUeiMIL1553BMFrame extends tUeiMIL1553BMFrame with methods to print
            # BM frames
            extFrm = UeiDaq.CUeiMIL1553BMFrame(bmFrm[0])
            print(extFrm.GetBmMessageStr())
            print(extFrm.GetBmDataStrDataOnly())

            break
         
        print("====================================================\n")
         
        print("iteration:%d" %c)
          
        c = c + 1

    session.Stop()

except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print("Exception: %s" % e)