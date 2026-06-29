import struct
import time
from typing import List, Union, Dict

import numpy as np
import serial
import serial.tools.list_ports

SWEEP_LENGTH = 131


def get_arduino_port(**kwargs):
    ports = []
    for port in serial.tools.list_ports.comports():
        if 'Arduino' not in port.manufacturer:
            continue
        if not all(getattr(port, key) == value for key, value in kwargs.items()):
            continue
        ports.append(port)
    return ports if ports else None


def get_sweep_vals(length: int = SWEEP_LENGTH):
    arr = np.linspace(0, 6.5, length).tolist()
    # print("[" + ", ".join([f"{i:.2f}" for i in arr]) + "]")
    vals = [int((1239.628 * i) + 8192) for i in arr]
    # print("[" + ", ".join([f"{i}" for i in vals]) + "]")
    return arr, vals


class UsbVoa:
    class Functions:
        PRINT = 1
        GET_VOLTAGE = 2
        SET_VOLTAGE = 3
        SET_ALL_VOLTAGES = 4
        SWEEP_CHANNEL = 5
        SWEEP_HALF_CHANNELS = 6
        SWEEP_ALL_CHANNELS = 7
        SET_VOLTAGE_DIRECTLY = 8
        SET_ALL_VOLTAGES_DIRECTLY = 9
        SWEEP_CHANNEL_DIRECTLY = 10
        SWEEP_ALL_CHANNELS_DIRECTLY = 11
        SWEEP_ALL_CHANNELS_DIRECTLY_ASYNC = 12
        AVAILABLE_MEMORY = 255

    def __init__(
            self,
            persist_conn: bool = True,
            verbose: bool = True,
            device_params=None
    ):
        self.serial_params = {
            'baudrate': 9600,
            'parity': serial.PARITY_EVEN,
            'stopbits': serial.STOPBITS_ONE,
            'bytesize': serial.EIGHTBITS,
            'write_timeout': None,
            'timeout': None,
        }

        self.vid = 9025
        self.pid = 32822

        self.Inputs = 9
        self.volt_zero = 6.5
        self.volt_one = 0
        self.min_voltage = 0
        self.max_voltage = 6.5
        self.num_inputs = 9

        self.persist_conn = persist_conn
        self.connections = {}
        self.ports: List = None
        self.ids: Dict[str, int] = None
        self.rev_ids: Dict[int, str] = None
        self.device_params = device_params or {}

        self.verbose = verbose
        self.initialize()

    def initialize(self):
        self.ports = get_arduino_port(vid=self.vid, pid=self.pid, **self.device_params)
        self.ids, self.rev_ids = self._get_ids()
        self.reset_all()

    def __enter__(self):
        return self

    def close(self):
        for name, ser in self.connections.items():
            ser.close()
            print(f"Closed {name}")
        self.connections = {}

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def create_connection(self, port):
        if port in self.connections:
            return self.connections[port]
        time.sleep(0.1)
        ser = serial.Serial(port, **self.serial_params)
        self.connections[port] = ser
        return ser

    def close_connection(self, port, force=False):
        if port not in self.connections:
            return
        if self.persist_conn and not force:
            return
        self.connections[port].close()
        del self.connections[port]

    def write_read(self, port, data):
        ser = self.create_connection(port)
        length_str = f"{len(data):03d}".encode("ascii")
        data = length_str + data
        if self.verbose:
            print(f"L: {length_str.decode('ascii')}, D: {data}")
        if len(data) < 999:
            data += b" " * (999 - len(data))
        if len(data) > 999:
            raise ValueError("Data too long")
        ser.write(data)
        time.sleep(0.1)
        line = ser.readline()
        self.close_connection(port)
        if self.verbose:
            try:
                print(
                    "R: ",
                    line[:2].decode('ascii'),
                    ", ".join([f"{i:.4f}" for i in struct.unpack("<16f", line[2:-2])])
                )
            except Exception:
                print("R: ", line)
        return line

    def _get_ids(self):
        ids_coms = {}
        for port in self.ports:
            line = self.write_read(port.device, bytearray([0, self.Functions.PRINT]))
            ids_coms[port.device] = int(line[:1])

        rev_ids = {v: k for k, v in ids_coms.items()}
        return ids_coms, rev_ids

    def get_memory(self, voa_id: int = None):
        if voa_id is None:
            voa_id = list(self.ids.values())
        else:
            voa_id = [voa_id]
        memory = {}
        for v in voa_id:
            line = self.write_read(self.rev_ids[v], bytearray([v, self.Functions.AVAILABLE_MEMORY]))
            memory[v] = int(line.strip()[2:-1])
        return memory

    def get(self, voa_id: int):
        line = self.write_read(self.rev_ids[voa_id], bytearray([voa_id, self.Functions.GET_VOLTAGE]))
        return np.array(struct.unpack("<16f", line[2:-2]))

    def set(self, voa_id: int, channel: int, voltage: float):
        data = bytearray([voa_id, self.Functions.SET_VOLTAGE, channel]) + struct.pack("<f", voltage)
        return self.write_read(self.rev_ids[voa_id], data)

    def set_voa(self, voa_id: int, voltage: Union[float, List[float], np.ndarray]):
        if isinstance(voltage, (float, int)):
            voltage = [voltage] * 16
        elif isinstance(voltage, np.ndarray):
            voltage = voltage.tolist()
        elif not isinstance(voltage, list):
            raise ValueError("Invalid voltage type")
        if len(voltage) != 16:
            raise ValueError("Invalid voltage length")
        data = bytearray([voa_id, self.Functions.SET_ALL_VOLTAGES]) + struct.pack("<16f", *voltage)
        return self.write_read(self.rev_ids[voa_id], data)

    def set_all(self, voltage: float):
        for voa_id in self.ids.values():
            self.set_voa(voa_id, voltage)
        return self

    def reset(self, voa_id: int):
        return self.set_voa(voa_id, 0)

    def reset_all(self):
        return self.set_all(0)

    def run_channel_sweep(self, voa_id: int, channel: int):
        return self.write_read(self.rev_ids[voa_id], bytearray([voa_id, self.Functions.SWEEP_CHANNEL, channel]))

    def run_half_sweeps(self, voa_id: int, which: int):
        return self.write_read(self.rev_ids[voa_id], bytearray([voa_id, self.Functions.SWEEP_HALF_CHANNELS, which]))

    def run_all_sweeps(self, voa_id: int):
        return self.write_read(self.rev_ids[voa_id], bytearray([voa_id, self.Functions.SWEEP_ALL_CHANNELS]))

    def voltages_to_index(self, voltage: Union[float, List[float], np.ndarray]):
        if isinstance(voltage, (float, int)):
            index = np.round(np.round(voltage, 2) * 20, 0) * 5 / 100
            index = int(index / self.max_voltage * (SWEEP_LENGTH - 1))
            return index
        elif isinstance(voltage, np.ndarray):
            pass
        elif not isinstance(voltage, list):
            raise ValueError("Invalid voltage type")

        index = np.round(np.round(np.array(voltage), 2) * 20, 0) * 5 / 100
        index = (index / self.max_voltage * (SWEEP_LENGTH - 1)).astype(np.uint8).tolist()
        return index

    def set_directly_index(self, voa_id: int, channel: int, index: int):
        data = bytearray([voa_id, self.Functions.SET_VOLTAGE_DIRECTLY, channel]) + struct.pack("<B", index)
        return self.write_read(self.rev_ids[voa_id], data)

    def set_directly(self, voa_id: int, channel: int, voltage: float):
        return self.set_directly_index(voa_id, channel, self.voltages_to_index(voltage))

    def set_voa_directly_index(self, voa_id: int, index: Union[int, List[int], np.ndarray]):
        if isinstance(index, (float, int)):
            index = [index] * 16
        data = bytearray([voa_id, self.Functions.SET_ALL_VOLTAGES_DIRECTLY]) + struct.pack("<16B", *index)
        return self.write_read(self.rev_ids[voa_id], data)

    def set_voa_directly(self, voa_id: int, voltage: Union[float, List[float], np.ndarray]):
        return self.set_voa_directly_index(voa_id, self.voltages_to_index(voltage))

    def run_channel_sweep_directly_index(self, voa_id: int, channel: int, index: List[int]):
        len_v = len(index)
        if len_v >= 255:
            raise ValueError("Too many values")
        data = (
                bytearray([voa_id, self.Functions.SWEEP_CHANNEL_DIRECTLY, channel, len_v]) +
                struct.pack(f"<{len_v}B", *index)
        )
        return self.write_read(self.rev_ids[voa_id], data)

    def run_channel_sweep_directly(self, voa_id: int, channel: int, voltages: List[float]):
        return self.run_channel_sweep_directly_index(voa_id, channel, self.voltages_to_index(voltages))

    def run_all_sweeps_directly_index(self, voa_id: int, index: Union[List[List[int]], np.ndarray]):
        index = np.array(index)
        if index.shape[0] != 16:
            raise ValueError("Invalid shape")
        len_v = index.shape[1]
        if len_v >= 255:
            raise ValueError("Too many values")
        index = index.flatten().tolist()
        data = (
                bytearray([voa_id, self.Functions.SWEEP_ALL_CHANNELS_DIRECTLY, len_v]) +
                struct.pack(f"<{len_v * 16}B", *index)
        )
        return self.write_read(self.rev_ids[voa_id], data)

    def run_all_sweeps_directly(self, voa_id: int, voltages: Union[List[List[float]], np.ndarray]):
        return self.run_all_sweeps_directly_index(voa_id, self.voltages_to_index(np.array(voltages)))

    def run_all_sweeps_directly_index_async(self, voa_id: int, index: Union[List[List[float]], np.ndarray]):
        index = np.array(index)
        if index.shape[0] != 16:
            raise ValueError("Invalid shape")
        len_v = index.shape[1]
        if len_v >= 255:
            raise ValueError("Too many values")
        index = index.T.flatten().tolist()
        data = (
                bytearray([voa_id, self.Functions.SWEEP_ALL_CHANNELS_DIRECTLY_ASYNC, len_v]) +
                struct.pack(f"<{len_v * 16}B", *index)
        )
        return self.write_read(self.rev_ids[voa_id], data)

    def run_all_sweeps_directly_async(self, voa_id: int, voltages: Union[List[List[float]], np.ndarray]):
        return self.run_all_sweeps_directly_index_async(voa_id, self.voltages_to_index(np.array(voltages)))


if __name__ == '__main__':
    voa = UsbVoa()
    print(voa.ids)
    voa.reset_all()
    voa.set_all(voa.volt_one) #open everything
    voa.set_voa(voa.Inputs, voa.volt_zero) #close all inputs
    time.sleep(2)
    voa.set(voa_id=voa.Inputs, channel=0, voltage=voa.volt_one) #open input 0
    voa.set(voa_id=9, channel=0, voltage=3.25) #set channel 0 to 50%
