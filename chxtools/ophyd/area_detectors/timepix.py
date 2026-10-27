from collections.abc import Callable
from datetime import datetime
from typing import Annotated as A
from typing import Sequence, get_args, get_type_hints

import bluesky.plan_stubs as bps
import numpy as np
from nslsii.ad33 import SingleTriggerV33
from nslsii.ophyd_async.providers import NSLS2PathProvider
from ophyd import Component as Cpt
from ophyd import Device
from ophyd.areadetector.base import EpicsSignalWithRBV
from ophyd.areadetector.detectors import AreaDetector
from ophyd.areadetector.filestore_mixins import new_short_uid
from ophyd.areadetector.paths import EpicsPathSignal
from ophyd.areadetector.plugins import (
    ROIPlugin_V34,
    StatsPlugin_V34,
    TimeSeriesPlugin_V34,
)
from ophyd.signal import EpicsSignal, Signal
from ophyd_async.core import (
    AsyncStatus,
    Device,
    PathProvider,
    SignalR,
    SignalRW,
    SignalW,
    SoftSignalBackend,
    StandardReadable,
    StrictEnum,
    UUIDFilenameProvider,
    init_devices,
)
from ophyd_async.core import (
    StandardReadableFormat as Format,
)
from ophyd_async.epics.adcore import (
    NDROIIO,
    ADAcquireLogic,
    ADBaseIO,
    AreaDetector,
    NDPluginBaseIO,
    NDPluginFileIO,
    NDStatsIO,
    PluginSignalDataLogic,
)
from ophyd_async.epics.core import EpicsDevice, PvSuffix

from .utils import _asset_undefined_error, str_to_wav


class PreciseDtypeSignal(Signal):
    def describe(self):
        ret = super().describe()
        ret[self.name].setdefault('dtype_str', str(np.asarray(self.get()).dtype))
        return ret

class Tpx3Files(Device):
    # The other PVs only take affect after this is set
    set_settings = Cpt(EpicsSignal, "WriteData", kind="omitted")

    raw_filepath = Cpt(
        EpicsPathSignal,
        "RawFilePath",
        string=True,
        kind="config",
        path_semantics="posix",
    )
    raw_filepath2 = Cpt(EpicsSignal,"Raw1FilePath")

    raw_file_template = Cpt(
        EpicsSignalWithRBV, "RawFileTemplate", string=True, kind="config"
    )
    raw_write_enable = Cpt(EpicsSignalWithRBV, "WriteRaw", string=True, kind="omitted", put_complete=True)
    raw_write_enable2 = Cpt(EpicsSignalWithRBV, "WriteRaw1", string=True, kind="omitted", put_complete=True)

    img_filepath = Cpt(EpicsSignalWithRBV, "ImgFilePath", kind="config")
    img_file_template = Cpt(EpicsSignalWithRBV, "ImgFileTemplate", kind="config")
    img_write_enable = Cpt(EpicsSignalWithRBV, "WriteImg", kind="omitted")

    prv_filepath = Cpt(EpicsSignal, "PrvImgFilePath", kind="config")
    prv_file_template = Cpt(EpicsSignal, "PrvImgFileTemplate", kind="config")

    prv1_filepath = Cpt(EpicsSignal, "PrvImg1FilePath", kind="config")

    # HACK UNTIL WE GET HANDLERS SET UP
    raw_filepaths = Cpt(PreciseDtypeSignal, kind="normal")

    def __init__(self, *args, **kwargs):
        self.sequence_id_offset = 1
        # This is changed for when a datum is a slice
        # also used by ophyd
        self.filestore_spec = "TPX3_RAW"
        self.streaming = False
        self.frame_num = None
        self.assets_path = _asset_undefined_error
        super().__init__(*args, **kwargs)
        self._datum_kwargs_map = {}  # store kwargs for each uid
        self._n = 0

        self.stage_sigs['img_write_enable'] = 'false'

    def stage(self):
        # TODO also do the images
        
        self._res_uid = res_uid = new_short_uid()
        write_path_template = "file:" + self.assets_path() + f"{self.parent.assets_name}/%Y/%m/%d/"
        self._write_path = write_path = datetime.now().strftime(write_path_template)
        self.raw_filepath.set(write_path).wait()

        # TODO check what the % formatting means to the server
        self.raw_file_template.set(f"{res_uid}_0").wait()

        # because we need to flush setting to actual server from IOC
        self.raw_write_enable.set(1).wait()
        if self.streaming:
            self.raw_filepath2.set(str_to_wav("tcp://connect@localhost:8088")).wait()
            self.raw_write_enable2.set(1).wait()
        self.set_settings.set(1).wait()
        self.set_settings.set(1).wait()

        # fill in first guess, this ill increment self._n but we really do not want to!
        self.update_file_template()
        # reset this back to 0!  
        self._n = 0
        
        super().stage()

    def update_file_template(self):
        # The server generates files with in a trigger that are formatted as
        # filepath/template{datetime only}_{j:d6}.tpx3
        # however the counting is only within the trigger and because we want to be able to predict the file names we can not
        # rely on the date formatting, this we need to set this template on every trigger

        # TODO check what the % formatting means to the server
        self.raw_file_template.set(f"{self._res_uid}_{self._n:05d}_").wait()
        # because we need to flush setting to actual server from IOC
        self.set_settings.set(1).wait()

        filenames = [f'{self._write_path}{self._res_uid}_{self._n:05d}_{j:06d}.tpx3' for j in range(self.parent.cam.num_images.get())]
        self._n += 1
        self.raw_filepaths.set(filenames).wait()

    def unstage(self) -> list[object]:
        # TODO reset these to their original values rather than junk
        self.raw_filepath.set('file:/media/nvme/raw/').wait()
        self.raw_file_template.set("garbage").wait()
        self.raw_write_enable.set(0).wait()
        if self.streaming:
            self.raw_write_enable2.set(0).wait()
        # because we need to flush setting to actual server from IOC
        self.set_settings.set(1).wait()
        return super().unstage()


