Libraries linked into the CPython interpreter that is bundled with Leafweaving
(the exact set depends on the Python build used by the release workflow:
python.org / actions/setup-python CPython 3.12 on Windows and macOS, and the
distribution's shared libraries on Linux):

  OpenSSL      Apache-2.0        OpenSSL-LICENSE.txt   (ssl, hashlib)
  libffi       MIT               libffi-LICENSE.txt    (ctypes)
  Expat        MIT               expat-COPYING.txt     (xml.parsers.expat)
  bzip2        bzip2 license     bzip2-LICENSE.txt     (bz2)
  xz / liblzma 0BSD / PD         xz-COPYING.txt        (lzma)
  mpdecimal    BSD-2-Clause      mpdecimal-LICENSE.txt (decimal)
  SQLite       public domain     https://sqlite.org/copyright.html (sqlite3)
  zlib         Zlib              ../mupdf-thirdparty/zlib/LICENSE (zlib)

CPython itself: PSF License, see ../third-party/CPython/LICENSE.txt in the
collected LICENSES folder (which also lists the exact interpreter version).
