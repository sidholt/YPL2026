import UeiDaq
import numpy as np
import time

pwmOutputResource = "pdna://192.168.100.2/dev2/co0,2"
inputResource = "pdna://192.168.100.2/dev2/ci1,3"

pwmOutputFreq = 1234

try:    
    #Configure PWM output
    # PWM low and high counts are specified as multiple of 66MHz reference clock
    # Divide period by two to obtain 50% duty cycle
    pwmHalfPeriodTickCount = (66000000 / pwmOutputFreq)/2
    pwmSession = UeiDaq.CUeiSession()
    pwmSession.CreateCOChannel(pwmOutputResource, UeiDaq.UeiCounterSourceClock, UeiDaq.UeiCounterModeGeneratePulseTrain, \
                               UeiDaq.UeiCounterGateInternal, int(pwmHalfPeriodTickCount),int(pwmHalfPeriodTickCount), 1, 0)
    pwmSession.ConfigureTimingForSimpleIO()

    #Create a writer to update PWM output       
    pwmWriter = UeiDaq.CUeiCounterWriter(pwmSession.GetDataStream())
    
    # Configure Freq Measurement
    inputSession = UeiDaq.CUeiSession()
    inputSession.CreateCIChannel(inputResource, UeiDaq.UeiCounterSourceInput, UeiDaq.UeiCounterModeMeasurePeriod, \
                                 UeiDaq.UeiCounterGateInternal, 1, 0)
    inputSession.ConfigureTimingForSimpleIO()

    #Create a reader object to read counter input
    freqReader = UeiDaq.CUeiCounterReader(inputSession.GetDataStream())

    #Start sessions
    pwmSession.Start()
    inputSession.Start()
    
    #Initialize PWM Data to write
    # we provide the number of high ticks and the number of low ticks of the PWM signal.
    # allocate an array big enough to hold 2 values per output channel
    pwmData = np.zeros(2 * pwmSession.GetNumberOfChannels(), dtype='uint32')
    
    #Initalize pulseCount variable for Freq. Measurement.
    pulseCount = np.zeros(inputSession.GetNumberOfChannels(),dtype='uint32')

    
    #Now Write PWM data on one board (pwmSession) and measure back the frequency on the other board (freqMeasSession)
    #Press Control-C to stop

    loopCount = 0

    while True:        
        for ch in range(0,pwmSession.GetNumberOfChannels()):
            pwmHalfPeriodTickCount = (66000000 / pwmOutputFreq)/2
            pwmData[2 * ch] = int(pwmHalfPeriodTickCount)
            pwmData[2 * ch + 1] = int(pwmHalfPeriodTickCount)                        
            pwmWriter.WriteSingleScanUInt32(pwmData)
            
            time.sleep(1)
            
            freqReader.ReadSingleScanUInt32(pulseCount)
            
            frequency = 0
            if pulseCount[ch] > 0:
                frequency = 66000000.0/pulseCount[ch]
            print("Chan %d - Pulse Count: %d - Frequency Measured: %f (Hz)" % (inputSession.GetChannel(ch).GetIndex(), pulseCount[ch], frequency))
            
        # Increase PWM frequency by 10Hz
        pwmOutputFreq = pwmOutputFreq + 10


except KeyboardInterrupt:
    pass
    
except Exception as e:
    print("Exception: %s" % e)

finally:
    pwmSession.Stop()
    inputSession.Stop()        
    