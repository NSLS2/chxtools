import re
import h5py
import os

import dask.array as da
from pims import FramesSequence, Frame


'''
    The logic is a little convoluted here so here is an explanation:
        - The user should use EigerHanderDask for everything they need
        - There were cases where the user used "EigerImages" with the PIMS version.
            To make this backwards compatible, I had to move code to a separate _load_eiger_images
            function. This is because previously the handler handed a filepath to EigerImages. Currently,
                the handler doesn't do this (it shouldn't need to, the handler should just open the data).
'''

try:
    # databroker v0.9.0
    from databroker.assets.handlers import HandlerBase
except ImportError:
    # databroker < v0.9.0
    from filestore.retrieve import HandlerBase

# wrapper to create a class similar to EigerImages (PIMS version)
def EigerImagesDask(master_path, _images_per_file, md={}):
    # we don't care about _images_per_file, so we ignore it
    # left there (as opposed to *) just to understand the logic
    res, md = _load_eiger_images(master_path)
    return PIMSDask(res, md=md)

class PIMSDask(FramesSequence):
    ''' the dask version of PIMS, takes dask array.

        Notes
        -----
            - this should eventually become a PR into PIMS.
            - this should be upgraded to allow nested FramesSequences
                (need to allow for defining axes etc)
    '''
    def __init__(self, data, md=None):
        '''
            Initialized a lazy loader for EigerImages
            Parameters
            ----------
            data : dask.array.Array
                the data
            md : dict, optional
                the dictionary of metadata
        '''
        self._data = data
        self._md = md

    @property
    def md(self):
        return self._md

    def get_frame(self, i):
        # had to return Frame to be friendly with pims_pipeline operations...
        img = self._data[i].compute()
        return Frame(img, frame_no=i)

    def __len__(self):
        return len(self._data)

    @property
    def frame_shape(self):
        return self[0].shape

    @property
    def pixel_type(self):
        return self[0].dtype

    @property
    def dtype(self):
        return self.pixel_type

    @property
    def shape(self):
        return self.frame_shape

    def _to_dask(self):
        return self._data


# TODO : remove this eventually (this should not be used, metadata should be accessed via metadatastore)
EIGER_MD_LAYOUT = {
    'y_pixel_size': 'entry/instrument/detector/y_pixel_size',
    'x_pixel_size': 'entry/instrument/detector/x_pixel_size',
    'detector_distance': 'entry/instrument/detector/detector_distance',
    'incident_wavelength': 'entry/instrument/beam/incident_wavelength',
    'frame_time': 'entry/instrument/detector/frame_time',
    'beam_center_x': 'entry/instrument/detector/beam_center_x',
    'beam_center_y': 'entry/instrument/detector/beam_center_y',
    'count_time': 'entry/instrument/detector/count_time',
    'pixel_mask': 'entry/instrument/detector/detectorSpecific/pixel_mask',
}
def _load_eiger_images(master_path):
    ''' load images from EIGER data using fpath.

        This separation is made from the handler to allow for some code that unfortunately depended
            on this step. (which used to be in EigerImages)

        master_path : the full filename of the path
    '''
    with h5py.File(master_path, 'r') as f:
        try:
            # Eiger firmware v1.3.0 and onwards
            _entry = f['entry']['data']
        except KeyError:
            _entry = f['entry']          # Older firmwares
    
        # TODO : perhaps remove the metadata eventually
        md = dict()
        md = {k: f[v].value for k, v in EIGER_MD_LAYOUT.items()}
        # the pixel mask from the eiger contains:
        # 1  -- gap
        # 2  -- dead
        # 4  -- under-responsive
        # 8  -- over-responsive
        # 16 -- noisy
        pixel_mask = md['pixel_mask']
        md['binary_mask'] = (pixel_mask == 0)
        md['framerate'] = 1./md['frame_time']
    
        # TODO : Return a multi-dimensional PIMS seq.
        # this is the logic that creates the linked dask array
        elements = list()
        key_names = sorted(list(_entry.keys()))
        for keyname in key_names:
            #print(f"{keyname}")
            val = _entry[keyname]
            elements.append(da.from_array(val, chunks=val.chunks))
    
        res = da.concatenate(elements)

    return res, md


class EigerHandlerDask(HandlerBase):
    specs = {'AD_EIGER2', 'AD_EIGER'}

    def __init__(self, fpath, images_per_file=None, frame_per_point=None):
        if images_per_file is None and frame_per_point is None:
            errormsg = "images_per_file and frame_per_point both set"
            errormsg += "\n This is likely an error."
            errormsg += " Please check your resource"
            errormsg += "\n (tip: use a RawHandler to debug resource output)"
            raise ValueError(errormsg)

        if images_per_file is None:
            # then grab from frame_per_point
            if frame_per_point is None:
                # if both are none, then raise an error
                msg = "Both images_per_file and frame_per_point not set"
                raise ValueError(msg)
            # got frame_per_point
            images_per_file = frame_per_point
        else:
            # go images per file
            pass

        # don't need images_per_file, we can figure it out from hdf5
        # TODO : might need to check valid_keys
        # (some keys may be invalid it seems? Only add if this comes up)
        self.images_per_file = images_per_file
        self._base_path = fpath

    # this is on a per event level
    def __call__(self, seq_id, frame_num=None):
        master_path = '{}_{}_master.h5'.format(self._base_path, seq_id)

        data, md = _load_eiger_images(master_path)
        # PIMS subclass using Dask
        # this gives metadata and also makes the assumption when
        # to run .compute() for dask array
        ret = PIMSDask(data, md=md)
        if frame_num is not None:
            ret = ret[frame_num]
        return ret

    def get_file_list(self, datum_kwargs):
        ''' get the file list.

            Receives a list of datum_kwargs for each datum
        '''
        filenames = []
        for dm_kw in datum_kwargs:
            seq_id = dm_kw['seq_id']
            filename = '{}_{}_master.h5'.format(self._base_path, seq_id)
            filenames.append(filename)

        return filenames
