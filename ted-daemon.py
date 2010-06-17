#!/usr/bin/env python
"""
Listener daemon for the serial tedrx receiver.

usage: tedrx-daemon.py <datadir>

For each data channel, this daemon updates a corresponing rrd file
with the history of that channel, and writes its current state to an
xml file. Channels are named "tedrx-hc<housecode>-volts/kw".

Micah Dowty <micah@navi.cx>

===============
Modifications by Brandon Tallent <btallent@gmail.com> to read
data directly from OEM TED 1001 receiver based on code from Micah Dowty
This is based on my RDU with firmware 8.01U.  Try changing
packet length to 278 for later firmware versions. 
"""

import os
import sys
import time
import serial
import rrdtool
import struct

# Special bytes

PKT_REQUEST = "\xAA"
ESCAPE      = "\x10"
PKT_BEGIN   = "\x04"
PKT_END     = "\x03"

# Global vars
output_rrd = True
output_xml = True
debug = True
xmlpath = "/var/www/ted.xml"
rrdpath = "/home/brandon/teddata"

class ProtocolError(Exception):
    pass

class TedReceiver:
    def __init__(self, port="/dev/ttyUSB0"):
        self.port = serial.Serial(port, 19200, timeout=0)
        self.escape_flag = False

        # None indicates that the packet buffer is invalid:
        # we are not receiving any valid packet at the moment.
        self.packet_buffer = None

    def read(self):
        """Request a packet from the RDU, and flush the operating
           system's receive buffer. Any complete packets we've
           received will be decoded. Returns a list of Packet
           instances.

           Raises ProtocolError if we see anything from the RDU that
           we don't expect.
           """

        # Request a packet. The RDU will ignore this request if no
        # data is available, and there doesn't seem to be any harm in
        # sending the request more frequently than once per second.
        self.port.write(PKT_REQUEST)
        return self.decode(self.port.read(4096))

    def readMultiple(self, timeout=60):
        """Read as many packets as we can during 'timeout' seconds."""
        deadline = time.time() + timeout
        allpackets = []
        while time.time() < deadline:
            allpackets.append(self.read())
            time.sleep(1.0)

        return allpackets

    def decode(self, raw):
        """Decode some raw data from the RDU. Updates internal
           state, and returns a list of any valid Packet() instances
           we were able to extract from the raw data stream.
           """

        packets = []

        # The raw data from the RDU is framed and escaped. The byte
        # 0x10 is the escape byte: It takes on different meanings,
        # depending on the byte that follows it. These are the
        # escape sequence I know about:
        #
        #    10 10: Encodes a literal 0x10 byte.
        #    10 04: Beginning of packet
        #    10 03: End of packet
        #
        # This code illustrates the most straightforward way to
        # decode the packets. It's best in a low-level language like C
        # or Assembly. In Python we'd get better performance by using
        # string operations like split() or replace()- but that would
        # make this code much harder to understand.

        for byte in raw:
            if self.escape_flag:
                self.escape_flag = False
                if byte == ESCAPE:
                    if self.packet_buffer is not None:
                        self.packet_buffer += ESCAPE
                elif byte == PKT_BEGIN:
                    self.packet_buffer = ''
                elif byte == PKT_END:
                    if self.packet_buffer is not None:
                        packets.append(Packet(self.packet_buffer))
                        self.packet_buffer = None
                else:
                    raise ProtocolError("Unknown escape byte %r" % byte)

            elif byte == ESCAPE:
                self.escape_flag = True
            elif self.packet_buffer is not None:
                self.packet_buffer += byte

        return packets
    

