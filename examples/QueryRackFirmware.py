import UeiDaq
import numpy
import time
import sys

# Parse info string in the format '<info name>=<info value>'
def GetInfo(hwInfo, infoName):
    index = hwInfo.find(infoName)
    info = hwInfo[index+len(infoName)+1:hwInfo.find("\n", index)]
    return info

try:
    cpuDev = UeiDaq.CUeiDeviceEnumerator_GetDeviceFromResource("pdna://192.168.100.11/dev14")

    # Get the GetHardware Info string for the CPU
    # This string contains Firmware version
    hwInfo = cpuDev.GetHardwareInformation()
    
    # Firmware ervision is encoded as 'FwRev=XXYYZZ' in hexadecimal
    fwInfoRev = int(GetInfo(hwInfo, "FwRev"),16)

    major = (fwInfoRev & 0x00FF0000) >>16
    minor = (fwInfoRev & 0x0000FF00) >>8
    revision = (fwInfoRev & 0x000000FF)

    # Firmware build is encoded as 'FwBuild=XX'
    build = int(GetInfo(hwInfo, "FwBuild"),16)

    cubefwVer = str(major) + "." + str(minor) + "." + str(revision) + "." + str(build)

    print("Cube/RACK's Firmware version: %s" %(cubefwVer))

    # Number of I/O cards is encoded as 'Layers=XX'
    numLayersInRack = int(GetInfo(hwInfo, "Layers"))

    # The total numLayersInRack does include the power and CPU layers
    # We only are interested in the I/O boards so we take numLayersInRack - 2
    for i in range((numLayersInRack - 2)): 
        layerDev = UeiDaq.CUeiDeviceEnumerator_GetDeviceFromResource("pdna://192.168.100.11/dev" + str(i))

        layerName = GetInfo(layerDev.GetHardwareInformation(), "DevName")
        layerLogicInfo = GetInfo(layerDev.GetHardwareInformation(), "LogicRev")

        print("Layer: " + str(i) + " " + "Device Name: " + str(layerName) + " " + " " + "Logic Ver: " + str(layerLogicInfo))


except Exception as e:
    exception_type, exception_object, exception_traceback = sys.exc_info()
    line_number = exception_traceback.tb_lineno  
    print("Exception type: ", exception_type)
    print("Line number: ", line_number)
    
    print("Exception: %s" % e)
