from hardware.visa_module.visa_interface import VisaInterface

class HP8168F(VisaInterface):
    def __new__(cls, *args, **kwargs):
        if 'device_name' not in kwargs and not args:
            kwargs['device_name'] = 'GPIB0::9::INSTR'
        if 'identifier' not in kwargs and not args:
             kwargs['identifier'] = '8168' 
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()
        if self.device is None:
            print("Error: Laser HP-8168F not found")
            raise Exception("Laser HP-8168F not found")
        self.dev_name = "Dev1"
        self.write(f":SOUR:POW:UNIT W") #this command sets the power to be in Watts 
        raw_min_wavelength = float(self.query(":WAVE? MIN"))
        self._min_wavelength = (raw_min_wavelength) * 1E9 # this laser uses meters as standard unit for wavelength, so convert to nm after quering the min wavelength
        raw_max_wavelength = float(self.query(":WAVE? MAX"))
        self._max_wavelength = (raw_max_wavelength) * 1E9
        self._max_power = float(self.query(":POW? MAX")) * 1000 
        self._wavelength = self.wavelength
        self._power = self.power
        self._on_or_off = self.on_or_off

    @property
    def wavelength(self) -> float:
        raw_wavelength = float(self.query(":WAVE?")) #val in meters
        self._wavelength = raw_wavelength * 1e9 #val in nm
        return self._wavelength
    
    @wavelength.setter
    def wavelength(self, wavelength: float) -> None:
        #assume user input wavelength in units of nm
        
        if wavelength > self._max_wavelength or wavelength < self._min_wavelength:
            raise ValueError(
                f'hp-8168F wavelength out of range! {self._min_wavelength} - {self._max_wavelength} Supported. Given {wavelength}.')
        
        wavelength_inMeters = wavelength * 1e-9
        self.write(f':WAVE {wavelength_inMeters}')
        self._wavelength = wavelength
    
    @property
    def power(self) -> float:
        self._power = float(self.query(":POW?")) * 1000 # in mW
        return self._power

    @power.setter
    def power(self, power_input: float) -> None:
        #assume user input power in mW
        power_watts = power_input * 1e-3
        if power_input > self._max_power or power_input < 0:
            raise ValueError(
                f'HP_8168F power out of range! 0.0 - {self._max_power} mW Supported. Given {power_input}.')
        self.write(f':POW {power_watts}')
        self._power = power_input

    @property
    def on_or_off(self) -> bool:
        state = self.query(":OUTP?")
        self._on_or_off = (int(state) == 1)
        return self._on_or_off

    @on_or_off.setter
    def on_or_off(self, open_on_or_off: bool) -> None:
        if(open_on_or_off):
            val = 1 
        else: 
            val = 0
        self.write(f":OUTP {val}")
        self._on_or_off = open_on_or_off

    def on(self):
        self.on_or_off = True

    def off(self):
        self.on_or_off = False

   