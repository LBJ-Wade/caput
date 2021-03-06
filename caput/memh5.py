"""
Module for making in-memory mockups of h5py objects.

.. currentmodule:: caput.memh5

It is sometimes usefull to have a consistent API for data that is independant
of whether that data lives on disk or in memory. ``h5py`` provides this to a
certain extent, having ``Dataset`` objects that act very much like ``numpy``
arrays. ``memh5`` extends this, providing an in-memory containers, analagous to
``h5py`` ``Group`` and ``Attribute`` objects.


Classes
=======

.. autosummary::
   :toctree: generated/

    ro_dict
    MemGroup
    MemAttrs
    MemDataset


Utility Functions
=================

.. autosummary::
   :toctree: generated/

    attrs2dict
    is_group
    get_h5py_File
    copyattrs
    deep_group_copy

"""


import collections
import warnings

import numpy as np
import h5py


# Classes
# --------------

class ro_dict(collections.Mapping):
    """A dict that is read-only to the user.

    This class isn't strictly read-only but it cannot be modified through the
    traditional dict interface. This prevents the user from mistaking this for
    a normal dictionary.

    Provides the same interface for reading as the builtin python ``dict``s but
    no methods for writing.

    Parameters
    ----------
    d : dict
        Initial data for the new dictionary.

    """
    
    def __init__(self, d=None):
        if not d:
            d = {}
        else:
            d = dict(d)
        self._dict = d

    def __getitem__(self, key):
        return self._dict[key]

    def __len__(self):
        return self._dict.__len__()

    def __iter__(self):
        return self._dict.__iter__()


class MemGroup(ro_dict):
    """In memory implementation of the ``h5py.Group`` class.

    This class doubles as the a ``h5py.File``, object, since the destinction
    between a file and a group for in-memory data is moot.

    Attributes
    ----------
    attrs : MemAttrs

    Methods
    -------
    __getitem__
    from_group
    from_hdf5
    to_hdf5
    create_group
    require_group
    create_dataset

    """

    def __init__(self):
        ro_dict.__init__(self)
        self._attrs = MemAttrs()

    def __getitem__(self, key):
        """Impliment '/' for accessing nested groups."""
        key_parts = key.split('/')
        if len(key_parts) == 1:
            return ro_dict.__getitem__(self, key)
        else:
            # Enter the first level and call __getitem__ recursively.
            return self[key_parts[0]]['/'.join(key_parts[1:])]

    @property
    def attrs(self):
        """Attributes attached to this object.
        
        Returns
        -------
        attrs : MemAttrs
    
        """

        return self._attrs

    @classmethod
    def from_group(cls, group):
        """Create a new instance by deep copying an existing group.

        Agnostic as to whether the group to be copyed is a `MemGroup` or an
        `h5py.Group` (which includes `hdf5.File` objects). 
        
        """

        self = cls()
        deep_group_copy(group, self)
        return self

    @classmethod
    def from_hdf5(cls, f, **kwargs):
        """Create a new instance by copying from an hdf5 group.

        This is the same as `from_group` except that an hdf5 filename is
        accepted.  Any keyword arguments are passed on to the constructor for
        `h5py.File`.
        
        """

        f, to_close = get_h5py_File(f, **kwargs)
        self = cls.from_group(f)
        if to_close:
            f.close()
        return self

    def to_hdf5(self, f, **kwargs):
        """Replicate object on disk in an hdf5 file.
      
        Any keyword arguments are passed on to the constructor for `h5py.File`.
        
        """
        
        f, opened = get_h5py_File(f, **kwargs)
        deep_group_copy(self, f)
        return f

    def create_group(self, key):
        if key in self.keys():
            msg = "Group '%s' already exists." % key
            raise ValueError(msg)
        else:
            out = MemGroup()
            self._dict[key] = out
            return out

    def require_group(self, key):
        if key in self.keys():
            if not isinstance(self[key], MemGroup):
                msg = "Entry '%s' exists and is not a Group." % key
                raise TypeError(msg)
            else:
                return self[key]
        else:
            return self.create_group(key)

    def create_dataset(self, name, shape=None, dtype=None, data=None,
                       **kwargs):
        """Create a new dataset.

        """

        if kwargs:
            msg = ("No extra keyword arguments accepted, this is not an hdf5"
                   " object but a memory object mocked up to look like one.")
            raise TypeError(msg)
            # XXX In future could accept extra arguments and use them if
            # writing to disk.
        if not data is None:
            if shape is None:
                shape = data.shape
            if dtype is None:
                dtype = data.dtype
        # Otherwise shape is required.
        if shape is None:
            raise ValueError('shape must be provided.')
        # Default dtype is float.
        if dtype is None:
            dtype = np.float64
        # Convert to numpy dtype.
        dtype = np.dtype(dtype)
        if (not data is None and shape == data.shape
            and dtype is data.dtype and hasattr(data, 'view')):
            new_dataset = data.view(MemDataset)
        else:
            # Just copy the data.
            new_dataset = np.empty(shape=shape,
                                   dtype=dtype).view(MemDataset)
            if not data is None:
                new_dataset[...] = data[...]
        self._dict[name] = new_dataset
        return new_dataset


