import time # <--- Make sure this is imported at the top!
from typing import Union, Optional
from pyvisa import Resource
from hardware.visa_module.SingleHopVisaConnection import SingleHopVisaConnection

class PrologixVisaConnection(SingleHopVisaConnection):
    def pre_initialization(self, device: Union[Resource, None]) -> Optional[Resource]:
        if "gpib_addr" not in self.extra_parameters:
            raise Exception("gpib_addr not specified")

        device = super().pre_initialization(device)
        device.read_termination = '\n'
        device.write_termination = '\n'
        device.write('++savecfg 0')
        device.write('++mode 1')
        device.write('++auto 0')
        device.write('++eoi 0')
        device.write('++eos 2')
        device.write('++eot_enable 0')
        device.write('++read_tmo_ms 1000')

        return device

    def static_query(self, device: Resource, command: str, **kwargs) -> str: 
        device.write(f'++addr {self.extra_parameters["gpib_addr"]}')
        device.write(command)
        time.sleep(0.2)
        return device.query('++read eoi').strip()

    def static_write(self, device: Resource, command: str) -> Resource:
        device.write(f'++addr {self.extra_parameters["gpib_addr"]}')
        device.write(command)
        return device

    def static_read(self, device: Resource) -> str:
        device.write(f'++addr {self.extra_parameters["gpib_addr"]}')
        time.sleep(0.2) # <--- Give hardware time to put data on bus
        return device.query('++read eoi').strip() # <--- Changed to eoi