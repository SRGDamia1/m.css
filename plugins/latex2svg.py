#
#   This file is part of m.css.
#
#   Copyright © 2017 Tino Wagner <ich@tinowagner.com>
#   Copyright © 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025
#             Vladimír Vondruš <mosra@centrum.cz>
#   Copyright © 2017 gotchafr <gotchafr@users.noreply.github.com>
#
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and associated documentation files (the "Software"),
#   to deal in the Software without restriction, including without limitation
#   the rights to use, copy, modify, merge, publish, distribute, sublicense,
#   and/or sell copies of the Software, and to permit persons to whom the
#   Software is furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included
#   in all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#   THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#   FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#   DEALINGS IN THE SOFTWARE.
#

import os
import sys
import subprocess
import shlex
import re
from tempfile import TemporaryDirectory
# from ctypes import windll
from ctypes import *
from ctypes.util import find_library

default_template = r"""
\documentclass[{{ fontsize }}pt,preview]{standalone}
{{ preamble }}
\begin{document}
\begin{preview}
{{ code }}
\end{preview}
\end{document}
"""

default_preamble = r"""
\usepackage[utf8x]{inputenc}
\usepackage{amsmath}
\usepackage{amsfonts}
\usepackage{amssymb}
\usepackage{newtxtext}
\usepackage[libertine]{newtxmath}
"""

latex_cmd = 'latex -interaction nonstopmode -halt-on-error'
dvisvgm_cmd = 'dvisvgm --no-fonts'

default_params = {
    'fontsize': 12,  # pt
    'template': default_template,
    'preamble': default_preamble,
    'latex_cmd': latex_cmd,
    'dvisvgm_cmd': dvisvgm_cmd,
    'libgs': None,
}

# Taken from the Camelot library's _gsprint.py
# https://github.com/atlanhq/camelot/blob/master/camelot/ext/ghostscript/_gsprint.py
# Camelot is distributed with a MIT license.
def __win32_finddll():
    try:
        import winreg
    except ImportError:
        # assume Python 2
        from _winreg import (
            OpenKey,
            CloseKey,
            EnumKey,
            QueryValueEx,
            QueryInfoKey,
            HKEY_LOCAL_MACHINE,
        )
    else:
        from winreg import (
            OpenKey,
            CloseKey,
            EnumKey,
            QueryValueEx,
            QueryInfoKey,
            HKEY_LOCAL_MACHINE,
        )

    from distutils.version import LooseVersion
    import os

    dlls = []
    # Look up different variants of Ghostscript and take the highest
    # version for which the DLL is to be found in the filesystem.
    for key_name in (
        "AFPL Ghostscript",
        "Aladdin Ghostscript",
        "GNU Ghostscript",
        "GPL Ghostscript",
    ):
        try:
            k1 = OpenKey(HKEY_LOCAL_MACHINE, "Software\\%s" % key_name)
            for num in range(0, QueryInfoKey(k1)[0]):
                version = EnumKey(k1, num)
                try:
                    k2 = OpenKey(k1, version)
                    dll_path = QueryValueEx(k2, "GS_DLL")[0]
                    CloseKey(k2)
                    if os.path.exists(dll_path):
                        dlls.append((LooseVersion(version), dll_path))
                except WindowsError:
                    pass
            CloseKey(k1)
        except WindowsError:
            pass
    if dlls:
        dlls.sort()
        return dlls[-1][-1]
    else:
        return None


if sys.platform == "win32":
    libgs = __win32_finddll()
    if not libgs:
        raise RuntimeError("Please make sure that Ghostscript is installed")
    libgs = windll.LoadLibrary(libgs)
else:
    try:
        libgs = cdll.LoadLibrary("libgs.so")
    except OSError:
        # shared object file not found
        libgs = find_library("gs")
        # if not libgs:
        #     raise RuntimeError("Please make sure that Ghostscript is installed")
        libgs = cdll.LoadLibrary(libgs)

del __win32_finddll

if not hasattr(os.environ, 'LIBGS') and not libgs:
    if sys.platform == 'darwin':
        # Fallback to homebrew Ghostscript on macOS
        homebrew_libgs = '/usr/local/opt/ghostscript/lib/libgs.dylib'
        if os.path.exists(homebrew_libgs):
            default_params['libgs'] = homebrew_libgs
    if sys.platform == 'linux':
        # On certain Linux distros find_library() may not work even though the
        # library is in usual paths. Try some candidates before failing hard.
        for linux_libgs in [
            '/usr/lib/libgs.so.10',
            '/usr/lib/{}-linux-gnu/libgs.so.10'.format(os.uname().machine)
        ]:
            if os.path.exists(linux_libgs):
                default_params['libgs'] = linux_libgs
                break
    if not default_params['libgs']:
        print('Warning: libgs not found')

