import re
import time
from typing import Union

from hardware.visa_module.visa_interface import VisaInterface


class KEITH2400(VisaInterface):
    # See Tables 4-3 and 4-4 in the 2400 Series User Manual (pgs 92-3)
    def __new__(
            cls,
            device_name: Union[str, None] = None,
            gpib_addr: Union[int, None] = None,
            prologix=False,
            *args,
            **kwargs
    ):
        kwargs['identifier'] = 'KEITHLEY INSTRUMENTS INC.,MODEL 2400'

        if device_name is None or not device_name.startswith("visa://"):
            if gpib_addr is not None:
                kwargs['write_termination'] = '\n'
                kwargs['read_termination'] = '\n'
            else:
                kwargs['write_termination'] = '\r'
                kwargs['read_termination'] = '\r'
                kwargs['baud_rate'] = 57600

        if gpib_addr is None:
            kwargs['device_name'] = device_name
            return super().__new__(cls, *args, **kwargs)

        if prologix is True:
            if device_name is None:
                device_name = f"Prologix::{gpib_addr}"
            else:
                device_name = f"Prologix::{gpib_addr}::{device_name}"

            return super().__new__(cls, device_name=device_name, *args, **kwargs)

        return super().__new__(cls, device_name=f"GPIB0::{gpib_addr}::INSTR", *args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()
        # print(self.query('*IDN?'))
        # self.write('*RST')
        # keith.property_command('SENS:FUNC', 'RES')
        # keith.property_command('SENS:RES:RANG', 100)
        # keith.property_command('SENS:RES:MODE', 'MAN')
        # keith.property_command('SENS:RES:OCOM', 'OFF')
        # keith.property_command('SENS:CURR:PROT', 1e-3)
        # keith.property_command('SENS:VOLT:PROT', 21)
        # keith.property_command('SOUR:FUNC', 'CURR')
        # keith.property_command('SOUR:CURR:LEV', 10e-6)
        # keith.property_command('FORM:ELEM', 'RES')
        # keith.property_command('OUTP', 'ON')
        # self.close()

    def get_resistance(self) -> float:
        # t = time.time()
        # self.open()
        # print(time.time() - t)
        p = self.property_command('READ')
        out = float(re.split(',', p)[2])
        # self.close()
        return out

    def set_compliance_voltage(self, val: float):
        # self.open()
        self.property_command('SENS:VOLT:PROT:LEV', val)
        # self.close()

    def on(self):
        # self.open()
        self.property_command('OUTP:STAT', 'ON')
        # self.close()

    def off(self):
        # self.open()
        self.property_command('OUTP:STAT', 'OFF')
        # self.close()


if __name__ == '__main__':
    # from moku.instruments import LockInAmp
    # moku_pro = LockInAmp('42.0.2.2', force_connect=True)
    # moku_pro.set_demodulation(mode='ExternalPLL', frequency=10000)
    # moku_pro.set_filter(corner_frequency=60, slope='Slope24dB')
    # moku_pro.set_frontend(channel=1, coupling='AC', impedance='1MOhm', attenuation='0dB')
    # moku_pro.set_frontend(channel=2, coupling='AC', impedance='1MOhm', attenuation='20dB')
    # moku_pro.use_pid('Off')
    # moku_pro.set_outputs(main='R', aux='None', main_offset=0, aux_offset=0)
    # moku_pro.set_polar_mode(range='2Vpp')
    # # moku_pro.set_gain(main=10, aux=10)
    # moku_pro.set_monitor(monitor_channel=1, source='MainOutput')
    # moku_pro.set_timebase(-10e-3, 10e-3)
    # print(moku_pro.summary())
    # from moku.instruments import Oscilloscope
    # moku_pro = Oscilloscope('42.0.2.2', force_connect=True)
    # moku_pro.set_timebase(-10e-3, 10e-3)
    # moku_pro.set_source(1, 'Input1')
    # moku_pro.set_frontend(1, impedance='1MOhm', coupling='DC', range='40Vpp')
    # moku_pro.set_source(2, 'None')
    # moku_pro.set_source(3, 'None')
    # moku_pro.set_source(4, 'None')
    # moku_pro.set_trigger(type='Edge', source='Input1', level=0, mode='Auto')
    with KEITH2400(gpib_addr=3, prologix=True) as keith1, KEITH2400(gpib_addr=2, prologix=True) as keith2:
        print(keith1.__class__.__name__)
        print(keith2.__class__.__name__)
        print(keith1.query(':SOUR:FUNC?'))
        keith1.write(':SOUR:FUNC?')
        print(keith1.read())
        time.sleep(1)
        keith2.write(':SYST:BEEP:IMM 440,1')
        keith1.write(':SYST:BEEP:IMM 523,1')
        time.sleep(1)
        # keith1.write(':SYST:BEEP:IMM 466,1')
        # keith2.write(':SYST:BEEP:IMM 466,1')
        # time.sleep(2)
        # keith2.write(':SYST:BEEP:IMM 466,1')
        # time.sleep(1)
        # with PM100() as det:
        #     keith.device.timeout = 600000
        #     keith.write(':SENS:FUNC "CURR"')
        #     keith.write(':SENS:CURR:RANG:AUTO 0')
        #     keith.write(':SENS:CURR:PROT 35E-3')
        #     keith.write(':SOUR:FUNC VOLT')
        #     keith.write(':FORM:ELEM CURR')
        #     keith.write(':SOUR:DEL 0.003')
        #     keith.write(':SYST:BEEP:STAT OFF')
        #
        #     det.wavelength = 1557
        #     print(det.wavelength)
        #
        #     voltage = list(np.arange(start=0, stop=6.6, step=0.1))
        #     temp = voltage[::-1]
        #     voltage.extend(temp[1:len(temp)-1])
        #     print(voltage)
        #     repeats = 5
        #     volt = []
        #     current = []
        #     resistance = []
        #     optical_signal = []
        #     times = []
        #     start = datetime.now()
        #
        #     for j in range(repeats):
        #         for i in range(len(voltage)):
        #             current_v = float(voltage[i])
        #             string = f":SOUR:VOLT {current_v}"
        #             print(f"{string=}")
        #             keith.write('%s' % string)
        #             keith.write(':OUTP ON')
        #
        #             current_i = float(keith.query(':READ?'))
        #             print(f"{current_i=}")
        #             volt.append(current_v)
        #             current.append(current_i)
        #             resistance.append(current_v / current_i)
        #             # optical_signal.append(np.mean(moku_pro.get_data(timeout=600)['ch1']))
        #             current_o = det.power
        #             print(f"{current_o=}")
        #             optical_signal.append(current_o)
        #             t = datetime.now() - start
        #             times.append(t.total_seconds())
        #             time.sleep(0.1)
        #             keith.write(':OUTP OFF')
        #             time.sleep(0.5)
        #     print(volt)
        #     print(current)
        #     #print(resistance)
        #     print(optical_signal)
        #     print(times)
        #     results = {}
        #     results["time"] = times
        #     results["voltage"] = volt
        #     results["current"] = current
        #     results["optical_sig"] = optical_signal
        #     name = "AgiltronVOACharacterization_2-16-23_CH1"
        #     filename = f"../measurements/{name}_{datetime.timestamp(datetime.now())}.mat"
        #     savemat(filename, results)
        #     keith.write(':SYST:BEEP:STAT ON')
        #     time.sleep(1)
        #     keith.write(':SYST:BEEP:IMM 466,1')
        #     time.sleep(2)
        #     keith.write(':SYST:BEEP:IMM 466,1')
        #     time.sleep(2)
        #     keith.write(':SYST:BEEP:IMM 466,1')
        #     time.sleep(1)
        # print(x.query('*IDN?'))
        # x.write('*RST')
        # x.write(':SENS:FUNC:CONC ON')
        # x.write(':SOUR:FUNC VOLT')
        # x.write(":SENS:FUNC 'CURR:DC'")
        # x.write(':SENS:CURR:PROT 0.015')
        # x.write(':SOUR:VOLT:START 0')
        # x.write(':SOUR:VOLT:STOP 5')
        # x.write(':SOUR:VOLT:STEP 0.1')
        # x.write(':SOUR:VOLT:MODE SWE')
        # x.write(':SOUR:SWE:RANG AUTO')
        # x.write(':SOUR:SWE:SPAC LIN')
        # x.write(':SOUR:DEL 1')
        # points = x.query(':SOUR:SWE:POIN?')
        # print(points)
        # x.write(':TRIG:COUN ' + str(points))
        # x.write(':TRIG:OUTP SENS')
        # x.write(':OUTP ON')
        # print(x.query(':READ?'))
        # x.write(':OUTP OFF')