class Tpx3HDF(Device):
    # Use the HDF5 plugin directory creation feature to avoid having to
    # create directory creation logic for TPX FW explicitly.
    hdf5_file_path = Cpt(EpicsSignalWithRBV, "FilePath", kind="omitted")
    hdf5_create_directory = Cpt(EpicsSignalWithRBV, "CreateDirectory", kind="omitted")
    
    def __init__(self, *args, **kwargs):
        self.assets_path = _asset_undefined_error
        super().__init__(*args, **kwargs)

    def stage(self):
         self.hdf5_create_directory.set(-4)
         write_path_template = self.assets_path() + f"{self.parent.assets_name}/%Y/%m/%d/"
         write_path = datetime.now().strftime(write_path_template)
         self.hdf5_file_path.put(write_path)


class TimePixDetector(SingleTriggerV33, AreaDetector):
    _default_configuration_attrs = None
    _default_read_attrs = None

    hdf_plugin = Cpt(Tpx3HDF, "HDF1:")

    files = Cpt(Tpx3Files, "cam1:")
    
    stats1 = Cpt(StatsPlugin_V34, "Stats1:")
    stats2 = Cpt(StatsPlugin_V34, "Stats2:")
    stats3 = Cpt(StatsPlugin_V34, "Stats3:")
    stats4 = Cpt(StatsPlugin_V34, "Stats4:")

    roi1 = Cpt(ROIPlugin_V34, "ROI1:")
    roi2 = Cpt(ROIPlugin_V34, "ROI2:")
    roi3 = Cpt(ROIPlugin_V34, "ROI3:")
    roi4 = Cpt(ROIPlugin_V34, "ROI4:")

    ts1 = Cpt(TimeSeriesPlugin_V34, "Stats1:TS:")
    ts2 = Cpt(TimeSeriesPlugin_V34, "Stats2:TS:")
    ts3 = Cpt(TimeSeriesPlugin_V34, "Stats3:TS:")
    ts4 = Cpt(TimeSeriesPlugin_V34, "Stats4:TS:")

    def __init__(self, *args,path_provider:Callable[[],str], **kwargs):
        self.assets_name = kwargs.pop("assets_name", "timepix")
        self.assets_path = path_provider
        streaming = kwargs.pop("streaming",False)

        super().__init__(*args, **kwargs)

        self.files.streaming = streaming
        self.files.assets_path = path_provider
        self.hdf_plugin.assets_path = path_provider

        for j in range(1, 5):
            stat = getattr(self, f'stats{j}')
            stat.kind = 'normal'
            stat.total.kind = 'hinted'
            stat.ts_total.kind = 'normal'

    @property
    def streaming(self):
        return self.files.streaming

    @streaming.setter
    def streaming(self,active:bool):
        self.files.streaming = active

    def trigger(self):
        self.files.update_file_template()
        for j in range(1, 5):
            getattr(self, f'ts{j}').ts_acquire.set(1).wait()    
        return super().trigger()
    
    def set_num_images(self, n):
        yield from bps.mv(
            self.cam.num_images, n, 
            self.ts1.ts_num_points, n,
            self.ts2.ts_num_points, n,
            self.ts3.ts_num_points, n,
            self.ts4.ts_num_points, n)
        
    def set_total_exposure(self, exp, *, max_exposure=10):
        num_frames = 1 + exp // max_exposure
        real_exp = exp / num_frames
        period = real_exp + .1

        yield from bps.mv(self.cam.acquire_period, period)
        yield from bps.mv(self.cam.acquire_time, real_exp)
        yield from self.set_num_images(num_frames)      





