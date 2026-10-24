# SPDX-License-Identifier: GPL-3.0-or-later
"""Experimental SHIQUN SQ-8500 driver.
Testing was performed but not every function was tested.
Other potentially compatible models:
- KSUN UV119D
- Motolola MT-628
- CRWSTA GK-8500UV (GX-8500UV)
"""

import logging
import struct
import time
from decimal import Decimal, InvalidOperation

from chirp import chirp_common, directory, errors, memmap
from chirp.settings import (RadioSetting, RadioSettingGroup, RadioSettings,
                            RadioSettingValueBoolean, RadioSettingValueList,
                            RadioSettingValueString)

LOG = logging.getLogger(__name__)


IMAGE_SIZE = 0x1F40
BLOCK_SIZE = 0x20
# Six-byte programming password here.
# Never expose or change it, including when cloning images.
PASSWORD_REGION = slice(0x1B40, 0x1B46)
IDENT = b'P31183\xff\xff'
MAGIC = bytes.fromhex('505b4f4a485e44')
# The numerical values distinguish CHIRP power objects. Actual RF output has
# not been measured; these are ordinal labels, not claimed wattages.
POWER = [chirp_common.PowerLevel(label, dBm=index)
         for index, label in enumerate(['Low', 'Mid', 'High'])]
# Allow disabling upload functionality.
UPLOAD_ENABLED = True
UPLOAD_GROUPS = [('options', 'General Settings'), ('vfo', 'VFO A and B'),
                 ('fm', 'FM Broadcast'), ('dtmf', 'DTMF')]
UPLOAD_METADATA = 'sq8500_upload_groups'
DTMF_CHARS = '0123456789ABCD*#'
DTCS_CODES = sorted(set(chirp_common.DTCS_CODES) | {645})
TONE_CHOICES = (['OFF'] + [str(t) for t in chirp_common.TONES] +
                ['D%03d%s' % (c, p) for p in ('N', 'I')
                 for c in DTCS_CODES])

# (name, label, byte offset, mask, shift, choices, group, encoded values)
FIELD_SPECS = [
    ('active_vfo', 'Active VFO', 0x1960, 0x01, 0, ['A', 'B'],
     'options', None),
    ('vfo_channel_A', 'Selected channel', 0x0CA4, 0xFF, 0,
     [str(n) for n in range(1, 200)], 'vfo', list(range(1, 200))),
    ('vfo_channel_B', 'Selected channel', 0x0CA5, 0xFF, 0,
     [str(n) for n in range(1, 200)], 'vfo', list(range(1, 200))),
    ('opt_1017', 'Squelch', 3241, 15, 0, [
     '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'], 'options', None),
    ('opt_1031',
     'Time out',
     3242,
     7,
     0,
     ['OFF',
      '30S',
      '60S',
      '90S',
      '120S',
      '150S',
      '180S',
      '210S'],
     'options',
     None),
    ('opt_1018', 'Backlight', 3234, 96, 5, [
     'CONT', '10S', '20S', '30S'], 'options', None),
    ('opt_1059', 'Auto lock', 3233, 16, 4, ['OFF', 'ON'], 'options', None),
    ('opt_1019', 'Dual receive', 3235, 4, 2, ['OFF', 'ON'], 'options', None),
    ('opt_1022', 'Battery save', 3233, 8, 3, ['OFF', 'ON'], 'options', None),
    ('opt_1026', 'Voice prompt', 3233, 1, 0, ['OFF', 'ON'], 'options', None),
    ('opt_1036', 'Language', 3243, 1, 0, [
     'Chinese', 'English'], 'options', None),
    ('opt_1027', 'VOX gain', 3239, 3, 0, [
     'OFF', '1', '2', '3'], 'options', None),
    ('opt_1028', 'VOX delay', 3246, 3, 0, [
     '0.5S', '1.0S', '2.0S', '3.0S'], 'options', None),
    ('opt_1056', 'Scan mode', 3233, 192, 6,
     ['TO', 'CO', 'SE'], 'options', None),
    ('opt_1040', 'Priority TX', 3232, 1, 0, ['Edit', 'Busy'], 'options', None),
    ('opt_1029',
     'PF1 short',
     3216,
     7,
     0,
     ['None',
      'Scan',
      'FM',
      'Warn',
      'TONE',
      'Weather',
      'Lamp',
      'ANC'],
     'options',
     None),
    ('opt_1032',
     'PF1 long',
     3217,
     15,
     0,
     ['None',
      'Scan',
      'FM',
      'Warn',
      'TONE',
      'Weather',
      'Lamp',
      'ANC',
      'Monitor'],
     'options',
     None),
    ('opt_1033',
     'PF2 short',
     3218,
     7,
     0,
     ['None',
      'Scan',
      'FM',
      'Warn',
      'TONE',
      'Weather',
      'Lamp',
      'ANC'],
     'options',
     None),
    ('opt_1020', 'Channel name', 3234, 4, 2, ['OFF', 'ON'], 'options', None),
    ('opt_1047',
     'PF2 long',
     3219,
     15,
     0,
     ['None',
      'Scan',
      'FM',
      'Warn',
      'TONE',
      'Weather',
      'Lamp',
      'ANC',
      'Monitor'],
     'options',
     None),
    ('opt_1021', 'Power-on display', 3221, 3,
     0, ['OFF', 'Msg', 'DC'], 'options', None),
    ('opt_1044', 'Mic gain', 3220, 15, 0, [
     '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'], 'options', None),
    ('opt_1058', 'Work mode', 3227, 1, 0, [
     'Double Display', 'Single Display'], 'options', None),
    ('opt_1035', 'Beep', 3233, 4, 2, None, 'options', None),
    ('opt_1085', 'Roger', 3239, 32, 5, None, 'options', None),
    ('opt_1041', 'TX LCD', 3232, 128, 7, None, 'options', None),
    ('opt_1042', 'RX LCD', 3232, 64, 6, None, 'options', None),
    ('opt_1090', 'QT/DQT tail', 3239, 64, 6, None, 'options', None),
    ('opt_1038', 'ANC', 3232, 4, 2, None, 'options', None),
    ('vfo_1018', 'A power', 7006, 16, 4, ['Low', 'High'], 'vfo', None),
    ('vfo_1019', 'A bandwidth', 7006, 8, 3, ['Wide', 'Narrow'], 'vfo', None),
    ('vfo_1020', 'A busy lock', 7005, 4, 2, ['OFF', 'ON'], 'vfo', None),
    ('vfo_1021', 'A special QT/DQT', 7005, 32, 5, ['OFF', 'ON'], 'vfo', None),
    ('vfo_1022', 'A work mode', 3234, 1, 0, ['VFO', 'VFO+CH'], 'vfo', None),
    ('vfo_1023', 'A offset direction', 7006,
     3, 0, ['OFF', '-', '+'], 'vfo', None),
    ('vfo_1025', 'B power', 7022, 16, 4, ['Low', 'High'], 'vfo', None),
    ('vfo_1029', 'B bandwidth', 7022, 8, 3, ['Wide', 'Narrow'], 'vfo', None),
    ('vfo_1030', 'B busy lock', 7021, 4, 2, ['OFF', 'ON'], 'vfo', None),
    ('vfo_1031', 'B special QT/DQT', 7021, 32, 5, ['OFF', 'ON'], 'vfo', None),
    ('vfo_1032', 'B work mode', 3235, 1, 0, ['VFO', 'VFO+CH'], 'vfo', None),
    ('vfo_1034', 'B offset direction', 7022,
     3, 0, ['OFF', '-', '+'], 'vfo', None),
    ('vfo_1026',
     'A tuning step',
     3240,
     112,
     4,
     ['2.5K',
      '5.0K',
      '6.25K',
      '10.0K',
      '12.5K',
      '20.0K',
      '25.0K',
      '50.0K'],
     'vfo',
     None),
    ('vfo_1027',
     'B tuning step',
     3240,
     7,
     0,
     ['2.5K',
      '5.0K',
      '6.25K',
      '10.0K',
      '12.5K',
      '20.0K',
      '25.0K',
      '50.0K'],
     'vfo',
     None),
    ('fm_1075', 'Work mode', 3234, 128, 7, ['VFO', 'CH'], 'fm', None),
    ('fm_1019',
     'Selected channel',
     3238,
     31,
     0,
     ['1',
      '2',
      '3',
      '4',
      '5',
      '6',
      '7',
      '8',
      '9',
      '10',
      '11',
      '12',
      '13',
      '14',
      '15',
      '16',
      '17',
      '18',
      '19',
      '20',
      '21',
      '22',
      '23',
      '24',
      '25'],
     'fm',
     None),
    ('fm_1070', 'Allow radio interruptions', 3234, 8, 3, None, 'fm', None),
    ('dtmf_1092',
     'Auto reset time (seconds)',
     3224,
     15,
     0,
     ['OFF',
      '1',
      '2',
      '3',
      '4',
      '5',
      '6',
      '7',
      '8',
      '9',
      '10',
      '11',
      '12',
      '13',
      '14',
      '15'],
     'dtmf',
     None),
    ('dtmf_1079', 'Stun enable', 3223, 1, 0, None, 'dtmf', None),
    ('dtmf_1080', 'Kill enable', 3223, 2, 1, None, 'dtmf', None),
    ('dtmf_1081', 'DTMF side tone', 3232, 2, 1, None, 'dtmf', None),
    ('dtmf_1046', 'ANI', 3239, 128, 7, None, 'dtmf', None),
    ('dtmf_1090', 'Group code', 5161, 255, 0, [
     'OFF', '*', '#', 'A', 'B', 'C', 'D'],
     'dtmf', [255, 14, 15, 10, 11, 12, 13]),
]

