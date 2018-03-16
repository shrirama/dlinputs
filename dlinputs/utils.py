# Copyright (c) 2017 NVIDIA CORPORATION. All rights reserved.
# See the LICENSE file for licensing terms (BSD-style).

import functools as ft
import re
import StringIO

import numpy as np
import PIL

def print_sample(sample):
    """Pretty print a standard sample.

    :param dict sample: key value pairs used for training

    """
    for k in sorted(sample.keys()):
        v = sample[k]
        print k,
        if isinstance(v, np.ndarray):
            print v.dtype, v.shape
        elif isinstance(v, (str, unicode)):
            print repr(v)[:60]
        elif isinstance(v, (int, float)):
            print v
        elif isinstance(v, buffer):
            print type(v), len(v)
        else:
            print type(v), repr(v)[:60]

def make_gray(image):
    """Converts any image to a grayscale image by averaging.

    Knows about alpha channels etc.

    :param image: rank 2 or 3 ndarray
    :returns: rank 2 ndarray

    """
    if image.ndim == 2:
        return image
    assert image.ndim == 3
    assert image.shape[2] in [1, 3, 4]
    return np.mean(image[:, :, :3], 2)


def make_rgb(image):
    """Converts any image to an RGB image.

    Knows about alpha channels etc.

    :param image: rank 2 or 3 ndarray
    :returns: rank 3 ndarray of shape :,:,3

    """
    if image.ndim == 2:
        image = image.reshape(image.shape + (1,))
    assert image.ndim == 3
    if image.shape[2] == 1:
        return np.repeat(image, 3, 2)
    elif image.shape[2] == 3:
        return image
    elif image.shape[2] == 4:
        return image[:, :, :3]


def make_rgba(image, alpha=255):
    """Converts any image to an RGBA image.

    Knows about alpha channels etc.

    :param image: rank 2 or 3 ndarray
    :param alpha: default alpha value
    :returns: rank 3 ndarray with shape :,:,4

    """
    if image.ndim == 2:
        image = image.reshape(image.shape + (1,))
    assert image.ndim == 3
    if image.shape[2] == 1:
        result = np.repeat(image, 4, 2)
        result[:, :, 3] = alpha
        return result
    elif image.shape[2] == 3:
        h, w, _ = image.shape
        result = np.zeros((h, w, 4), 'uint8')
        result[:, :, :3] = image
        result[:, :, 3] = alpha
        return result
    elif image.shape[2] == 4:
        return image

def invert_mapping(kvp):
    """Inverts the mapping given by a dictionary.

    :param kvp: mapping to be inverted
    :returns: inverted mapping
    :rtype: dictionary

    """
    return {v: k for k, v in kvp.items()}

def get_string_mapping(kvp):
    """Returns a dictionary mapping strings to strings.

    This can take either a string of the form "name=value:name2=value2"
    or a dictionary containing all string keys and values.

    :param kvp: dictionary or string
    :returns: dictionary

    """
    if kvp is None:
        return {}
    if isinstance(kvp, (str, unicode)):
        return {k: v for k, v in [kv.split("=", 1) for kv in kvp.split(":")]}
    elif isinstance(kvp, dict):
        for k, v in kvp.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
        return kvp
    else:
        raise ValueError("{}: wrong type".format(type(kvp)))


def pilread(stream, color="gray", asfloat=True):
    """Read an image from a stream using PIL.

    :param stream: stream to read the image from
    :param color: "gray", "rgb" or "rgba".
    :param asfloat: return float image instead of uint8 image

    """
    image = PIL.Image.open(stream)
    result = np.array(image, 'uint8')
    if color is None:
        pass
    elif color == "gray":
        result = make_gray(result)
    elif color == "rgb":
        result = make_rgb(result)
    elif color == "rgba":
        result = make_rgba(result)
    else:
        raise ValueError("{}: unknown color space".format(color))
    if asfloat:
        result = result.astype("f") / 255.0
    return result

