# Windows M68000 toolchain

GCC 14.2.0 / Binutils 2.44, m68k-elf, M68000, normal 32-bit-int ABI.

Download dev-mcd-toolchain-win32-x64.zip for the compiler. MD Game Editor
verifies dev-mcd-toolchain-release.json and installs it automatically. The
compiler can be relocated and includes its non-system runtime DLLs.

Corresponding Source: dev-mcd-toolchain-sources.zip in this same Release.
It includes the original GCC/Binutils source archives, matching MSYS2 source
packages (including source or Git objects, patches and PKGBUILD), and build
scripts. Licenses are included in the binary package; upstream sources contain
additional notices. Keep source and binary available to the same recipients.

This release contains no game assets, BIOS, firmware or emulator. It does not
change the license of the repository's audiovisual samples or make the private
repository public. See docs/RELEASE-LICENSING.md for the inventory and scope.

Validation: relocated compiler on Windows, no MSYS2 directories on PATH,
M68000 C compilation, libgcc linking and binary generation. This is toolchain
validation, not an emulator or physical hardware compatibility claim.
