# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable shared-configuration policy and CPS transaction tests."""
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from chirp import errors, memmap
from chirp.drivers import shiqun_sq8500 as driver
from tests.unit.test_sq8500_transport import fixture_radio, SimulatedRadio


def settings_by_name(radio):
    settings = radio.get_settings()
    return settings, {s.get_name(): s for s in driver._walk(settings)}


def select_groups(radio, selected):
    settings, fields = settings_by_name(radio)
    for name, label in driver.UPLOAD_GROUPS:
        fields['upload_' + name].value = name in selected
    radio.set_settings(settings)


class UploadPolicyTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(driver, 'time')
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_stored_bands_allow_wide_channels_and_vfos(self):
        radio = fixture_radio()
        data = bytearray(radio.get_mmap().get_packed())
        data[0xCC0:0xCC8] = bytes.fromhex('1360260031005200')
        radio._mmap = memmap.MemoryMapBytes(bytes(data))
        self.assertEqual(radio.get_features().valid_bands,
                         [(136000000, 260000010), (310000000, 520000010)])
        for frequency in (136000000, 223500000, 260000000,
                          310000000, 350000000, 520000000):
            memory = radio.get_memory(1)
            memory.freq = frequency
            memory.duplex = ''
            radio.set_memory(memory)
            self.assertEqual(radio.get_memory(1).freq, frequency)
        settings, fields = settings_by_name(radio)
        fields['vfo_freq_A'].value = '223.50000'
        radio.set_settings(settings)
        _, fields = settings_by_name(radio)
        self.assertEqual(str(fields['vfo_freq_A'].value), '223.50000')

    def test_stored_band_gap_and_split_tx_rejected_atomically(self):
        radio = fixture_radio()
        before = radio.get_mmap().get_packed()
        for rx, tx in [(300000000, 145000000), (145000000, 300000000)]:
            memory = radio.get_memory(1)
            memory.freq, memory.offset, memory.duplex = rx, tx, 'split'
            with self.assertRaises(errors.RadioError):
                radio.set_memory(memory)
            self.assertEqual(radio.get_mmap().get_packed(), before)

    def test_narrow_target_blocks_wide_source_before_write(self):
        for edit_vfo in (False, True):
            radio = fixture_radio()
            data = bytearray(radio.get_mmap().get_packed())
            data[0xCC0:0xCC8] = bytes.fromhex('1360260031005200')
            radio._mmap = memmap.MemoryMapBytes(bytes(data))
            target = bytearray(data)
            target[0xCC0:0xCC8] = bytes.fromhex('1360174040004700')
            if edit_vfo:
                settings, fields = settings_by_name(radio)
                fields['vfo_freq_A'].value = '223.50000'
                radio.set_settings(settings)
            else:
                memory = radio.get_memory(1)
                memory.freq, memory.duplex = 223500000, ''
                radio.set_memory(memory)
            fake = SimulatedRadio(bytes(target))
            radio.pipe = fake
            radio.status_fn = lambda status: None
            with self.assertRaisesRegex(errors.RadioError,
                                        'stored radio bands'):
                radio.sync_out()
            self.assertFalse(fake.uploads)

    def test_narrow_and_malformed_image_band_limits(self):
        for bands in ('1360174040004700', 'ffffffffffffffff',
                      '2600136031005200', '0000260031005200'):
            radio = fixture_radio()
            data = bytearray(radio.get_mmap().get_packed())
            data[0xCC0:0xCC8] = bytes.fromhex(bands)
            radio._mmap = memmap.MemoryMapBytes(bytes(data))
            if bands == '1360174040004700':
                memory = radio.get_memory(1)
                memory.freq, memory.duplex = 223500000, ''
                with self.assertRaises(errors.RadioError):
                    radio.set_memory(memory)
                settings, fields = settings_by_name(radio)
                fields['vfo_freq_A'].value = '223.50000'
                with self.assertRaises(errors.RadioError):
                    radio.set_settings(settings)
            else:
                with self.assertRaisesRegex(errors.RadioError,
                                            'Invalid stored band limits'):
                    radio.process_mmap()

    def test_fm_modes_and_interruptions_match_confirmed_hardware(self):
        for mode, bit in [('VFO', 0), ('CH', 0x80)]:
            for allow in (False, True):
                with self.subTest(mode=mode, allow=allow):
                    radio = fixture_radio()
                    settings, fields = settings_by_name(radio)
                    original = radio.get_mmap().get_packed()
                    fields['fm_1075'].value = mode
                    fields['fm_1070'].value = allow
                    radio.set_settings(settings)
                    actual = radio.get_mmap().get_packed()
                    self.assertEqual(actual[0xCA2] & 0x88,
                                     bit | (0x08 if allow else 0))
                    self.assertEqual(actual[0xCA2] & ~0x88,
                                     original[0xCA2] & ~0x88)
                    settings, fields = settings_by_name(radio)
                    self.assertEqual(str(fields['fm_1075'].value), mode)
                    self.assertEqual(bool(fields['fm_1070'].value), allow)
                    radio.set_settings(settings)
                    self.assertEqual(radio.get_mmap().get_packed(), actual)

    def test_active_vfo_preserves_other_bits_and_upload_choice(self):
        source = fixture_radio()
        current = bytearray(source.get_mmap().get_packed())
        current[0x1960] = 0xA0
        select_groups(source, set())
        settings, fields = settings_by_name(source)
        fields['active_vfo'].value = 'B'
        source.set_settings(settings)
        self.assertEqual(source._merge_upload(bytes(current))[0x1960], 0xA0)
        self.assertEqual(source._upload_groups(), set())
        select_groups(source, {'options'})
        self.assertEqual(source._merge_upload(bytes(current))[0x1960], 0xA1)

    def test_selected_channels_follow_only_vfo_upload_option(self):
        source = fixture_radio()
        current = source.get_mmap().get_packed()
        select_groups(source, set())
        settings, fields = settings_by_name(source)
        fields['vfo_channel_A'].value = '13'
        fields['vfo_channel_B'].value = '199'
        source.set_settings(settings)
        self.assertEqual(source.get_mmap().get_packed()[0xCA4:0xCA6],
                         bytes([13, 199]))
        self.assertEqual(source._merge_upload(current)[0xCA4:0xCA6],
                         current[0xCA4:0xCA6])
        self.assertEqual(source._upload_groups(), set())
        select_groups(source, {'vfo'})
        self.assertEqual(source._merge_upload(current)[0xCA4:0xCA6],
                         bytes([13, 199]))

    def test_unchecking_all_retains_target_settings(self):
        source, target = fixture_radio(), fixture_radio()
        select_groups(source, set())
        settings, fields = settings_by_name(target)
        fields['opt_1017'].value.set_index(6)
        fields['message_0'].value = 'TARGET UNIT'
        fields['vfo_freq_A'].value = '145.55000'
        fields['fm_preset_0'].value = '89.9'
        fields['call_0'].value = '123456'
        target.set_settings(settings)
        current = target.get_mmap().get_packed()
        memory = source.get_memory(1)
        memory.name = 'SHARED01'
        source.set_memory(memory)
        expected = bytearray(current)
        expected[0x0D40:0x0D48] = b'SHARED01'
        self.assertEqual(source._merge_upload(current), bytes(expected))
        self.assertEqual(source._upload_groups(), set())

    def test_each_native_upload_checkbox_only_allows_its_group(self):
        for group, label in driver.UPLOAD_GROUPS:
            with self.subTest(group=group):
                source, target = fixture_radio(), fixture_radio()
                current = target.get_mmap().get_packed()
                # Different source values in fields owned by each group.
                wanted = bytearray(current)
                for offset in (0x0CA9, 0x1390, 0x0CB0, 0x1B50,
                               0x0CD0, 0x1B70, 0x0C97, 0x1400):
                    wanted[offset] ^= 1
                source._mmap = memmap.MemoryMapBytes(bytes(wanted))
                settings, fields = settings_by_name(source)
                for name, label in driver.UPLOAD_GROUPS:
                    fields['upload_' + name].value = name == group
                source.set_settings(settings)
                self.assertEqual(source._upload_groups(), {group})
                result = source._merge_upload(current)
                checks = {'options': (0x0CA9, 0x1390),
                          'vfo': (0x0CB0, 0x1B50),
                          'fm': (0x0CD0, 0x1B70),
                          'dtmf': (0x0C97, 0x1400)}
                for owner, offsets in checks.items():
                    for offset in offsets:
                        self.assertEqual(result[offset],
                                         wanted[offset] if owner == group
                                         else current[offset])

    def test_default_includes_all_mapped_settings(self):
        source, target = fixture_radio(), fixture_radio()
        self.assertEqual(source._upload_groups(),
                         {name for name, label in driver.UPLOAD_GROUPS})
        settings, fields = settings_by_name(source)
        self.assertTrue(all(bool(fields['upload_' + name].value)
                            for name, label in driver.UPLOAD_GROUPS))
        fields['opt_1017'].value.set_index(6)
        fields['message_0'].value = 'SHARED'
        fields['vfo_freq_A'].value = '145.55000'
        fields['fm_preset_0'].value = '89.9'
        fields['call_0'].value = '123456'
        source.set_settings(settings)
        self.assertEqual(source._merge_upload(target.get_mmap().get_packed()),
                         source.get_mmap().get_packed())

    def test_unchecked_groups_stay_off_after_edits_and_save(self):
        radio = fixture_radio()
        target = radio.get_mmap().get_packed()
        select_groups(radio, set())
        settings, fields = settings_by_name(radio)
        fields['opt_1017'].value.set_index(6)
        fields['message_0'].value = 'LOCAL ONLY'
        fields['vfo_freq_A'].value = '145.55000'
        fields['fm_preset_0'].value = '89.9'
        fields['call_0'].value = '123456'
        radio.set_settings(settings)
        self.assertEqual(radio._upload_groups(), set())
        self.assertNotEqual(radio.get_mmap().get_packed(), target)
        self.assertEqual(radio._merge_upload(target), target)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'shared.img')
            radio.save_mmap(path)
            loaded = driver.ShiqunSQ8500Radio(path)
            self.assertEqual(loaded._upload_groups(), set())
            self.assertEqual(loaded.get_mmap().get_packed(),
                             radio.get_mmap().get_packed())
            self.assertEqual(loaded._merge_upload(target), target)
        before = radio.get_mmap().get_packed()
        select_groups(radio, {'options'})
        self.assertEqual(radio._upload_groups(), {'options'})
        self.assertEqual(radio.get_mmap().get_packed(), before)
        self.assertNotEqual(radio._merge_upload(target), target)

    def test_failed_edit_keeps_image_and_policy_atomic(self):
        radio = fixture_radio()
        before = radio.get_mmap().get_packed()
        settings, fields = settings_by_name(radio)
        fields['upload_options'].value = False
        fields['vfo_freq_A'].value = '300.00000'
        with self.assertRaises(errors.RadioError):
            radio.set_settings(settings)
        self.assertEqual(radio._upload_groups(),
                         {name for name, label in driver.UPLOAD_GROUPS})
        self.assertEqual(radio.get_mmap().get_packed(), before)

    def test_protected_bit_guard_stops_faulty_merge_before_write(self):
        radio = fixture_radio()
        select_groups(radio, set())
        current = radio.get_mmap().get_packed()
        for offset in (0, 0x0CC0, 0x0CA9, 0x0C97):
            with self.subTest(offset=offset):
                bad = bytearray(current)
                bad[offset] ^= 1
                fake = SimulatedRadio(current)
                radio.pipe = fake
                radio.status_fn = lambda status: None
                with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
                    with mock.patch.object(radio, '_merge_upload',
                                           return_value=bytes(bad)):
                        with self.assertRaisesRegex(errors.RadioError,
                                                    'protected bit'):
                            radio.sync_out()
                self.assertFalse(fake.uploads)

    def test_one_config_retains_different_targets_and_reserved_bits(self):
        radio = fixture_radio()
        select_groups(radio, set())
        memory = radio.get_memory(1)
        memory.name = 'SHARED01'
        radio.set_memory(memory)
        source = radio.get_mmap().get_packed()
        for marker in (0x35, 0xA2):
            target = bytearray(fixture_radio().get_mmap().get_packed())
            for offset in (0, 0x0C80, 0x1B40, 0x1F30, 0x0CA9):
                target[offset] = marker
            target[0xCC0:0xCC8] = bytes.fromhex(
                '1360174040004700' if marker == 0x35 else '1350261030005300')
            target[0x1D] = (target[0x1D] & 0xD4) | (marker & 0x2B)
            merged = radio._merge_upload(bytes(target))
            expected = bytearray(target)
            expected[0x0D40:0x0D48] = b'SHARED01'
            self.assertEqual(merged, bytes(expected))
        self.assertEqual(radio.get_mmap().get_packed(), source)

    def test_full_upload_retains_target_nonblank_programming_password(self):
        radio = fixture_radio()
        source = bytearray(radio.get_mmap().get_packed())
        source[driver.PASSWORD_REGION] = b'OTHER1'
        radio._mmap = memmap.MemoryMapBytes(bytes(source))
        target = bytearray(source)
        target[driver.PASSWORD_REGION] = b'TEST42'
        fake = SimulatedRadio(bytes(target))
        radio.pipe = fake
        radio.status_fn = lambda status: None
        # Offline protocol simulation only; production uploads stay disabled.
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            radio.sync_out()
        self.assertEqual(bytes(fake.image), bytes(target))
        self.assertEqual(radio.get_mmap().get_packed(), bytes(source))
        self.assertEqual(len(fake.uploads), 250)
        self.assertTrue(all(request == driver.MAGIC or
                            request in (b'\x02', b'\x06', b'E',
                                        b'PORT_CLOSE', b'PORT_OPEN') or
                            request[:1] in (b'R', b'W')
                            for request in fake.requests))
        settings, fields = settings_by_name(radio)
        self.assertFalse(any('password' in name.lower() for name in fields))

    def test_reopen_failure_aborts_before_memory_write(self):
        radio = fixture_radio()
        fake = SimulatedRadio(radio.get_mmap().get_packed())
        radio.pipe = fake
        radio.status_fn = lambda status: None
        with mock.patch.object(fake, 'open', side_effect=OSError('busy')):
            with self.assertRaisesRegex(errors.RadioError, 'busy'):
                radio.sync_out()
        self.assertFalse(fake.uploads)
        self.assertEqual(fake.requests.count(driver.MAGIC), 1)

    def test_cps_write_session_and_separate_verification_read(self):
        radio = fixture_radio()
        image = radio.get_mmap().get_packed()
        fake = SimulatedRadio(image)
        radio.pipe = fake
        radio.status_fn = lambda status: None
        self.clock.sleep.side_effect = lambda seconds: self.assertFalse(
            fake.is_open)
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            radio.sync_out()
        starts = [i for i, request in enumerate(fake.requests)
                  if request == driver.MAGIC]
        self.assertEqual(len(starts), 3)
        self.assertEqual(self.clock.sleep.call_args_list,
                         [mock.call(5), mock.call(5)])
        for start in starts[1:]:
            self.assertEqual(fake.requests[start - 2:start],
                             [b'PORT_CLOSE', b'PORT_OPEN'])
        write = fake.requests[starts[1]:starts[2] - 2]
        self.assertEqual(write[:4], [driver.MAGIC, b'\x02', b'\x06',
                                     b'R\x1b\x40\x20'])
        self.assertEqual([int.from_bytes(r[1:3], 'big') for r in write[4:-2]],
                         list(range(0, 8000, 32)))
        self.assertTrue(all(r[:1] == b'W' and r[3] == 32
                            for r in write[4:-2]))
        self.assertEqual(write[-2:], [b'E', b'\x02'])
        self.assertEqual(sum(r[:1] == b'R'
                             for r in fake.requests[starts[2]:]), 251)

    def test_readback_mismatch_is_failure_without_retry(self):
        class CorruptAfterWrite(SimulatedRadio):
            def write(self, data):
                result = super().write(data)
                if data == b'E' and len(self.uploads) == 250:
                    self.image[0x0D40] ^= 1
                return result
        radio = fixture_radio()
        fake = CorruptAfterWrite(radio.get_mmap().get_packed())
        radio.pipe = fake
        radio.status_fn = lambda status: None
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            with self.assertRaisesRegex(errors.RadioError, 'readback differs'):
                radio.sync_out()
        self.assertEqual(len(fake.uploads), 250)

    def test_changed_preflight_aborts_before_upload(self):
        class ChangingTarget(SimulatedRadio):
            sessions = 0

            def write(self, data):
                if data == driver.MAGIC:
                    self.sessions += 1
                    if self.sessions == 2:
                        self.image[0x1B40] ^= 1
                return super().write(data)
        radio = fixture_radio()
        fake = ChangingTarget(radio.get_mmap().get_packed())
        radio.pipe = fake
        radio.status_fn = lambda status: None
        with mock.patch.object(driver, 'UPLOAD_ENABLED', True):
            with self.assertRaisesRegex(errors.RadioError,
                                        'preflight changed'):
                radio.sync_out()
        self.assertFalse(fake.uploads)


if __name__ == '__main__':
    unittest.main()
