from pylablib.devices import Thorlabs
import numpy as np
import time

class KDC101(Thorlabs.KinesisMotor):

    def homing(self) -> None:  #had to not be named home to preserve functionality
        self.home(sync=True, force=True, channel=None, timeout=None)  #for some reason cw doesnt work and it only homes fully extended
        self.set_position_reference(25000)

    def absolute_position(self) -> float:
        return self.get_position()

    def absolute_position_set(self, position: float) -> None:
        self.move_to(position)
        self.wait_move()


if __name__ == "__main__":
    with KDC101("27262260") as kdc:
        kdc.homing()
        print(kdc.absolute_position)
