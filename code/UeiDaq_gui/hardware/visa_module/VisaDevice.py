import time
import warnings
from asyncio import sleep
from typing import Union, Optional, Any

import deprecation
import pyvisa
from pyvisa import Resource

from hardware.visa_module.WeakResource import WeakResource

class VisaDevice:
    active_devices: WeakResource = WeakResource()

    def __init__(
            self,
            device_name: Union[str, None] = None,
            identifier: Union[str, None] = None,
            id_cmd: Union[str, bytes] = "*IDN?",
            read_buffer_len: Union[int, None] = None,
            visa_library: Union[str, None] = "@py",
            **kwargs
    ):
        self.visa_library = visa_library
        self.extra_parameters = kwargs
        self.id_cmd = id_cmd
        self._is_binary = not isinstance(id_cmd, str)
        self.read_buffer_len = read_buffer_len
        
        # Pull the force_connect flag from kwargs
        self.force_connect = kwargs.get('force_connect', False)

        rm = pyvisa.ResourceManager(visa_library=visa_library)
        device = None

        if device_name is None and identifier is None:
            raise Exception("device_name and identifier are None")

        if read_buffer_len is None and self._is_binary:
            raise Exception("Binary Type Device did not specify default read buffer size")

        if device_name in self.active_devices:
            device = self.active_devices[device_name]
            if not self.force_connect and identifier is not None:
                if self._is_binary:
                    if identifier not in self.static_query(device=device, command=self.id_cmd, read_len=self.read_buffer_len):
                        device = None
                else:
                     if identifier not in self.static_query(device=device, command=self.id_cmd).strip():
                        device = None

        if device is None and device_name is not None:
            device = self._find_device_by_name(resource_manager=rm, device_name=device_name, identifier=identifier)
            if device is None and not self.force_connect:
                warnings.warn(f"Device with name {device_name!a} not found. Trying identifier.")

        if device is None and identifier is not None and not self.force_connect:
            device = self._find_device_by_identifier(resource_manager=rm, identifier=identifier)

        if device is None:
            raise Exception(f"{self.__class__.__name__} with identifier={identifier!a}, device_name={device_name!a}, not found.")

        self._device_name = device.resource_name
        
        # Bypass strict ID query if force_connect is True
        if self.force_connect:
            if identifier:
                self.__identifier = identifier
            else:
                self.__identifier = "Forced Connection"
        else:
            if self._is_binary:
                device.write_raw(self.id_cmd)
                self.__identifier = device.read_bytes(self.read_buffer_len)
            else:
                self.__identifier = device.query(self.id_cmd).strip()
                
        if self._device_name not in self.active_devices:
            device.close()

    def _find_device_by_name(self, resource_manager, device_name, identifier) -> Optional[Resource]:
        if device_name is None:
            return None
        try:
            if device_name in self.active_devices:
                this_device = self.active_devices[device_name]
            else:
                this_device = resource_manager.open_resource(device_name)
        except Exception:
            return None

        this_device = self.pre_initialization(this_device)
        
        # Immediately return the device if we are forcing the connection
        if self.force_connect:
            return self.post_initialization(this_device)
            
        try:
            this_identifier = self.static_query(this_device, self.id_cmd, self.read_buffer_len)
        except Exception:
            this_identifier = None

        if this_identifier is None:
            this_device.close()
            return None

        if identifier is not None:
            if self._is_binary:
                if this_identifier != identifier:
                    this_device.close()
                    return None
            else:
                if not this_identifier.__contains__(identifier):
                    this_device.close()
                    return None

        return self.post_initialization(this_device)

    def _find_device_by_identifier(self, resource_manager, identifier: str) -> Optional[Resource]:
        if identifier is None: return None
        list_resources = list(set(resource_manager.list_resources()).difference(list(resource_manager.list_opened_resources())))

        for i in list_resources:
            try:
                if i in self.active_devices:
                    this_device = self.active_devices[i]
                else:
                    this_device = resource_manager.open_resource(i)
            except Exception:
                continue

            this_device = self.pre_initialization(this_device)
            try:
                this_identifier = self.static_query(this_device=this_device, command=self.id_cmd, read_len=self.read_buffer_len)
            except Exception:
                this_device.close()
                continue

            if self._is_binary:
                if identifier == this_identifier:
                    return self.post_initialization(this_device)
            else:
                if identifier in this_identifier:
                    return self.post_initialization(this_device)
            this_device.close()
        return None

    @property
    def device_name(self): return self._device_name

    @property
    def identifier(self) -> Optional[str]:
        if self._is_binary: return f"{type(self).__name__} at Interface {self._device_name} with response 0x{self.__identifier.hex()}"
        else: return self.__identifier

    @property
    def device(self) -> Optional[Resource]: return self.active_devices.get_resource_from_id(id(self))

    def open(self) -> None:
        if self.device_name in self.active_devices:
            self.active_devices.add_id(id(self), self.active_devices[self.device_name])
            return

        rm = pyvisa.ResourceManager(self.visa_library)
        this_device = rm.open_resource(self.device_name)
        this_device = self.pre_initialization(this_device)
        this_device = self.post_initialization(this_device)

        if not self.force_connect:
            if self._is_binary:
                this_device.write_raw(self.id_cmd)
                if this_device.read_bytes(self.read_buffer_len) != self.__identifier:
                    raise Exception(f"Device {self.device_name!a} is not the expected device.")
            else:
                if this_device.query(self.id_cmd).strip() != self.identifier:
                    raise Exception(f"Device {self.device_name!a} is not the expected device.")

        self.active_devices.add_id(id(self), this_device)

    def close(self) -> None:
        if self.device_name in self.active_devices:
            self.active_devices.remove_id(id(self))

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): self.close()
    def __del__(self):
        try: self.close()
        except: pass

    @staticmethod
    def static_write(this_device: Resource, command: Union[str, bytes]):
        if isinstance(command, bytes): this_device.write_raw(command)
        else: this_device.write(command)
        return this_device

    @staticmethod
    def static_read(this_device: Resource) -> str: return this_device.read().strip()

    @staticmethod
    def static_read_binary(this_device: Resource, read_len: int = 256) -> bytes: return this_device.read_bytes(read_len)

    @staticmethod
    def static_query(this_device: Resource, command: Union[str, bytes], read_len: int = 256) -> Union[str, bytes]:
        if isinstance(command, bytes):
            this_device.write_raw(command)
            return this_device.read_bytes(read_len)
        else:
            return this_device.query(command).strip()

    def write(self, command: Union[str, bytes], retries: int = 3):
        last_exc = None
        for attempt in range(retries):
            try:
                self.static_write(self.device, command)
                return self
            except Exception as e:
                last_exc = e
                time.sleep(0.1 * (2 ** attempt))
        raise last_exc

    def read(self, read_len: Union[int, None] = None) -> Union[str, bytes]:
        if self._is_binary: return self.static_read_binary(device=self.device, read_len=read_len or self.read_buffer_len)
        else: return self.static_read(self.device)

    def query(self, command: Union[str, bytes], read_len: Union[int, None] = None,
              retries: int = 3) -> Union[str, bytes]:
        last_exc = None
        for attempt in range(retries):
            try:
                return self.static_query(
                    self.device, command=command,
                    read_len=read_len or (self.read_buffer_len if self._is_binary else 256)
                )
            except Exception as e:
                last_exc = e
                time.sleep(0.1 * (2 ** attempt))
        raise last_exc

    def ask(self, command: str) -> str: return self.query(':' + command + '?')

    def command(self, command: str, value=None):
        if value is None: self.write(':' + command)
        else: self.write(':' + command + ' ' + str(value))

    def sync_command(self, command: str, value=None):
        self.command(command, value)
        self.wait_for_completion()

    def property_command(self, command: str, val=None, round_to=None):
        if val is None:
            response = self.ask(command)
            if response is None or response == "None": return None
            elif type(response) is str:
                try: return float(response)
                except Exception: return response
            else: return response
        else:
            if round_to is not None: val = round(val, round_to)
            self.command(command, val)

    def operation_completion(self): return self.query('*OPC?') == '1'

    async def wait_for_completion(self, timeout: float = 30.0):
        step = 0.5
        await sleep(step)
        for i in range(0, int(timeout / step)):
            if self.operation_completion(): break
            await sleep(step)

    def reboot(self): self.write('*RST')

    @deprecation.deprecated()
    def identification(self): return self.query(self.id_cmd).strip()

    def error(self): return self.ask("SYST:ERR")
    def version(self): return self.ask("SYST:VERS")
    def is_working(self): return not self.operation_completion()

    @staticmethod
    def pre_initialization(device: Union[Resource, None]) -> Optional[Resource]: return device

    @staticmethod
    def post_initialization(device: Union[Resource, None]) -> Optional[Resource]: return device

    def __getattr__(self, name: str) -> Any:
        if self.device is None:
            raise AttributeError(f"device not connected and '{type(self).__name__}' object has no attribute '{name}'")
        if self.device is not None and hasattr(self.device, name):
            return getattr(self.device, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")