# Windows development appearance

Local feature branch: `windev-dark-mode`, based on SQ-8500 development
`bbe38fa9ac06e2f1884f64532c6854ff601a03fe`. Personal development build;
no upstream merge, push, publishing or hardware operations were performed.

## Launch and appearance

The checkout is `C:\Users\dwjohns\Documents\source\chirp\source`.
From Explorer run `source\tools\windev\Launch-CHIRP.cmd` inside the project.
The project-root `Launch-CHIRP-Dark.cmd` is also available.
Open `examples\SHIQUN_SQ-8500.img` for offline work; this is a synthetic image,
not a backup suitable for restoring a radio.

View > Appearance (restart required) offers System, Light and Dark. The default
is System. The preference is stored as `prefs.appearance` in the private
project `profile\chirp.config`; restart to apply either a new choice or a changed
Windows appearance. Choosing an appearance does not modify the open image.
Dark is disabled in the menu when the runtime has no native appearance API.

The committed launcher uses the sibling `runtime-dark` directory, locates this
checkout independently of the working directory, retains pywin32 DLL handles,
and uses the private project profile. Existing `Launch-CHIRP-Dev.cmd` and the
original `runtime` remain available for light-mode rollback.

## Runtime and reproducibility

The baseline archive was verified against SHA256
`f116d43841ade8af3aec83d084a7698281ed012a76b4355509148a52d5592928`.
Its embedded Python 3.10.11 amd64, wxPython 4.2.0 / wxWidgets 3.2.0 runtime
was retained unchanged. A live probe showed no SetAppearance or
MSWEnableDarkMode in that runtime.

`runtime-dark` is a separate copy with the official PyPI Windows CPython 3.10
amd64 wxPython 4.3.2 wheel extracted over its site-packages. All other packaged
dependencies, including numpy 1.26.4, remain unchanged. The wheel is
`wxpython-4.3.2-cp310-cp310-win_amd64.whl`, SHA256
`649cb23d5b817cd28cd54f9504a8509a73628b9063a1f7f20bca32311dd900f0`.
Its actual wx runtime reports wxWidgets 3.3.4. The baseline manifest describes
only the retained baseline, not this modified development runtime.

To reproduce, copy the baseline runtime to a new `runtime-dark` sibling,
download that exact wheel from PyPI, verify the hash and extract it into
`runtime-dark\Lib\site-packages` using Python's zipfile module. Never overwrite
a running runtime. No global Python installation, PATH change or pip bootstrap
inside the embedded runtime is required.

