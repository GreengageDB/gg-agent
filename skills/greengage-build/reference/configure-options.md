# `./configure` option inventory

Derived from `configure.in` on `refs/remotes/origin/7.x` and `refs/remotes/origin/6.x`.
`configure.in` is the source; `configure` is generated and checked in. Regenerate with
`autoconf && autoheader` at the repo root (6.x also has `make autoconf -C gpAux`).
The `m4_if(... [2.69] ...)` autoconf version pin is **commented out** on both branches
(`configure.in:27-30`), so a newer autoconf will produce a `configure` without complaint.

`PGAC_ARG_BOOL(enable|with, <name>, <default>, ...)` — the third argument is the default.
`./configure --help` on 6.x lies about some defaults (see `--with-blocksize` below); the
table here reads the actual default expression, not the help text.

## `--enable-*`

| Option | 7.x default | 6.x default | What it changes |
|---|---|---|---|
| `--enable-cassert` | no | no | Defines `USE_ASSERT_CHECKING`. Turns `Assert()` live and sets `GPOS_DEBUG=1` so ORCA is also built in debug (`configure.in:790-794`). Visible at runtime as `SHOW debug_assertions`. |
| `--enable-debug` | no | no | Appends `-g` to `CFLAGS`/`CXXFLAGS` (`configure.in:661-667`). Does **not** lower optimization — see the CFLAGS note below. |
| `--enable-debug-extensions` | **yes** | **no** | Defines `FAULT_INJECTOR` and switches `gpcontrib/Makefile` to its long `recurse_targets` list. The delta is exactly three extensions on both branches: `gp_inject_fault`, `gp_debug_numsegments`, `gp_replica_check`. Regression and isolation2 suites need them. |
| `--enable-depend` | no | no | Turns on `-MMD -MP` dependency files under `.deps/` for both `%.o: %.c` and `%.o: %.cpp` (`src/Makefile.global.in:1023-1063`). Without it a header edit rebuilds nothing. |
| `--enable-orca` | **yes** | **yes** | Adds `gporca gpopt` to `src/backend/Makefile` `SUBDIRS` and `orca.o` to `src/backend/optimizer/plan/OBJS`. `--disable-orca` makes `SET optimizer=on` fail with `ORCA is not supported by this build` (`src/backend/utils/misc/guc_gp.c:5110`) and flips the `optimizer` GUC default to `false`. |
| `--enable-gpcloud` | **no** | **yes** | Builds `gpcontrib/gpcloud` and `gpcheckcloud`. Requires `--with-libcurl` and `--with-libxml`, else `configure` aborts with `libcurl is required by gpcloud`. |
| `--enable-orafce` | no | no | Builds `gpcontrib/orafce` (Oracle compatibility functions). |
| `--enable-ic-proxy` | no | no | Defines `ENABLE_IC_PROXY`; needed for `gp_interconnect_type=proxy` and the `installcheck-ic-proxy` isolation2 target. Requires libuv. |
| `--enable-gpfdist` | yes | yes | Gates `src/bin/gpfdist`, the external-table server (`src/bin/Makefile:43`). |
| `--enable-tap-tests` | no | no | Enables the Perl TAP suites. The CI test container passes it. |
| `--enable-coverage` | no | no | Requires `gcov`, `lcov`, `genhtml` on PATH or `configure` errors. Suppresses default optimization. |
| `--enable-profiling` | no | no | gcc `-pg`. |
| `--enable-dtrace` | no | no | Requires `dtrace` on PATH. |
| `--enable-rpath` | yes | yes | Embeds the shared-library search path. Packaging turns it off (`--disable-rpath` in `gpAux/Makefile`). |
| `--enable-spinlocks` / `--enable-atomics` | yes | yes | Never disable outside a port bring-up. |
| `--enable-strong-random` | yes | — | 7.x only. |
| `--enable-thread-safety` | yes | yes | Client libraries. |
| `--enable-integer-datetimes` | yes (obsolete) | yes | 7.x marks it "obsolete option, no longer supported". |
| `--enable-gpperfmon` | — | no | **6.x only.** Removed in 7.x. |
| `--enable-mapreduce` | — | no | **6.x only** (`gpcontrib/gpmapreduce`). Removed in 7.x. |
| `--enable-debugntuplestore` | — | no | **6.x only.** |
| `--enable-nls` | not available | not available | Commented out of `configure.in` on both branches, and of `src/Makefile.global.in:217`. Passing it yields `WARNING: unrecognized options` and changes nothing. |

