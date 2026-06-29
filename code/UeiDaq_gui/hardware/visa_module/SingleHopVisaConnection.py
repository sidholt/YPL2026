from typing import Union, Optional

from pyvisa import Resource

from hardware.visa_module.VisaDevice import VisaDevice


class SingleHopVisaConnection(VisaDevice):
    def pre_initialization(self, device: Union[Resource, None]) -> Optional[Resource]:
        for key, value in self.extra_parameters.items():
            if hasattr(device, key):
                setattr(device, key, value)
        return super().pre_initialization(device)
