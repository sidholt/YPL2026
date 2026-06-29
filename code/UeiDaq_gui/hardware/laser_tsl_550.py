import asyncio
import nidaqmx
import numpy as np
from functools import partial, wraps
from nidaqmx.constants import AcquisitionType, TriggerType, Edge, TaskMode
from pyvisa import Resource
from typing import Union, Optional, Sequence

from hardware.visa_module.visa_interface import VisaInterface

def async_wrap(func):
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)

    return run


@async_wrap
def run_task_async(task: nidaqmx.Task, *args, **kwargs):
    return task.read(*args, **kwargs)


class TSL550(VisaInterface):
    def __new__(cls, *args, **kwargs):
        if 'device_name' not in kwargs and not args:
            kwargs['device_name'] = 'GPIB0::1::INSTR'
        if 'identifier' not in kwargs and not args:
            kwargs['identifier'] = 'TSL-550'
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()
        if self.device is None:
            print("Error: Laser TSL-550 not found")
            raise Exception("Laser Laser TSL-550 not found")
        self.dev_name = "Dev1"
        self.write(f"POW:UNIT 1")
        self.write(f"WAV:UNIT 0")
        self.write('TRIG:OUTP 2')
        self.write('TRIG:OUTP:ACT 0')
        self._min_wavelength = float(self.query("WAV:MIN?"))
        self._max_wavelength = float(self.query("WAV:MAX?"))
        self._wavelength = self.wavelength
        self._max_power = float(self.query("POW:MAX?"))
        self._set_power = self.set_power
        self._power = self.power
        self._shutter = self.shutter

    @property
    def wavelength(self) -> float:
        self._wavelength = float(self.query("WAV?"))
        return self._wavelength

    @wavelength.setter
    def wavelength(self, wavelength: float) -> None:
        if wavelength > self._max_wavelength or wavelength < self._min_wavelength:
            raise ValueError(
                f'TSL-550 wavelength out of range! {self._min_wavelength} - {self._max_wavelength} Supported. Given {wavelength}.')
        self.write(f'WAV {wavelength}')
        self._wavelength = wavelength

    @property
    def power(self) -> float:
        self._power = float(self.query("POW:ACT?"))
        return self._power

    @power.setter
    def power(self, power: float) -> None:
        if power > self._max_power or power < 0:
            raise ValueError(
                f'TSL-550 power out of range! 0.0 - {self._max_power} mW Supported. Given {power}.')
        self.write(f'POW {power}')
        self._power = power

    @property
    def set_power(self) -> float:
        self._set_power = float(self.query("POW?"))
        return self._set_power

    @property
    def shutter(self) -> bool:
        self._shutter = self.query('POW:SHUT?') == "1"
        return self._shutter

    @shutter.setter
    def shutter(self, shutter: bool) -> None:
        if shutter:
            self.write('POW:SHUT 1')
        else:
            self.write('POW:SHUT 0')
        self._shutter = shutter

    def on(self):
        self.write('POW:STAT 1')

    def off(self):
        self.write('POW:STAT 0')

    async def laser_sweep(
            self,
            input_channels: Union[int, Sequence[int]] = [0, 1],
            trigger_channel: Optional[int] = 0,
            start_wavelength: float = 1500,
            stop_wavelength: float = 1630,
            speed: float = 100,
            power: float = 1,
            name: str = "",
            save: bool = True,
            power_ch: Optional[int] = 2
    ) -> Sequence[float]:

        if not isinstance(input_channels, Sequence):
            input_channels = [input_channels]

        if len(input_channels) == 0:
            raise ValueError("No input channels were given!")

        pre_wavelength = self.wavelength
        pre_power = self.power
        pre_shutter = self.shutter
        num_samples = int(np.floor(abs(stop_wavelength - start_wavelength) / speed * 125000))

        read_task = nidaqmx.Task("read_task")
        for channel in input_channels:
            read_task.ai_channels.add_ai_voltage_chan(f"{self.dev_name}/ai{channel}")
        if power_ch is not None:
            read_task.ai_channels.add_ai_voltage_chan(f"{self.dev_name}/ai{power_ch}")
        read_task.ai_channels.all.ai_term_cfg = nidaqmx.constants.TerminalConfiguration.RSE
        read_task.ai_channels.all.ai_max = 10.0
        read_task.ai_channels.all.ai_min = -10.0
        read_task.timing.cfg_samp_clk_timing(
            rate=12500,
            active_edge=nidaqmx.constants.Edge.RISING,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=num_samples,
        )
        if trigger_channel is not None:
            read_task.triggers.start_trigger.trig_type = TriggerType.DIGITAL_EDGE
            read_task.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=f"/{self.dev_name}/PFI{trigger_channel}",
                trigger_edge=Edge.RISING
            )
        self.wavelength = start_wavelength
        self.power = power
        self.on()
        self.shutter = False
        self.write('TRIG:OUTP 2')
        self.write('TRIG:OUTP:ACT 0')

        self.write(f'WAV:SWE:STAR {start_wavelength}')
        self.write(f'WAV:SWE:STOP {stop_wavelength}')
        self.write(f'WAV:SWE:SPE {speed}')
        self.write('WAV:SWE:MOD 1')
        self.write('WAV:SWE:CYCL 1')

        read_task.control(TaskMode.TASK_COMMIT)
        await asyncio.sleep(0.5)

        daq_data = run_task_async(read_task, number_of_samples_per_channel=num_samples, timeout=20)
        self.write('WAV:SWE 1')
        daq_data = await daq_data

        if len(np.array(daq_data).shape) == 1:
            daq_data = [daq_data]

        self.wavelength = pre_wavelength
        self.power = pre_power
        self.shutter = pre_shutter

        read_task.close()
        return daq_data

if __name__ == '__main__':
    print("Hello World")
    async def main():
        with TSL550() as x:
            x.laser_sweep(
                save=False
            )
    try:
        asyncio.run(main())
    except:
        pass

