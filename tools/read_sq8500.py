#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless download using a transport that rejects upload frames."""
import argparse
import hashlib
import json
from pathlib import Path

import serial
from chirp.drivers.shiqun_sq8500 import IMAGE_SIZE, MAGIC, ShiqunSQ8500Radio


class ReadOnlySerial:
    def __init__(self, port):
        object.__setattr__(self, '_port', port)
        object.__setattr__(self, 'requests', [])

    def __getattr__(self, name):
        return getattr(self._port, name)

    def __setattr__(self, name, value):
        setattr(self._port, name, value)

    def write(self, data):
        allowed = data in (MAGIC, b'\x02', b'\x06', b'E')
        if len(data) == 4 and data[:1] == b'R' and data[3] == 32:
            address = int.from_bytes(data[1:3], 'big')
            allowed = address % 32 == 0 and address < IMAGE_SIZE
        if not allowed:
            raise RuntimeError('Read-only transport rejected outgoing command')
        self.requests.append(data.hex())
        return self._port.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('destination', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=False)
    with serial.Serial(args.port, baudrate=57600, timeout=2,
                       write_timeout=2) as port:
        pipe = ReadOnlySerial(port)
        radio = ShiqunSQ8500Radio(pipe)
        radio.status_fn = lambda status: None
        radio.sync_in()
    data = radio.get_mmap().get_packed()
    (args.destination / 'download.bin').write_bytes(data)
    radio.save_mmap(str(args.destination / 'download.img'))
    report = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'channel_count': sum(not radio.get_memory(n).empty
                                   for n in range(1, 200)),
              'outgoing_commands': pipe.requests,
              'upload_frames': 0}
    if args.compare:
        expected = args.compare.read_bytes()[:IMAGE_SIZE]
        report['differences_from_comparison'] = [
            i for i, (a, b) in enumerate(zip(data, expected)) if a != b]
        report['comparison_length'] = len(expected)
    (args.destination / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items()
                      if k != 'outgoing_commands'}, indent=2))


if __name__ == '__main__':
    main()
