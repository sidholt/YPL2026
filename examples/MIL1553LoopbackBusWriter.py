import UeiDaq
import time

try:
    session = UeiDaq.CUeiSession()
    startRt = 1
    startSa = 1
    messageSize = 10
    cycles = 10

    # Configure port 0 as bus monitor and bus writer
    session.CreateMIL1553Port("pdna://192.168.100.2/Dev10/MILB0", UeiDaq.UeiMIL1553CouplingTransformer, UeiDaq.UeiMIL1553OpModeBusMonitor)

    session.ConfigureTimingForSimpleIO()
    session.GetTiming().SetTimeout(1000)

    # create one reader and one writer per each port
    reader = UeiDaq.CUeiMIL1553Reader(session.GetDataStream(), session.GetChannel(0).GetIndex())
    writer = UeiDaq.CUeiMIL1553Writer(session.GetDataStream(), session.GetChannel(0).GetIndex())

        
    #filterFrm = UeiDaq.CUeiMIL1553FilterEntry()

    # Set UP RT/SAs we want to operate
    #pPort0->ClearFilterEntries();
    #filterFrm->Set(UeiMIL1553FilterByRt, startRt, startSa);
    #filterFrm->EnableCommands(TRUE, TRUE, TRUE);
    #pPort0->AddFilterEntry(*filterFrm);
    #pPort0->EnableFilter(TRUE);

    for c in range(0, cycles):   
        txData = [0] * 36
        for i in range(0, messageSize):
           txData[i] = c + i

        outFrm = UeiDaq.tUeiMIL1553BusWriterFrame()
        outFrm.TxData = txData
        outFrm.Command = UeiDaq.UeiMIL1553CmdBCRT
        outFrm.Rt = startRt
        outFrm.Sa = startSa #+ (c % 31)
        outFrm.WordCount = messageSize
        outFrm.DataSize = messageSize
        
        writer.WriteBusWriterFrame([outFrm])

        time.sleep(0.5)

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
            
        print("====================================================\n")
        
        
    session.Stop()
        
except KeyboardInterrupt:
    session.Stop()

except Exception as e:
    print("Exception: %s" % e)

