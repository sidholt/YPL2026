import time

from hardware.visa_module.visa_interface import VisaInterface


class PM100(VisaInterface):
    def __new__(cls, *args, **kwargs):
        kwargs['visa_library'] = "@py"
        kwargs['device_name'] = 'USB0::4883::32882::1908129::0::INSTR'
        kwargs['timeout'] = 10
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, wavelength: int = 1550, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()
        self.wavelength = wavelength
        self.write('CONF:POW')

    @property
    def wavelength(self) -> int:
        self._wavelength = int(float(self.query('SENS:CORR:WAV?')))
        return self._wavelength

    @wavelength.setter
    def wavelength(self, val: int) -> None:
        self.write(f'SENS:CORR:WAV {val}')
        self._wavelength = val

    @property
    def power(self) -> float:
        self._power = float(self.query('READ?'))
        return self._power


if __name__ == '__main__':
    with PM100(wavelength=1557) as x:
        print(x.query('*IDN?'))
        print(x.query('CONF?'))
        x.wavelength = 1557
        x.wavelength = 800
        x.wavelength = 1557
        print(x.wavelength)
        time.sleep(5)
        print(x.wavelength)
        print(x.wavelength)
        print(x.wavelength)
        print(x.power)
        print(x.power)
        print(x.power)
        print(x.power)