The approach follows wxPython's native
[SetAppearance documentation](https://wxpython.org/Phoenix/docs/html/wx.PyApp.html)
and [release notes](https://wxpython.org/pages/changes/). Native appearance is
selected immediately after wx.App construction, before creating windows.
The custom channel grid uses system colours, including selection and headers;
read-only cell backgrounds use button-face rather than the grey text colour.
Disabled Settings text uses a brighter grey in dark mode; yellow validation
highlights explicitly use black text in either mode.

## Verification on windev, 2026-10-24

- Windows Enterprise, version 26H1, build 28000.3231 (the compatibility platform
  string reports Windows-10-10.0.28000-SP0).
- Baseline light GUI opened the synthetic SQ-8500 image with Python 3.10.11 and
  wxPython 4.2.0. Native dark-mode probe returned AppearanceResult.Ok with 4.3.2.
- Real GUI inspected in dark and light: channel grid, empty cells, selection,
  focus, headers, tabs, status bar, Settings checkboxes and lists. Dark File/View
  menus, Save As, restart notice and save-before-close dialogs were inspected.
- Dark preference survived a restart. Light was selected through the menu,
  persisted and applied at the next launch. System probe reported dark, matching
  Windows AppsUseLightTheme=0. No OS appearance setting was changed.
- A new scratch image, `examples\dark-mode-edited.img`, was copied from the
  synthetic fixture. In the GUI channel 1 was renamed `d` and keypad beep was
  enabled. Saved, closed and reopened: both values persisted, verified in the
  GUI and through the driver (`opt_1035=True`).
- The saved scratch image SHA256 remained
  `1c73602fbdee8a1a4b78d1e7859f855bf12217f384c08c098096fac47f0b01bb`
  through appearance changes and light-mode reopening. The untouched synthetic
  fixture remains SHA256
  `16f7781d462b5788824582592838498773261c05d3d8cbc663bef146b09d6a92`.
- Focused offline suite: **64 passed, 8 skipped, 2 xpassed**, plus 17 passing
  subtests. Three harness warnings concern an optional pytest config option,
  generated driver mark and collection adapter. No failures.
- Changed Python files pass flake8 with CHIRP's translation builtins
  (`--builtins=_,ngettext`); `git diff --check` passes.

Screenshots are outside Git in the project `screenshots` directory:
`baseline-grid.jpg`, `dark-grid.jpg`, `dark-settings.jpg`, `dark-empty.jpg`,
`light-grid.jpg`, `light-settings.jpg`, `light-readonly.jpg`, `dark-readonly.jpg`.

The focused tests use workspace-local `test-deps` (pytest, mock, ddt, PyYAML),
an explicit checkout import path and a scratch `test-profile`, with
CHIRP_TESTIMG=SHIQUN_SQ-8500.img. Run tests/test_drivers.py,
tests/unit/test_sq8500_transport.py and tests/unit/test_sq8500_upload_policy.py
from the checkout root after calling chirp.platform.get_platform with that
scratch profile path.

## Boundaries and known gaps

The SQ-8500 driver, image format, transport and upload policy were not edited.
Git's CRLF checkout changes its on-disk SHA256; normalized LF SHA256 remains
`2f196cae1bac7c303dccaed655f8eb1672cd544680600308ef5531b62af39969`.
The driver blob is unchanged from the baseline commit.

Native dark support remains experimental in wxWidgets. Colour/font/print
dialogs, all radio drivers, query providers and developer-only windows have not
been exhaustively visually tested. Initial logs showed accessibility adapter
GetFocus result errors (resolved by the follow-up below). Property-grid
deprecation warnings remain; screen-reader certification is outstanding.
Settings pages can briefly appear blank during loading. No claim of complete
hardware or accessibility validation is made.

Rollback: close CHIRP, select Light and restart, or use the preserved baseline
runtime via `Launch-CHIRP-Dev.cmd`. Reverting the feature commit restores the
source baseline. Keep profile, runtime, archives, screenshots and scratch images
outside the source repository; do not commit private radio backups.

## Welcome contrast and grid responsiveness follow-up

The transparent welcome bitmap had black text baked into it. It is replaced by
native translated text controls and the unchanged `chirp-logo.png` asset, centred
with a DIP-scaled logo. Both dark and light welcome layouts were visually
checked. New screenshots: `screenshots\welcome-dark.jpg` and
`screenshots\welcome-light.jpg` in the project directory.

The grid slowdown came from accessibility enumeration of the entire image.
Instrumentation of a synthetic 200-memory image recorded roughly 38,000 Python
accessibility calls in a scan, creating about 4.7 seconds between UI timer ticks.
wx 3.3 exposes accessibility on both the outer Grid and its inner drawing window;
overriding just the drawing window still leaves a large native tree to traverse.

Both surfaces now expose only the focused row's columns. All memories remain
reachable by ordinary arrow-key navigation and scrolling. Row selection changes
notify clients to refresh the bounded subtree. Screen-reader tree exploration
is deliberately limited to the current row rather than materializing every
memory at once. This is a virtualization change, not a screen-reader validation
claim. Grid cell rectangles also account for scrolling.

Native GetFocus virtual callbacks require `(status, child_id, child_object)`;
the old two-element returns caused bridge TypeErrors. Both grid and Settings
adapters now return the native triple. This was verified against live Windows
accessibility queries, not just Python calls to the methods.

With the fix, UI timer delivery stayed around one second during repeated
accessibility queries. Mouse row selection, keyboard navigation, File menus and
bottom-right window resizing were exercised with the memory grid active. The
window resized from approximately 995x694 to 856x616 promptly. A fresh diagnostic
log had no focus callback TypeErrors. `screenshots\grid-responsive.jpg` records
the final grid. Temporary instrumentation is outside the source repository and
is not part of the normal launcher.

Five regression tests cover bounded child counts for 10/200/20,000-row grids,
both native grid surfaces, changing focused rows, invalid children and the
native grid/Settings focus result shape. Combined suite result: **69 passed,
8 skipped, 2 xpassed**, plus 17 passing subtests. Flake8 and diff whitespace
checks passed. The SQ-8500 driver and synthetic fixture remain unchanged.

## Transfer status text follow-up

The shared clone dialog created empty `ST_NO_AUTORESIZE` labels for transfer
status and model identity. On this Windows/wx build those labels initially had
zero height; updating the label without laying out the dialog left the text
invisible. The dialog now assigns a minimum line height and lays out its controls
after each status update. This applies to the shared download/upload presentation
without changing either transfer protocol.

An owner-authorized SQ-8500 download on COM3 completed successfully. The real GUI
showed `Reading SQ-8500` above the progress bar and `SHIQUN SQ-8500` below it.
The local screenshot is `screenshots\download-status-dark.jpg`. CHIRP saved its
automatic download backup under the private project `profile\backups` directory;
no radio data or backup was added to Git. **No upload operation was performed.**

An offline native-dialog probe exercised the same `_status()` callback with
`Waiting for radio between operations` and `Reading SQ-8500` in both dark and
light appearance, without opening a serial port. The status/model labels had
15-pixel height after the callback, matching their font height, instead of zero.
The focused suite still passes: 69 passed, 8 skipped, 2 xpassed, plus 17 passing
subtests. Flake8 and whitespace checks pass; the SQ-8500 driver is unchanged.
