import time

from ophyd import Component as Cpt
from ophyd import Device, EpicsSignal, EpicsSignalRO


## Peltier cooler
class Peltier_Cooler(Device):
    enable_command = Cpt(EpicsSignal, 'B-ES{Pel-IO:1}DO:1-Cmd')
    enable_status = Cpt(EpicsSignal, 'B-ES{Pel-IO:1}DO:1-Sts')
    set_power_command = Cpt(EpicsSignal, '-CT{Peltier:1}ai2')
    setup_power = Cpt(EpicsSignal, '-CT{Peltier:1}ai2.DESC')
    setup_hot_side_max = Cpt(EpicsSignal, '-CT{Peltier:1}ai3.DESC')
    set_hot_side_max = Cpt(EpicsSignal, '-CT{Peltier:1}ai3')
    setup_chiller_temperature = Cpt(EpicsSignal, '-CT{Peltier:1}ai1.DESC')
    set_chiller_temperature = Cpt(EpicsSignal, '-CT{Peltier:1}ai1')
    setup_peltier_enabled = Cpt(EpicsSignal, '-CT{Peltier:1}bi9.DESC')

    def enable(self):
        self.enable_command.put(1)
        print('Peltier Power enabled.')
        
    def disable(self):
        self.enable_command.put(0,use_complete=True)
        print('Peltier Power diabled.')
            
    def power(self,P):
        self.set_power_command.put(P)
        print(f'Peltier Power set to: {P} percent')
        
    def status(self):
        return print(f'Peltier enabled: {bool(self.enable_status.get())} Peltier Power: {self.set_power_command.get()} percent')
    
    def setup(self):
        self.setup_chiller_temperature.put('chiller temp. [12-22C]')
        self.set_chiller_temperature.put(22)
        self.setup_power.put('Peltier Power [0-100%]')
        self.set_power_command.put(0)
        self.setup_hot_side_max.put('Pel. hot side max T [C]')
        self.set_hot_side_max.put(17.5)
        self.setup_peltier_enabled.put('Peltier ENABLED')
    
    def chiller_temperature(self,T):
        self.set_chiller_temperature.put(T)
        print(f'Chiller temperature set to: {T} [C]')

def _yes_no(bool):
    return "yes" if bool else "no"

def _on_off(bool):
    return "on" if bool else "off"

class LinkamThermal(Device):
    # Set-and-read signals
    cmd = Cpt(EpicsSignal, "STARTHEAT")
    temperature_setpoint = Cpt(EpicsSignal, "SETPOINT:SET")
    temperature_rate_setpoint = Cpt(EpicsSignal, "RAMPRATE:SET")

    # Read-Only signals
    status_power = Cpt(EpicsSignalRO, "STARTHEAT")
    status_code = Cpt(EpicsSignalRO, "STATUS")
    # status_code = Cpt(EpicsSignal, 'STATUS')
    # done = Cpt(AtSetpoint, parent_attr = 'status_code')
    temperature_current = Cpt(EpicsSignalRO, "TEMP")
    temperature_rate_current = Cpt(EpicsSignalRO, "RAMPRATE")

    # not commonly used
    init = Cpt(EpicsSignal, "INIT")
    model_array = Cpt(EpicsSignal, "MODEL")
    serial_array = Cpt(EpicsSignal, "SERIAL")
    stage_model_array = Cpt(EpicsSignal, "STAGE:MODEL")
    stage_serial_array = Cpt(EpicsSignal, "STAGE:SERIAL")
    firm_ver = Cpt(EpicsSignal, "FIRM:VER")
    hard_ver = Cpt(EpicsSignal, "HARD:VER")
    ctrllr_err = Cpt(EpicsSignal, "CTRLLR:ERR")
    config = Cpt(EpicsSignal, "CONFIG")
    stage_config = Cpt(EpicsSignal, "STAGE:CONFIG")
    disable = Cpt(EpicsSignal, "DISABLE")
    dsc = Cpt(EpicsSignal, "DSC")
    # RR_set = Cpt(EpicsSignal, 'RAMPRATE:SET')
    # RR = Cpt(EpicsSignal, 'RAMPRATE')
    ramptime = Cpt(EpicsSignal, "RAMPTIME")
    # startheat = Cpt(EpicsSignal, 'STARTHEAT')
    holdtime_set = Cpt(EpicsSignal, "HOLDTIME:SET")
    holdtime = Cpt(EpicsSignal, "HOLDTIME")
    power = Cpt(EpicsSignalRO, "POWER")
    lnp_speed = Cpt(EpicsSignal, "LNP_SPEED")
    lnp_mode_set = Cpt(EpicsSignal, "LNP_MODE:SET")
    lnp_speed_set = Cpt(EpicsSignal, "LNP_SPEED:SET")

    def on(self):
        return self.cmd.put(1)

    # def _on(self):              # bad practice, put as attribute in profile collection
    #     yield from bps.mv(self.cmd, 1)

    def off(self):
        return self.cmd.put(0)

    # def _off(self):             # bad practice
    #     yield from bps.mv(self.cmd, 0)

    def setTemperature(self, temperature):
        return self.temperature_setpoint.put(temperature)

    def setTemperatureRate(self, temperature_rate):
        return self.temperature_rate_setpoint.put(temperature_rate)

    def temperature(self):
        return self.temperature_current.get()

    def temperatureRate(self):
        return self.temperature_rate_current.get()

    @property
    def serial(self):
        return self.arr2word(self.serial_array.get())

    @property
    def model(self):
        return self.arr2word(self.model_array.get())

    @property
    def stage_model(self):
        return self.arr2word(self.stage_model_array.get())

    @property
    def stage_serial(self):
        return self.arr2word(self.stage_serial_array.get())

    @property
    def firmware_version(self):
        return self.arr2word(self.firm_ver.get())

    @property
    def hardware_version(self):
        return self.arr2word(self.hard_ver.get())

    def status(self):
        code = int(self.status_code.get())
        print("\n"
            f"Current temperature = {self.temperature():.1f}, setpoint = {self.temperature_setpoint.get():.1f}\n"
            f"Error\t\t:{_yes_no(code&1)}\n"
            f"At setpoint\t:{_yes_no(code&2)}\n"
            f"Heater\t\t:{_on_off(code&4)}\n"
            f"pump\t\t:{_on_off(code&8)}\n"
            f"pump Auto\t:{_on_off(code&16)}\n"
        )


