from typing import Union

import pyvisa

from hardware.visa_module.PrologixVisaConnection import PrologixVisaConnection
from hardware.visa_module.SingleHopVisaConnection import SingleHopVisaConnection
from hardware.visa_module.VisaDevice import VisaDevice


class VisaInterface(VisaDevice):
    def __new__(cls, device_name: Union[str, None] = None, *args, **kwargs):
        # print(f"VisaInterface.__new__({device_name}, {args}, {kwargs})")
        # Prologix GPIB-USB controller
        # device_name = "Prologix::3::ASRL1::INSTR"

        if device_name is not None and device_name.startswith("Prologix::"):
            split_device_name = device_name.split("::")
            gpib_addr = split_device_name[1]

            if len(gpib_addr) == 0:
                raise Exception("Invalid device name. GPIB address not specified")

            if len(split_device_name) > 2:
                device_name = "::".join(split_device_name[2:])
            else:
                device_name = None

            kwargs["gpib_addr"] = gpib_addr
            kwargs["device_name"] = device_name
            super_class = PrologixVisaConnection
        else:
            kwargs["device_name"] = device_name
            super_class = SingleHopVisaConnection

        def __new_class_init__(self, *_, **__):
            # print(args)
            # print(kwargs)
            # print(self.__class__.__name__)
            # print(self.__class__.__mro__)
            # print(super().__init__)
            super(self.__class__, self).__init__(*args, **kwargs)

        param_cls = type(
            f"Device{cls.__name__}",
            (cls, super_class),
            {"__init__": __new_class_init__}  # type: ignore
        )
        # print(param_cls.__init__)
        return super(VisaInterface, param_cls).__new__(param_cls)


if __name__ == '__main__':
    # d = VisaInterface(
    #     device_name="Prologix::21::ASRL10::INSTR",
    # )
    # d.timeout = 10000
    # d.open()
    # print(d.device_name)
    # print(d.__class__.__name__)
    # print(d.identifier)
    # y = d.query('LDATA R1-R2000').split(',')[1:]
    # y = [float(i) for i in y]
    # x = d.query('WDATA R1-R2000').split(',')[1:]
    # x = [float(i) for i in x]
    # plt.plot(x, y)
    # plt.show()
    # d.close()
    # print(d.resource_info)
    # print(d.device_name)
    # d.open()
    # print(d.device_name)
    # print(d.query(':SENS:CURR:PROT?'))
    # d.close()
    # print(d.device_name)

    resource_manager = pyvisa.ResourceManager()
    list_resources = list(resource_manager.list_resources())
    print(list_resources)
    # for i in list_resources:
    #     try:
    #         device = resource_manager.open_resource(i)
    #     except Exception:
    #         continue
    #     try:
    #         this_identifier = device.query('*IDN?')
    #     except Exception:
    #         device.close()
    #         continue
    #     print(i, this_identifier)
    #     device.read_termination = '\n'
    #     device.write_termination = '\n'
    #     device.write('++rst')
    #     device.write('++addr 3')
    #     device.write('++savecfg 0')
    #     device.write('++mode 1')
    #     device.write('++auto 0')
    #     device.write('++eoi 0')
    #     device.write('++eos 2')
    #     device.write('++eot_enable 0')
    #     device.write('++eot_char 13')
    #     device.write('++read_tmo_ms 200')
    #     device.write('*IDN?')
    #     print(device.query('++read 10'))
    #     # device.write('++eoi 0')
    #     # device.write('++auto 1')
    #     # device.write('++eos 3')
    #     # device.write('++eot_enable 1')
    #     # device.write('++eot_char 10')
    #     # print(device.query('*IDN?').strip())
    #     # print(device.query('*IDN?').strip())
    #     # print(device.query(':READ?'))
    #     device.write(':SENS:CURR:PROT?')
    #     print(device.query(f'++read {ord(device.write_termination)}'))
    #     print(device.resource_info)
    #     device.close()
