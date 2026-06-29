from typing import Union, List

import nidaqmx
import nidaqmx.system
import numpy as np
from nidaqmx.constants import AcquisitionType
from nidaqmx.stream_readers import AnalogMultiChannelReader


class DAQDevices:
    def __init__(self):
        self.device: nidaqmx.system.device.Device = None
        self.ai_voltage_channels = []
        self.calibrations = {}
        self.ai_voltage_channel_reader: AnalogMultiChannelReader = None
        # No task created here — deferred until first channel is added

    # ── device selection ──────────────────────────────────────────────────────
    def device_name(self, name: str):
        system = nidaqmx.system.System.local()
        if name in system.devices:
            self.device = system.devices[name]
        else:
            raise Exception(f'"{name}" is not found. Available: {list(system.devices)}')

    @staticmethod
    def list_all_devices():
        return list(nidaqmx.system.System.local().devices)

    def list_channels(self, channel_type: str):
        if hasattr(self.device, channel_type):
            return [i.name for i in getattr(self.device, channel_type)]
        return []

    # ── channel management ────────────────────────────────────────────────────
    def add_ai_voltage_channel(self, channel):
        if channel not in self.ai_voltage_channels and channel in self.list_channels("ai_physical_chans"):
            self.ai_voltage_channels.append(channel)
            self._rebuild_task()

    def remove_ai_voltage_channel(self, channel):
        if channel in self.ai_voltage_channels:
            self.ai_voltage_channels.remove(channel)
            if self.ai_voltage_channels:
                self._rebuild_task()

    def _rebuild_task(self):
        """Tear down any existing task and create a fresh software-timed one."""
        self._close_task()
        task = nidaqmx.Task()
        for ch in self.ai_voltage_channels:
            task.ai_channels.add_ai_voltage_chan(ch)
        self.ai_voltage_channel_reader = AnalogMultiChannelReader(task.in_stream)

    # kept for compatibility with existing call sites
    def create_new_read_stream(self):
        self._rebuild_task()

    # ── task lifecycle ────────────────────────────────────────────────────────
    def stop(self):
        """Stop the task (does not close it — use before configure_timing)."""
        if self.ai_voltage_channel_reader is not None:
            try:
                self.ai_voltage_channel_reader._task.stop()
            except Exception:
                pass

    def start(self):
        """Restart a stopped task."""
        if self.ai_voltage_channel_reader is not None:
            try:
                self.ai_voltage_channel_reader._task.start()
            except Exception:
                pass

    def _close_task(self):
        if self.ai_voltage_channel_reader is not None:
            try:
                self.ai_voltage_channel_reader._task.__exit__(None, None, None)
            except Exception:
                pass
            self.ai_voltage_channel_reader = None

    # ── reading ───────────────────────────────────────────────────────────────
    def read_one(self):
        """Single software-timed sample across all configured channels. Returns list."""
        vals = np.zeros(len(self.ai_voltage_channels), dtype=np.float64)
        self.ai_voltage_channel_reader.read_one_sample(vals)
        return vals.tolist()

    def configure_timing(self, rate: int, samples_per_channel: int):
        """Switch the existing task to hardware-timed continuous acquisition."""
        task = self.ai_voltage_channel_reader._task
        task.stop()
        task.timing.cfg_samp_clk_timing(
            rate=rate,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=samples_per_channel,
        )
        task.start()

    def read_chunk(self, num_samples: int) -> np.ndarray:
        """Read num_samples per channel. Returns (n_channels, num_samples) float64."""
        n_ch = len(self.ai_voltage_channels)
        data = np.zeros((n_ch, num_samples), dtype=np.float64)
        self.ai_voltage_channel_reader.read_many_sample(
            data,
            number_of_samples_per_channel=num_samples,
            timeout=10.0,
        )
        return data

    def configure_finite_triggered(
        self,
        rate: int,
        samples: int,
        pfi_line: str = "/Dev2/PFI0",
    ):
        """
        Configure a finite hardware-triggered acquisition.
        Task will not start collecting until a rising edge arrives on pfi_line.
        Call read_finite() after the trigger fires to block until complete.
        """
        self._close_task()
        task = nidaqmx.Task()
        for ch in self.ai_voltage_channels:
            task.ai_channels.add_ai_voltage_chan(ch)
        task.timing.cfg_samp_clk_timing(
            rate=rate,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=samples,
        )
        task.triggers.start_trigger.cfg_dig_edge_start_trig(
            trigger_source=pfi_line,
            trigger_edge=nidaqmx.constants.Edge.RISING,
        )
        task.start()   # arms and waits for trigger — does not block here
        self.ai_voltage_channel_reader = AnalogMultiChannelReader(task.in_stream)

    def read_finite(self, samples: int, timeout: float = 120.0) -> np.ndarray:
        """
        Block until all finite samples are available, then return (n_ch, samples).
        Restores the task to software-timed mode afterwards.
        """
        n_ch = len(self.ai_voltage_channels)
        data = np.zeros((n_ch, samples), dtype=np.float64)
        self.ai_voltage_channel_reader.read_many_sample(
            data, number_of_samples_per_channel=samples, timeout=timeout
        )
        self._rebuild_task()   # restore software-timed mode
        return data

    # ── one-shot utility ──────────────────────────────────────────────────────
    @staticmethod
    def daq_one_read(ai_voltage_channels: Union[str, List[str]]) -> dict:
        if not isinstance(ai_voltage_channels, list):
            ai_voltage_channels = [ai_voltage_channels]
        result = {}
        with nidaqmx.Task() as task:
            for ch in ai_voltage_channels:
                task.ai_channels.add_ai_voltage_chan(ch)
            data = task.read()
            if not isinstance(data, list):
                data = [data]
            for i, ch in enumerate(ai_voltage_channels):
                result[ch] = data[i]
        return result

    def calibrate(self, channel) -> float:
        with nidaqmx.Task() as task:
            task.ai_channels.add_ai_voltage_chan(channel)
            data = task.read(number_of_samples_per_channel=1000)
        avg = float(np.array(data).mean())
        self.calibrations[channel] = avg
        return avg

    # ── context manager / cleanup ─────────────────────────────────────────────
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._close_task()


if __name__ == '__main__':
    d = DAQDevices()
    d.device_name("Dev2")
    print(d.list_channels("ai_physical_chans"))
    d.add_ai_voltage_channel('Dev2/ai0')
    print(d.read_one())
    d.add_ai_voltage_channel('Dev2/ai1')
    print(d.read_one())
    d.close()