class MemAttrs(dict):
    """In memory implementation of the ``h5py.AttributeManager``.

    Currently just a normal dictionary.

    """

    pass


class MemDataset(np.ndarray):
    """In memory implementation of the ``h5py.Dataset`` class.
    
    Numpy array mocked up to look like an hdf5 dataset.  This just allows a
    numpy array to carry around ab `attrs` dictionary as a stand-in for hdf5
    attributes.
    
    Attributes
    ----------
    attrs : MemAttrs

    """
    
    def __array_finalize__(self, obj):
        self._attrs = MemAttrs(getattr(obj, 'attrs', {}))

    @property
    def attrs(self):
        """Attributes attached to this object.
        
        Returns
        -------
        attrs : MemAttrs
    
        """

        return self._attrs

    def resize(self):
        # h5py datasets' reshape() is different from numpy reshape.
        msg = "Dataset reshaping not allowed. Perhapse make an new array view."
        raise NotImplementedError(msg)


# Utilities
# ---------

def attrs2dict(attrs):
    """Safely copy an h5py attributes object to a dictionary."""

    out = {}
    for key, value in attrs.iteritems():
        if isinstance(value, np.ndarray):
            value = value.copy()
        out[key] = value
    return out


def is_group(obj):
    """Check if the object is a Group, which includes File objects.
    
    In most cases, if it isn't a Group it's a Dataset, so this can be used to
    check for Datasets as well.

    """
    
    return hasattr(obj, 'create_group')


def get_h5py_File(f, **kwargs):
    """Checks if input is an `h5py.File` or filename and returns the former.
    
    Parameters
    ----------
    f : h5py Group or filename string
    **kwargs : all keyword arguments
        Passed to `h5py.File` constructor. If `f` is already an open file,
        silently ignores all keywords.

    Returns
    -------
    f : hdf5 group
    opened : bool
        Whether the a file was opened or not (i.e. was already open).

    """
    
    # Figure out if F is a file or a filename, and whether the file should be
    # closed.
    if is_group(f):
        opened = False
        #if kwargs:
        #    msg = "Got some keywork arguments but File is alrady open."
        #    warnings.warn(msg)
    else:
        opened = True
        f = h5py.File(f, **kwargs)
    return f, opened


def copyattrs(a1, a2):
    # Make sure everything is a copy.
    a1 = attrs2dict(a1)
    for key, value in a1.iteritems():
        a2[key] = value


def deep_group_copy(g1, g2):
    """Copy full data tree from one group to another."""
    
    copyattrs(g1.attrs, g2.attrs)
    for key, entry in g1.iteritems():
        if is_group(entry):
            g2.create_group(key)
            deep_group_copy(entry, g2[key])
        else:
            g2.create_dataset(key, shape=entry.shape, dtype=entry.dtype, 
                    data=entry)
            copyattrs(entry.attrs, g2[key].attrs)

