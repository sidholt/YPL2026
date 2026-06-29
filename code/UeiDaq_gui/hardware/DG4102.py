import math
from fractions import Fraction

import numpy as np

from hardware.visa_module.visa_interface import VisaInterface


class DG4102(VisaInterface):
    def __new__(cls, *args, **kwargs):
        if 'device_name' not in kwargs and not args:
            kwargs['device_name'] = 'TCPIP0::172.28.5.1::inst0::INSTR'
        if 'identifier' not in kwargs and not args:
            kwargs['identifier'] = 'DG4E213901966'
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()
        self.write('*CLS')

    def triggered_pulse(self, voltage: float, pulse_width: float, source: int = 1, rise_time: float = 50e-9, fall_time: float = 50e-9):
        # Exceptions used to make sure values are within instrument specifications
        duty_cycle = 0.3
        period = pulse_width / duty_cycle
        if period < 50e-9 and voltage > 5:
            duty_cycle = 0.24
            period = pulse_width / duty_cycle
        if period < 40e-9:
            raise Exception("DG4102 cannot support pulses under 12ns in the pulse wave mode!")
        if rise_time < 7e-9 or rise_time > 0.312*period:
            raise Exception(f"DG4102 Cannot Support rise time of {rise_time}! Valid rise times: 7E-9 - {0.312*period}")
        if fall_time < 7e-9 or fall_time > 0.312*period:
            raise Exception(f"DG4102 Cannot Support fall time of {fall_time}! Valid fall times: 7E-9 - {0.312*period}")

        # Sets function shape to square and duty cycle (time circuit is on/off)
        self.write(f":SOUR{source}:FUNC:SHAP PULS")
        self.write(f":SOUR{source}:FUNC:PULS:DCYC {int(duty_cycle*100)}")
        self.write(f":SOUR{source}:FUNC:PULS:TRAN {rise_time}")
        self.write(f":SOUR{source}:FUNC:PULS:TRAN:TRA {fall_time}")

        # Sets period, max voltage, and low voltage
        self.write(f":SOUR{source}:PER {period}")
        self.write(f":SOUR{source}:VOLT:HIGH {voltage}")
        self.write(f":SOUR{source}:VOLT:LOW 0")

        # Sets burst mode to trigger and sets the number of bursts to 1 to produce a single pulse
        self.write(f":SOUR{source}:BURS:MODE TRIG")
        self.write(f":SOUR{source}:BURS:NCYC 1")

        # Sets trigger source as manual
        self.write(f":SOUR{source}:BURS:TRIG:SOUR MAN")

        # Sets trigger output signal to a rising edge
        self.write(f":SOUR{source}:BURS:TRIG:TRIGO POS")

        # Sets burst output on the rising edge of the trigger signal
        self.write(f":SOUR{source}:BURS:TRIG:SLOP POS")

        # Enables burst function
        self.write(f":SOUR{source}:BURS:STAT ON")
    
        # Turns on output
        self.write(f":OUTP{source}:STAT ON")

    # Sets to trigger immediately
    def trigger(self, source: int = 1):
        self.write(f":SOUR{str(source)}:BURS:TRIG:IMM")

        # Returns the maximum value of the voltage

    def get_pulse_volt(self, source: int = 1):
        return float(self.query(f":SOUR{str(source)}:VOLT:HIGH?"))

        # Calculates and returns the pulse width

    def get_pulse_width(self, source: int = 1):
        dcyc = float(self.query(f":SOUR{str(source)}:FUNC:SQU:DCYC?"))
        period = float(self.query(f":SOUR{str(source)}:PER?"))
        return period * dcyc / 100

        # Returns sources

    def get_sources(self):
        return 1, 2

    def set_custom_waveform(self, points: list, source: int = 1) -> None:
        # Exceptions used to make sure values are within instrument specifications
        points = sorted(points, key=lambda x: x[0])
        times = [x[0] for x in points]
        if times[0] != 0.0:
            raise Exception("DG4102 Arbitrary Waveform Initial Point Not Defined!")
        voltages = [x[1] for x in points]
        if voltages[-1] != 0:
            raise Exception("DG4102 Arbitrary Waveform Final Point Not Zero!")
        maxV = max(voltages)
        if maxV > 5:
            raise Exception("DG4102 Arbitrary Waveform Maximum Voltage Too High!")
        minV = min(voltages)
        if minV < -5:
            raise Exception("DG4102 Arbitrary Waveform Minimum Voltage Too Low!")
        # End of Exceptions

        # Calculates voltages and rounds to the nearest 5 decimal places
        vout = [round((x - minV) * 2 / (maxV - minV) - 1, 5) for x in voltages]

        # Finds maximum value between times list and 40e-9 to set the period
        period = max([max(times), 40e-9])

        # Rationalises each value in times list divided by the period into a list of fractions
        rel_times = [Fraction(x / period).limit_denominator() for x in times]

        # Find the least common denominator for time intervals
        denominators = [x.denominator for x in rel_times]
        totalPoints = denominators[0]
        for d in denominators[1:]:
            totalPoints = totalPoints // math.gcd(totalPoints, d) * d

        # Makes regular timing intervals for the voltages
        indicies = [int(x.numerator * totalPoints / x.denominator) for x in rel_times]

        # Makes a list of voltages at their corresponding regular time intervals
        rep = np.diff(indicies)
        data = []
        for i in range(len(rep)):
            for j in range(rep[i]):
                data.append(vout[i])
        data.append(vout[-1])

        # Final voltage and timing values
        mess = ','.join([str(x) for x in data])

        # Writes custom burst waveform function to generator
        self.write(f":PER {period + 0.1e-9}")
        self.write(f":SOUR{source}:VOLT:HIGH{maxV}")
        self.write(f":SOUR{source}:VOLT:LOW {minV}")
        self.write(f":SOUR'{source}:FUNC:SHAP ARB")
        self.write(f":TRAC:DATA:DATA VOLATILE, {mess}")
        self.write(":TRAC:DATA:POIN:INT OFF")
        self.write(f":PER {period + 0.1e-9}")
        self.write(f":SOUR'{source}':BURS:MODE TRIG")
        self.write(f":SOUR{source}:BURS:NCYC 1")
        self.write(f":SOUR{source}:BURS:TRIG:SOUR MAN")
        self.write(f":SOUR{source}:BURS:TRIG:TRIGO POS")
        self.write(f":SOUR{source}:BURS:TRIG:SLOP POS")
        self.write(f":SOUR{source}:BURS:STAT ON")
        self.write(f":PER {period + 0.1e-9}")

if __name__ == '__main__':
    with DG4102() as x:
        print(x.identifier)
        x.triggered_pulse(voltage=5, pulse_width=10e-9)
        x.trigger()
        print(x.get_pulse_volt())