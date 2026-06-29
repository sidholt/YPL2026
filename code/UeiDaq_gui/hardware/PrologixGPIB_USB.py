import string

import pyvisa as visa
import serial


class PrologixInstrument(object):
    """
    Class for instruments connected via prologix USB-GPIB adapter
    """
    serFd = None
    lineEnd = "\n"

    def __init__(self, gpibAddr, comPort, baud_rate=921600, timeout=0.25, silent=True):
        # comPort = int(comPort[3:])-1
        self._silent = silent
        self.gpibAddr = gpibAddr

        if timeout == None:
            timeout = 2
        if PrologixInstrument.serFd == None:
            PrologixInstrument.serFd = serial.Serial(comPort, baudrate=baud_rate, timeout=timeout)
        mess = "++mode 1" + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        mess = "++ifc" + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        # serialInterface.serFd.write("++auto 1"+serialInterface.lineEnd )
        mess = "++read_tmo_ms 200" + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        ver = tuple((int(i) for i in self.query('++ver').split()[-1].split('.')))
        if ver != (6, 107):
            raise (RuntimeError("Prologix is of version: %d.%d\n Please Update." % ver))

    def ask(self, cmd):
        return self.query(cmd)

    def query(self, cmd):
        mess = '++addr ' + str(self.gpibAddr) + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        if isinstance(cmd, list):
            for i in cmd:
                if not self._silent:
                    print("Command: \'%s\'" % cmd)
                mess = i + PrologixInstrument.lineEnd
                PrologixInstrument.serFd.write(mess.encode())
        else:
            if not self._silent:
                print("Command: \'%s\'" % cmd)
            mess = cmd + PrologixInstrument.lineEnd
            PrologixInstrument.serFd.write(mess.encode())
        # serialInterface.serFd.write("++read eoi"+serialInterface.lineEnd)
        mess = "++read" + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        retry = 1
        while retry > 0:
            res = PrologixInstrument.serFd.readlines()
            if len(res) > 0:
                if not self._silent:
                    print("Obtained result:")
                retry = 0
                if res[0][0] == '#':
                    sizeLen = int(res[0][1])
                    binSize = int(res[0][2:2 + sizeLen])
                    oRes = res[0][2 + sizeLen:] + res[1] + res[2][0:-1]
                    if binSize != len(oRes):
                        oRes = None
                    res = oRes
                    if not self._silent:
                        print("Obtained binary data of size %d" % binSize)
                else:
                    res = [i.decode().strip('\n\r') for i in res]
                if not self._silent:
                    if len(str(res)) < 100:
                        print(res)
                    else:
                        print("Obtained large chunk of data of length %d" % len(res))
            retry -= 1
        if not isinstance(cmd, list):
            res = res[0]
        return res

    def write(self, cmd):
        mess = '++addr ' + str(self.gpibAddr) + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        if isinstance(cmd, list):
            for i in cmd:
                if not self._silent:
                    print("Command: \"%s\"" % cmd)
                mess = i + PrologixInstrument.lineEnd
                PrologixInstrument.serFd.write(mess.encode())
        else:
            mess = cmd + PrologixInstrument.lineEnd
            PrologixInstrument.serFd.write(mess.encode())
            if not self._silent:
                print("Command: \"%s\"" % cmd)
        return
    
    def read(self):
        # Point the adapter to this device
        mess = '++addr ' + str(self.gpibAddr) + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        
        # Tell Prologix to read from the device
        mess = "++read" + PrologixInstrument.lineEnd
        PrologixInstrument.serFd.write(mess.encode())
        
        retry = 1
        while retry > 0:
            res = PrologixInstrument.serFd.readlines()
            if len(res) > 0:
                # Handle binary block or string response
                if res[0][0] == ord('#') or res[0][0] == '#':
                    return res[0].decode().strip('\n\r')
                else:
                    return res[0].decode().strip('\n\r')
            retry -= 1
        return ""


class ScpiInstrumentWrapper(object):
    '''
    Wrapper for visa/prologix connected instruments supporting SCPI language
    possible resources are:
        - COM<NR> where '<NR>' is the COM-port number
        - GPIB::<ADDR> where <ADDR> is the GPIB address of the instrument
        - TCPIP::<IPADDR> where <IPADDR> is the ip address of the instrument
        - PROLOGIX::COM<NR>::GPIB::<ADDR> if the instrument is connected via Prologix
          USB-GPIB adapter. <NR> is the COM-port number of the Prologix adapter
          and <ADDR> is the GPIB address of the instrument
        - USB identifiers e.g. 'RSNRP::0x000c::101628'
    '''

    def __init__(self, resource, silent=True):
        self.resource = resource
        if resource[0:8].lower() == 'prologix':
            # device is connected via prologix adapter
            resource = resource.split('::')
            comport = resource[1]
            gpibAddr = int(resource[-1])
            self._inst = PrologixInstrument(gpibAddr, comport, silent=silent)
        else:
            # device is connected using a VISA resource (includes LAN)
            rm = visa.ResourceManager()
            self._inst = rm.open_resource(resource)
        # if self.resource[:5] != 'RSNRP':
        #     self.clear()

    def query(self, cmd):
        ret = self._inst.query(cmd).strip('\n')
        return ret

    def ask(self, cmd):
        return self.query(cmd)

    def write(self, cmd):
        self._inst.write(cmd)

    def read(self, ):
        return self._inst.read().strip('\n')

    def getErr(self):
        err = self.ask('SYST:ERR?')
        (errno, errstr) = string.split(err, ',', 1)
        return (int(errno), errstr)

    def checkErr(self):
        '''
        Asks the instrument for errors and raises an exception if there is an error
        '''
        err = self.getErr()
        if err[0] != 0:
            name = self.__class__.__name__
            raise Exception('%s Remote Control Error: ' % name + str(err[0]) + ', ' + err[1])

    def reset(self):
        '''
        perform an instrument reset
        '''
        self.write('*RST')
        return

    def clear(self):
        '''
        Clear instrument status byte
        '''
        self.write('*CLS')
        return

    def getIdent(self):
        '''
        Get device ID
        '''
        return self.ask('*IDN?')

    def wait(self, timeout=None):
        '''
        Wait for operation to complete
        '''
        if timeout != None:
            to = self._inst.timeout
            self._inst.timeout = timeout
            self.ask('*OPC?')
            self._inst.timeout = to
        else:
            self.ask('*OPC?')

    @property
    def timeout(self, ):
        return self._inst.timeout

    @timeout.setter
    def timeout(self, timeout):
        self._inst.timeout = timeout


if __name__ == '__main__':
    with PrologixInstrument(21, 'ASRL10::INSTR') as osm:
        print(osm.identifier)
