import math
import time
from typing import Sequence

import numpy as np
from pyvisa import Resource
from pyvisa.constants import VI_READ_BUF_DISCARD, VI_WRITE_BUF, VI_WRITE_BUF_DISCARD, VI_READ_BUF, VI_ASRL_FLOW_RTS_CTS

from hardware.visa_module.visa_interface import VisaInterface

# something cannot be less than 6 (say invalid input)
# minimize latency
# include all startup code from all drivers
# remember to open the resource and at the en disconnect and close the resource
# using with statements when including other classes
# make sure to read on page 32 plus

# this is just defining constants to be used with the kdc101 ex KDC101.acc_mult
class KDC101(VisaInterface):
    T = 2048 / (6e6)  # For KDC101
    EncCnt = 34554.96  # For Z8*** Brushed DC Motor Stage
    vel_mult = EncCnt * T * 65536
    acc_mult = EncCnt * T * T * 65536

    # dont mess with this!!! might call a library
    def __new__(cls, *args, **kwargs):
        if 'visa_library' not in kwargs and not args:
            kwargs['visa_library'] = "@ivi"
        if 'device_name' not in kwargs and not args:
            kwargs['device_name'] = 'ASRL26::INSTR'
        if 'identifier' not in kwargs and not args:
            kwargs['identifier'] = b'\x00\x26\xff\xff'
        if 'id_cmd' not in kwargs and not args:
            kwargs['id_cmd'] = b'\x00\x26\x00\x00'
        if 'read_buffer_len' not in kwargs and not args:
            kwargs['read_buffer_len'] = 4
        return super().__new__(cls, *args, **kwargs)


    @staticmethod
    def pre_initialization(device: Resource) -> Resource:
        device.baud_rate = 115200
        device.data_bits = 8
        device.parity = 0
        device.stop_bits = 1
        device.flow_control = VI_ASRL_FLOW_RTS_CTS
        device.timeout = 5000
        return device

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()

    def read(self, length: int = 256) -> Sequence[bytes]:
        out = np.array(self.device.read_raw(length), dtype=np.uint8)
        time.sleep(0.05)
        self.device.flush(VI_READ_BUF_DISCARD)
        # self.close()
        # self.open()
        return out

    def write(self, message: Sequence[bytes]) -> int:
        self.device.flush(VI_WRITE_BUF)
        out = self.device.write_binary_values(message='', values=message, datatype='B', is_big_endian=False,
                                              header_fmt='empty', termination=None, encoding=None)
        self.device.flush(VI_WRITE_BUF)
        time.sleep(0.05)
        return out

    def query(self, message: Sequence[bytes], length: int = 256) -> Sequence[bytes]:
        self.device.flush(VI_READ_BUF)
        self.write(message)
        return self.read(length)

    def close(self):
        if self.device_name in self.active_devices:
            self.write(np.array([0x02, 0x00, 0x00, 0x00, 0x50, 0x01], dtype=np.uint8))
            time.sleep(1)
        super().close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def home(self) -> None:
        self.write('430400005001')

    def getStatusBits(self):
        return self.query(np.array([0x29, 0x04, 0x00, 0x00, 0x50, 0x01], dtype=np.uint8), length=12)

    @property
    def position(self) -> float:  # absolute position from home in mm
        resp = self.query('0a0400005001', length=12)
        resp = resp[-4:]
        resp = int.from_bytes(resp, "little")
        self._position = resp / KDC101.EncCnt
        return self._position

    @property
    def velocity(self) -> float:  # max velocity in mm/s
        resp = self.query('140400005001', length=20)
        resp = resp[-4:]
        resp = int.from_bytes(resp, "little")
        resp = resp / KDC101.vel_mult
        self._velocity = resp
        return self._velocity

    @velocity.setter
    def velocity(self, val: float) -> None:
        if val < 0 or val > 2.3:
            raise ValueError('KDC101 can only accept velocities from 0 to 2.3 mm/s!')
        mes = self.query('140400005001', length=20)
        val = int(math.floor(val * KDC101.vel_mult))
        val = int.to_bytes(val, byteorder="little", length=4)
        mes = bytearray([a & b for a, b in zip(bytes.fromhex('000000000000FFFFFFFFFFFFFFFFFFFF00000000'), mes)])
        mes = bytearray([a | b for a, b in zip(bytes.fromhex('13040E00D00100000000000000000000' + val.hex()), mes)])
        self.write(mes.hex())
        self._velocity = self.velocity

    @property
    def acceleration(self) -> float:  # acceleration in mm/s/s
        resp = self.query('140400005001', length=20)
        resp = resp[-8:-4]
        resp = int.from_bytes(resp, "little")
        resp = resp / KDC101.acc_mult
        self._acceleration = resp
        return self._acceleration

    @acceleration.setter
    def acceleration(self, val: float) -> None:
        if val < 0 or val > 10:
            raise ValueError('KDC101 can only accept accelerations from 0 to 10 mm/s/s!')
        mes = self.query('140400005001', length=20)
        val = int(math.floor(val * KDC101.acc_mult))
        val = int.to_bytes(val, byteorder="little", length=4)
        mes = bytearray([a & b for a, b in zip(bytes.fromhex('000000000000FFFFFFFFFFFF00000000FFFFFFFF'), mes)])
        mes = bytearray(
            [a | b for a, b in zip(bytes.fromhex('13040E00D001000000000000' + val.hex() + '00000000'), mes)])
        self.write(mes.hex())
        self._acceleration = self.acceleration


if __name__ == '__main__':
    with KDC101(device_name='ASRL26::INSTR') as motor:
        print(motor.identifier)
        print(motor.getStatusBits())
    # motor.home()
    # motor.position = 16.25
