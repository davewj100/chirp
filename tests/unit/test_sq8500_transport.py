# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable serial tests; no private captures or hardware required."""
from pathlib import Path
import struct
import unittest
from unittest import mock

from chirp import chirp_common, errors, memmap
from chirp.drivers import shiqun_sq8500 as driver
from tools.read_sq8500 import ReadOnlySerial

FIXTURE = Path(__file__).parents[1] / 'images/SHIQUN_SQ-8500.img'


class SimulatedRadio:
    def __init__(self, image, fail_address=None):
        self.image = bytearray(image)
        self.pending = b''
        self.requests = []
        self.fail_address = fail_address
        self.uploads = []
        self.complete = False
        self.stage = 'entry'
        self.is_open = True

    def close(self):
        self.is_open = False
        self.requests.append(b'PORT_CLOSE')

    def open(self):
        self.is_open = True
        self.requests.append(b'PORT_OPEN')

    def read(self, size):
        size = min(size, 3)
        result, self.pending = self.pending[:size], self.pending[size:]
        return result

    def write(self, data):
        if not self.is_open:
            raise AssertionError('Command sent while port closed')
        if self.pending:
            raise AssertionError('Unread simulated radio response')
        self.requests.append(data)
        if data == driver.MAGIC and self.stage == 'entry':
            self.stage = 'identify'
            self.pending = b'\x06'
        elif data == b'\x02' and self.stage == 'identify':
            self.stage = 'ack'
            self.pending = driver.IDENT
        elif data == b'\x06' and self.stage == 'ack':
            self.stage = 'blocks'
            self.pending = b'\x06'
        elif data == b'E':
            self.pending = b'\x06'
            self.stage = 'finish'
        elif data == b'\x02' and self.stage == 'finish':
            self.complete = True
            self.stage = 'entry'
        elif data[:1] == b'R' and self.stage == 'blocks':
            address, size = struct.unpack('>HB', data[1:])
            payload = self.image[address:address + size]
            self.pending = (b'W' + data[1:] + payload +
                            bytes([sum(payload) & 255]))
        elif data[:1] == b'W' and self.stage == 'blocks':
            address, size = struct.unpack('>HB', data[1:4])
            if len(data) != size + 5 or sum(data[4:-1]) & 255 != data[-1]:
                raise AssertionError('Malformed simulated write frame')
            self.uploads.append(address)
            if address == self.fail_address:
                self.pending = b'\x15'
            else:
                self.image[address:address + size] = data[4:-1]
                self.pending = b'\x06'
        else:
            raise AssertionError('Unexpected command: %r' % data)
        return len(data)


def fixture_radio():
    return driver.ShiqunSQ8500Radio(str(FIXTURE))


class TransportTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(driver, 'time')
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_read_only_transport_rejects_all_uploads_and_bad_reads(self):
        pipe = ReadOnlySerial(SimulatedRadio(bytes(8000)))
        for request in [b'W' + bytes(36), b'R\x1f\x40\x20',
                        b'R\x00\x01\x20', b'R\x00\x00\x40', b'unknown']:
            with self.subTest(request=request):
                with self.assertRaises(RuntimeError):
                    pipe.write(request)
        self.assertFalse(pipe.requests)

    def test_full_read_is_fragment_safe_and_sends_no_upload(self):
        expected = fixture_radio().get_mmap().get_packed()
        fake = SimulatedRadio(expected)
        radio = driver.ShiqunSQ8500Radio(ReadOnlySerial(fake))
        radio.status_fn = lambda status: None
        radio.sync_in()
        self.assertEqual(radio.get_mmap().get_packed(), expected)
        self.assertFalse(fake.uploads)
        self.assertTrue(fake.complete)

    def test_disabled_upload_does_not_open_protocol(self):
        fake = SimulatedRadio(bytes(8000))
        radio = driver.ShiqunSQ8500Radio(fake)
        with mock.patch.object(driver, 'UPLOAD_ENABLED', False):
            with self.assertRaises(errors.RadioError):
                radio.sync_out()
        self.assertFalse(fake.requests)

    def test_simulated_upload_preserves_target_hardware_and_unknowns(self):
        source = fixture_radio()
        wanted = bytearray(source.get_mmap().get_packed())
        # These mutations deliberately simulate a different saved image's
        # unknown/calibration bytes. They must never reach the target.
        for address in [0, 0x0C80, 0x1B40, 0x1F30,
                        0x1C00, 0x1C0C, 0x1F3F]:
            wanted[address] ^= 0x5A
        wanted[0xCC0:0xCC8] = bytes.fromhex('1350261030005300')
        wanted[0x1D] ^= 0x0B  # Reserved channel flag bits
        source._mmap = memmap.MemoryMapBytes(bytes(wanted))
        memory = source.get_memory(1)
        memory.name = 'EDIT0001'
        memory.freq = 145550000
        source.set_memory(memory)
        target = fixture_radio().get_mmap().get_packed()
        fake = SimulatedRadio(target)
        source.pipe = fake
        source.status_fn = lambda status: None
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            source.sync_out()
        self.assertEqual(len(fake.uploads), 250)
        self.assertEqual(fake.uploads, list(range(0, 8000, 32)))
        self.assertTrue(fake.complete)
        expected = fixture_radio()
        memory = expected.get_memory(1)
        memory.name = 'EDIT0001'
        memory.freq = 145550000
        expected.set_memory(memory)
        self.assertEqual(bytes(fake.image), expected.get_mmap().get_packed())

    def test_nak_stops_upload_without_retry_or_later_blocks(self):
        radio = fixture_radio()
        fake = SimulatedRadio(radio.get_mmap().get_packed(), fail_address=64)
        radio.pipe = fake
        radio.status_fn = lambda status: None
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            with self.assertRaises(errors.RadioError):
                radio.sync_out()
        self.assertEqual(fake.uploads, [0, 32, 64])
        self.assertTrue(fake.complete)

    def test_new_channel_and_deletion_preserve_other_target_data(self):
        radio = fixture_radio()
        current = radio.get_mmap().get_packed()
        memory = chirp_common.Memory()
        memory.number = 18
        memory.freq = 446012500
        memory.power = driver.POWER[1]
        memory.name = 'NEW018'
        radio.set_memory(memory)
        deleted = radio.get_memory(1)
        deleted.empty = True
        radio.set_memory(deleted)
        self.assertEqual(radio._merge_upload(current),
                         radio.get_mmap().get_packed())

    def test_password_from_source_is_never_transferred(self):
        radio = fixture_radio()
        current = bytearray(radio.get_mmap().get_packed())
        current[driver.PASSWORD_REGION] = b'TARGET'
        wanted = bytearray(current)
        wanted[driver.PASSWORD_REGION] = b'SOURCE'
        radio._mmap = memmap.MemoryMapBytes(bytes(wanted))
        fake = SimulatedRadio(bytes(current))
        radio.pipe = fake
        radio.status_fn = lambda status: None
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            radio.sync_out()
        self.assertEqual(fake.image[driver.PASSWORD_REGION], b'TARGET')
        self.assertEqual(bytes(fake.image), bytes(current))

    def test_password_guard_stops_before_first_write(self):
        radio = fixture_radio()
        current = radio.get_mmap().get_packed()
        poisoned = bytearray(current)
        poisoned[driver.PASSWORD_REGION] = b'CHANGE'
        fake = SimulatedRadio(current)
        radio.pipe = fake
        radio.status_fn = lambda status: None
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            with mock.patch.object(radio, '_merge_upload',
                                   return_value=bytes(poisoned)):
                with self.assertRaisesRegex(errors.RadioError, 'password'):
                    radio.sync_out()
        self.assertFalse(fake.uploads)
        self.assertTrue(fake.complete)

    def test_empty_target_record_is_not_normalized(self):
        radio = fixture_radio()
        current = bytearray(radio.get_mmap().get_packed())
        base = 18 * 16
        current[base:base + 16] = bytes(range(16))
        merged = radio._merge_upload(bytes(current))
        self.assertEqual(merged, bytes(current))

    def test_new_channel_never_copies_source_reserved_bits(self):
        radio = fixture_radio()
        current = radio.get_mmap().get_packed()
        memory = chirp_common.Memory()
        memory.number = 18
        memory.freq = 446012500
        memory.name = 'NEW018'
        radio.set_memory(memory)
        expected = radio.get_mmap().get_packed()
        poisoned = bytearray(expected)
        base = 18 * 16
        poisoned[base + 12] = 0xA5
        poisoned[base + 13] |= 0x2B
        poisoned[base + 14] |= 0x87
        poisoned[base + 15] |= 0xF0
        radio._mmap = memmap.MemoryMapBytes(bytes(poisoned))
        self.assertEqual(radio._merge_upload(current), expected)

    def test_invalid_settings_batch_is_atomic(self):
        radio = fixture_radio()
        before = radio.get_mmap().get_packed()
        settings = radio.get_settings()
        fields = {s.get_name(): s for s in driver._walk(settings)}
        fields['opt_1017'].value.set_index(6)
        fields['vfo_freq_A'].value = '300.00000'
        with self.assertRaises(errors.RadioError):
            radio.set_settings(settings)
        self.assertEqual(before, radio.get_mmap().get_packed())


if __name__ == '__main__':
    unittest.main()
