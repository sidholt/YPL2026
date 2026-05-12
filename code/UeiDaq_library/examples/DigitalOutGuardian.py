import UeiDaq
import numpy
import time

try:
    doSs = UeiDaq.CUeiSession()
    aiSs = UeiDaq.CUeiSession()

    numDOLines = 8 # number of DO lines updated in the for loop
      
    # Create a digital output protected channel
    # This type of channels gives access to DIO cards with guardian features such
    # as circuit breaker and voltage/current readback
    # 
    # Circuit breaker will trip if current flowing through an output line outside of 0/0.1 A
    # Current is sampled at 100Hz
    # Circuit breaker will automatically try to re-arm every 500ms (2.0 Hz) until the over current
    # condition is resolved.
    doSs.CreateDOProtectedChannel("pdna://192.168.100.2/Dev2/do0", 0.0, 0.1, 100.0, True, 2.0)  
    doSs.ConfigureTimingForSimpleIO()

    # Additionnaly, you can configure some of the output lines to generate a PWM signal
    # for a certain duration during low/high and high/low transitions (soft start and soft stop)
    # It is also possible to continuously generate the PWM
            
    # Program PWM on output line 0 to generate soft start and soft stop PWM for 20ms 
    doChannel = doSs.GetDOProtectedChannel(0)
    doChannel.SetPWMMode(0, UeiDaq.UeiDOPWMSoftBoth)
    doChannel.SetPWMLength(0, 20000)
    doChannel.SetPWMPeriod(0, 100)

    # Program PWM on output line 1 to generate PWM continuously with 50% duty cycle
    doChannel.SetPWMMode(1, UeiDaq.UeiDOPWMContinuous)
    doChannel.SetPWMDutyCycle(1, 0.1)
    doChannel.SetPWMPeriod(1, 100)

    # Digital data will be stored in a 32 bits integer buffer
    doData = numpy.zeros(1, dtype='uint32')  # Create an array of uint32's for output data
    # Create a writer object to update output port.
    doWriter = UeiDaq.CUeiDigitalWriter(doSs.GetDataStream())

    # Create a circuit breaker object to monitor circuit breakers status and eventually reset them
    cb = UeiDaq.CUeiCircuitBreaker(doSs.GetDataStream(), 0)
    breakCounts = []
    for i in range(0, doSs.GetDevice().GetDOResolution()):
      breakCounts.append(0)

    # Create an analog input session to read back currents and voltages flowing through each of the output lines
    # AI channels 0 to 31 return the current measured at each closed DO line
    # AI channels 32 to 63 return the voltage measured at each opened DO line 
    aiSs.CreateAIChannel("pdna://192.168.100.2/Dev2/ai0:63", -10.0, 10.0, UeiDaq.UeiAIChannelInputModeDifferential)
    aiSs.ConfigureTimingForSimpleIO()

    # Allocate AI buffer to hold one value for each ouput line
    aiData = numpy.zeros(aiSs.GetNumberOfChannels())
    aiReader = UeiDaq.CUeiAnalogScaledReader(aiSs.GetDataStream())

    # Start the sessions
    doSs.Start()
    aiSs.Start()

    # Write 100 values and measure voltage and current at each output line
    for i in range(0,100):
        # Turn on each output line one by one
        doData[0] = 1 << (i % numDOLines)

        doWriter.WriteSingleScanUInt32(doData)
        print("%d: Digital output port set to 0x%x" %(i, doData[0]))

        # Read back voltages and currents
        aiReader.ReadSingleScan(aiData)
        for l in range(0, numDOLines):
            print("  DO line %d current=%f A" % (l, aiData[l]))
            print("  DO line %d voltage=%f V" % (l, aiData[l+32]))
     
        # Monitor CB status
        currStatus=0
        stickyStatus=0
     
        (currStatus, stickyStatus) = cb.ReadStatus()
        print("CB Status: curr = %x sticky = %x" % (currStatus, stickyStatus))

        for l in range(0, numDOLines):
            if (currStatus & (1 << l)) > 0:
               breakCounts[l]=+1

            # reset breaker after 5 iterations
            if breakCounts[l] > 5:
               print("Resetting breaker for line %d" % l)
               cb.Reset(1 << l)
               breakCounts[l] = 0

        time.sleep(0.5)


    doSs.Stop()
    aiSs.Stop()

except KeyboardInterrupt:
    doSs.Stop()
    aiSs.Stop()

except Exception as e:  # Catch any errors thrown by reading/writing
    print ("Error: " + str(e))