def gather_config_signals(device: Device) -> Sequence[SignalR]:
    config_signals: list[SignalR] = []
    annotations = get_type_hints(type(device), include_extras=True)

    for attr_name, child in device.children():
        annotation = annotations.get(attr_name)
        metadata = get_args(annotation)

        if isinstance(child, SignalR):
            if Format.CONFIG_SIGNAL in metadata:
                config_signals.append(child)
        else:
            config_signals.extend(gather_config_signals(child))

    return config_signals


class ChainMode(StrictEnum):
    NONE = "NONE"
    LEADER = "LEADER"
    FOLLOWER = "FOLLOWER"


class Polarity(StrictEnum):
    POSITIVE = "Positive"
    NEGATIVE = "Negative"


class TDC(StrictEnum):
    P0123 = "P0123"
    N0123 = "N0123"
    PNO123 = "PN0123"
    P0 = "P0"
    N0 = "N0"
    PN0 = "PN0"


class Orientation(StrictEnum):
    UP = "UP"
    RIGHT = "RIGHT"
    DOWN = "DOWN"
    LEFT = "LEFT"
    UP_MIRRORED = "UP_MIRRORED"
    RIGHT_MIRRORED = "RIGHT_MIRRORED"
    DOWN_MIRRORED = "DOWN_MIRRORED"
    LEFT_MIRRORED = "LEFT_MIRRORED"


class FilePathsSignal(SignalRW[Sequence[str]]):
    def __init__(self, name: str = ""):
        super().__init__(
            SoftSignalBackend(Sequence[str]),
            name=name,
        )

    async def describe(self):
        datakeys = await super().describe()
        ret_dict = await self.read()
        for val in ret_dict.values():
            if isinstance(val, dict) and 'value' in val:
                datakeys[self.name]["dtype_numpy"] = str(np.asarray(val['value']).dtype)

        return datakeys


class Tpx3AcquireLogic(ADAcquireLogic):

    def __init__(self, driver, *args, **kwargs):
        self.driver = driver
        super().__init__(driver, *args, **kwargs)

    async def start_acquiring(self):
        await self.driver.parent.driver.update_file_template()
        await super().start_acquiring()