CHANNEL_SPECS = [
    ('busylock', 'Busy lock', 13, 0x04, 2, ['OFF', 'ON']),
    ('special', 'Special QT/DQT', 13, 0x10, 4, ['OFF', 'ON']),
    ('scramble', 'Scramble', 15, 0x0F, 0,
     ['OFF'] + [str(n) for n in range(1, 9)]),
    ('hop', 'Frequency hopping', 14, 0x40, 6, ['OFF', 'ON']),
    ('pttid', 'PTT ID', 13, 0xC0, 6, ['OFF', 'BOT', 'EOT', 'BOTH']),
]


# Presentation only: setting identifiers and encoded choices remain stable.
SETTING_UI = {
    'active_vfo': ('Active VFO',
                   'Select display A or B for tuning and keypad controls.'),
    'vfo_channel_A': ('Selected channel',
                      'Memory channel selected on display A.'),
    'vfo_channel_B': ('Selected channel',
                      'Memory channel selected on display B.'),
    'opt_1017': ('Squelch level',
                 'Receive squelch threshold; 0 opens squelch.'),
    'opt_1031': ('Transmit time limit [Time out]',
                 'Maximum continuous transmission time; OFF disables the '
                 'timer.'),
    'opt_1018': ('Backlight timeout [Light Control]',
                 'How long the display backlight stays on; CONT is '
                 'continuous.'),
    'opt_1059': ('Automatic keypad lock [Auto Lock]',
                 'Automatically lock the keypad when idle.'),
    'opt_1019': ('Dual watch [Double Rx]',
                 'Monitor the A and B sides with dual watch.'),
    'opt_1022': ('Battery saver',
                 'Enable the radio battery-saving option.'),
    'opt_1026': ('Voice announcements [Voice Prompt]',
                 'Enable spoken radio prompts.'),
    'opt_1036': ('Voice/menu language [Language]',
                 'Select the radio language, not the CHIRP interface '
                 'language.'),
    'opt_1027': ('VOX sensitivity [VOX Gain]',
                 'Voice-operated transmit sensitivity; OFF disables VOX.'),
    'opt_1028': ('VOX release delay [VOX Delay]',
                 'Delay before voice-operated transmission ends after '
                 'speech.'),
    'opt_1056': ('Scan resume mode',
                 'TO: resume after a timed pause. CO: resume when the signal '
                 'clears. SE: stop scanning when a signal is found.'),
    'opt_1040': ('Transmit selection [Priority TX]',
                 'Choose the Edit or Busy transmit-priority setting for the '
                 'A/B sides.'),
    'opt_1020': ('Show channel names [Channel Name]',
                 'Enable the radio channel-name display option.'),
    'opt_1021': ('Power-on display [PONMSG]',
                 'OFF: no custom startup display; Msg: the four message '
                 'lines; DC: battery voltage.'),
    'opt_1044': ('Microphone gain [MIC GAIN]',
                 'Microphone gain level from 0 to 9.'),
    'opt_1058': ('Display layout [Work Mode]',
                 'Choose a single display or the A/B dual display. This is '
                 'separate from dual watch.'),
    'opt_1035': ('Keypad beep [Beep]',
                 'Enable audible key/operation feedback.'),
    'opt_1085': ('End-of-transmission beep [Roger]',
                 'Enable the radio roger-beep option at the end of transmit.'),
    'opt_1041': ('Display during transmit [Disp Lcd(TX)]',
                 'Enable the display during transmission.'),
    'opt_1042': ('Display during receive [Disp Lcd(RX)]',
                 'Enable the display during reception.'),
    'opt_1090': ('Tone tail control [QT/DQT Tail]',
                 'Enable CTCSS/DCS tone-tail control at the end of a '
                 'transmission.'),
    'opt_1038': ('Noise reduction [ANC]',
                 'Enable active noise reduction.'),
    'fm_1075': ('Tuning mode [Work Mode]',
                'CH selects stored FM broadcast presets; VFO selects '
                'tuning.'),
    'fm_1019': ('Selected preset [Channel]',
                'Stored FM broadcast preset selected by the radio.'),
    'fm_1070': ('Allow radio interruptions [Forbid Receive]',
                'Allow received signals on the normal radio channels to '
                'interrupt FM broadcast listening. This does not disable '
                'the FM broadcast receiver.'),
    'dtmf_1092': ('Signaling reset timer [Auto Reset Time]',
                  'DTMF signaling reset interval in seconds; OFF disables the '
                  'timer.'),
    'dtmf_1079': ('Allow remote disable [Stun]',
                  'Allow the received Stun code to activate the '
                  'remote-disable function.'),
    'dtmf_1080': ('Allow remote inhibit [Kill]',
                  'Allow the received Kill code to activate the '
                  'remote-inhibit function.'),
    'dtmf_1081': ('Audible DTMF feedback [DTMF Side Tone]',
                  'Enable local audible feedback for DTMF signaling.'),
    'dtmf_1046': ('Automatic identification [ANI]',
                  'Enable automatic number identification for DTMF '
                  'signaling.'),
    'dtmf_1090': ('Group-call character [Group Code]',
                  'DTMF group-call character, or OFF to disable grouping.'),
}

