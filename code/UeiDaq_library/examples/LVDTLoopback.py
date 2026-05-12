import UeiDaq
import numpy
import time


try:
    aisession = UeiDaq.CUeiSession()
    aosession = UeiDaq.CUeiSession()
  
    aisession.CreateLVDTChannel("pdna://192.168.100.22/Dev4/Ai0,2", -40.0, 40.0, 1000, UeiDaq.UeiLVDTFiveWires, 5, 1800, False)
    aisession.ConfigureTimingForSimpleIO()

    aosession.CreateSimulatedLVDTChannel("pdna://192.168.100.22/Dev4/Ao1,3", 1000, UeiDaq.UeiLVDTFiveWires, 5, 1800)
    aosession.ConfigureTimingForSimpleIO()

    reader = UeiDaq.CUeiAnalogScaledReader(aisession.GetDataStream())
    writer = UeiDaq.CUeiAnalogScaledWriter(aosession.GetDataStream())

    lvdt_reader = UeiDaq.CUeiLVDTReader(aisession.GetDataStream())

    aisession.Start()
    aosession.Start()

    data_read = numpy.zeros(aisession.GetNumberOfChannels())
    data_write = numpy.zeros(aosession.GetNumberOfChannels())
    coils = numpy.zeros(2*aisession.GetNumberOfChannels())

    for i in range(-10, 10):
        for ch in range(0,aosession.GetNumberOfChannels()):
            data_write[ch] = i /10
            print("Out Ch%d: writing %f" % (aosession.GetChannel(ch).GetIndex(), data_write[ch]))

        writer.WriteSingleScan(data_write)

        time.sleep(0.1)

        reader.ReadSingleScan(data_read)
        lvdt_reader.ReadCoilAmplitudes(coils)

        for ch in range(0,aisession.GetNumberOfChannels()):
            val = data_read[ch]
            print ("In Ch%d: Ratio=%f. prim. coil=%f, sec. coil=%f)" % \
                   (aosession.GetChannel(ch).GetIndex(), data_read[ch], coils[ch], coils[aisession.GetNumberOfChannels()+ch]))

        

    aisession.Stop()

except Exception as e:
    print("Exception: %s" % e)

finally:
    aisession.CleanUp()
    aosession.CleanUp()