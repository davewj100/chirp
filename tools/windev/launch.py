"""Launch the local Windows development runtime with an isolated profile."""
import os
from pathlib import Path
import sys


def main():
    source = Path(__file__).resolve().parents[2]
    project = source.parent
    dll_handles = []
    dlls = Path(sys.executable).parent / 'Lib/site-packages/pywin32_system32'
    if dlls.is_dir():
        dll_handles.append(os.add_dll_directory(str(dlls)))
    sys.path.insert(0, str(source))
    from chirp import platform
    platform.get_platform(str(project / 'profile'))
    os.environ['CHIRP_DEBUG_LOG'] = '1'
    from chirp.wxui import chirpmain
    sys.argv = [str(source / 'chirpwx.py'),
                '--config-dir', str(project / 'profile')] + sys.argv[1:]
    return chirpmain()


if __name__ == '__main__':
    raise SystemExit(main())