OPTION_ORDER = [
    'active_vfo', 'opt_1017', 'opt_1031', 'opt_1019', 'opt_1040', 'opt_1056',
    'opt_1022', 'opt_1044', 'opt_1038', 'opt_1027', 'opt_1028',
    'opt_1059', 'opt_1026', 'opt_1036', 'opt_1035', 'opt_1085', 'opt_1090',
    'opt_1029', 'opt_1032', 'opt_1033', 'opt_1047',
    'opt_1058', 'opt_1020', 'opt_1018', 'opt_1041', 'opt_1042', 'opt_1021',
] + ['message_%d' % i for i in range(4)]

VFO_FIELDS = {
    'A': ['vfo_1022', 'vfo_1026', 'vfo_1018', 'vfo_1019',
          'vfo_1020', 'vfo_1021', 'vfo_1023'],
    'B': ['vfo_1032', 'vfo_1027', 'vfo_1025', 'vfo_1029',
          'vfo_1030', 'vfo_1031', 'vfo_1034'],
}
for side, names in VFO_FIELDS.items():
    for name, label, doc in zip(names, [
            'Tuning mode [Work Mode]', 'Tuning step', 'Power', 'Bandwidth',
            'Busy-channel lockout [Busy Lock]', 'Special tone mode [SPEC]',
            'Repeater shift [Offset]'], [
            'Select frequency mode (VFO) or combined frequency/channel '
            'mode (VFO+CH).',
            'Frequency increment used when tuning this VFO.',
            'Select the transmit power level.',
            'Wide or narrow FM bandwidth.',
            'Inhibit transmission when the channel is busy.',
            'Enable special CTCSS/DCS tone mode.',
            'Transmit frequency shift direction; OFF selects no shift.']):
        SETTING_UI[name] = (label, doc)
for name, button, press in [('opt_1029', 1, 'short'),
                            ('opt_1032', 1, 'long'),
                            ('opt_1033', 2, 'short'),
                            ('opt_1047', 2, 'long')]:
    SETTING_UI[name] = (
        'PF%d %s press' % (button, press),
        'Function assigned to a %s press of programmable key PF%d.' %
        (press, button))


def _describe(setting, label, doc):
    setting.set_shortname(label)
    setting.set_doc(doc)
    return setting


def decode_bcd(data):
    digits = data[::-1].hex()
    if any(c not in '0123456789' for c in digits):
        raise errors.RadioError('Invalid packed BCD: %s' % data.hex())
    return int(digits)


def encode_bcd(value, size):
    if value < 0 or value >= 10 ** (size * 2):
        raise errors.RadioError('Value does not fit packed BCD')
    return bytes.fromhex(('%0*d' % (size * 2, value)))[::-1]


def decode_tone(data):
    word = int.from_bytes(data, 'little')
    if word == 0xFFFF:
        return '', None, None
    if word & 0x8000:
        code = decode_bcd((word & 0x3FFF).to_bytes(2, 'little'))
        return 'DTCS', code, 'R' if word & 0x4000 else 'N'
    return 'Tone', decode_bcd(data) / 10.0, None


def encode_tone(tone):
    mode, value, polarity = tone
    if not mode:
        return b'\xff\xff'
    if mode == 'Tone':
        return encode_bcd(round(value * 10), 2)
    if mode == 'DTCS' and polarity in ('N', 'R'):
        code = int.from_bytes(encode_bcd(value, 2), 'little')
        return (code | 0x8000 | (0x4000 if polarity == 'R' else 0)
                ).to_bytes(2, 'little')
    raise errors.RadioError('Unsupported tone encoding')


