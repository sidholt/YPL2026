import UeiDaq
import numpy as np

CUBE_IP = "172.28.2.4"


def create_session(mode):
    """create a new session based on mode (voltage or current)"""
    # session manages communication with a DAQ subsystem
    session = UeiDaq.CUeiSession()
    
    if mode == 'voltage':
        # configure analog output channel for voltage (-10V to +10V)
        # format: "device_class://ip/device_id/subsystem_channels"
        voltagePins = int(input("Enter a total number of voltage pins to use (1-32): "))
        if voltagePins < 1 or voltagePins > 32:
            print("Invalid number of voltage pins. Defaulting to 1.")
            voltagePins = 1
        print(f"pdna://{CUBE_IP}/Dev2/Ao0:{str(voltagePins-1)}")
        session.CreateAOChannel(f"pdna://{CUBE_IP}/Dev2/Ao0:{str(voltagePins-1)}", -10.0, 10.0)
        unit = "V"
        min_val = -10.0
        max_val = 10.0
    else:  # current mode
        # configure analog output channel for current (0-20mA)
        voltagePins = 1
        session.CreateAOCurrentChannel(f"pdna://{CUBE_IP}/Dev0/Ao0", 0.0, 20.0)
        unit = "mA"
        min_val = 0.0
        max_val = 20.0
    
    # set software-timed mode (point-by-point operation)
    session.ConfigureTimingForSimpleIO()
    
    # writer handles data transfer in real units (V, mA)
    writer = UeiDaq.CUeiAnalogScaledWriter(session.GetDataStream())
    
    return session, writer, unit, min_val, max_val, voltagePins

print("DAQ Control")
print("=" * 50)

selected = input("Select mode: 'v' Voltage Output, 'c' Current Output: ")

mode = 'voltage' if selected == 'v' else 'current'
session, writer, unit, min_val, max_val, voltagePins = create_session(mode)
values = [0.0] * voltagePins
print(f"Current mode: {mode.upper()}")
print(f"Pins: {voltagePins}, range: {min_val} to {max_val} {unit}")
print("=" * 50)

while True:
    try:
        # collect a value for each pin
        valid = True
        user_input = None
        for pin in range(voltagePins):
            user_input = input(f"\nEnter {unit} for pin {pin} ({min_val} to {max_val}), 's' to switch, or 'q' to quit: ")

            if user_input.lower() in ('q', 's'):
                break

            val = float(user_input)
            if val < min_val or val > max_val:
                print(f"Error: Value must be between {min_val} and {max_val} {unit}")
                valid = False
                break

            values[pin] = val

        if user_input is not None and user_input.lower() == 'q':
            writer.WriteSingleScan([0.0] * voltagePins)
            print("Shutting down...")
            break

        if user_input is not None and user_input.lower() == 's':
            session.Stop()
            del session, writer

            mode = 'current' if mode == 'voltage' else 'voltage'
            session, writer, unit, min_val, max_val, voltagePins = create_session(mode)
            values = [0.0] * voltagePins

            print(f"\n✓ Switched to {mode.upper()} mode")
            print(f"Pins: {voltagePins}, range: {min_val} to {max_val} {unit}")
            continue

        if valid:
            writer.WriteSingleScan(values)
            for pin in range(voltagePins):
                print(f"✓ Channel {pin} set to {values[pin]} {unit}")

    except ValueError:
        print("Error: Please enter a valid number, 's', or 'q'")
    except KeyboardInterrupt:
        print("\nShutting down...")
        break
    except Exception as e:
        print(f"Error: {e}")

# cleanly shut down session
session.Stop()
del session, writer
print("Done.")