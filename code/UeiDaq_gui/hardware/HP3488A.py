import time
from typing import List, Union, Optional, Sequence

import pyvisa
from pyvisa import Resource
from pyvisa.constants import *
from hardware.visa_module.visa_interface import VisaInterface


class HP3488A(VisaInterface):
    def __new__(cls, *args, **kwargs):
        if 'device_name' not in kwargs and not args:
            kwargs['device_name'] = 'GPIB0::10::INSTR'
        if 'identifier' not in kwargs and not args:
            kwargs['identifier'] = 'HP3488A'
        if 'id_cmd' not in kwargs and not args:
            kwargs['id_cmd'] = "ID?"
        return super().__new__(cls, *args, **kwargs)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open()
        self.reset()
        self._connect_mat = [[[0 for _ in range(4)] for _ in range(2)] for _ in range(5)]
        
    def reset(self):
        self.write("RESET")

    def startup_verify(self, expected=None):
        """
        Destructive startup check: reset all relays, then close `expected`
        channels and confirm the shadow matrix matches.

        Because HP3488A has no hardware readback, this resets the instrument
        to a known state and rebuilds the shadow matrix from scratch.

        Parameters
        ----------
        expected : list of int, optional
            Relay codes to close after reset (e.g. [300, 312, 401]).
            If None, leaves all relays open after reset.

        Returns
        -------
        bool — True if shadow state matches expected after the sequence.
        """
        self.reset()
        # Reset clears all relays; rebuild the shadow matrix accordingly
        self._connect_mat = [[[0 for _ in range(4)] for _ in range(2)] for _ in range(5)]

        if not expected:
            print("[HP3488A] startup_verify: all relays open.")
            return True

        self.conn(expected)
        actual = sorted(self.get_conn())
        wanted = sorted(int(x) for x in expected)

        if actual == wanted:
            print(f"[HP3488A] startup_verify: OK — {actual}")
            return True
        else:
            print(f"[HP3488A] startup_verify: MISMATCH — expected {wanted}, shadow has {actual}")
            return False

    def conn(self, val: Union[Sequence[Union[str, int]], str, int, None] = None, card: Union[Sequence[int], int, None] = None, group: Union[Sequence[int], int, None] = None, chan: Union[Sequence[int], int, None] = None):
        if val is None and card is None:
            raise ValueError("Error: Command string or card, group, and chan must be specified in connect command!")
        if val is not None:
            if isinstance(val, str):
                val = [int(val)]
            if not isinstance(val, Sequence):
                val = [val]
            if not isinstance(val[0], int):
                val = [int(x) for x in val]
            card = [(x % 1000) // 100 for x in val]
            group = [(x % 100) // 10 for x in val]
            chan = [x % 10 for x in val]
        if isinstance(card, str):
            card = [int(card)]
        if not isinstance(card, Sequence):
            card = [card]
        if not isinstance(card[0], int):
            card = [int(x) for x in card]
        if isinstance(group, str):
            group = [int(group)]
        if not isinstance(group, Sequence):
            group = [group]
        if not isinstance(group[0], int):
            group = [int(x) for x in group]
        if isinstance(chan, str):
            chan = [int(chan)]
        if not isinstance(chan, Sequence):
            chan = [chan]
        if not isinstance(chan[0], int):
            chan = [int(x) for x in chan]
        if not all(len(x) == len(card) for x in [card, group, chan]):
            raise ValueError("Error: Card, Group, and Channel must be same length!")
        if not all(1 <= x <= 5 for x in card): #new 44472a cards coming in so made it 1 to 5
            raise ValueError(f"Error: Card values must be between 1 and 5 inclusive! Got {card}.")
        if not all(0 <= x <= 1 for x in group):
            raise ValueError(f"Error: Group values must be between 0 and 1 inclusive! Got {group}.")
        if not all(0 <= x <= 3 for x in chan):
            raise ValueError(f"Error: Channel values must be between 0 and 3 inclusive! Got {chan}.")
        check = [f"{x}{y}" for x,y in zip(card, group)]
        if len(set(check)) != len(check):
            err = [f"{x}{y}{z}" for x,y,z in zip(card, group, chan)]
            raise ValueError(f"Error: Attempted to close multiple channels on the same group! Got {err}.")
        message = "CLOSE " + ",".join([f"{x}{y}{z}" for x,y,z in zip(card, group, chan)])
        self.write(message)
        for i in range(len(card)):
            self._connect_mat[card[i]-1][group[i]] = [0]*4 # changed to index card 1 down to 0 instead of card 3
            self._connect_mat[card[i]-1][group[i]][chan[i]] = 1

    def disconn(self, val: Union[Sequence[Union[str, int]], str, int, None] = None, card: Union[Sequence[int], int, None] = None, group: Union[Sequence[int], int, None] = None):
        if val is None and card is None:
            raise ValueError("Error: Command string or card and group must be specified in disconnect command!")
        if val is not None:
            if isinstance(val, str):
                val = [int(val)]
            if not isinstance(val, Sequence):
                val = [val]
            if not isinstance(val[0], int):
                val = [int(x) for x in val]
            val = [x if x >= 100 else x * 10 for x in val]
            card = [(x % 1000) // 100 for x in val]
            group = [(x % 100) // 10 for x in val]
        if isinstance(card, str):
            card = [int(card)]
        if not isinstance(card, Sequence):
            card = [card]
        if not isinstance(card[0], int):
            card = [int(x) for x in card]
        if isinstance(group, str):
            group = [int(group)]
        if not isinstance(group, Sequence):
            group = [group]
        if not isinstance(group[0], int):
            group = [int(x) for x in group]
        if not all(len(x) == len(card) for x in [card, group]):
            raise ValueError("Error: Card and Group must be same length!")
        if not all(1 <= x <= 5 for x in card): # same modification as for conn
            raise ValueError(f"Error: Card values must be between 1 and 5 inclusive! Got {card}.")
        if not all(0 <= x <= 1 for x in group):
            raise ValueError(f"Error: Group values must be between 0 and 1 inclusive! Got {group}.")
        cd = []
        gp = []
        chan = []
        for i in range(len(card)):
            try:
                temp = self._connect_mat[card[i]-3][group[i]]
                ch_idx = temp.index(1)
                cd.append(card[i])
                gp.append(group[i])
                chan.append(ch_idx)
            except ValueError:
                pass
        card = cd
        group = gp
        if len(card) == 0:
            return
        message = "OPEN " + ",".join([f"{x}{y}{z}" for x,y,z in zip(card, group, chan)])
        self.write(message)
        for i in range(len(card)):
            self._connect_mat[card[i]-1][group[i]] = [0]*4 # changed like for conn functionality

    def get_conn(self) -> List[int]:
        active_connections = []
        for i in range(len(self._connect_mat)):
            card_num = i+1
            for j in range(len(self._connect_mat[i])):
                group_num = j
                for k in range(len(self._connect_mat[i][j])):
                    if self._connect_mat[i][j][k] == 1:
                        connection_code = card_num * 100 + group_num * 10 + k
                        active_connections.append(connection_code)
                        break 
        return active_connections
    
    def print(self, message: str):
        message = message.upper()
        if len(message) > 127:
            raise ValueError(f"Message length {len(message)} exceeds maximum allowed length of 127.")
        if not all(x not in [':', ';', '#'] for x in message) or not all(32 <= ord(x) for x in message):
            raise ValueError("Displayed message contains an invalid character!")
        self.write(f"DISP {message}")


if __name__ == '__main__':
    resource_manager = pyvisa.ResourceManager()
    list_resources = list(resource_manager.list_resources())
    print(list_resources)
    with HP3488A() as x:
        print(x.identifier)
        x.print("hi")
        x.conn([300, 312, 401, 410, 502, 513])
        print(x.get_conn())
        time.sleep(5)
        x.disconn(31)
        print(x.get_conn())
        x.disconn(31)