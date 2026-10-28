import glob

import dask.DataFrame as dd
from pathlib import Path
from tiled.client.container import Container

class TimePixLoader:
    root_dir = Path("/nsls2/chx/proposals")

    def __init__(self, cycle:str, dpass: int = 316251, device: str = "timepix-1", processed_override = "Compressed_Data"):
        self.path = self.root_dir/ cycle / str(dpass)
        self.device = device
        self.narrow = self.path / processed_override / device
        if not self.narrow.exists():
            self.narrow = self.path/ "assets" / device

    def from_client(self, client, sid: int | None = None):
        run = client
        if not isinstance(client,Container):  #very loose way to check if its one of the special catalogue of bluesky runs
            run = run[sid]
        if 'primary' not in run:
            raise ValueError("primary data stream not present")

        data = run['primary/data']
        for channel_name in data:
            if all(k in channel_name for k in ('timepix','file')):
                #yeah this is most likely the correct file stream
                ...

            # if 'timepix-1-driver-raw_filepaths' not in d:
            #     print(d, 'filepaths not present')
            #     continue

    def from_source_path(path):
        hash = Path(path).stem.split('-')[0]
        return dd.from_parquet