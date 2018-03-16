# Copyright (c) 2017 NVIDIA CORPORATION. All rights reserved.
# See the LICENSE file for licensing terms (BSD-style).

import math
import random as pyr
import re
import numpy as np
from functools import wraps
import logging
import utils
import improc

def curried(f):
    """A decorator for currying functions in the first argument."""
    @wraps(f)
    def wrapper(*args, **kw):
        def g(x):
            return f(x, *args, **kw)
        return g
    return wrapper

def compose2(f, g):
    return lambda x: f(g(x))

def compose(*args):
    return reduce(compose2, args)

def merge(sources, weights=None):
    """Merge samples from multiple sources into a single iterator.

    :param sources: list of iterators
    :param weights: weights for sampling
    :returns: iterator

    """
    assert weights is None, "weighted sampling not implemented yet"
    while len(sources) > 0:
        index = pyr.randint(0, len(sources)-1)
        try:
            sample = sources[index].next()
            yield sample
        except StopIteration:
            del sources[index]
    raise StopIteration()

def concat(sources, maxepoch=1):
    """Concatenate multiple sources, usually for test sets.

    :param sources: list of iterators
    :param maxepochs: number of epochs (default=1)
    :returns: iterator

    """
    count = 0
    for source in sources:
        for sample in source:
            if maxepoch is not None and "__epoch__" in sample:
                if sample["__epoch__"] >= maxepoch:
                    break
            sample = dict(sample)
            sample["__count__"] = count
            yield sample
            count += 1

@curried
def info(data, every=0):
    """Print info about samples.

    By default only prints the first sample, but with
    `every>0`, prints `every` samples.

    :param data: sample iterator
    :param every: how often to print information
    :returns: iterator

    """
    count = 0
    for sample in data:
        if (count == 0 and every == 0) or (every > 0 and count % every == 0):
            print "# itinfo", count
            utils.print_sample(sample)
        count += 1
        yield sample


@curried
def grep(source, **kw):
    """Select samples from the source that match given patterns.

    Arguments are of the form `fieldname="regex"`.
    If `_not=True`, samples matching the pattern are rejected.

    :param source: iterator
    :param kw: fieldname="regex" entries
    :returns: iterator

    """
    _not = not not kw.get("_not", False)
    if "_not" in kw:
        del kw["_not"]
    for item in source:
        for data in source:
            skip = False
            for k, v in kw.items():
                matching = not not re.search(v, data[k])
                if matching == _not:
                    skip = True
                    break
            if skip:
                continue
            yield data


@curried
def select(source, **kw):
    """Select samples from the source that match given predicates.

    Arguments are of the form `fieldname=predicate`.

    :param source: iterator
    :param kw: fieldname=predicate selectors
    :returns: iterator

    """
    for item in source:
        for data in source:
            skip = False
            for k, f in kw.items():
                matching = not not f(data[k])
                if not matching:
                    skip = True
                    break
            if skip:
                continue
            yield data


@curried
def rename(data, keep_all=False, keep_meta=True, skip_missing=False, **kw):
    """Rename and select fields using new_name="old_name" keyword arguments.

    :param data: iterator
    :param keep_all: keep all fields, even those that haven't been renamed
    :param keep_meta: keep metadata (fields starting with "_")
    :param skip_missing: skip records where not all fields are present
    :param kw: new_name="old_name" rename rules
    :returns: iterator

    """
    assert not keep_all
    for sample in data:
        skip = False
        result = {}
        if keep_meta:
            for k, v in sample.items():
                if k[0]=="_":
                    result[k] = v
        for k, v in kw.items():
            if v not in sample:
                skip = True
                break
            result[k] = sample[v]
        if skip and skip_missing:
            if skip_missing is 1:
                print v, ": missing field; skipping"
                utils.print_sample(sample)
            continue
        yield result

