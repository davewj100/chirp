# Experimental SHIQUN SQ-8500 support

This branch adds a CHIRP driver for the SHIQUN SQ-8500 handheld. Development
included captured manufacturer-software transactions, controlled settings edits,
offline tests and successful downloads/uploads on two owner-operated SQ-8500s.
It is experimental community testing code, not an official CHIRP release.

## Testing the module

Use a current official CHIRP build. Download
[`shiqun_sq8500.py`](../chirp/drivers/shiqun_sq8500.py) as a Python file, enable
CHIRP's Developer Mode as needed, and load it using **File > Load module** before
opening an image or downloading from a radio. Select **SHIQUN / SQ-8500**.
Alternatively, if the module is attached to a CHIRP issue, use **Help > Load
module from issue**. Reload the module after restarting CHIRP. A full CHIRP
checkout is not required for this method.

Keep an untouched download before editing. The driver supports channels 1–199,
independent RX/TX frequencies and tones, channel names and signaling options,
general settings, A/B VFOs, FM broadcast presets and DTMF settings.
Frequency validation follows the image's stored band limits. Power selections
are Low/Mid/High labels; actual output wattages have not been measured.

Uploads first download the connected target, merge channels and selected settings,
preserve unknown and protected fields, then use the observed full write sequence
and verify with a separate download. Programming-password changes are prohibited.
An upload or verification failure is reported without an automatic retry.
Unknown data is preserved, but calibration locations have not been conclusively
identified. Not every setting's on-air behavior has been tested.

KSUN UV119D, Motolola MT-628 and CRWSTA GK/GX-8500UV are suspected related models,
not verified hardware aliases. The GK8500UV manufacturer-software file format
can be decoded offline; that does not establish hardware compatibility.

## Offline verification

The included `tests/images/SHIQUN_SQ-8500.img` is synthetic and contains no
owner's radio backup. The serial tests simulate the protocol without hardware.
With CHIRP's development dependencies installed, run from the checkout root:

```sh
CHIRP_TESTIMG=SHIQUN_SQ-8500.img python -m pytest \
  tests/test_drivers.py tests/unit/test_sq8500_transport.py \
  tests/unit/test_sq8500_upload_policy.py -q
```

`tools/read_sq8500.py` provides a headless download helper whose transport rejects
upload frames. Run it with the checkout on `PYTHONPATH`:

```sh
PYTHONPATH=. python tools/read_sq8500.py PORT NEW_OUTPUT_DIRECTORY
```

The driver and added source files are GPL-3.0-or-later, consistent with CHIRP.