# dvisvgm < 3.0 only looks for ghostscript < 10 on its own, attempt to supply
# it directly if version 10 is found. Fixed in
# https://github.com/mgieseki/dvisvgm/commit/46b11c02a46883309a824e3fc798f8093041daec
# TODO related https://bugs.archlinux.org/task/76083 was resolved on May 29th
# 2023, remove after enough time passes if no similar case happens in other
# distros
elif '.so.10' in str(libgs):
    # If dvisvgm seems to be at least 3.0, don't even attempt to find libgs and
    # just assume it works
    dvisvgm_is_new_enough = False
    try:
        ret = subprocess.run(['dvisvgm', '--version'], stdout=subprocess.PIPE)
        if b'dvisvgm 3' in ret.stdout:
            dvisvgm_is_new_enough = True
    except:
        pass

    # Just winging it here, there doesn't seem to be an easy way to get the
    # actual full path the library was found in -- ctypes/util.py does crazy
    # stuff like invoking gcc (!!) to get the library filename.
    #
    # On Arch /usr/lib64 is a symlink to /usr/lib, so only the former is
    # needed; on Fedora it's two distinct directories and libgs is in the
    # latter (ugh). Elsewhere it might be /usr/lib/x86_64-linux-gnu or just
    # anything else, so let's just bet that dvisvgm is 3.0+ in most cases and
    # this gets hit only very rarely.
    if not dvisvgm_is_new_enough:
        prefixes = ['/usr/lib', '/usr/lib64']
        for prefix in prefixes:
            libgs_absolute = os.path.join(prefix, libgs)
            if os.path.exists(libgs_absolute):
                default_params['libgs'] = libgs_absolute
                break
        else:
            raise RuntimeError('libgs found by linker magic, but is not in {}'.format(' or '.join(prefixes)))

def latex2svg(code, params=default_params, working_directory=None):
    """Convert LaTeX to SVG using dvisvgm.

    Parameters
    ----------
    code : str
        LaTeX code to render.
    params : dict
        Conversion parameters.
    working_directory : str or None
        Working directory for external commands and place for temporary files.

    Returns
    -------
    dict
        Dictionary of SVG output and output information:

        * `svg`: SVG data
        * `width`: image width in *em*
        * `height`: image height in *em*
        * `depth`: baseline position in *em*
    """
    if working_directory is None:
        with TemporaryDirectory() as tmpdir:
            return latex2svg(code, params, working_directory=tmpdir)

    fontsize = params['fontsize']
    document = (params['template']
                .replace('{{ preamble }}', params['preamble'])
                .replace('{{ fontsize }}', str(fontsize))
                .replace('{{ code }}', code))

    with open(os.path.join(working_directory, 'code.tex'), 'w') as f:
        f.write(document)

    # Run LaTeX and create DVI file
    try:
        ret = subprocess.run(shlex.split(params['latex_cmd']+' code.tex'),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=working_directory)
        # LaTeX prints errors on stdout instead of stderr (stderr is empty),
        # so print stdout instead
        if ret.returncode: print(ret.stdout.decode('utf-8'))
        ret.check_returncode()
    except FileNotFoundError:
        raise RuntimeError('latex not found')

    # Add LIBGS to environment if supplied
    env = os.environ.copy()
    if params['libgs']:
        env['LIBGS'] = params['libgs']

    # Convert DVI to SVG
    try:
        ret = subprocess.run(shlex.split(params['dvisvgm_cmd']+' code.dvi'),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=working_directory, env=env)
        if ret.returncode: print(ret.stderr.decode('utf-8'))
        ret.check_returncode()
    except FileNotFoundError:
        raise RuntimeError('dvisvgm not found')

    with open(os.path.join(working_directory, 'code.svg'), 'r') as f:
        svg = f.read()

    # Parse dvisvgm output for size and alignment
    def get_size(output):
        regex = r'\b([0-9.]+)pt x ([0-9.]+)pt'
        match = re.search(regex, output)
        if match:
            return (float(match.group(1)) / fontsize,
                    float(match.group(2)) / fontsize)
        else:
            return None, None

    def get_measure(output, name):
        regex = r'\b%s=([0-9.e-]+)pt' % name
        match = re.search(regex, output)
        if match:
            return float(match.group(1)) / fontsize
        else:
            return None

    output = ret.stderr.decode('utf-8')

    # Since we rely on Ghostscript to give us a "depth" (= vertical alignment)
    # value, dvisvgm not using it means the output would be broken and it makes
    # no sense to continue.
    if 'Ghostscript not found' in output:
        raise RuntimeError('libgs not detected by dvisvgm, point the LIBGS environment variable to its location')

    width, height = get_size(output)
    depth = get_measure(output, 'depth')
    return {'svg': svg, 'depth': depth, 'width': width, 'height': height}


def main():
    """Simple command line interface to latex2svg.

    - Read from `stdin`.
    - Write SVG to `stdout`.
    - Write metadata as JSON to `stderr`.
    - On error: write error messages to `stdout` and return with error code.
    """
    import json
    import argparse
    parser = argparse.ArgumentParser(description="""
    Render LaTeX code from stdin as SVG to stdout. Writes metadata (baseline
    position, width, height in em units) as JSON to stderr.
    """)
    parser.add_argument('--preamble',
                        help="LaTeX preamble code to read from file")
    args = parser.parse_args()
    preamble = default_preamble
    if args.preamble is not None:
        with open(args.preamble) as f:
            preamble = f.read()
    latex = sys.stdin.read()
    try:
        params = default_params.copy()
        params['preamble'] = preamble
        out = latex2svg(latex, params)
        sys.stdout.write(out['svg'])
        meta = {key: out[key] for key in out if key != 'svg'}
        sys.stderr.write(json.dumps(meta))
    except subprocess.CalledProcessError as exc:
        print(exc.output.decode('utf-8'))
        sys.exit(exc.returncode)


if __name__ == '__main__':
    main()
