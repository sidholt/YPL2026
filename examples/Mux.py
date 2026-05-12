import UeiDaq
import numpy
import time

try:
    muxSession = UeiDaq.CUeiSession()

    muxPort = muxSession.CreateMuxPort("simu://192.168.100.55/dev9/mux0", True)
    
    # optionally configure sync input and output lines
    muxPort.EnableSyncInput(False)
    muxPort.SetSyncOutputMode(UeiDaq.UeiMuxSyncOutputLogic0)
    
    muxSession.ConfigureTimingForSimpleIO()
    
    numMuxChannels = muxSession.GetDevice().GetDOResolution()

    muxWriter = UeiDaq.CUeiMuxWriter(muxSession.GetDataStream())

    muxSession.Start()

    count = 0
    for i in range(0, 100):
        # This example sets one channel per iteration but it is possible to
        # set an arbitrary number of channels
        channel = [ count % numMuxChannels ]
        relay = [ count % 4 ]
 
        muxWriter.WriteMux((channel, relay))

        time.sleep(0.5)

        adcBuffer = muxWriter.ReadADC(5)
        for j in range(0,5):
            print("adc%d = %f" % (j, adcBuffer[j]))

        # uInt32 stRelayA, stRelayB, stRelayC, status;
        # muxWriter.ReadStatus(&stRelayA, &stRelayB, &stRelayC, &status);
        # std::cout << std::hex << " relayA=" << stRelayA <<
        #    " relayB=" << stRelayB <<
        #    " relayC=" << stRelayC <<
        #    " status=" << status << std::dec << std::endl;

        count = count+1

    muxSession.Stop()

except Exception as e:
    print (e)
