"""
Module made for calibrating the beam to a line, 
which will then let the user choose a position on the z-axis
and have the motors move to the correct focus for the beam.
"""
from pcdsdevices.epics_motor import IMS
from pcdsdevices.mv_interface import setup_preset_paths
from ophyd.device import Component as Cpt
from ophyd.device import Device
from ophyd.device import FormattedComponent as FCpt
from ophyd.positioner import SoftPositioner
from pcdsdevices.mv_interface import FltMvInterface

class Motor(FltMvInterface, SoftPositioner):
    pass

class position:
    """
    Class for keeping a set of positions tidy.
    """
    def __init__(self,x=0,y=0,z=0):
        self.z=z
        self.y=y
        self.x=x

class line_info:
    """
    Class for keeping the info about the line made.
    """
    def __init__(self,mx=0,bx=0,my=0,by=0):
        self.mx=mx
        self.bx=bx
        self.my=my
        self.by=by

class motor_stack:
    """
    Testing class.
    """
    def __init__(self, x=Motor(name="test_x", init_pos=0),
                       y=Motor(name="test_y", init_pos=0),
                       z=Motor(name="test_z", init_pos=0)):
        self.x_motor=x
        self.y_motor=y
        self.z_motor=z

def allign(lens=None,z_position=None,recall=False):
    """
    Generates equations for the beam based on user input.
    
    This program uses two points, one made on the entrance
    and the other made on the exit, adjusted by the user
    to put the beam into alignment, and uses those two points
    to make two equations to determine a y- and x-position
    for any z-value the user wants that will keep the beam focused.
    The beam line can be saved between runs,
    but is not recommended for long periods of time.
    """
    def get_positions(lens=None):
        """
        Uses user input to make a focused point on both ends of the beam.
        Returns two different points, entrance then exit.
        """
        lens.z_motor.move(lens.z_motor.limits[0])
        lens.x_motor.tweak(lens.y_motor)
        pos1 = position(lens.x_motor.position,lens.y_motor.position,lens.z_motor.position)
        lens.z_motor.move(lens.z_motor.limits[1])
        print()
        lens.x_motor.tweak(lens.y_motor)
        return [pos1,position(lens.x_motor.position,lens.y_motor.position,lens.z_motor.position)]

    def make_line(positions):
        """
        Creates two equations, one for y and one for x,
        based on the two end points, that gets the focused
        position for any position.
        Data saved in z = m(x or y) + b format.
        """
        pos_one=positions[0]
        pos_two=positions[1]
        mx = (pos_one.x-pos_two.x)/(pos_two.z-pos_one.z)
        bx = pos_one.x - (mx * pos_one.z)
        my = (pos_two.y-pos_one.y)/(pos_two.z-pos_one.z)
        by = pos_one.y - (mx * pos_one.z)
        return line_info(mx,bx,my,by) 

    def move(lens=None,line_info=None,z_position=5):
        """
        Moves the motor to the z_position specified, while focusing
        the other dimensions using the line data make before.
        """
        lens.x_motor.move((line_info.mx * z_position) + line_info.bx) 
        lens.y_motor.move((line_info.my * z_position) + line_info.by)
        lens.z_motor.move(z_position)

    setup_preset_paths(hutch='presets',exp='presets')
    positions = []
    if recall == False:
        positions = get_positions(lens)
        lens.x_motor.presets.add_hutch(value=positions[0].x,name="entry")
        lens.x_motor.presets.add_hutch(value=positions[1].x,name="exit")
        lens.y_motor.presets.add_hutch(value=positions[0].y,name="entry")
        lens.y_motor.presets.add_hutch(value=positions[1].y,name="exit")
        lens.z_motor.presets.add_hutch(value=positions[0].z,name="entry")
        lens.z_motor.presets.add_hutch(value=positions[1].z,name="exit")
    else:
       positions = [position(lens.x_motor.presets.positions.entry.pos,
                             lens.y_motor.presets.positions.entry.pos,
                             lens.z_motor.presets.positions.entry.pos),
                    position(lens.x_motor.presets.positions.exit.pos,
                             lens.y_motor.presets.positions.exit.pos,
                             lens.z_motor.presets.positions.exit.pos)] 
    move(lens,make_line(positions),z_position)
    print(lens.z_motor.position,lens.y_motor.position,lens.x_motor.position)

allign(motor_stack(),5,recall=False)