class Packet(object):
    """Decoder for TED packets. We use a lookup table to find individual
       fields in the packet, convert them using the 'struct' module,
       and scale them. The results are available in the 'fields'
       dictionary, or as attributes of this object.
       """
    
    # We only support one packet length. Any other is a protocol error.
    _protocol_len = 276

    _protocol_table = (
        # TODO: Fill in the rest of this table.
        #
        # It needs verification on my firmware version, but so far the
        # offsets in David Satterfield's code match mine. Since his
        # code does not handle packet framing, his offsets are 2 bytes
        # higher than mine. These offsets start counting at the
        # beginning of the packet body. Packet start and packet end
        # codes are omitted.

        # Offset,  name,          fmt,     scale
        (82,       'CurrentRate', "<H",    0.0001),
        (247,      'KWNow',       "<H",    0.01),
        (249,      'DlrNow',      "<H",    0.01),
        (251,      'VrmsNowDsp',  "<H",    0.1),
        (253,      'DlrMtd',      "<H",    0.1),
        (255,      'DlrProj',     "<H",    0.1),
        (257,      'KWProj',      "<H",    1),
        (132,      'LoVrmsTdy',   "<H",    0.1),
        (136,      'HiVrmsTdy',   "<H",    0.1),
        (140,      'LoVrmsMtd',   "<H",    0.1),
        (143,      'HiVrmsMtd',   "<H",    0.1),
        (146,      'KwPeakTdy',   "<H",    0.01),
        (148,      'DlrPeakTdy',  "<H",    0.01),
        (150,      'KwPeakMtd',   "<H",    0.01),
        (152,      'DlrPeakMtd',  "<H",    0.01),        
        (154,      'DlrTdy',      "<L",    0.00000167),
        (158,      'KWTdy',       "<L",    0.0000167),
        (166,      'KWMtd',       "<L",    0.0000167),
        (170,      'DlrMtd',      "<L",    0.00000167),
        )

    def __init__(self, data):
        self.data = data
        self.fields = {}
        if len(data) != self._protocol_len:
            raise ProtocolError("Unsupported packet length %r" % len(data))

        for offset, name, fmt, scale in self._protocol_table:
            size = struct.calcsize(fmt)
            field = data[offset:offset+size]
            value = struct.unpack(fmt, field)[0] * scale

            setattr(self, name, value)
            self.fields[name] = value

        _nowtime = time.time()
        setattr(self, 'timestamp', _nowtime)
        self.fields['timestamp'] = _nowtime


def updateChannelRRD(name, values, lastTS={}):
    filename = os.path.join(rrdpath, '%s.rrd' % name)

    if os.path.isfile(filename):
        updates = []
        for ts, v in values:
            ts = int(ts + 0.5)

            # Throw out updates that are less than a second apart.
            if ts != lastTS.get(name, 0):
                lastTS[name] = ts
                updates.append('%s:%s' % (ts, v))

        print updates
        rrdtool.update(filename, *updates)
    
    else:
        rra = []
        for cf in 'AVERAGE', 'MIN', 'MAX':
            rra.extend([
                    "RRA:%s:0.99:1:172800" % cf,
                    "RRA:%s:0.99:60:2880" % cf,
                    "RRA:%s:0.5:420:2880" % cf,
                    "RRA:%s:0.5:1860:2880" % cf,
                    "RRA:%s:0.5:21900:2880" % cf,
                    ])
        rrdtool.create(filename,
                       "DS:value:GAUGE:120:U:U",
                       "-s 1", *rra)


def updateDashboardData(packet):
    """Outputs an XML file that is similar to the original DashboardData
       page that TED Footprints software produces.  This allows other apps
       that interface with TED (such as the TED Toolbar for Firefox) to
       read data gathered with this script.  
       """

    xmltext = """
<?xml version="1.0" encoding="utf-8"?>
<DashboardData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xmlns:xsd="http://www.w3.org/2001/XMLSchema">
"""
    for (field, value) in packet.fields.items():
        xmltext += "<%s>%s</%s>\n" % (field, value, field)
    xmltext += "</DashboardData>"
    if debug is True:
        print xmltext
    open(os.path.join(xmlpath), 'w').write(xmltext)

def main():
    rx = TedReceiver()

    if debug is True:
        print "TEst"
    while True:
        # Read a bundle of packets, and resort them into
        # data points for each channel.
        allpackets = rx.readMultiple()
        channels = {}
        for packets in allpackets:
            for packet in packets:
                channels.setdefault("tedrx-kw", []).append((packet.timestamp,
                                                            packet.KWNow))
                channels.setdefault("tedrx-d", []).append((packet.timestamp,
                                                           packet.DlrNow))
                lastpacket = packet

        # Update each channel, processing multiple packets at once to
        # save disk wear.
        if output_rrd is True:
            for channel, values in channels.iteritems():
                updateChannelRRD(channel, values)
          
        if output_xml is True:
            updateDashboardData(lastpacket)

if __name__ == "__main__":
    main()
