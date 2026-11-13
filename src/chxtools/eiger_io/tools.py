import dask.array as da
# some temporary tools
# DO NOT use unless you know what you're doing
def dask_images(header, field):
    ''' temporary tools to collapse events from a header into one big dask
    array. Should eventually be superseded by better subclassing of pims.

    usage (for example):
        uid = 'be6e4c'
        h = db[uid]
        #imgs = list(h.data('eiger4m_single_image'))
        imgs = dask_images(h, 'eiger4m_single_image')
    '''
    arrs = list()
    for elem in header.data(field):
        arrs.append(elem._to_dask())
    return da.stack(arrs)
