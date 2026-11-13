import h5py
import os
import re
from glob import glob

from pims import FramesSequence, Frame

try:
    # databroker v0.9.0
    from databroker.assets.handlers import HandlerBase
except ImportError:
    raise RuntimeError(
        "legacy runtime is not supported in builtin tools module, "
        "please use eiger_io library directly"
    ) from None
#     # databroker < v0.9.0
#     from filestore.retrieve import HandlerBase


class EigerImages(FramesSequence):
    # the regexp patterns for expected files
    # here it is just file containing "master" but could potentially be
    # expanded upon
    pattern = re.compile('(.*)master.*')

    def __init__(self, master_filepath, images_per_file, md=None):
        # check that 'master' is in file
        m = self.pattern.match(os.path.basename(master_filepath))

        if m is None:
            raise ValueError("This reader expects filenames containing "
                             "the word 'master'. If the file was renamed, "
                             "revert to the original name given by the "
                             "detector.")
        self._md = md
        self.master_filepath = master_filepath
        self.images_per_file = images_per_file
        self._handle = h5py.File(master_filepath, 'r')
        try:
            # Eiger firmware v1.3.0 and onwards
            self._entry = self._handle['entry']['data']
        except KeyError:
            # Older firmwares
            self._entry = self._handle['entry']

    @property
    def md(self):
        return self._md

    @property
    def valid_keys(self):
        valid_keys = [key for key in self._entry.keys() if
                      key.startswith("data")]
        valid_keys.sort()
        return valid_keys

    def get_frame(self, i):
        dataset = self._entry['data_{:06d}'
                              .format(1 + (i // self.images_per_file))]
        img = dataset[i % self.images_per_file]
        return Frame(img, frame_no=i)

    # this uses a trick to check for valid keys before counting
    def __len__(self):
        return sum(self._entry[k].shape[0] for k in self.valid_keys)

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

    def close(self):
        self._handle.close()


class EigerHandler(HandlerBase):
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
    specs = {'AD_EIGER2', 'AD_EIGER'}

    def __init__(self, fpath, images_per_file=None, frame_per_point=None):
        ''' Initializer for Eiger handler.

            Parameters
            ----------
            fpath : str
                the partial file path

            images_per_file : int, optional
                images per file. If not set, must set frame_per_point

            frame_per_point : int, optional. If not set, must set
                images_per_file

            This one is backwards compatible for both versions of resources
            saved in databroker. Old resources used 'frame_per_point' as a
            kwarg. Newer resources call this 'images_per_file'.
        '''
        print("filepath : {}".format(fpath))
        # create pims handler
        self._base_path = fpath
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
            images_per_file = frame_per_point
            print("got frame_per_point")
        else:
            print("got images_per_file")

        self._images_per_file = images_per_file

    def __call__(self, seq_id, frame_num=None):
        '''
            This returns data contained in the file.

            Parameters
            ----------
            seq_id : int
                The sequence id of the data

            frame_num: int or None
                If not None, return the frame_num'th image from this
                3D array. Useful for when an event is one image rather
                than a stack.

            Returns
            -------
                A PIMS FramesSequence of data
        '''
        master_path = '{}_{}_master.h5'.format(self._base_path, seq_id)
        with h5py.File(master_path, 'r') as f:
            md = {k: f[v].value for k, v in self.EIGER_MD_LAYOUT.items()}
        # the pixel mask from the eiger contains:
        # 1  -- gap
        # 2  -- dead
        # 4  -- under-responsive
        # 8  -- over-responsive
        # 16 -- noisy
        pixel_mask = md['pixel_mask']
        # pixel_mask[pixel_mask>0] = 1
        # pixel_mask[pixel_mask==0] = 2
        # pixel_mask[pixel_mask==1] = 0
        # pixel_mask[pixel_mask==2] = 1
        md['binary_mask'] = (pixel_mask == 0)
        md['framerate'] = 1./md['frame_time']
        # TODO Return a multi-dimensional PIMS seq.
        ret = EigerImages(master_path, self._images_per_file, md=md)
        if frame_num is not None:
            ret = ret[frame_num]
        return ret

    def get_file_list(self, datum_kwargs_gen):
        ''' get the file list.

            Receives a list of datum_kwargs for each datum
        '''
        filenames = []
        for dm_kw in datum_kwargs_gen:
            seq_id = dm_kw['seq_id']
            new_filenames = glob(self._base_path + "_" + str(seq_id) + "*")
            filenames.extend(new_filenames)

        return filenames

    def get_file_sizes(self, datum_kwargs_gen):
        '''get the file size

           returns size in bytes
        '''
        sizes = []
        file_name = self.get_file_list(datum_kwargs_gen)
        for file in file_name:
            sizes.append(os.path.getsize(file))

        return sizes
