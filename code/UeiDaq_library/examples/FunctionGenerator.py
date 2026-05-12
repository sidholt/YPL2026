import UeiDaq
import time

try:
    aowfmSession = UeiDaq.CUeiSession()

    # Create a AO waveform channel on a function generator device (AO-364)
    # This type of channels gives access to waveform shape parameters and 
    # frequency/amplitude/offset/phase sweep.
 
    # Use channel 0 as master clock to synchronize all channels
    aowfmSession.CreateAOWaveformChannel("pdna://192.168.100.11/Dev4/ao0", 
                                     UeiDaq.UeiAOWaveformClockSourceALT0,       # use alternate trig out signal as clock for main DAC
                                     UeiDaq.UeiAOWaveformOffsetClockSourceSW,   # use software clock for offset DAC (DC only)
                                     UeiDaq.UeiAOWaveformClockRoutePLLToTrgOut) # route channel 0 PLL clock to trigout    
    # Configure channels 1, 2 and 3 to pick-up clock from channel 0
    aowfmSession.CreateAOWaveformChannel("pdna://192.168.100.11/Dev4/ao1,2,3", 
                                    UeiDaq.UeiAOWaveformClockSourceALT0,        # use alternate trig out signal as clock for main DAC 
                                    UeiDaq.UeiAOWaveformOffsetClockSourceSW,    # use software clock for offset DAC (DC only) 
                                    UeiDaq.UeiAOWaveformClockRouteNone)     
    aowfmSession.ConfigureTimingForSimpleIO()

    writers = []
    
    # Function generator channels can generate different waveforms at different rates.
    # We need one writer per channel to configure them independantly
    # Create a writer and configure different waveform shape on each channel
    for ch in range(0, aowfmSession.GetNumberOfChannels()):
        channel = aowfmSession.GetChannel(ch).GetIndex()

        writers.append(UeiDaq.CUeiAOWaveformWriter(aowfmSession.GetDataStream(), channel))

        wfmParams = UeiDaq.tUeiAOWaveformParameters()
        swpParams = UeiDaq.tUeiAOWaveformSweepParameters()
        
        # Use DDS mode which allows to dial-in exact output frequency within 0.1Hz or better 
        # but has slightly higher level of harmonics than PLL mode
        wfmParams.mode = UeiDaq.UeiAOWaveformModeDDS

        # First channel will output a 100Hz, 5V peak to peak sine wave
        if 0 == ch:
            wfmParams.type = UeiDaq.UeiAOWaveformTypeSine
            wfmParams.frequency = 100.0
            wfmParams.span = 5.0
           
        # Second channel will output a 50Hz, 7V peak to peak triangle wave
        if 1 == ch:     
            wfmParams.type = UeiDaq.UeiAOWaveformTypeTriangle
            wfmParams.frequency = 50.0
            wfmParams.span = 7.0
  
        # Third channel will output a 200Hz, 3V peak to peak pulse wave 
        # with 20% duty cycle and sharp edges
        if 2 == ch: 
            wfmParams.type = UeiDaq.UeiAOWaveformTypePulse
            wfmParams.frequency = 200.0
            wfmParams.span = 3.0
            wfmParams.dutyCycle = 0.2
            wfmParams.riseTime = 0.0
            wfmParams.fallTime = 0.0
        
        # Fourth channel will output a 100Hz, 10V peak to peak sawtooth wave
        # rising for 80% of the period and falling for 20% of the period
        if 3 == ch:
            wfmParams.type = UeiDaq.UeiAOWaveformTypeSine
            wfmParams.frequency = 100.0
            wfmParams.span = 10.0
            wfmParams.riseTime = 0.8
            wfmParams.fallTime = 0.2

        # Don't set any offset or phase on any channel
        wfmParams.offset = 0.0
        wfmParams.phase = 0.0
        
        writers[ch].WriteWaveform([wfmParams])
    
    print("All channels are started")
      
    # Wait for 5 secs then program channel 0 to sweep its frequency 
    # between 1Hz and 1kHz in 2 secs
    time.sleep(5)
      
    swpParams.control = UeiDaq.UeiAOWaveformSweepUpStart
    swpParams.mode = UeiDaq.UeiTimingDurationSingleShot
    swpParams.sweepTime = 2.0
    swpParams.lowerFrequency = 1.0
    swpParams.upperFrequency = 1000.0
      
    writers[0].WriteSweep([swpParams])

    print("Sweep started")

    time.sleep(4)

    swpParams.control = UeiDaq.UeiAOWaveformSweepStop
    writers[0].WriteSweep([swpParams])

    print("Sweep stopped")

    time.sleep(3)

    aowfmSession.Stop()

except Exception as e:
    print (e)