class Tpx3ChipIO(EpicsDevice, StandardReadable):
    cp_pll: A[SignalR[int], PvSuffix("CP_PLL_RBV"), Format.CONFIG_SIGNAL]
    s1_off: A[SignalR[int], PvSuffix("S1_OFF_RBV"), Format.CONFIG_SIGNAL]
    s1_on: A[SignalR[int], PvSuffix("S1_ON_RBV"), Format.CONFIG_SIGNAL]
    s2_off: A[SignalR[int], PvSuffix("S2_OFF_RBV"), Format.CONFIG_SIGNAL]
    s2_on: A[SignalR[int], PvSuffix("S2_ON_RBV"), Format.CONFIG_SIGNAL]
    ikrum: A[SignalRW[int], PvSuffix("Ikrum_RBV"), Format.CONFIG_SIGNAL]
    pixel_dac: A[SignalR[int], PvSuffix("PixelDAC_RBV"), Format.CONFIG_SIGNAL]
    preamp_off: A[SignalR[int], PvSuffix("Preamp_OFF_RBV"), Format.CONFIG_SIGNAL]
    preamp_on: A[SignalR[int], PvSuffix("Preamp_ON_RBV"), Format.CONFIG_SIGNAL]
    tp_buffer_in: A[SignalR[int], PvSuffix("TPbufferIn_RBV"), Format.CONFIG_SIGNAL]
    tp_buffer_out: A[SignalR[int], PvSuffix("TPbufferOut_RBV"), Format.CONFIG_SIGNAL]
    pll_vcntrl: A[SignalR[int], PvSuffix("PLL_Vcntrl_RBV"), Format.CONFIG_SIGNAL]
    v_preamp_ncas: A[SignalR[int], PvSuffix("VPreamp_NCAS_RBV"), Format.CONFIG_SIGNAL]
    vtp_coarse: A[SignalR[int], PvSuffix("VTP_coarse_RBV"), Format.CONFIG_SIGNAL]
    vtp_fine: A[SignalR[int], PvSuffix("VTP_fine_RBV"), Format.CONFIG_SIGNAL]
    vfbk: A[SignalR[int], PvSuffix("Vfbk_RBV"), Format.CONFIG_SIGNAL]
    vth_coarse: A[SignalRW[int], PvSuffix.rbv("Vth_coarse"), Format.CONFIG_SIGNAL]
    vth_fine: A[SignalRW[int], PvSuffix.rbv("Vth_fine"), Format.CONFIG_SIGNAL]
    adjust: A[SignalR[int], PvSuffix("Adjust_RBV"), Format.CONFIG_SIGNAL]
    layout: A[SignalR[str], PvSuffix("Layout_RBV"), Format.CONFIG_SIGNAL]
    temp: A[SignalR[int], PvSuffix("Temp_RBV"), Format.CONFIG_SIGNAL]