def pilreads(data, color, asfloat=True):
    """Read an image from a string or buffer using PIL.

    :param data: data to be decoded
    :param color: "gray", "rgb" or "rgba".
    :param asfloat: return float instead of uint8

    """
    assert color is not None
    return pilread(StringIO.StringIO(data), color=color, asfloat=asfloat)


pilgray = ft.partial(pilreads, color="gray")
pilrgb = ft.partial(pilreads, color="rgb")

def pildumps(image, format="PNG"):
    """Compress an image using PIL and return it as a string.

    Can handle float or uint8 images.

    :param image: ndarray representing an image
    :param format: compression format ("PNG" or "JPEG")

    """
    result = StringIO.StringIO()
    if image.dtype in [np.dtype('f'), np.dtype('d')]:
        assert np.amin(image) > -0.001 and np.amax(image) < 1.001
        image = np.clip(image, 0.0, 1.0)
        image = np.array(image * 255.0, 'uint8')
    PIL.Image.fromarray(image).save(result, format=format)
    return result.getvalue()


pilpng = pildumps
piljpg = ft.partial(pildumps, format="JPEG")

def autodecode1(data, tname):
    extension = re.sub(r".*\.", "", tname).lower()
    if extension in ["png", "jpg", "jpeg"]:
        import numpy as np
        data = StringIO.StringIO(data)
        try:
            import imageio
            return np.array(imageio.imread(data, format=extension))
        except:
            pass
        import scipy.misc
        return scipy.misc.imread(data)
    if extension in ["json", "jsn"]:
        import simplejson
        return simplejson.loads(data)
    if extension in ["pyd", "pickle"]:
        import pickle
        return pickle.loads(data)
    if extension in ["mp", "msgpack", "msg"]:
        import msgpack
        return msgpack.unpackb(data)
    return data

def autodecode(sample):
    return {k: autodecode1(v, k) for k, v in sample.items()}

def autoencode1(data, tname):
    extension = re.sub(r".*\.", "", tname).lower()
    if extension in ["png", "jpg", "jpeg"]:
        import imageio
        if isinstance(data, np.ndarray):
            if data.dtype in [np.dtype("f"), np.dtype("d")]:
                assert np.amin(data) >= 0.0, (data.dtype, np.amin(data))
                assert np.amax(data) <= 1.0, (data.dtype, np.amax(data))
                data = np.array(255 * data, dtype='uint8')
            elif data.dtype in [np.dtype("uint8")]:
                pass
            else:
                raise ValueError("{}: unknown image array dtype".format(data.dtype))
        else:
            raise ValueError("{}: unknown image type".format(type(data)))
        stream = StringIO.StringIO()
        imageio.imsave(stream, data, format=extension)
        result = stream.getvalue()
        del stream
        return result
    if extension in ["json", "jsn"]:
        import simplejson
        return simplejson.dumps(data)
    if extension in ["pyd", "pickle"]:
        import pickle
        return pickle.dumps(data)
    if extension in ["mp", "msgpack", "msg"]:
        import msgpack
        return msgpack.packb(data)
    return data

def autoencode(sample):
    return {k: autoencode1(v, k) for k, v in sample.items()}


def samples_to_batch(samples, tensors=True):
    """Take a collection of samples (dictionaries) and create a batch.

    If `tensors` is True, `ndarray` objects are combined into
    tensor batches.

    :param dict samples: list of samples
    :param bool tensors: whether to turn lists of ndarrays into a single ndarray
    :returns: single sample consisting of a batch
    :rtype: dict

    """
    result = {k: [] for k in samples[0].keys()}
    for i in range(len(samples)):
        for k in result.keys():
            result[k].append(samples[i][k])
    if tensors == True:
        tensors = [x for x in result.keys()
                   if isinstance(result[x][0], (np.ndarray, int, float))]
    for k in tensors:
        result[k] = np.array(result[k])
    return result
