# Third-party notices

## Megadev

https://github.com/drojaazu/megadev — v1.2.0 / `7a7246c14b845ad2f1bd3c7d73afb04cf67d83ef`.
The IP/SP boot integration is adapted from Megadev examples. Megadev startup,
headers, CD coroutine, security block, and linker scripts are fetched by setup
and used during the build. The following notice applies to those portions.

MIT License

Copyright (c) 2021 Damian Rogers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Development tools

GNU GCC and binutils retain their upstream licenses. Source archives and
installed toolchains remain in `.deps/`; they are not embedded in the game.
MSYS2 and its packages retain their individual licenses.

Genesis Plus GX is used only as a separately fetched verification tool.
Its upstream [license](https://github.com/libretro/Genesis-Plus-GX/blob/master/LICENSE.txt)
must be followed; no emulator binary is bundled with this project or game.

No SGDK source or runtime is linked. The bridge API and procedural test assets
are project code. No commercial music or user BIOS data is used in the generated assets.
