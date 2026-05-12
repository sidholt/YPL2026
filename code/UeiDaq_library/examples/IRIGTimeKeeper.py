import UeiDaq
import time

try:
    irigSession = UeiDaq.CUeiSession()

    irigPort = irigSession.CreateIRIGTimeKeeperChannel("simu://192.168.100.55/dev8/irig0", UeiDaq.UeiIRIG1PPSInternal, False)
    irigSession.ConfigureTimingForSimpleIO()
    
    reader = UeiDaq.CUeiIRIGReader(irigSession.GetDataStream())

    irigSession.Start()

    for i in range(0, 100):
        bcdTime, status = reader.ReadBCDTime()
        print("BCD %d:%d:%d" % (bcdTime.hours, bcdTime.minutes, bcdTime.seconds))
        sbsTime, status = reader.ReadSBSTime()
        print("SBS %d:%d:%d" % (sbsTime.year, sbsTime.dayofyear, sbsTime.seconds))

        time.sleep(0.5)

    irigSession.Stop()

except Exception as e:
    print (e)