class LinkamTensile(LinkamThermal):
    #TODO: restore _mov, _setDirection, _start, _stop in package due to yielding from bluesky plans
    # cmd = Cpt(EpicsSignal, 'STARTHEAT')
    # temperature_setpoint = Cpt(EpicsSignal, 'SETPOINT:SET')
    # temperature_rate_setpoint = Cpt(EpicsSignal, 'RAMPRATE:SET')

    # status = Cpt(EpicsSignalRO, 'STATUS')
    # temperature = Cpt(EpicsSignalRO, 'TEMP')
    # rampRate = Cpt(EpicsSignalRO, 'RAMPRATE')

    # Read-Only signals for the states of the stage
    status_code_Tensile = Cpt(EpicsSignalRO, "TST_STATUS")
    POS = Cpt(EpicsSignalRO, "TST_MOTOR_POS")
    POS_RAW = Cpt(EpicsSignalRO, "TST_RAW_MOTOR_POS")

    FORCE = Cpt(EpicsSignalRO, "TST_FORCE")
    STRAIN = Cpt(EpicsSignalRO, "TST_STRAIN")
    STRESS = Cpt(EpicsSignalRO, "TST_STRESS")

    tensile_maxs_force = Cpt(EpicsSignalRO, "TST_MAX_FORCE")
    tensile_remain_cycles = Cpt(EpicsSignalRO, "TST_CYCLES_REMAINING")

    # Read-Only signals of the set points
    direction = Cpt(EpicsSignalRO, "TST_TABLE_DIR")
    force = Cpt(EpicsSignal, "TST_FORCE_SETPOINT")
    distance = Cpt(EpicsSignal, "TST_MTR_DIST_SP")  # relative distance
    mode = Cpt(EpicsSignalRO, "TST_TABLE_MODE")
    modes= ("velocity","step","cycle","force","relax","stop")
    velocity = Cpt(EpicsSignal, "TST_MTR_VEL")

    # Set-and-read signals
    run_cmd = Cpt(EpicsSignal, "TST_START_MOTOR")  # start/stop the motor

    direction_setpoint = Cpt(EpicsSignal, "TST_TABLE_DIR:SET")
    force_setpoint = Cpt(EpicsSignal, "TST_FORCE_SETPOINT:SET")
    distance_setpoint = Cpt(EpicsSignal, "TST_MTR_DIST_SP:SET")  # relative distance
    mode_setpoint = Cpt(EpicsSignal, "TST_TABLE_MODE:SET")
    velocity_setpoint = Cpt(EpicsSignal, "TST_MTR_VEL:SET")

    # not commonly used ones
    J2J_distance = Cpt(EpicsSignal, "TST_JAW_TO_JAW_SIZE")
    J2J_distance_setpoint = Cpt(EpicsSignal, "TST_JAW_TO_JAW_SIZE:SET")

    def statusTensile(self, verbosity=3):
        code = int(self.status_code_Tensile.get())
        text = ("\n"
            f"Current temperature = {self.temperature():.1f}, setpoint = {self.temperature_setpoint.get():.1f}\n"
            f"Current mode = {self.getMode(verbosity=5):}\n"
            f"Zero Limit\t{_yes_no(code&1)}\n"
            f"ref Limit\t{_yes_no(code&2)}\n"
            f"Move Done\t{_on_off(code&4)}\n"
            f"Direction\t{_on_off(code&8)}\n"
            f"Force\t\t{_yes_no(code&16)}\n"
            f"Cycle Mode\t{_yes_no(code&32)}\n"
            f"Cycle dir Open\t{_yes_no(code&64)}\n"
        )

        if verbosity >= 3:
            print(text)
        return code

    def start(self):
        return self.run_cmd.put(1)

    # def _start(self):              # bad practice
    #     yield from bps.mv(self.run_cmd, 1)

    def stop(self):
        return self.run_cmd.put(0)

    # def _stop(self):              # bad practice
    #     yield from bps.mv(self.run_cmd, 0)


    def setMode(self, mode):
        """
        mode = 0 : 'velocity'
        mode = 1 : 'step'
        mode = 2 : 'cycle'
        mode = 3 : 'force'
        mode = 4 : 'relax'
        mode = 5 : 'stop'
        """
        try:
            mode = mode if isinstance(mode,int) else self.modes.index(mode)
            print(f"mode:\t\t{self.modes[mode]}")
        except ValueError:
            return print("Wrong mode. Please choose from 0-velocity, 1-step, 3-force, 4-relax and 5-stop")

        match mode:
            case 0:
                print("Constant velocity is expected.")
                print("Inputs are limited to velocity and distance.")
            case 1:
                print("Distance is expected.")
                print("Inputs are limited to velocity and distance.")
            case 2:
                print("SWITCH TO step MODE!")
            case 3:
                print("Constant force is expected.")
                print("Inputs are limited to force and distance.")
            case 4:
                print("Nothing is expected except time.")

        return self.mode_setpoint.put(mode)

    def getMode(self, verbosity=0):
        value = self.mode_setpoint.get()
        if verbosity >= 3:
            return self.modes[value]
        return value

    def mov(self, position, velocity=None, verbosity=3):
        # move to the absolute position

        if position < 0:
            return "Error: position < 0. "

        # set distance
        relative_pos = position - self.POS.get()
        if verbosity >= 3:
            print(f"The motor will move {relative_pos:1f} mm.")

        if relative_pos > 0:
            self.setDirection(0)
        elif relative_pos < 0:
            self.setDirection(1)
        else:
            return self.POS.get()

        self.distance_setpoint.put(abs(relative_pos))

        # set velocity
        if velocity == None and self.velocity.get() == 0:
            return print("The velocity is 0. No movement.")
            # self.velocity_setpoint.put(self.velocity.get())
        elif velocity == None and self.velocity.get() != 0:
            pass
        else:
            self.velocity_setpoint.put(velocity)

        self.run_cmd.put(1)
        if verbosity >= 1:
            while int(self.status_code_Tensile.get()) & 4:
                return self.POS.get()

        if verbosity >= 3:
            print(self.POS.get())
        return self.POS.get()

    def movr(self, distance, velocity=None, verbosity=3):
        # move to the absolute position
        relative_pos = distance
        if relative_pos > 0:  # open
            self.setDirection(0)
        elif relative_pos < 0:  # close
            self.setDirection(1)
        else:
            return self.POS.get()
        self.distance_setpoint.put(abs(relative_pos))

        if velocity == None and self.velocity.get() == 0:
            return print("The velocity is 0. No movement.")
            # self.velocity_setpoint.put(self.velocity.get())
        elif velocity == None and self.velocity.get() != 0:
            pass
        else:
            self.velocity_setpoint.put(velocity)

        self.run_cmd.put(1)
        if verbosity >= 1:
            while int(self.status_code_Tensile.get()) & 4:
                return self.POS.get()

        if verbosity >= 3:
            print(self.POS.get())
        return self.POS.get()

    def setDirection(self, direction, wait_time=0.1, verbosity=3):
        # 0 = Open, 1 = close
        if direction == 0 or direction == "open":
            self.direction_setpoint.put(0)
            print("test0")

        elif direction == 1 or direction == "close":
            print("test1")
            self.direction_setpoint.put(1)
        else:
            print("Wrong input.")

        time.sleep(wait_time)
        if verbosity >= 3:
            if self.direction.get() == 0:
                text_direction = "open"
            else:
                text_direction = "close"
            print(f"Current direction : {text_direction}")

        return self.direction.get()
    
    def states(self):
        # show the current states of the tensile stage, including
        # T, motor position and direction, force, velocity and mode

        # from Temperature sensor, independent from the tensile
        print("\n"
            f"Current temperature = {self.temperature():.1f}, setpoint = {self.temperature_setpoint.get():.1f}\n"

            # stage states, RO
            f"STAGE POSITION = {self.POS.get():1f}\n"
            f"STAGE FORCE  = {self.FORCE.get():1f}\n"
            f"STAGE STRAIN = {self.STRAIN.get():1f}\n"
            f"STAGE STRESS = {self.STRESS.get():1f}\n"

            # setting for the tensile part
            f"Current mode = {self.getMode(verbosity=5)}\n\n"
            f"Current distance = {self.distance.get():1f}, setpoint={self.distance_setposition.get():1f}\n"
            f"Current velocity = {self.velocity.get():1f}, setpoint={self.velocity_setposition.get():1f}\n"
            f"Current force = {self.force.get():1f}, setpoint={self.force_setposition.get():1f}\n"
        )
