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

## MD Game Editor novel model and Ishinoura episode 1

The MCD novel interpreter and converter follow the command model and import
semantics in HOSSIE-JP/md-game-editor at
`26f0cda3d9869acd3c44961d89e42e102af6381d`.
They do not bundle or modify the editor, SGDK, or the generated cartridge ROM.

The story, artwork and recorded voices/music in `examples/ishinoura_ep01/data`
are converted from the owner's HOSSIE-JP/pce-novel-game-projects repository at
`6e0ff601e7ac2af69ce39677b623781ff01f1e0c`, episode
`いしのうらにいる！？/01_部室の白い箱`, with the owner's permission for this sample.
Their ownership is retained; this notice does not grant an additional license
for unrelated reuse of the story or audiovisual assets.

The Japanese glyph subset is derived from JF-Dot-Shinonome16, distributed with
MD Game Editor. The accompanying efont/Shinonome notice is reproduced in
`examples/ishinoura_ep01/FONT-LICENSE.txt` (lossless EUC-JP to UTF-8 conversion).
The full font is not required for normal builds and is not bundled.
