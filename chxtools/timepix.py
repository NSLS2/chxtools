from pathlib import Path

import dask.DataFrame as dd
import numpy as np
from bluesky_tiled_plugins.clients.catalog_of_bluesky_runs import (
    CatalogOfBlueskyRuns as Catalog,
)
from tiled.client.container import Container

_proposal_root_dir = Path("/nsls2/data/chx/proposals")


def load_from_scan(run, processed_override="Compressed_Data"):
    if "primary" not in run:
        raise ValueError("primary data stream not present")
    start = run.start
    cycle = start["cycle"]
    proposal = start["proposal"]["proposal_id"]

    if not any("timepix" in det for det in run.start["detectors"]):
        raise ValueError("the timepix detector was not listed in this run")
    device = next([det for det in start["detectors"] if "timepix" in det])

    proposal_path = _proposal_root_dir / cycle / f"pass-{proposal!s}"
    narrow = proposal_path / processed_override / device
    if not narrow.exists():
        narrow = proposal_path / "assets" / device

    data = run["primary/data"]
    for channel_name in data:
        tpx = any(alias in channel_name for alias in ("timepix", "tpx", "timpix"))
        file = "file" in channel_name
        if tpx and file:
            # yeah this is most likely the correct file stream
            dataset = data[channel_name].read()
            if not isinstance(dataset, np.ndarray):
                dataset = dataset.compute()
            return [
                dd.read_parquet(
                    find_from_source(fileset[0], proposal_path, processed_override)
                )
                for fileset in dataset
            ]


def find_from_source(
    source, base: Path | None = None, processed_loc: str = "Compressed_Data"
):
    hash = Path(source).stem.split("-")[0]
    if not base:
        base_ind = hash.parts.index("assets")
        base = Path(*hash[:base_ind])
    narrow = base / processed_loc
    schema = f"{hash}*_cent.parquet"

    flist = list(narrow.rglob(schema))  # first guess
    if len(flist) < 1:
        flist = list(base.rglob(schema))
    return flist


def gen_images_from_dataset(dataset,dt,output_path:Path,sparse=False):
    if not (set('t','xc','yc')<= set(dataset.columns)):
        raise ValueError("necesary columns ['t','xc','yc'] are not present")
    nsections = (dataset.t.max()-dataset.t.min()).compute()/dt
    print(f"sequence is roughly {nsections} long")
    # volume = nsections*512*512
    if nsections> 5000:
        if (nsections > 10000 and not sparse 
            and input("this will mak an image set > 20gb, proceed? (y/n)") not in ('y','yes')):
            return
        print(f"warning: this is a large dataset and may take some time{" consider using sparse" if not sparse else ""}")



    dataset["t_d"] = dataset.t//dt
    dataset['xi'] = dataset.xc.round().astype('int16')
    dataset['yi'] = dataset.yc.round().astype('int16')
    count = (
        dataset.groupby(["t_d", "yi", "xi"])
        .size()
        .rename("n")
        .reset_index()
        .persist()
    )
    
    print()

