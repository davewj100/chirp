# CHIRP with SHIQUN SQ-8500 support and beta Windows dark mode

This is David Johnston's personal CHIRP development fork, with an experimental
**SHIQUN SQ-8500 radio driver** and **beta dark mode for Windows**. It is not the
official CHIRP repository or an official CHIRP release.

For official downloads and support, visit [CHIRP](https://www.chirpmyradio.com).
The upstream source repository is [kk7ds/chirp](https://github.com/kk7ds/chirp).

## Beta Windows dark mode

The Windows UI can follow the system appearance or use an explicit light or dark
theme. Choose **View > Appearance (restart required) > System / Light / Dark**,
then restart CHIRP. The preference is saved between sessions.

- Native dark menus, tabs, dialogs and controls, with matching channel-grid and
  Settings colours, readable disabled fields and a theme-aware welcome screen.
- Transfer status/model text remains visible during downloads and uploads.
- Bounded grid accessibility avoids enumerating thousands of cells during
  ordinary interaction. Arrow keys still navigate every memory; accessibility
  tree exploration exposes the focused row's cells.

Windows dark mode requires **wxPython 4.3 or later**. Development and visual
testing used **wxPython 4.3.2 / wxWidgets 3.3.4**, embedded **Python 3.10.11 amd64**,
and Windows Enterprise 26H1. The older wxPython 4.2.0 runtime retains light-mode
support. Native Windows dark support is experimental; not every specialized
dialog, driver UI or screen-reader workflow has been validated.

This is a **source/development build**, not a packaged Windows installer. The
test runtime and local profiles are not included in Git. See the
[Windows setup, launch, validation and rollback notes](doc/WINDEV-DARK-MODE.md).
For the documented sibling-runtime layout, use
[`tools/windev/Launch-CHIRP.cmd`](tools/windev/Launch-CHIRP.cmd).
Loading only the SQ-8500 driver module into an official CHIRP installation does
not add these UI changes.

## Experimental SQ-8500 driver

- [Driver module](chirp/drivers/shiqun_sq8500.py)
- [Loading instructions, supported features and testing notes](doc/SHIQUN-SQ-8500.md)
- [Download the Python module directly](https://raw.githubusercontent.com/davewj100/chirp/main/chirp/drivers/shiqun_sq8500.py)

The module can be loaded into a current official CHIRP installation; you do not
need to build or install this entire source tree. Read the loading instructions
before testing, and keep an untouched download before making changes.

Development included successful reads and writes on two owner-operated SHIQUN
SQ-8500 radios, but not every setting or on-air behaviour has been verified.
Other brands and models mentioned in the documentation remain unverified
compatibility candidates. The Windows UI work preserves the driver and its
transport/upload policy. Its latest hardware check was a successful download;
no upload was performed during that UI validation.

## Validation and repository scope

The focused offline driver and UI-accessibility suite reports **69 passed,
8 skipped and 2 xpassed**, with 17 additional passing subtests. The radio fixture
in `tests/images/SHIQUN_SQ-8500.img` is synthetic. Personal radio backups, profiles,
runtime bundles and diagnostic screenshots are kept outside this repository.

`main` includes the driver, Windows beta UI changes and this README.
`windev-dark-mode` publishes the Windows development work;
`sq8500-development` retains the earlier driver-focused baseline. The complete
CHIRP source tree is retained for development and testing; this fork does not
replace official CHIRP releases. Potential upstream contributions should be
reviewed as focused changes.

Git attributes keep text files LF in the repository and source checkouts, with
CRLF checkouts for Windows `.cmd` and `.bat` launchers.

CHIRP and the added source are distributed under the GNU GPL; see
[COPYING](COPYING), [LICENSE](LICENSE) and the source-file license notices.
