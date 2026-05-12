import UeiDaq
import numpy
    
session = UeiDaq.CUeiSession()
session.CreateAIVExChannel("pdna://192.168.100.5/Dev5/Ai0", -0.015, 0.015, UeiDaq.UeiSensorQuarterBridge, 10.0, False,  UeiDaq.UeiAIChannelInputModeDifferential)
session.ConfigureTimingForSimpleIO()
reader = UeiDaq.CUeiAnalogScaledReader(session.GetDataStream())
    
#Take one measurement without shunt resistor
session.Start()
voltageWithoutShunt = numpy.zeros(session.GetNumberOfChannels())
reader.ReadSingleScan(voltageWithoutShunt)
session.Stop()
# voltageWithoutShunt is a numpy array
print("voltage without shunt = %f" % voltageWithoutShunt[0])

# Turn on shunt calibration for channel 0, shunt branch R4
# and program the shunt resistance to 100kOhms
channel0 = session.GetAIVExChannel(0)
channel0.EnableShuntCalibration(True)
channel0.SetShuntLocation(UeiDaq.UeiWheatstoneBridgeR4)
channel0.SetShuntResistance(100000.0)
    
#Take one measurement with shunt resistance enabled
session.Start()
voltageWithShunt = numpy.zeros(session.GetNumberOfChannels())
reader.ReadSingleScan(voltageWithShunt)
session.Stop()
    
print("voltage with shunt = %f" % voltageWithShunt[0])
    
#Retrieve the global shunt resistance for the first channel and
#the actual excitation voltage.
Rs = channel0.GetActualShuntResistance()    
Vex = channel0.GetExcitationVoltage()
    
    
#Assume all gauge resistances are 330 Ohms
Rgage = 330
#calculate actual and theoretical offset caused by shunt.
measuredDeltaV = voltageWithShunt-voltageWithoutShunt
calculatedDeltaV = -Vex*(Rgage/(4.0*Rs+2.0*Rgage));
    
#Calculate gain adjustment factor.
gaf = (calculatedDeltaV/measuredDeltaV)
#Turn off shunt resistor
channel0.EnableShuntCalibration(False)
    
#Starts the session again
session.Start()
#Read calibrated measurements
calibratedVoltage = numpy.zeros(session.GetNumberOfChannels())
reader.ReadSingleScan(calibratedVoltage)
calibratedVoltage = (calibratedVoltage * gaf)
print("voltage with shunt = %f" % calibratedVoltage[0])
session.CleanUp()

    
    
    
    
    
