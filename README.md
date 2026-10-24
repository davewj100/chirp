# CHIRP with experimental SHIQUN SQ-8500 support

This is David Johnston's personal copy of CHIRP for testing and sharing an
experimental **SHIQUN SQ-8500** radio driver. It is not the official CHIRP
repository or an official CHIRP release.

For official downloads and support, visit [CHIRP](https://www.chirpmyradio.com).
The upstream source repository is [kk7ds/chirp](https://github.com/kk7ds/chirp).

## SQ-8500 driver

- [Driver module](chirp/drivers/shiqun_sq8500.py)
- [Loading instructions, supported features and testing notes](doc/SHIQUN-SQ-8500.md)
- [Download the Python module directly](https://raw.githubusercontent.com/davewj100/chirp/main/chirp/drivers/shiqun_sq8500.py)

The module can be loaded into a current official CHIRP installation; you do not
need to build or install this entire source tree. Read the loading instructions
before testing. Development included successful reads and writes on two
SHIQUN SQ-8500 radios, but not every feature has been verified on air.
Other brands and models mentioned in the documentation remain unverified
compatibility candidates.

## Repository scope

The complete CHIRP source tree is retained here for development and testing.
The intended upstream contribution is the SQ-8500 driver and its supporting
documentation and tests, not this entire repository as a replacement for CHIRP.
The `sq8500-development` branch keeps those changes separate from the
repository-specific README and initial license commit on `main`.

CHIRP and the added driver source are distributed under the GNU GPL; see
[COPYING](COPYING) and the source-file license notices.