## `--with-*`

| Option | 7.x default | 6.x default | Notes |
|---|---|---|---|
| `--with-python` | **yes** | **no** | Builds PL/Python. 7.x enables it by default; 6.x does not. Pick the interpreter with `PYTHON=python3.11` (what CI does). |
| `--with-perl` | no | no | Gates `src/pl/plperl` (`src/pl/Makefile:17-21`); `src/pl` is in `ICW_TARGETS`, so without it the plperl suite is silently not run. The 7.x README passes it. Unrelated to the Perl the test harness itself needs (`gpdiff.pl`, `atmsort.pl` run under the system perl either way). |
| `--with-tcl` / `--with-tclconfig=DIR` | no | no | PL/Tcl. |
| `--with-llvm` | no | — | **7.x only.** LLVM JIT (`USE_LLVM`). Emits a `.bc` next to every `.o` and installs bitcode via `install-postgres-bitcode`; ORCA is excluded (`src/backend/gporca/gporca.mk` sets `with_llvm = no`). Required to reproduce the CI `jit-tests` job. |
| `--with-gssapi` | no | no | In the CI `CONFIGURE_FLAGS` on both branches. |
| `--with-openssl` | no | no | Gates `contrib/sslinfo` in the top-level `all:`/`install:` rules and in `ICW_TARGETS`. |
| `--with-libxml` | no | no | XML support; also a hard requirement of `--enable-gpcloud`. |
| `--with-libxslt` | no | no | `contrib/xml2`. |
| `--with-ldap`, `--with-pam`, `--with-bonjour`, `--with-selinux` | no | no | Auth/platform integrations. |
| `--with-bsd-auth`, `--with-systemd` | no | — | **7.x only**; neither option exists in 6.x `configure.in`. `--with-systemd` also adds `-lsystemd` to the backend (`src/backend/Makefile:62-64`). |
| `--with-uuid=bsd\|e2fs\|ossp` | unset | unset | Gates `contrib/uuid-ossp` in the top-level `all:` rule. CI uses `--with-uuid=e2fs`. `--with-ossp-uuid` is the obsolete spelling. |
| `--with-icu` | no | — | 7.x only. |
| `--with-zstd` | yes | yes | Builds `gpcontrib/zstd` and the zstd workfile compression. Needs a **static** `libzstd` ≥ 1.4.0 or configure aborts with `static zstd library not found`. |
| `--with-zlib` | yes | yes | |
| `--with-libbz2` | yes | yes | |
| `--with-libcurl` | yes | yes | External-table support; required by gpcloud. |
| `--with-rt` | yes | yes | |
| `--with-readline` / `--with-libedit-preferred` | yes / no | yes / no | psql line editing. |
| `--with-quicklz` | — | no | **6.x only.** |
| `--with-pythonsrc-ext` | — | no | **6.x only**; builds the vendored Python modules for `gpMgmt`. |
| `--with-blocksize=N` | **32** | **32** | kB. 6.x `--help` says `[8]`; the actual default expression is `blocksize=32` on both (`configure.in:288-290` on 6.x, `293-295` on 7.x). Changing it changes the on-disk format — a cluster initdb'd with a different block size will not start. |
| `--with-wal-blocksize=N` | 32 | 32 | kB. |
| `--with-segsize=N` | 1 | 1 | GB. |
| `--with-wal-segsize=N` | — | 16 | 6.x only; on 7.x (PostgreSQL 12) WAL segment size is an `initdb` option. |
| `--with-pgport=N` | 5432 | 5432 | |
| `--with-extra-version=STRING` | unset | unset | Appended to the reported version. |
| `--with-includes=DIRS` / `--with-libraries=DIRS` | unset | unset | The CI test container sets `LDFLAGS`/`CPPFLAGS` pointing at `$GPHOME` instead. |
| `--with-system-tzdata=DIR` | unset | unset | |
| `--with-apr-config` | unset | unset | |
| `--with-apu-config` | — | unset | **6.x only.** |