@curried
def copy(data, **kw):
    """Copy fields.

    :param data: iterator
    :param kw: new_value="old_value"
    :returns: iterator

    """
    for sample in data:
        result = {k: v for k, v in sample.items()}
        for k, v in kw.items():
            result[k] = result[v]
        yield result

@curried
def map(data, **keys):
    """Map the fields in each sample using name=function arguments.

    Unmentioned fields are left alone.

    :param data: iterator
    :param keys: name=function pairs, applying function to each sample field
    :returns: iterator

    """
    for sample in data:
        sample = sample.copy()
        for k, f in keys.items():
            try:
                sample[k] = f(sample[k])
            except Exception, e:
                logging.warn("itmap {}".format(repr(e)))
                sample = None
                break
        if sample is not None:
            yield sample

@curried
def transform(data, f=None):
    """Map entire samples using the given function.

    :param data: iterator
    :param f: function from samples to samples
    :returns: iterator over transformed samples

    """

    if f is None: f = lambda x: x
    for sample in data:
        yield f(sample)

###
### Shuffling
###

@curried
def shuffle(data, bufsize=1000, initial=100):
    """Shuffle the data in the stream.

    This uses a buffer of size `bufsize`. Shuffling at
    startup is less random; this is traded off against
    yielding samples quickly.

    :param data: iterator
    :param bufsize: buffer size for shuffling
    :returns: iterator

    """
    assert initial <= bufsize
    buf = []
    startup = True
    for sample in data:
        if len(buf) < bufsize:
            buf.append(data.next())
        k = pyr.randint(0, len(buf) - 1)
        sample, buf[k] = buf[k], sample
        if startup and len(buf) < initial:
            buf.append(sample)
            continue
        startup = False
        yield sample
    for sample in buf:
        yield sample
        
###
### Batching
###

@curried
def batched(data, batchsize=20, tensors=True, partial=True):
    """Create batches of the given size.

    :param data: iterator
    :param batchsize: target batch size
    :param tensors: automatically batch lists of ndarrays into ndarrays
    :param partial: return partial batches
    :returns: iterator

    """
    batch = []
    for sample in data:
        if len(batch) >= batchsize:
            yield utils.samples_to_batch(batch, tensors=tensors)
            batch = []
        batch.append(sample)
    if len(batch) == 0:
        return
    elif len(batch) == batchsize or partial:
        yield utils.samples_to_batch(batch, tensors=tensors)


def maybe_index(v, i):
    """Index if indexable.

    :param v: object to be indexed
    :param i: index
    :returns: v[i] if that succeeds, otherwise v

    """
    try:
        return v[i]
    except:
        return v

@curried
def unbatch(data):
    """Unbatch data.

    :param data: iterator over batches
    :returns: iterator over samples

    """
    for sample in data:
        keys = sample.keys()
        bs = len(sample[keys[0]])
        for i in xrange(bs):
            yield {k: maybe_index(v, i) for k, v in sample.items()}

###
### Image data augmentation
###

@curried
def distort(sample, distortions=[(5.0, 5)], keys=["image"]):
    """Apply distortions to images in sample.

    :param sample
    :param distortions: distortion parameters
    :param keys: fields to distort
    :returns: distorted sample

    """
    images = [sample[k] for k in keys]
    distorted = improc.random_distortions(images, distortions)
    result = dict(sample)
    for k, v in zip(keys, distorted): result[k] = v
    return result

