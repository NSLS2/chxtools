"""Data models supporting validation of CHX run metadata."""
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Proposal(BaseModel):
    """NSLS2 proposal specific metadata."""

    proposal_id: str
    title: str
    type: str
    pi_name: str


class Versions(BaseModel):
    """Bluesky ecosystem versioning metadata."""

    ophyd: str | None = None
    ophyd_async: str | None = None
    bluesky: str | None = None
    event_model: str | None = None


class BeamPosition(BaseModel):
    """Dictionary used to describe the beam position of active detectors."""

    beam_center_x: float
    beam_center_y: float
    det_x: float
    det_y: float


class BlueskyRun(BaseModel):
    """Standard metadata expected in a CHX bluesky run."""

    beamline_id: str
    owner: str
    cycle: str
    data_session: str
    user: str
    username: str
    user_group: list[str]
    proposal: Proposal
    tiled_access_tags: list[str]

    time: float
    start_datetime: str
    uid: str
    scan_id: int
    plan_name: str
    plan_type: str

    detectors: list[str] | None = None
    motors: list[str] | None = None
    versions: Versions | None = None
    auto_pipeline: str | None = None


class XPCS_WAXS_2026(BaseModel):  # noqa: N801
    """Base XPCS pipeline required metadata."""

    model_config = ConfigDict(populate_by_name=True)

    beam_position_dict: dict[str, BeamPosition]
    auto_pipeline: Literal["XPCS_WAXS_2026_auto"]
    sample: str
    oav_resolution_um_pixel: float | str = Field(
        alias="OAV_resolution [um_pixel]",
        union_mode="left_to_right",
    )


class XPCS(XPCS_WAXS_2026):
    """Extended XPCS pipeline required metadata."""

    model_config = ConfigDict(populate_by_name=True)

    auto_pipeline: Literal["XPCS_auto"]  # type: ignore
    scat_geometry: str

    xpcs_data: bool = Field(validation_alias=AliasChoices("XPCS_data_", "XPCS_data"))
    exposure_time: float = Field(validation_alias=AliasChoices("exposure time_", "exposure time"))
    acquire_period: float = Field(validation_alias=AliasChoices("acquire period_", "acquire period"))
    shutter_mode: str = Field(validation_alias=AliasChoices("shutter mode_", "shutter mode"))
    number_of_images: int = Field(validation_alias=AliasChoices("number of images_", "number of images"))
    data_path: str = Field(validation_alias=AliasChoices("data path_", "data path"))
    sequence_id: int = Field(validation_alias=AliasChoices("sequence id_", "sequence id"))
    auto_trigger: bool = Field(validation_alias=AliasChoices("auto_trigger_", "auto_trigger"))
    transmission: float = Field(validation_alias=AliasChoices("transmission_", "transmission"))
    oav_mode: str = Field(validation_alias=AliasChoices("OAV_mode_", "OAV_mode"))
    t_yoke: float = Field(validation_alias=AliasChoices("T_yoke_", "T_yoke"))
    t_sample: float = Field(validation_alias=AliasChoices("T_sample_", "T_sample"))
    t_sample_stinger: float = Field(validation_alias=AliasChoices("T_sample_stinger_", "T_sample_stinger"))
    analysis: str = Field(validation_alias=AliasChoices("analysis_", "analysis"))
    feedback_x: str = Field(validation_alias=AliasChoices("feedback_x_", "feedback_x"))
    feedback_y: str = Field(validation_alias=AliasChoices("feedback_y_", "feedback_y"))
    measurement: str = Field(alias="Measurement")