`--prefix` defaults to `/usr/local/gpdb` on both branches (`AC_PREFIX_DEFAULT`,
`configure.in:34`).

## The CFLAGS trap

`configure` picks optimization before it appends debug symbols (`configure.in:446-463`
for `CFLAGS`, `:465-478` for `CXXFLAGS`):

- environment `CFLAGS` set  -> that wins;
- else the platform template already set it -> keep it;
- else `--enable-coverage`  -> no optimization;
- else GCC                  -> `CFLAGS="-O3"`;
- else                      -> `-O`, or nothing when `--enable-debug`.

Then `configure.in:661-667` appends `-g` if `--enable-debug`. So on GCC a
`--enable-debug --enable-cassert` build is compiled **`-O3 -g`**, and gdb will report
`<optimized out>` for most locals. For a debuggable backend pass the flags explicitly:

```sh
CFLAGS='-O0 -g3' CXXFLAGS='-O0 -g3' ./configure --enable-debug --enable-cassert ...
```

The 6.x `gpAux` build already does this for you: `devel` sets `CFLAGS` to `DEBUGFLAGS`
(`-O0 -g3`, `gpAux/Makefile:105-117`) and `dist` to `OPTFLAGS` (`-O3 … -g`, `:102`) before
invoking `configure` (`:179-183`), and the environment value wins the ladder above.

## Which flags matter for what

| Goal | Add |
|---|---|
| Run the regression / isolation2 suites | `--enable-debug-extensions` (6.x: mandatory, default is off), `--with-python`, `--with-perl` |
| Reproduce a crash / catch corruption early | `--enable-cassert --enable-debug` + explicit `CFLAGS='-O0 -g3'` |
| Iterate on headers | `--enable-depend` (otherwise every header edit needs a manual object purge) |
| Reproduce the CI build | `--enable-debug-extensions --with-gssapi --enable-cassert --enable-debug --enable-depend` (`ci/Dockerfile.ubuntu`, `ci/Dockerfile`) |
| Reproduce the CI JIT job | add `--with-llvm` (7.x only) |
| Broadest compile-warning coverage | the `ci/Dockerfile.ubuntu.clang-check` set: `--enable-orafce --enable-debug --enable-profiling --with-uuid=e2fs --with-python --enable-orca --enable-depend --enable-cassert --enable-gpcloud --enable-ic-proxy --with-llvm --with-perl --with-gssapi --with-ldap --with-pam --with-openssl --with-libxml --with-libxslt --enable-debug-extensions` |
| Packaging (what `gpAux` adds on 6.x) | a per-`BLD_ARCH` flag set (`gpAux/Makefile:127-146`), `--with-perl --with-python` unless `PG_LANG=false` (`:152-157`), `--with-libxslt --with-openssl --with-pam --with-ldap` (`:162`), `--disable-rpath` (`:167`), `LDFLAGS='-Wl,--enable-new-dtags -Wl,-rpath,$$ORIGIN/../lib'` (`:168`). The `--with-includes`/`--with-libraries` on `:162` expand to **empty** — `BLD_THIRDPARTY_INCLUDE_DIR`/`BLD_THIRDPARTY_LIB_DIR` are referenced but defined nowhere in the tree, so ignore the "thirdparty libraries from the ext/ directory" comment above them. |
| Fastest build for a quick syntax check | `--disable-orca` (skips the whole C++ tree) — but then `SET optimizer=on` fails |