class Tpx3DriverIO(ADBaseIO, StandardReadable):
    # Detector health
    local_temp: A[SignalR[float], PvSuffix("LocalTemp_RBV"), Format.CONFIG_SIGNAL]
    fpga_temp: A[SignalR[float], PvSuffix("FPGATemp_RBV"), Format.CONFIG_SIGNAL]
    fan1_speed: A[SignalR[float], PvSuffix("Fan1Speed_RBV"), Format.CONFIG_SIGNAL]
    fan2_speed: A[SignalR[float], PvSuffix("Fan2Speed_RBV"), Format.CONFIG_SIGNAL]
    bias_voltage_h: A[SignalR[float], PvSuffix("BiasVoltage_RBV"), Format.CONFIG_SIGNAL]
    humidity: A[SignalR[int], PvSuffix("Humidity_RBV"), Format.CONFIG_SIGNAL]
    chip_temps: A[SignalR[str], PvSuffix("ChipTemps_RBV"), Format.CONFIG_SIGNAL]
    vdd: A[SignalR[str], PvSuffix("VDD_RBV"), Format.CONFIG_SIGNAL]
    avdd: A[SignalR[str], PvSuffix("AVDD_RBV"), Format.CONFIG_SIGNAL]

    # Detector config
    fan1_pwm: A[SignalR[int], PvSuffix("Fan1PWM_RBV"), Format.CONFIG_SIGNAL]
    fan2_pwm: A[SignalR[int], PvSuffix("Fan2PWM_RBV"), Format.CONFIG_SIGNAL]
    bias_voltage: A[SignalRW[int], PvSuffix.rbv("BiasVolt"), Format.CONFIG_SIGNAL]
    bias_enable: A[SignalRW[bool], PvSuffix.rbv("BiasEnbl"), Format.CONFIG_SIGNAL]
    chain_mode: A[SignalRW[ChainMode], PvSuffix.rbv("ChainMode"), Format.CONFIG_SIGNAL]
    polarity: A[SignalRW[Polarity], PvSuffix.rbv("Polarity"), Format.CONFIG_SIGNAL]
    trigger_modec: A[SignalR[str], PvSuffix("TriggerModeC_RBV"), Format.CONFIG_SIGNAL]
    exposure_time: A[SignalR[float], PvSuffix("ExposureTime_RBV"), Format.CONFIG_SIGNAL]
    trigger_period: A[SignalR[float], PvSuffix("TriggerPeriod_RBV"), Format.CONFIG_SIGNAL]
    nTriggers: A[SignalR[int], PvSuffix("nTriggers_RBV"), Format.CONFIG_SIGNAL]
    periph_clk80: A[SignalRW[bool], PvSuffix("PeriphClk80"), Format.CONFIG_SIGNAL]
    trigger_delay: A[SignalRW[float], PvSuffix("TriggerDelay"), Format.CONFIG_SIGNAL]
    tdc: A[SignalR[str], PvSuffix("Tdc_RBV"), Format.CONFIG_SIGNAL]
    tdc_port0: A[SignalRW[TDC], PvSuffix.rbv("Tdc0"), Format.CONFIG_SIGNAL]
    tdc_port1: A[SignalRW[TDC], PvSuffix.rbv("Tdc1"), Format.CONFIG_SIGNAL]
    global_timestamp_intvl: A[SignalRW[float], PvSuffix.rbv("GlblTimestampIntvl"), Format.CONFIG_SIGNAL]
    ref_clock: A[SignalRW[bool], PvSuffix.rbv("RefClock"), Format.CONFIG_SIGNAL]
    # log_level: A[SignalRW[int], PvSuffix.rbv("LogLevel"), Format.CONFIG_SIGNAL]
    det_orientation: A[SignalRW[Orientation], PvSuffix.rbv("DetOrient"), Format.CONFIG_SIGNAL]

    # Detector chip config
    chip0: A[Tpx3ChipIO, PvSuffix("CHIP0_")]
    chip1: A[Tpx3ChipIO, PvSuffix("CHIP1_")]
    chip2: A[Tpx3ChipIO, PvSuffix("CHIP2_")]
    chip3: A[Tpx3ChipIO, PvSuffix("CHIP3_")]

    # BPC/DACS file config
    bpc_filepath: A[SignalRW[str], PvSuffix.rbv("BPCFilePath"), Format.CONFIG_SIGNAL]
    bpc_filename: A[SignalRW[str], PvSuffix.rbv("BPCFileName"), Format.CONFIG_SIGNAL]
    bpc_filepath_exists: A[SignalR[bool], PvSuffix("BPCFilePathExists_RBV"), Format.CONFIG_SIGNAL]
    bpc_write_file: A[SignalRW[bool], PvSuffix("WriteBPCFile")]

    dacs_filepath: A[SignalRW[str], PvSuffix.rbv("DACSFilePath"), Format.CONFIG_SIGNAL]
    dacs_filename: A[SignalRW[str], PvSuffix.rbv("DACSFileName"), Format.CONFIG_SIGNAL]
    dacs_filepath_exists: A[SignalR[bool], PvSuffix("DACSFilePathExists_RBV"), Format.CONFIG_SIGNAL]
    dacs_write_file: A[SignalRW[bool], PvSuffix("WriteDACSFile")]

    write_file_msg: A[SignalR[str], PvSuffix("WriteFileMessage")]

    # Filepath logic
    set_settings: A[SignalW[bool], PvSuffix("WriteData")]

    raw_filepath: A[SignalRW[str], PvSuffix.rbv("RawFilePath"), Format.CONFIG_SIGNAL]
    raw_file_template: A[SignalRW[str], PvSuffix.rbv("RawFileTemplate"), Format.CONFIG_SIGNAL]
    raw_write_enable: A[SignalRW[bool], PvSuffix.rbv("WriteRaw")]

    img_filepath: A[SignalRW[str], PvSuffix.rbv("ImgFilePath"), Format.CONFIG_SIGNAL]
    img_file_template: A[SignalRW[str], PvSuffix.rbv("ImgFileTemplate"), Format.CONFIG_SIGNAL]
    img_write_enable: A[SignalRW[bool], PvSuffix.rbv("WriteImg")]

    prv_filepath: A[SignalRW[str], PvSuffix.rbv("PrvImgFilePath"), Format.CONFIG_SIGNAL]
    prv_file_template: A[SignalRW[str], PvSuffix.rbv("PrvImgFileTemplate"), Format.CONFIG_SIGNAL]

    prv1_filepath: A[SignalRW[str], PvSuffix.rbv("PrvImg1FilePath"), Format.CONFIG_SIGNAL]

    async def init_file_writing(self) -> None:
        """Initialize filepaths on Serval through IOC and create directory on NFS"""
        self._write_path = str(self._path_provider(self._det_name).directory_path)

        # create directory in NFS
        await self.parent.hdf1.create_directory.set(-4)
        await self.parent.hdf1.file_path.set(self._write_path)


        # set directory/filename in Serval
        self._res_uid = str('-'.join(self._uu().split("-")[:-1]))
        await self.raw_filepath.set("file:" + self._write_path)
        # await self.raw_file_template.set(f"{self._res_uid}_0") # TODO i don't think we need this, gets called in trigger

        await self.raw_write_enable.set(True)
        await self.set_settings.set(True)

        # await self.update_file_template() # TODO shouldn't need this, it gets called on trigger
        self._n = 0

    async def uninit_file_writing(self) -> None:
        """Uninitialize filepaths on Serval through IOC"""
        await self.raw_filepath.set('file:placeholder')
        await self.raw_file_template.set(f"add_bacon_to_{"shopping_list"}")
        await self.raw_write_enable.set(False)
        await self.set_settings.set(True)

    async def update_file_template(self) -> None:
        # set file template on Serval, will be <uid>_<n>_<serval_counter>.tpx3
        await self.raw_file_template.set(f"{self._res_uid}_{self._n:05d}_")
        await self.set_settings.set(True)

        # predict what the future filepaths will be
        num_images = await self.num_images.get_value()
        filenames = [f'{"file:" + self._write_path}/{self._res_uid}_{self._n:05d}_{j:06d}.tpx3' for j in range(num_images)] # TODO pretty sure we can remove 'file:' here
        await self.raw_filepaths.set(filenames)

        self._n += 1

    def __init__(self, prefix: str, path_provider: PathProvider, det_name: str, *args, **kwargs):
        self._path_provider = path_provider
        self._det_name = det_name
        self._uu = UUIDFilenameProvider()
        # soft signal that stores the predicted filepaths when staged
        with self.add_children_as_readables(Format.UNCACHED_SIGNAL):
            self.raw_filepaths = FilePathsSignal()

        super().__init__(prefix, *args, **kwargs)
  
        self._n = 0


