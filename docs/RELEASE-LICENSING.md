# Release licensing and distribution audit (2026-09-08)

## Scope and findings

The tracked repository contains original SDK C/assembly/Python code, adapted
Megadev boot integration, procedural examples, and a separately owned novel
sample. The original SDK code is MIT with owner approval. MIT does not replace
third-party notices or grant rights to sample audiovisual content.

- Megadev v1.2.0 is pinned; keep the existing MIT notice on adapted IP/SP code.
- JF-Dot-Shinonome16 glyphs retain the efont/Shinonome notice in FONT-LICENSE.txt.
- Story, images, voices, music, scenario and packed data in the novel sample are
  excluded from MIT. Evidence screenshots depicting that sample are excluded too.
- GCC 14.2.0 / Binutils 2.44: retain GPL texts, corresponding upstream sources,
  GCC Runtime Library Exception and the exact build scripts.
- Native DLLs and statically linked host runtime inputs: record pacman package
  versions and include matching MSYS2 source packages and license files.
- BIOS, firmware, saves, emulator binaries and game images are not Release inputs.
- The repository remains private. This change does not change repository visibility
  or assert that all historical sample content may be made public.

## Allowed release assets

Only dev-mcd-toolchain-win32-x64.zip, dev-mcd-toolchain-sources.zip and
 dev-mcd-toolchain-release.json are uploaded. The binary is the compiler install
prefix plus its DLL dependency closure and licenses; the source archive contains
upstream GCC/Binutils archives, corresponding MSYS2 source packages and build
scripts. Never upload the parent .deps, examples, dist or .local recursively.

The binary and corresponding source must be available to the same recipients,
with equivalent download access. Do not delete the source while retaining the
binary. A private Release is not a substitute for providing source to recipients.

package-release.py refuses missing sources, licenses and unresolved DLLs. This is
a technical inventory and release gate, not a guarantee about unknown provenance.
Before making the entire repository public, review sample ownership, evidence
screenshots and Git history separately. No visibility change is automated.

References:
- https://www.gnu.org/licenses/gpl-3.0.html (section 6)
- https://www.gnu.org/licenses/gcc-exception-3.1.html
- https://www.msys2.org/dev/mirrors/

## Editor SDK Release
The editor SDK archive uses a tracked-file allowlist: original SDK sources, include files, tools, top-level licenses/configuration, and the original examples/ishinoura_ep01/main.c entry point required by the editor builder. Sample data and audiovisual material are excluded. Python/FFmpeg/MSYS2 remain separately installed dependencies; compiler binaries and corresponding source remain in the pinned toolchain Release.