class Protocol:
    """Bounded serial framing, independent of USB packet boundaries."""

    def __init__(self, pipe):
        self.pipe = pipe

    def read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            chunk = self.pipe.read(size - len(result))
            if not chunk:
                raise errors.RadioError('Incomplete radio response (%d/%d)' %
                                        (len(result), size))
            result.extend(chunk)
        return bytes(result)

    def ack(self):
        if self.read_exact(1) != b'\x06':
            raise errors.RadioError('Unexpected radio acknowledgement')

    def enter(self):
        self.pipe.write(MAGIC)
        first = self.pipe.read(1)
        if not first:
            raise errors.RadioNoResponse()
        if first != b'\x06':
            raise errors.RadioError('Radio rejected programming entry')
        self.pipe.write(b'\x02')
        if self.read_exact(8) != IDENT:
            raise errors.RadioError('Unexpected radio model identification')
        self.pipe.write(b'\x06')
        self.ack()

    def read_block(self, address):
        header = struct.pack('>cHB', b'R', address, BLOCK_SIZE)
        self.pipe.write(header)
        response = self.read_exact(BLOCK_SIZE + 5)
        if response[:4] != b'W' + header[1:]:
            raise errors.RadioError('Incorrect response address or length')
        payload = response[4:-1]
        if sum(payload) & 0xFF != response[-1]:
            raise errors.RadioError('Radio block checksum mismatch')
        return payload

    def write_block(self, address, payload):
        # Uses the full write sequence; no automatic retries.
        if len(payload) != BLOCK_SIZE or not 0 <= address < IMAGE_SIZE or \
                address % BLOCK_SIZE:
            raise errors.RadioError('Invalid upload block')
        header = struct.pack('>cHB', b'W', address, len(payload))
        self.pipe.write(header + payload + bytes([sum(payload) & 0xFF]))
        self.ack()

    def finish(self):
        self.pipe.write(b'E')
        self.ack()
        self.pipe.write(b'\x02')


DTMF_STRINGS = [
    ('stun_code', 'Stun code', 0x1400, 8),
    ('kill_code', 'Kill code', 0x1410, 8),
    ('ptt_bot', 'PTT ID starting (BOT)', 0x14C0, 7),
    ('ptt_eot', 'PTT ID ending (EOT)', 0x14D0, 7),
] + [('call_%d' % i, 'Call code %d' % (i + 1), 0x1430 + i * 16, 15)
     for i in range(8)]


def _ascii(data):
    return ''.join(chr(c) if 32 <= c < 127 else '?'
                   for c in data.split(b'\x00')[0].split(b'\xff')[0])


def _string_setting(name, label, value, maximum,
                    charset=chirp_common.CHARSET_ASCII):
    return RadioSetting(name, label, RadioSettingValueString(
        0, maximum, value, autopad=False, charset=charset))


def _list_setting(name, label, choices, index):
    options = list(choices)
    if index < 0 or index >= len(options):
        options.append('Unknown (preserved)')
        index = len(options) - 1
    return RadioSetting(name, label, RadioSettingValueList(
        options, current_index=index))


def _walk(group):
    for item in group:
        if isinstance(item, RadioSetting):
            yield item
        else:
            yield from _walk(item)


def _mhz_units(text, multiplier):
    try:
        value = Decimal(text) * multiplier
        if not value.is_finite() or value < 0 or value != value.to_integral():
            raise ValueError()
        return int(value)
    except (InvalidOperation, ValueError):
        raise errors.RadioError('Invalid frequency or unsupported precision')


def _stored_bands(image):
    limits = image[0x0CC0:0x0CC8]
    if len(limits) != 8 or any((b >> 4) > 9 or (b & 15) > 9 for b in limits):
        raise errors.RadioError('Invalid stored band limits in radio image')
    values = [int(limits[i:i + 2].hex()) * 100000 for i in range(0, 8, 2)]
    bands = list(zip(values[::2], values[1::2]))
    if any(low <= 0 or low >= high for low, high in bands):
        raise errors.RadioError('Invalid stored band limits in radio image')
    return bands


def _check_frequency(hz, bands):
    if not any(low <= hz <= high for low, high in bands):
        raise errors.RadioError('Frequency is outside the stored radio bands')


def _tone_label(tone):
    mode, value, polarity = tone
    if not mode:
        return 'OFF'
    if mode == 'Tone':
        return '%.1f' % value
    return 'D%03d%s' % (value, 'I' if polarity == 'R' else 'N')


def _tone_bytes(label):
    if label == 'OFF':
        return b'\xff\xff'
    if label.startswith('D'):
        return encode_tone(('DTCS', int(label[1:-1]),
                            'R' if label.endswith('I') else 'N'))
    return encode_tone(('Tone', float(label), None))


