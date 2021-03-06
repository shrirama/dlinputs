from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from future import standard_library
standard_library.install_aliases()
from builtins import object
from past.utils import old_div
import time
import collections
from urllib2 import urlparse

import zmq
import msgpack

from . import utils

schemes = dict(
    # (KIND, BIND)
    zpush=(zmq.PUSH, False),
    zpull=(zmq.PULL, True),
    zpub=(zmq.PUB, True),
    zsub=(zmq.SUB, False),
    zrpush=(zmq.PUSH, True),
    zrpull=(zmq.PULL, False),
    zrpub=(zmq.PUB, False),
    zrsub=(zmq.SUB, True)
)

class Statistics(object):
    def __init__(self, horizon=1000):
        self.horizon = horizon
        self.reset()
    def reset(self):
        self.start = time.time()
        self.last = time.time()
        self.count = 0
        self.total = 0
        self.recent = collections.deque(maxlen=self.horizon)
    def add(self, x):
        self.last = time.time()
        self.count += 1
        self.total += x
        self.recent.append((self.last, x))
    def rate(self):
        if self.count==0: return 0
        return old_div(self.count, (self.last - self.start))
    def throughput(self):
        if self.count==0: return 0
        return old_div(self.total, (self.last - self.start))
    def recent_rate(self):
        if self.count==0: return 0 
        delta = self.recent[-1][0] - self.recent[0][0]
        if delta==0: return 0
        return old_div(len(self.recent), delta)
    def recent_throughput(self):
        if self.count==0: return 0
        total = sum(r[1] for r  in self.recent)
        delta = self.recent[-1][0] - self.recent[0][0]
        if delta==0: return 0
        return old_div(total, delta)
    def summary(self):
        return "rate {} throughput {}".format(self.recent_rate(), self.recent_throughput())

class Connection(object):
    def __init__(self, url, codec=True, pack=True, stats_horizon=1000):
        if codec is False:
            codec = lambda x: x
        self.stats = Statistics(stats_horizon)
        self.codec = codec
        self.pack = pack
        self.addr = urlparse.urlparse(url)
        kind, bind = schemes[self.addr.scheme]
        self.context = zmq.Context()
        self.socket = self.context.socket(kind)
        location = "tcp://"+self.addr.netloc
        self.socket.setsockopt(zmq.LINGER, 0)
        if bind:
            self.socket.bind(location)
        else:
            self.socket.connect(location)
        if kind==zmq.SUB:
            self.socket.setsockopt(zmq.SUBSCRIBE, '')
    def close(self):
        self.socket.close()
        self.socket = None
        self.context = None
    def send(self, data):
        if self.codec is True:
            data = utils.autoencode(data)
        else:
            data = self.codec(data)
        if self.pack:
            data = msgpack.dumps(data)
        self.socket.send(data)
        self.stats.add(len(data))
    def recv(self):
        data = self.socket.recv()
        self.stats.add(len(data))
        if self.pack:
            data = msgpack.loads(data)
        if self.codec is True:
            data = utils.autodecode(data)
        else:
            data = self.codec(data)
        return data
    def serve(self, source, report=-1):
        count = 0
        for sample in source:
            self.send(sample)
            if report>0 and count%report==0:
                print("count", count, self.stats.summary())
            count += 1
    def items(self):
        while True:
            result = self.recv()
            yield result
    def write(self, data):
        self.send(data)