@curried
def standardize(sample, size, keys=["image"], crop=0, mode="nearest",
                  ralpha=None, rscale=((0.8, 1.0), (0.8, 1.0)),
                  rgamma=None, cgamma=(0.8, 1.2)):
    """Standardize images in a sample.

    :param sample: sample
    :param size: target size
    :param keys: keys for images to be distorted
    :param crop: whether to crop
    :param mode: boundary mode
    :param ralpha: random rotation range (no affine if None)
    :param rscale: random scale range
    :param rgamma: random gamma range (no color distortion if None)
    :param cgamma: random color gamma range
    :returns: standardized szmple

    """
    if ralpha is True: ralpha = (-0.2, 0.2)
    if rgamma is True: rgamma = (0.5, 2.0)
    if ralpha is not None:
        affine = improc.random_affine(ralpha=ralpha, rscale=rscale)
    else:
        affine = np.eye(2)
    for key in keys:
        sample[key] = standardize(
            sample[key], size, crop=crop, mode=mode, affine=affine)
    if rgamma is not None:
        for key in keys:
            sample[key] = improc.random_gamma(sample[key],
                                        rgamma=rgamma,
                                        cgamma=cgamma)
    return sample

###
### Specialized input pipelines for OCR, speech, and related tasks.
###

def ld_makeseq(image):
    """Turn an image into an LD sequence.

    :param image: input image
    :returns: LD sequence

    """
    assert isinstance(image, np.ndarray), type(image)
    if image.ndim==3 and image.shape[2]==3:
        image = np.mean(image, 2)
    elif image.ndim==3 and image.shape[2]==1:
        image = image[:,:,0]
    assert image.ndim==2
    return image.T

def seq_makebatch(images, for_target=False):
    """Given a list of LD sequences, make a BLD batch tensor.

    This performs zero padding as necessary.

    :param images: list of images as LD sequences
    :param for_target: require ndim==2, inserts training blank steps.
    :returns: batched image sequences

    """
    assert isinstance(images, list), type(images)
    assert isinstance(images[0], np.ndarray), images
    if images[0].ndim==2:
        l, d = np.amax(np.array([img.shape for img in images], 'i'), axis=0)
        ibatch = np.zeros([len(images), int(l), int(d)])
        if for_target:
            ibatch[:, :, 0] = 1.0
        for i, image in enumerate(images):
            l, d = image.shape
            ibatch[i, :l, :d] = image
        return ibatch
    elif images[0].ndim==3:
        assert not for_target
        h, w, d = np.amax(np.array([img.shape for img in images], 'i'), axis=0)
        ibatch = np.zeros([len(images), h, w, d])
        for i, image in enumerate(images):
            h, w, d = image.shape
            ibatch[i, :h, :w, :d] = image
        return ibatch

def images2seqbatch(images):
    """Given a list of images, return a BLD batch tensor.

    :param images: list of images
    :returns: ndarray representing batch

    """
    images = [ld_makeseq(x) for x in images]
    return seq_makebatch(images)

def images2batch(images):
    """Given a list of images, return a batch tensor.

    :param images: list of imags
    :returns: batch tensor

    """
    return seq_makebatch(images)

class AsciiCodec(object):
    """An example of a codec, used for turning strings into tensors."""
    def _encode_char(self, c):
        if c=="": return 0
        return max(1, ord(c) - ord(" ") + 1)
    def _decode_char(self, c):
        if c==0: return ""
        return chr(ord(" ") + c - 1)
    def size(self):
        """The number of classes. Zero is always reserved for the empty class.
        """
        return 97
    def encode(self, s):
        """Encode a string.

        :param s: string to be encoded
        :returns: list of integers

        """
        return [self._encode_char(c) for c in s]
    def decode(self, l):
        """Decode a numerical encoding of a string.

        :param l: list of integers
        :returns: string

        """
        return "".join([self._decode_char(x) for x in l])

ascii_codec = AsciiCodec()

def maketarget(s, codec=ascii_codec):
    """Turn a string into an LD target.

    :param s: string
    :param codec: codec
    :returns: hot one encoding of string

    """
    assert isinstance(s, (str, unicode)), (type(s), s)
    codes = codec.encode(s)
    n = codec.size()
    return utils.intlist_to_hotonelist(codes, n)

