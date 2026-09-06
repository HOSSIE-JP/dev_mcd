# Development rules

- Work on `long-term/mcdk-native`. Keep the baseline `main` branch separate.
- Do not use Docker. Windows development uses the repo-local portable MSYS2/UCRT64 setup.
- Never add, upload to CI, or distribute BIOS ROMs, save states, firmware-containing dumps, or `.local/`.
- BIOS is supplied by the user and may be used locally for emulator tests. Never auto-download BIOS.
- Keep Megadev and emulator commits pinned. Fetch them into `.deps/`, not tracked source directories.
- Use M68000 instructions on both CPUs. Do not assume a 68020 or link host libc.
- Keep the normal GCC ABI with 32-bit int and argument slots; do not enable `-mshort`. BIOS assembly wrappers use that stack layout.
- Keep VBlank -> INT2 delivery running during CD I/O. Publish IPC command and access_op last.
- Respect Word RAM ownership. Check rounded CD sector lengths before starting a transfer.
- Do not clear a timed-out request and reuse its buffer while the Sub coroutine may still own it.
- Do not present SGDK-style APIs as complete SGDK/ResComp compatibility.
- Build with `make all`; run `make host-test` and `tools/doctor.py` before committing.
- For target changes, run `tools/smoke.py` with the local user BIOS. Record emulator vs real hardware evidence explicitly.
- CI must be able to build without BIOS. Use artifact allowlists and never upload `.local` or entire `.deps`.
