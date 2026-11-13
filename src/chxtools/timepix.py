"""Helpful loader functions for timepix data"""

from pathlib import Path

import dask.dataframe as dd
import numpy as np
from scipy.sparse import coo_array as sparse
from tifffile import imwrite

_proposal_root_dir = Path("/nsls2/data/chx/proposals")


def load_from_scan(run, processed_override="Compressed_Data"):
    """
    this does some fuzzy search to find the processed parquet files associated with the current tiled run container
    """
    if "primary" not in run:
        raise ValueError("primary data stream not present")

    start = run.start
    cycle = start["cycle"]
    proposal = start["proposal"]["proposal_id"]

    if not any("timepix" in det for det in run.start["detectors"]):
        raise ValueError("the timepix detector was not listed in this run")
    device = next(det for det in start["detectors"] if "timepix" in det)

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
    source: Path | str, base: Path | None = None, processed_loc: str = "Compressed_Data"
):
    """given the source file and a lowest root directory to search in, looks for the associated processed files"""
    source = Path(source)
    hash = source.stem.split("-")[0]
    if not base:
        base_ind = source.parts.index("assets")
        base = Path(*hash[:base_ind])
    narrow = base / processed_loc
    schema = f"{hash}*_cent.parquet"

    flist = list(narrow.rglob(schema))  # first guess
    if not any(flist):
        flist = list(base.rglob(schema))
        if not any(flist):
            raise FileNotFoundError(
                "files not found in even base directory, perhaps files are routed elsewhere"
            )
        print(f"found files of prototype {base / schema}")
    else:
        print(f"found files of prototype {narrow / schema}")
    return flist


def gen_images_from_dataset(
    dataset: dd.DataFrame,
    dt: float,
    output_path: str | Path,
    prefix: str,
    sparsity: int = 0,
):
    """
    A function for transforming timepicx parquet files into images.

    Given a dataframe bins the events into images and can store them sparsely or as pure tiff.
    a negative dt is treated as wanting a single bin histogram (may be extended to how many frames for the set to be binned into),
    stable convention will be -1.

    Parameters
    ----------
    dataset: dd.DataFrame| pd.DataFrame
        the dataset to convert to images
    dt: float
        the time interval to chunk in. in units of secound, -1 for single histogram
    output_path: str | Path
        the folder to pipe values into
    prefix: str
        the name of the dataset in the saved files
    sparsity: int
        a metric for if tiff file or resectioned parquet files will be made (this is a future endeavor to load sparse from tiff)
    """
    if not ({"t", "xc", "yc"} <= set(dataset.columns)):
        raise ValueError("necesary columns ['t','xc','yc'] are not present")

    output_path = Path(output_path)
    dataset["xi"] = dataset.xc.round().astype("int16")
    dataset["yi"] = dataset.yc.round().astype("int16")

    if dt < 0:
        print("saving single histogram of full time domain")
        dense = dataset.groupby(["xi", "yi"]).size().rename("n").reset_index().compute()
        hist = sparse((dense.n, (dense.xi, dense.yi)), shape=(514, 514)).todense()
        imwrite(output_path / f"{prefix}_full.tiff", hist)
        return

    dt = dt * 1e9  # convert from secs to ns
    nsections = (dataset.t.max() - dataset.t.min()).compute() // dt
    print(f"sequence is roughly {nsections} long")
    # volume = nsections*512*512
    if nsections > 5000:
        if (
            nsections > 10000
            and not sparsity
            and input("this will make an image set > 20gb, proceed? (y/n)")
            not in ("y", "yes")
        ):
            return
        print(
            "warning: this is a large dataset and may take some time. Consider using sparsity if not already"
        )

    dataset["t_d"] = ((dataset.t - dataset.t.min()) // dt).astype("uint32")
    count = dataset.groupby(["t_d", "yi", "xi"]).size().rename("n").reset_index()

    def save_to_file(df):
        if df.empty:
            return df
        print(df.name, end="\t")
        name = f"{prefix}_{df.name}"
        if sparsity > 0:
            df.to_parquet(output_path / f"{name}.parquet")
        else:
            im = sparse((df.n, (df.xi, df.yi)), shape=(514, 514)).todense()
            imwrite(output_path / f"{name}.tiff", im)
        return df.iloc[0:0]

    print("starting save ...", end="")
    if sparsity > 0:
        count.groupby(count.t_d // sparsity).apply(save_to_file).compute()
    else:
        count.groupby(["t_d"]).apply(save_to_file).compute()
    print("done")