class Tpx3Detector(AreaDetector[Tpx3DriverIO]):

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        driver_suffix: str = "cam1:",
        name: str = "",
        *args,
        **kwargs
    ):
        assets_name = kwargs.pop("assets_name", "timepix")
        driver = Tpx3DriverIO(prefix + driver_suffix, path_provider, assets_name)
        _acquire_logic = Tpx3AcquireLogic(driver)

        plugins: dict[str, NDPluginBaseIO] = {
            "stats1": NDStatsIO(prefix=prefix + 'Stats1:', name="stats1"),
            "stats2": NDStatsIO(prefix=prefix + 'Stats2:', name="stats2"),
            "stats3": NDStatsIO(prefix=prefix + 'Stats3:', name="stats3"),
            "stats4": NDStatsIO(prefix=prefix + 'Stats4:', name="stats4"),
            "roi1": NDROIIO(prefix=prefix + 'ROI1:', name="roi1"),
            "roi2": NDROIIO(prefix=prefix + 'ROI2:', name="roi2"),
            "roi3": NDROIIO(prefix=prefix + 'ROI3:', name="roi3"),
            "roi4": NDROIIO(prefix=prefix + 'ROI4:', name="roi4"),
            "hdf1": NDPluginFileIO(prefix=prefix + 'HDF1:', name="hdf1")
        }

        super().__init__(
            prefix=prefix,
            driver=driver,
            name=name,
            plugins=plugins,
            acquire_logic=_acquire_logic,
            *args,
            **kwargs
        )

        # rename the raw_filepaths signal to match ophyd sync
        self.driver.raw_filepaths.set_name("files_raw_filepaths")

        # gather and add all config signals
        self.add_config_signals(*gather_config_signals(self))

        # register plugin signals
        for j in range(1, 5):
            stat = getattr(self, f"stats{j}")
            self.add_detector_logics(
                PluginSignalDataLogic(
                    driver=self.driver,
                    signal=stat.total,
                    hinted=True
                )
            )

        self.add_detector_logics(
            PluginSignalDataLogic(
                driver=self.driver,
                signal=self.driver.raw_filepaths,
                hinted=False,
            )
        )

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await self.driver.init_file_writing()

        await super().stage()

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await self.driver.uninit_file_writing()
        await super().unstage()