@directory.register
class ShiqunSQ8500Radio(chirp_common.CloneModeRadio):
    VENDOR = 'SHIQUN'
    MODEL = 'SQ-8500'
    BAUD_RATE = 57600
    _memsize = IMAGE_SIZE

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = (
            'Experimental SQ-8500 support. Save a fresh download from the '
            'connected radio before uploading.' if UPLOAD_ENABLED else
            'Experimental SQ-8500 support. Uploads are disabled in this '
            'build.')
        prompts.pre_upload = (
            'The image replaces all channel memories, including empty slots. '
            'Optional settings groups are controlled under Settings > '
            'Upload options. Passwords and unmapped target data are retained.')
        return prompts

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 199)
        # CHIRP uses exclusive upper bounds; include the endpoint on our
        # 10 Hz frequency grid.
        rf.valid_bands = [(low, high + 10) for low, high in self._bands()]
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_duplexes = ['', '+', '-', 'split']
        rf.can_odd_split = True
        rf.has_nostep_tuning = True
        rf.valid_cross_modes = ['Tone->Tone', 'Tone->DTCS', 'DTCS->Tone',
                                '->Tone', '->DTCS', 'DTCS->', 'DTCS->DTCS']
        rf.valid_skips = ['', 'S']
        rf.valid_power_levels = POWER
        rf.valid_name_length = 8
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.has_tuning_step = False
        rf.valid_tuning_steps = []
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_settings = True
        return rf

    def _bands(self):
        if getattr(self, '_mmap', None) is None:
            # Discovery can ask for features before downloading an image.
            return [(136000000, 174000000), (400000000, 470000000)]
        return _stored_bands(self._mmap.get_packed())

    def process_mmap(self):
        if len(self._mmap) != IMAGE_SIZE:
            raise errors.RadioError('Expected an 8000-byte radio image.')
        self._bands()

    def _configure_pipe(self):
        self.pipe.timeout = 2
        self.pipe.parity = 'N'
        self.pipe.stopbits = 1
        self.pipe.bytesize = 8

    def _read_image(self, protocol, message):
        probe = protocol.read_block(0x1B40)
        image = bytearray()
        status = chirp_common.Status()
        status.msg = message
        status.max = IMAGE_SIZE
        for address in range(0, IMAGE_SIZE, BLOCK_SIZE):
            block = protocol.read_block(address)
            if address == 0x1B40 and block != probe:
                raise errors.RadioError('Repeated preflight block changed')
            image.extend(block)
            status.cur = address + BLOCK_SIZE
            self.status_fn(status)
        return bytes(image)

    def _session(self, operation, reopen=False):
        protocol = Protocol(self.pipe)
        entered = False
        try:
            if reopen:
                # A delay with the port left open did not allow re-entry on
                # hardware. Separate operations need a normal port reopen.
                self.pipe.close()
                status = chirp_common.Status()
                status.msg = 'Waiting for radio between operations'
                status.max = 1
                status.cur = 0
                self.status_fn(status)
                time.sleep(5)
                self.pipe.open()
            self._configure_pipe()
            protocol.enter()
            entered = True
            result = operation(protocol)
        except Exception as exc:
            if entered:
                try:
                    protocol.finish()
                except Exception:
                    LOG.warning('Could not complete programming cleanup')
            if isinstance(exc, errors.RadioError):
                raise
            raise errors.RadioError(
                'Radio communication failed: %s' %
                exc) from exc
        try:
            protocol.finish()
        except Exception as exc:
            raise errors.RadioError(
                'Radio completion failed: %s' %
                exc) from exc
        return result

    def sync_in(self):
        image = self._session(lambda p: self._read_image(p, 'Reading SQ-8500'))
        self._mmap = memmap.MemoryMapBytes(image)
        self.process_mmap()
        self._metadata.pop(UPLOAD_METADATA, None)

    def sync_out(self):
        if not UPLOAD_ENABLED:
            raise errors.RadioError('Read-only development build: uploads are '
                                    'disabled pending an owner write test')
        # Use separate normal read/write/read sessions, rather than mixing
        # a full download with uploads in one programming session.
        current = self._session(lambda p: self._read_image(
            p, 'Reading target before upload'))
        image = self._merge_upload(current)
        self._validate_upload(current, image)
        groups = ', '.join(sorted(self._upload_groups())) or 'none'
        changed = sum(a != b for a, b in zip(current, image))
        LOG.info('Upload: channels; optional groups: %s; %d changed bytes. '
                 'Password and unselected bits retained from target.',
                 groups, changed)
        self._session(lambda p: self._upload(p, current, image), reopen=True)
        actual = self._session(lambda p: self._read_image(
            p, 'Verifying uploaded configuration'), reopen=True)
        if actual != image:
            first = next(i for i, (a, b) in enumerate(zip(actual, image))
                         if a != b)
            raise errors.RadioError(
                'Upload readback differs at address 0x%04X; '
                'do not retry automatically' % first)

    def _upload_groups(self):
        selected = self._metadata.get(
            UPLOAD_METADATA, [name for name, label in UPLOAD_GROUPS])
        valid = {name for name, label in UPLOAD_GROUPS}
        if not isinstance(selected, list) or any(
                not isinstance(name, str) or name not in valid
                for name in selected):
            raise errors.RadioError('Invalid upload options in image metadata')
        return set(selected)

    def _upload(self, protocol, current, image):
        # The write session performs: one preflight R, all 250 W blocks,
        # then the common completion sequence. No skipped blocks or retries.
        if protocol.read_block(0x1B40) != current[0x1B40:0x1B60]:
            raise errors.RadioError('Target preflight changed before upload')
        status = chirp_common.Status()
        status.msg = 'Writing channels and selected settings'
        status.max = IMAGE_SIZE
        for address in range(0, IMAGE_SIZE, BLOCK_SIZE):
            protocol.write_block(address, image[address:address + BLOCK_SIZE])
            status.cur = address + BLOCK_SIZE
            self.status_fn(status)

    def _upload_mask(self, current):
        """Every bit authorized by the selected configuration scope."""
        wanted = self._mmap.get_packed()
        if len(current) != IMAGE_SIZE or len(wanted) != IMAGE_SIZE:
            raise errors.RadioError('Invalid source or target image length')
        groups = self._upload_groups()
        masks = bytearray(IMAGE_SIZE)
        for spec in FIELD_SPECS:
            name, label, offset, mask, shift, choices, group, values = spec
            if group in groups:
                masks[offset] |= mask
        masks[0x0D40:0x0D40 + 199 * 8] = b'\xff' * (199 * 8)
        if 'options' in groups:
            masks[0x1390:0x13D0] = b'\xff' * 64
        if 'vfo' in groups:
            masks[0x0CB0:0x0CB8] = b'\xff' * 8
            for base in (0x1B50, 0x1B60):
                masks[base:base + 12] = b'\xff' * 12
        if 'dtmf' in groups:
            masks[0x1420:0x1423] = b'\xff' * 3
            for _, _, offset, _ in DTMF_STRINGS:
                masks[offset:offset + 16] = b'\xff' * 16
        if 'fm' in groups:
            for i in range(25):
                start = 0x0CD0 + i * 4
                masks[start:start + 2] = b'\xff\xff'
                masks[0x1B70 + i // 8] |= 1 << (i % 8)
        for n in range(1, 200):
            base, index, bit = self._locations(n)
            present = bool(wanted[0x1A00 + index] & bit)
            was_present = bool(current[0x1A00 + index] & bit)
            masks[0x1A00 + index] |= bit
            masks[0x1A20 + index] |= bit
            if present != was_present:
                # Allocation/deletion explicitly initializes full records.
                masks[base:base + 16] = b'\xff' * 16
                if present:
                    aux = 0x1C00 + (n - 1) * 4
                    masks[aux:aux + 4] = b'\xff' * 4
            elif present:
                masks[base:base + 12] = b'\xff' * 12
                masks[base + 14] |= 0x38
                for _, _, offset, mask, _, _ in CHANNEL_SPECS:
                    masks[base + offset] |= mask
        return bytes(masks)

    def _validate_upload(self, current, image):
        if len(image) != IMAGE_SIZE:
            raise errors.RadioError('Invalid merged image length')
        if image[PASSWORD_REGION] != current[PASSWORD_REGION]:
            raise errors.RadioError('Refusing to change programming password')
        masks = self._upload_mask(current)
        for i, (old, new, mask) in enumerate(zip(current, image, masks)):
            if (old ^ new) & ~mask:
                raise errors.RadioError(
                    'Upload would change a protected bit at 0x%04X' % i)
        bands = _stored_bands(current)
        for n in range(1, 200):
            base, index, bit = self._locations(n)
            if not image[0x1A00 + index] & bit:
                continue
            if (current[0x1A00 + index] & bit and
                    image[base:base + 8] == current[base:base + 8]):
                continue
            for start in (base, base + 4):
                _check_frequency(decode_bcd(image[start:start + 4]) * 10,
                                 bands)
        for base in (0x1B50, 0x1B60):
            for start in (base, base + 4):
                if image[start:start + 4] != current[start:start + 4]:
                    _check_frequency(decode_bcd(image[start:start + 4]) * 10,
                                     bands)

    def _merge_upload(self, current):
        """Apply selected fields to target, with known allocation rules.
        """
        masks = self._upload_mask(current)
        wanted = bytearray(self._mmap.get_packed())
        for n in range(1, 200):
            base, index, bit = self._locations(n)
            present = bool(wanted[0x1A00 + index] & bit)
            was_present = bool(current[0x1A00 + index] & bit)
            if not present and was_present:
                wanted[base:base + 16] = b'\xff' * 16
            elif present and not was_present:
                # Explicit defaults for reserved bits in a new record.
                wanted[base + 12] = 0
                wanted[base + 13] &= 0xD4
                wanted[base + 14] &= 0x78
                wanted[base + 15] &= 0x0F
                aux = 0x1C00 + (n - 1) * 4
                wanted[aux:aux + 4] = b'\xff' * 4
        result = bytes((old & ~mask) | (new & mask)
                       for old, new, mask in zip(current, wanted, masks))
        self._validate_upload(current, result)
        return result

    def _locations(self, number):
        if not isinstance(number, int) or not 1 <= number <= 199:
            raise errors.InvalidMemoryLocation(number)
        return number * 16, (number - 1) // 8, 1 << ((number - 1) % 8)

    def get_memory(self, number):
        base, index, mask = self._locations(number)
        memory = chirp_common.Memory()
        memory.number = number
        if not self._mmap[0x1A00 + index][0] & mask:
            memory.empty = True
            return memory
        record = self._mmap[base:base + 16]
        chirp_common.split_to_offset(
            memory, decode_bcd(record[:4]) * 10, decode_bcd(record[4:8]) * 10)
        chirp_common.split_tone_decode(
            memory, decode_tone(record[10:12]), decode_tone(record[8:10]))
        memory.mode = 'NFM' if record[14] & 0x08 else 'FM'
        power_index = (record[14] >> 4) & 3
        memory.power = POWER[power_index if power_index < 3 else 2]
        memory.skip = '' if self._mmap[0x1A20 + index][0] & mask else 'S'
        name = self._mmap[0x0D40 + (number - 1) * 8:
                          0x0D40 + number * 8]
        memory.name = name.split(b'\xff')[0].split(b'\x00')[
            0].decode('ascii').rstrip()
        memory.extra = RadioSettingGroup('extra', 'Extra')
        docs = {
            'busylock': ('Busy-channel lockout [Busy Lock]',
                         'Inhibit transmission when this channel is '
                         'busy.'),
            'special': ('Special tone mode [SPEC]',
                        'Enable special CTCSS/DCS tone mode.'),
            'scramble': ('Voice scrambler [Scramble]',
                         'Select the voice-scrambler code, or OFF to '
                         'disable scrambling.'),
            'hop': ('Frequency hopping [Hop]',
                    'Enable frequency hopping for this channel.'),
            'pttid': ('PTT identification [PTT ID]',
                      'OFF, beginning (BOT), end (EOT), or both. '
                      'Uses the DTMF PTT identification codes.'),
        }
        for name, label, offset, mask, shift, choices in CHANNEL_SPECS:
            current = (record[offset] & mask) >> shift
            memory.extra.append(_describe(
                _list_setting(name, label, choices, current), *docs[name]))
        return memory

    def set_memory(self, memory):
        base, index, mask = self._locations(memory.number)
        old = self.get_memory(memory.number)
        candidate = bytearray(self._mmap.get_packed())
        if memory.empty:
            candidate[base:base + 16] = b'\xff' * 16
            candidate[0x1A00 + index] &= ~mask
            candidate[0x1A20 + index] &= ~mask
            self._mmap = memmap.MemoryMapBytes(bytes(candidate))
            return
        problems = [p for p in self.validate_memory(memory)
                    if isinstance(p, chirp_common.ValidationError)]
        if problems:
            raise errors.RadioError('; '.join(map(str, problems)))
        txfreq = memory.freq
        if memory.duplex == 'split':
            txfreq = memory.offset
        elif memory.duplex == '+':
            txfreq += memory.offset
        elif memory.duplex == '-':
            txfreq -= memory.offset
        _check_frequency(memory.freq, self._bands())
        _check_frequency(txfreq, self._bands())
        if memory.freq % 10 or txfreq % 10:
            raise errors.RadioError('Frequencies must be multiples of 10 Hz')
        if old.empty:
            record = bytearray(12) + bytearray.fromhex('00002000')
            candidate[0x0D40 + (memory.number - 1) * 8:
                      0x0D40 + memory.number * 8] = b'\xff' * 8
            aux = 0x1C00 + (memory.number - 1) * 4
            candidate[aux:aux + 4] = b'\xff' * 4
        else:
            record = bytearray(candidate[base:base + 16])
        record[:4] = encode_bcd(memory.freq // 10, 4)
        record[4:8] = encode_bcd(txfreq // 10, 4)
        tx, rx = chirp_common.split_tone_encode(memory)
        record[8:10] = encode_tone(rx)
        record[10:12] = encode_tone(tx)
        record[14] = ((record[14] & ~0x08) |
                      (0x08 if memory.mode == 'NFM' else 0))
        if old.empty or memory.power != old.power:
            level = str(memory.power) if memory.power is not None else 'High'
            try:
                power = [str(p) for p in POWER].index(level)
            except ValueError:
                raise errors.RadioError('Unsupported power level')
            record[14] = (record[14] & ~0x30) | (power << 4)
        extras = {e.get_name(): e for e in memory.extra}
        for name, label, offset, mask_bit, shift, choices in CHANNEL_SPECS:
            if name not in extras:
                continue
            value = int(extras[name].value)
            if value >= len(choices):
                # Unknown stored values may be displayed but never invented.
                if extras[name].changed():
                    raise errors.RadioError('Unsupported channel option')
                continue
            record[offset] = ((record[offset] & ~mask_bit) | (value << shift))
        if memory.name != old.name:
            name = memory.name.encode('ascii').ljust(8, b'\x00')
            candidate[0x0D40 + (memory.number - 1) * 8:
                      0x0D40 + memory.number * 8] = name
        candidate[base:base + 16] = record
        candidate[0x1A00 + index] |= mask
        if memory.skip == 'S':
            candidate[0x1A20 + index] &= ~mask
        else:
            candidate[0x1A20 + index] |= mask
        self._mmap = memmap.MemoryMapBytes(bytes(candidate))

    def get_settings(self):
        groups = {name: RadioSettingGroup(name, label) for name, label in
                  [('options', 'General Settings'),
                   ('vfo_a', 'VFO A'), ('vfo_b', 'VFO B'),
                   ('fm', 'FM Broadcast'), ('dtmf', 'DTMF'),
                   ('information', 'Radio Information'),
                   ('upload', 'Upload Options')]}
        data = self._mmap.get_packed()
        selected = self._upload_groups()
        for name, label in UPLOAD_GROUPS:
            setting = RadioSetting('upload_' + name, 'Include ' + label,
                                   RadioSettingValueBoolean(name in selected))
            setting.set_doc('Channels always upload. This option also copies '
                            'this settings group from the image. Uncheck to '
                            'keep the target radio settings for this group. '
                            'Editing settings does not change this choice. '
                            'The choice is saved with the image file.')
            groups['upload'].append(setting)
        for spec in FIELD_SPECS:
            name, label, offset, mask, shift, choices, group, values = spec
            current = (data[offset] & mask) >> shift
            if choices is None:
                setting = RadioSetting(name, label,
                                       RadioSettingValueBoolean(bool(current)))
            else:
                encoded = values or list(range(len(choices)))
                index = encoded.index(current) if current in encoded else -1
                setting = _list_setting(name, label, choices, index)
            setting = _describe(setting, *SETTING_UI[name])
            if group == 'vfo':
                group = ('vfo_a' if name in VFO_FIELDS['A'] or
                         name == 'vfo_channel_A' else 'vfo_b')
            groups[group].append(setting)
        for i in range(4):
            start = 0x1390 + i * 16
            text = _ascii(data[start:start + 16])
            groups['options'].append(_string_setting(
                'message_%d' % i, 'Power-on message - Line %d' % (i + 1),
                text, 16))
        for side, base, offset in [('A', 0x1B50, 0x0CB0),
                                   ('B', 0x1B60, 0x0CB4)]:
            groups['vfo_' + side.lower()].append(_string_setting(
                'vfo_freq_' + side, 'Frequency (MHz)',
                '%.5f' % (decode_bcd(data[base:base + 4]) / 100000), 9,
                '0123456789.'))
            groups['vfo_' + side.lower()].append(_string_setting(
                'vfo_offset_' + side, 'Repeater offset (MHz)',
                '%.5f' % (decode_bcd(data[offset:offset + 4]) / 100000), 8,
                '0123456789.'))
            tone = decode_tone(data[base + 8:base + 10])
            choice = _tone_label(tone)
            current = TONE_CHOICES.index(
                choice) if choice in TONE_CHOICES else -1
            groups['vfo_' + side.lower()].append(_list_setting(
                'vfo_tone_' + side, 'CTCSS/DCS tone [QT/DQT]',
                TONE_CHOICES, current))
        for i in range(25):
            valid = data[0x1B70 + i // 8] & (1 << (i % 8))
            start = 0x0CD0 + i * 4
            text = '%.1f' % (decode_bcd(
                data[start:start + 2]) / 10) if valid else ''
            groups['fm'].append(_string_setting(
                'fm_preset_%d' % i, 'Preset %d (MHz, blank clears)' % (i + 1),
                text, 5, '0123456789.'))
        for name, label, offset, maximum in DTMF_STRINGS:
            length = min(data[offset + 15], maximum)
            text = ''.join(DTMF_CHARS[c] if c < 16 else '?'
                           for c in data[offset:offset + length])
            groups['dtmf'].append(_string_setting(name, label, text, maximum,
                                                  DTMF_CHARS + '?'))
        text = ''.join(str(c) if c < 10 else '?' for c in data[0x1420:0x1423])
        groups['dtmf'].append(_string_setting('self_id', 'Self ID', text, 3,
                                              '0123456789?'))
        for i, label in enumerate(
                ['VHF low', 'VHF high', 'UHF low', 'UHF high']):
            start = 0x0CC0 + i * 2
            value = int(data[start:start + 2].hex()) / 10
            setting = _string_setting('band_%d' % i, label + ' (stored MHz)',
                                      str(value), 12)
            setting.value.set_mutable(False)
            groups['information'].append(setting)
        for group in groups.values():
            for setting in group:
                name = setting.get_name()
                if name.startswith('message_'):
                    setting.set_doc('Startup text, up to 16 ASCII characters. '
                                    'Shown when Power-on display is Msg.')
                elif name.startswith('vfo_freq_'):
                    setting.set_doc('VFO frequency in MHz within supported '
                                    'radio bands, in multiples of 10 Hz.')
                elif name.startswith('vfo_offset_'):
                    setting.set_doc('Repeater shift magnitude in MHz. '
                                    'Repeater shift selects the direction.')
                elif name.startswith('vfo_tone_'):
                    setting.set_doc('Shared transmit/receive CTCSS or DCS '
                                    'setting. DxxxN is normal DCS; DxxxI is '
                                    'inverted DCS; OFF disables tones.')
                elif name.startswith('fm_preset_'):
                    setting.set_doc('FM broadcast frequency from 76 to '
                                    '108 MHz in 0.1 MHz steps. Blank clears '
                                    'this preset.')
                elif name in {s[0] for s in DTMF_STRINGS}:
                    purpose = {
                        'stun_code': 'Received code for the Stun function.',
                        'kill_code': 'Received code for the Kill function.',
                        'ptt_bot': 'Identification sent at the start of '
                                   'transmit [BOT], when PTT ID selects it.',
                        'ptt_eot': 'Identification sent at the end of '
                                   'transmit [EOT], when PTT ID selects it.',
                    }.get(name, 'Stored DTMF calling sequence.')
                    setting.set_doc(purpose + ' Use digits 0-9, A-D, * or #. '
                                    'Blank clears the code.')
                elif name == 'self_id':
                    setting.set_doc('Three-digit DTMF identification '
                                    'assigned to this radio [Self ID].')
                elif name.startswith('band_'):
                    setting.set_doc('Read-only band limit reported in the '
                                    'image. Used to validate channel and VFO '
                                    'frequencies; RF performance may vary '
                                    'within these limits.')
        orders = {'options': OPTION_ORDER}
        for side in ('A', 'B'):
            orders['vfo_' + side.lower()] = (
                ['vfo_channel_' + side, 'vfo_freq_' + side,
                 'vfo_tone_' + side] +
                VFO_FIELDS[side][:4] +
                [VFO_FIELDS[side][-1], 'vfo_offset_' + side] +
                VFO_FIELDS[side][4:6])
        for name, order in orders.items():
            original = groups[name]
            fields = {s.get_name(): s for s in original}
            groups[name] = RadioSettingGroup(
                name, original.get_shortname(),
                *(fields[key] for key in order))
        return RadioSettings(*groups.values())

    def set_settings(self, settings):
        candidate = bytearray(self._mmap.get_packed())
        selected = self._upload_groups()
        explicit = {}
        fields = {s[0]: s for s in FIELD_SPECS}
        strings = {s[0]: s for s in DTMF_STRINGS}
        for setting in _walk(settings):
            if not setting.changed():
                continue
            name = setting.get_name()
            if name.startswith('upload_'):
                group = name[len('upload_'):]
                if group not in {n for n, label in UPLOAD_GROUPS}:
                    raise errors.RadioError('Unknown upload option')
                explicit[group] = bool(setting.value)
                continue
            if name in fields:
                _, _, offset, mask, shift, choices, _, values = fields[name]
                index = int(setting.value)
                if choices and index >= len(choices):
                    raise errors.RadioError('Cannot select an unknown value')
                value = values[index] if values else index
                candidate[offset] = ((candidate[offset] & ~mask) |
                                     ((value << shift) & mask))
            elif name.startswith('message_'):
                start = 0x1390 + int(name.split('_')[-1]) * 16
                candidate[start:start + 16] = str(setting.value).encode(
                    'ascii').ljust(16, b'\x00')
            elif name.startswith('vfo_freq_'):
                base = 0x1B50 if name.endswith('A') else 0x1B60
                value = _mhz_units(str(setting.value), 100000)
                _check_frequency(value * 10, self._bands())
                candidate[base:base + 4] = encode_bcd(value, 4)
                candidate[base + 4:base + 8] = encode_bcd(value, 4)
            elif name.startswith('vfo_offset_'):
                start = 0x0CB0 if name.endswith('A') else 0x0CB4
                value = _mhz_units(str(setting.value), 100000)
                candidate[start:start + 4] = encode_bcd(value, 4)
            elif name.startswith('vfo_tone_'):
                base = 0x1B50 if name.endswith('A') else 0x1B60
                value = _tone_bytes(str(setting.value))
                candidate[base + 8:base + 12] = value * 2
            elif name.startswith('fm_preset_'):
                i = int(name.split('_')[-1])
                text = str(setting.value).strip()
                start = 0x0CD0 + i * 4
                mask = 1 << (i % 8)
                if text:
                    value = _mhz_units(text, 10)
                    if not 760 <= value <= 1080:
                        raise errors.RadioError('FM preset must be 76–108 MHz')
                    candidate[start:start + 2] = encode_bcd(value, 2)
                    candidate[0x1B70 + i // 8] |= mask
                else:
                    candidate[start:start + 2] = b'\x00\x00'
                    candidate[0x1B70 + i // 8] &= ~mask
            elif name in strings:
                _, _, offset, maximum = strings[name]
                text = str(setting.value)
                if any(c not in DTMF_CHARS for c in text) or len(
                        text) > maximum:
                    raise errors.RadioError('Invalid DTMF string')
                candidate[offset:offset + 16] = (
                    bytes(DTMF_CHARS.index(c) for c in text).ljust(
                        15, b'\xff') +
                    bytes([len(text)]))
            elif name == 'self_id':
                text = str(setting.value)
                if len(text) != 3 or not text.isascii() or not text.isdigit():
                    raise errors.RadioError(
                        'Self ID must contain three digits')
                candidate[0x1420:0x1423] = bytes(int(c) for c in text)
            else:
                raise errors.RadioError(
                    'Unknown or read-only setting: ' + name)
        self._mmap = memmap.MemoryMapBytes(bytes(candidate))
        for group, enabled in explicit.items():
            if enabled:
                selected.add(group)
            else:
                selected.discard(group)
        self._metadata[UPLOAD_METADATA] = sorted(selected)
