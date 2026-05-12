# This example programs MIL-1553 RT and BM on channel 0 and BC on channel 1
# It continuously update "tranmit" area of RT, Rx data are of BC and read transaction data back
import UeiDaq
import time

try:
    session = UeiDaq.CUeiSession()

    startRt = 3
    startSa = 10
    wordCount = 10

    deviceResource = "pdna://192.168.100.2/dev9"
    bcResource = deviceResource + "/milb0"
    rtResource = deviceResource + "/milb1"

    # port 0 - bus controller
    bcPort = session.CreateMIL1553Port(bcResource, UeiDaq.UeiMIL1553CouplingTransformer,\
                                                   UeiDaq.UeiMIL1553OpModeBusController)

    # port 1 - remote terminal
    rtPort = session.CreateMIL1553Port(rtResource, UeiDaq.UeiMIL1553CouplingTransformer, \
                                                   UeiDaq.UeiMIL1553OpModeRemoteTerminal)

    session.ConfigureTimingForSimpleIO()
    session.GetTiming().SetTimeout(1000)

    # Get device status information
    status = session.GetDevice().GetStatus()
    print("device status: %s" % status)
    
    # create one reader and one writer per configured port
    writers = [] 
    readers = []
    for ch in range(0,2):
        readers.append(UeiDaq.CUeiMIL1553Reader(session.GetDataStream(), session.GetChannel(ch).GetIndex()))
        writers.append(UeiDaq.CUeiMIL1553Writer(session.GetDataStream(), session.GetChannel(ch).GetIndex()))

    # First, configure remote terminal on channel 1
    # RT needs "dummy" input frames to specify the Rt, Sa, block and datasize of the
    # receive area to be read
    inRtFrm = UeiDaq.CUeiMIL1553RTFrame(startRt, startSa, 0, wordCount).GetFrame()      
    outRtFrm = UeiDaq.CUeiMIL1553RTFrame(startRt, startSa, 0, wordCount).GetFrame()

    # RT also needs a pre-initialized status input frame to specify the Rt
    inRtStsFrm = UeiDaq.CUeiMIL1553RTStatusFrame(startRt).GetFrame()

    # Set UP RT/SAs we want to operate
    #pPort0->ClearFilterEntries();
    #CUeiMIL1553FilterEntry* filterFrm = new CUeiMIL1553FilterEntry;
    #filterFrm->Set(UeiMIL1553FilterByRt, startRt, startSa);
    #filterFrm->EnableCommands(TRUE, TRUE, TRUE);
    #pPort0->AddFilterEntry(*filterFrm);
    #pPort0->EnableFilter(TRUE);

    # Then, configure bus controller on channel 1
    # we will need three types of frames for BC: BCCB Data, BCCD Status and BCCB Scheduler (one minor and one major)
        
    retryType = UeiDaq.UeiMIL1553BCR_RNR | \
                UeiDaq.UeiMIL1553BCR_ESR | \
                UeiDaq.UeiMIL1553BCR_RE

    # prepare BCCB data frames used to store commands in minor frame entries
    bccbDataFrms = [] 
    bccbData = UeiDaq.CUeiMIL1553BCCBDataFrame(0, 0, 0) # Minor frame, minor index, block
    bccbData.SetCommand(UeiDaq.UeiMIL1553CmdBCRT, startRt, startSa, wordCount)
    bccbData.SetCommandBus(UeiDaq.UeiMIL1553OpModeBusA)    # Test: Both buses is a default setting
    bccbData.SetCommandDelay(100)   # Test: default is 0
    bccbData.SetRetryOptions(3, retryType)
    data16 = [0] * wordCount
    for i in range(0, wordCount):
       data16[i] = 0x1000 + startRt + i
    bccbData.CopyRxData(data16)
    bccbDataFrms.append(bccbData.GetFrame())
    
    bccbData = UeiDaq.CUeiMIL1553BCCBDataFrame(0, 1, 0)
    bccbData.SetCommand(UeiDaq.UeiMIL1553CmdRTBC, startRt, startSa, wordCount)
    bccbData.SetCommandBus(UeiDaq.UeiMIL1553OpModeBusA)    # Test: Both buses is a default setting
    bccbData.SetCommandDelay(100)   # Test: default is 0
    bccbData.SetRetryOptions(3, retryType)
    bccbDataFrms.append(bccbData.GetFrame())
    
    # prepare BCCB status frame used to report BCCB status (
    inBccbStatusFrms = [] 
    bccbStatus = UeiDaq.CUeiMIL1553BCCBStatusFrame(0, 0, 0)
    inBccbStatusFrms.append(bccbData.GetFrame())
    bccbStatus = UeiDaq.CUeiMIL1553BCCBStatusFrame(0, 1, 0)
    inBccbStatusFrms.append(bccbData.GetFrame())

    # write major frame
    major = UeiDaq.CUeiMIL1553BCSchedFrame(UeiDaq.UeiMIL1553BCFrameMajor)
    major.AddMajorEntry(0, UeiDaq.UeiMIL1553MjEnable)
    writers[0].WriteBCSchedFrame([major.GetFrame()])

    # fill minor frame - one for send and one for receive
    minor = UeiDaq.CUeiMIL1553BCSchedFrame(UeiDaq.UeiMIL1553BCFrameMinor)
    minor.AddMinorEntry(UeiDaq.UeiMIL1553MnEnable)
    minor.AddMinorEntry(UeiDaq.UeiMIL1553MnEnable)
    writers[0].WriteBCSchedFrame([minor.GetFrame()])

    # fill BCCB data for the only minor frame
    writers[0].WriteBCCBDataFrame([bccbDataFrms[0]])
    writers[0].WriteBCCBDataFrame([bccbDataFrms[1]])

    # Start operations
    # Start RT
    data16 = [0] * 36
    for i in range(0, wordCount):
       data16[i] =i + 1
    outRtFrm.RxTxData = data16
    writers[1].WriteRTFrame([outRtFrm])

    # start Bus Controller
    bcControl = UeiDaq.tUeiMIL1553BCControlFrame()   
    bcControl.Operation = UeiDaq.UeiMIL1553BcOpEnable
    bcControl.MajorClock = 4.0
    bcControl.MinorClock = 10.0
    writers[0].WriteBCControlFrame([bcControl])

    c=1
    while True:  
        time.sleep(0.5)

        # read RT status
        stsFrms = readers[1].ReadRTStatusFrame([inRtStsFrm])
        print("RT Rcv Sts=%d  RT Snt Sts=%d  Sts0=%x Sts1=%x" % (stsFrms[0].DataReady, stsFrms[0].DataSent, stsFrms[0].Status0, stsFrms[0].Status1))

        # Change and retrieve RT data at each iteration
        # Store data to RT "transmit" area
        data16 = [0] * 36
        for i in range(0, wordCount):
            data16[i] =i + c
        outRtFrm.RxTxData = data16
        writers[1].WriteRTFrame([outRtFrm])

        if stsFrms[0].DataReady:
            # Read data from RT "receive" area
            inRtFrms = readers[1].ReadRTFrame([inRtFrm])
            rtFrm = UeiDaq.CUeiMIL1553RTFrame(inRtFrms[0])
            print("RT=%s Data=%s" % (rtFrm.GetFrameStr(), rtFrm.GetDataStr()))


        # Change and retrieve BC data at each iteration
        # Store data for BC "Receive" command
        data16 = [0] * wordCount
        for i in range(0, wordCount):
            data16[i] = 0x1000 + c + i
        bccbDataFrms[0].rx_data = data16
        writers[0].WriteBCCBDataFrame([bccbDataFrms[0]])
        
        # Read data stored in BC "Transmit" command
        outBccbStatusOutFrms = readers[0].ReadBCCBStatusFrame([inBccbStatusFrms[1]])
        if len(outBccbStatusOutFrms) > 0:
            outBccbStatusOutFrm = UeiDaq.CUeiMIL1553BCCBStatusFrame(outBccbStatusOutFrms[0])
            print("BC Data to Be Transmitted= %s" % outBccbStatusOutFrm.GetBcDataStr(wordCount))
 

        # Read bus monitor and display bus activity
        bmFrms = readers[0].ReadBMFrame(10)
        for frm in bmFrms: 
            extFrm = UeiDaq.CUeiMIL1553BMFrame(frm)
            print(extFrm.GetBmMessageStr())
            print(extFrm.GetBmDataStrDataOnly())

        
        print("====================================================")
         
        print("iteration:%d" %c)
          
        c = c + 1

    # stop bus controller
    bcControl.Operation = UeiDaq.UeiMIL1553BcOpDisable
    writers[0].WriteBCControlFrame([bcControl])

    session.Stop()
        
except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print("Exception: %s" % e)