def transcripts2batch(transcripts, codec=ascii_codec):
    """Given a list of strings, makes ndarray target arrays.

    :param transcripts: list of strings
    :param codec: encoding codec
    :returns: batched hot one encoding of strings suitable for CTC

    """
    targets = [maketarget(s, codec=codec) for s in transcripts]
    return seq_makebatch(targets, for_target=True)

@curried
def encode(data):
    """Automatically encode data items based on key extension.

    Known extensions:
    - png, jpg, jpeg: images
    - json: JSON
    - pyd, pickle: Python pickles
    - mp: Messagepack
    """
    for sample in data:
        yield utils.autoencode(data)

@curried
def decode(data):
    """Automatically decode data items based on key extension.

    Known extensions:
    - png, jpg, jpeg: images
    - json: JSON
    - pyd, pickle: Python pickles
    - mp: Messagepack
    """
    for sample in data:
        yield utils.autodecode(sample)

@curried
def itbatchedbuckets(data, batchsize=5, scale=1.8, seqkey="input", batchdim=1):
    """List-batch input samples into similar sized batches.

    :param data: iterator of samples
    :param batchsize: target batch size
    :param scale: spacing of bucket sizes
    :param seqkey: input key to use for batching
    :param batchdim: input dimension to use for bucketing
    :returns: batches consisting of lists of similar sequence lengths

    """
    buckets = {}
    for sample in data:
        seq = sample[seqkey]
        l = seq.shape[batchdim]
        r = int(math.floor(math.log(l) / math.log(scale)))
        batched = buckets.get(r, {})
        for k, v in sample.items():
            if k in batched:
                batched[k].append(v)
            else:
                batched[k] = [v]
        if len(batched[seqkey]) >= batchsize:
            batched["_bucket"] = r
            yield batched
            batched = {}
        buckets[r] = batched
    for r, batched in buckets.items():
        if batched == {}: continue
        batched["_bucket"] = r
        yield batched

@curried
def itlineseqbatcher(data, input="image", transcript="transcript", target="target", codec=ascii_codec):
    """Performs text line batching for OCR.

    Usually this is used after itbatchedbuckets.

    :param data: iterator over OCR training samples
    :param input: input field name
    :param transcript: transcript field name
    :param target: target field name
    :param codec: codec used for encoding classes
    :returns: batched sequences

    """
    for sample in data:
        sample = sample.copy()
        sample[input] = images2batch(sample[input])
        sample[target] = transcripts2batch(sample[transcript], codec=codec)
        yield sample

@curried
def itlinebatcher(data, input="input", transcript="transcript", target="target", codec=ascii_codec):
    """Performs text line batching for OCR.

    Usually this is used after itbatchedbuckets.

    :param data: iterator over OCR training samples
    :param input: input field name
    :param transcript: transcript field name
    :param target: target field name
    :param codec: codec used for encoding classes
    :returns: batched sequences

    """
    for sample in data:
        sample = sample.copy()
        sample[input] = images2batch(sample[input])
        sample[target] = transcripts2batch(sample[transcript], codec=codec)
        yield sample

###
### various data sinks
###

@curried
def showgrid(data, key="input", label=None, grid=(4, 8)):
    """A sink that shows a grid of images.

    :param data: iterator
    :param key: key to be displayed
    :param label: label field to be displayed
    :param grid: grid size for display

    """
    import pylab
    rows, cols = grid
    for i, sample in enumerate(data):
        if i >= rows * cols:
            break
        pylab.subplot(rows, cols, i + 1)
        pylab.xticks([])
        pylab.yticks([])
        pylab.imshow(sample["input"])


@curried
def batchinfo(data, n=1):
    """A sink that provides info about samples/batches.

    :param data: iterator
    :param n: number of samples to print info for

    """
    for i, sample in enumerate(data):
        if i >= n:
            break
        print type(sample)
        for k, v in sample.items():
            print k, type(v),
            if isinstance(v, np.ndarray):
                print v.shape, np.amin(v), np.mean(v), np.amax(v),
            print
        print

