---
name: greengage-build
description: Turn a Greengage source change into a running binary and prove the binary under test is the one you built. Covers ./configure flags and real defaults, --enable-cassert/-depend/-debug-extensions, the 6.x gpAux devel vs dist build, ORCA link failures, stale-object and stale-install traps, ci/Dockerfile images, what CI compiles. Use when a source edit has no runtime effect, or on `ORCA is not supported by this build`, `undefined reference to optimize_query`, or `database files are incompatible with server`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Building Greengage

Two live branches build in two different ways. Get the branch right first: 7.x is
PostgreSQL 12.22 and builds with plain `./configure`; 6.x is PostgreSQL 9.4.26 and the
README tells you to drive the build through `gpAux`.

## The 7.x build, verbatim from `README.md`

```sh
git submodule update --init          # only gpcontrib/gpcloud/test/googletest
./configure --with-perl --with-python --with-libxml --with-gssapi \
            --prefix=/usr/local/gpdb
make -j8
make -j8 install
source /usr/local/gpdb/greengage_path.sh
make create-demo-cluster
source gpAux/gpdemo/gpdemo-env.sh
```

For anything you intend to test or debug, add the CI flag set on top:
`--enable-cassert --enable-debug --enable-debug-extensions --enable-depend`
(`ci/Dockerfile.ubuntu`, `ENV CONFIGURE_FLAGS`).

Two literal lines are the only proof the build and install finished, because `make`
exits 0 on plenty of half-done trees when you drive it per-directory:

- `All of Greengage Database successfully made. Ready to install.` (`GNUmakefile.in:45`)
- `Greengage Database installation complete.` (`GNUmakefile.in:95`)

Dependency bootstrap scripts differ **in case** between the branches. Getting this
wrong produces "No such file or directory", not a helpful error:

| Platform | 7.x | 6.x |
|---|---|---|
| Ubuntu | `README.Ubuntu.bash` | `README.ubuntu.bash` |
| RHEL / Rocky | `README.Rhel-Rocky.bash` | `README.Rhel-Rocky.bash`, `README.CentOS.bash` |
| macOS | `README.macOS.bash`, `README.macOS.arm.bash` | same |
| Prose guides | `README.Linux.md`, `README.macOS.md`, `README.Conda.md`, `README.Windows.md` | `README.linux.md`, `README.macOS.md`, `README.conda.md`, `README.windows.md`, `README.docker.md` |
| Also on 6.x | — | `README.amazon_linux` |

`export LANG=en_US.UTF-8` before you create any cluster — the tests require a UTF-8
locale (README, "Running tests").

## Top-level `make` is not upstream PostgreSQL's `make`

Do not carry over "plain `make` builds `src/` only, `make world` adds contrib". In this
tree the top-level `all:` rule (`GNUmakefile.in:13-45`) already recurses into `src` and
`config`, then a **curated** contrib list (`auto_explain pg_stat_statements citext
file_fdw postgres_fdw formatter formatter_fixedwidth fuzzystrmatch extprotocol dblink
indexscan pageinspect hstore ltree pgcrypto btree_gin pg_trgm isn tsm_system_rows
tsm_system_time pg_buffercache tablefunc`, plus `sslinfo` if `--with-openssl` and
`uuid-ossp` if `--with-uuid`), then `gpMgmt` and `gpcontrib`. `make world` /
`make install-world` adds `doc/` and *all* of `contrib/`, but recurses into
`doc src config contrib gpcontrib` only (`GNUmakefile.in:50`, `:100`) — **`world` does
not build `gpMgmt`**, so it is not a superset of `all`. Plain `make && make install` is
what the README uses and is sufficient.

## 6.x: `./configure` is not the documented path

```sh
git submodule update --init --recursive --force     # 6.x has three submodules
make GPROOT=~/build PARALLEL_MAKE_OPTS=-j8 devel -C gpAux
source ~/build/greengage-db-devel/greengage_path.sh
```

| Target | Optimization | Extra configure flags | Use it for |
|---|---|---|---|
| `devel` (`gpAux/Makefile:295-306`, flags at `:298`) | `DEBUGFLAGS` = `-O0 -g3` (`:105-117`) | `--enable-cassert --enable-debug --enable-debug-extensions --enable-depend` | **Required** for the regression suites |
| `dist` (`gpAux/Makefile:312-322`) | `OPTFLAGS` = `-O3 -fno-omit-frame-pointer -g` (`:102`) | none added | Packaging / release builds |

Both pass their flags as `CFLAGS=$(INSTCFLAGS) ./configure …` (`gpAux/Makefile:179-183`),
and an environment `CFLAGS` wins `configure`'s optimization ladder — so a 6.x `devel`
build is genuinely `-O0 -g3` and is **not** subject to the `-O3 -g` trap that bites a
hand-rolled `./configure --enable-debug` (see [reference/configure-options.md](reference/configure-options.md)).

`devel` is not merely "the slow one". On 6.x `--enable-debug-extensions` defaults to
**no** (`configure.in:212`), and `gpcontrib/Makefile` builds exactly three extensions only
when it is `yes` — `gp_inject_fault`, `gp_debug_numsegments`, `gp_replica_check` (the same
three on both branches). A `dist` build physically cannot run the fault-injection tests.
On 7.x the default flipped to **yes** (`configure.in:225`), which is why the 7.x README
does not mention the distinction.

Both targets configure with `--prefix=$(GPROOT)/$(GPDIR)` (`gpAux/Makefile:182`) where
`GPDIR` defaults to `greengage-db-devel` (`gpAux/Makefile:69-75`) — so `dist` also lands
in a directory called `...-devel`. Override the leaf with `GPDIR=`. `GPROOT` is mandatory
for `dist` (`GPROOTDEP`, `gpAux/Makefile:720-731`); omitting it aborts with
`The GPROOT path variable is not set.` `devel` only checks `$HOME` (`HOMEDEP`), so it
will silently configure `--prefix=/greengage-db-devel` if you forget `GPROOT`.

**The 6.x gpAux build is in-tree by default.** `ISCONFIG=$(GPPGDIR)/GNUmakefile` and
`BUILDDIR=$(GPPGDIR)` (`gpAux/Makefile:63-67`, `:89`) — it runs
`./configure` in the *repo root*, so after the first `make ... devel -C gpAux` you can
iterate with plain `make -C src/backend && make -C src/backend install` at the root and
keep the same flags and prefix. Only if `ENABLE_VPATH_BUILD` is set does it build into
`gpAux/Debug` / `gpAux/Release` (`gpAux/Makefile:299-302`, `:315-318`), and then the repo
root has no `GNUmakefile`, so `make` there hits the stub `Makefile` and stops with
`You need to run the 'configure' program first.`

7.x still ships `gpAux` and CI uses its `dist` target, but the supported developer path
on 7.x is plain `./configure`.

## A source change is not a running binary

Every step below is a place the change silently stops.

| Symptom | Cause | Detect / fix |
|---|---|---|
| Fix is in the source, behaviour unchanged | Never rebuilt: header edited without `--enable-depend`, so `make` marks no `.o` stale | `ls -l --time-style=+%T <file>.c <file>.o`. Purge the affected subtree only: `find src/backend/<subdir> -name '*.o' -delete`, then `make`. Reconfigure with `--enable-depend`. |
| Fix is in the source, behaviour unchanged | Built but not installed | `cmp $GPHOME/bin/postgres src/backend/postgres` |
| Fix is installed, behaviour unchanged | Installed but the cluster still runs the old image | Restart, then re-check `/proc/<pid>/exe` (below) |
| `gpstop` exits with `Environment Variable COORDINATOR_DATA_DIRECTORY not set!` (`gpMgmt/bin/gppylib/commands/gp.py:1230`), segments keep the old binary | Sourced `greengage_path.sh` but not `gpdemo-env.sh` | `source $GPHOME/greengage_path.sh; source gpAux/gpdemo/gpdemo-env.sh` — both, in that order (6.x: `MASTER_DATA_DIRECTORY`) |
| Server refuses to start: `database files are incompatible with server` … `It looks like you need to initdb.` | You changed a catalog header and `CATALOG_VERSION_NO` (`src/include/catalog/catversion.h:59`; check at `src/backend/access/transam/xlog.c:4827-4833`) or `--with-blocksize` moved (`xlog.c:4846`) | Destroy and recreate the cluster: `make destroy-demo-cluster && make create-demo-cluster` |
| `make -C <subdir>` returns 0 but nothing changed | A per-directory make only knows that subtree | Never treat a per-directory rc=0 as proof. A full `make` at the repo root ending in `All of Greengage Database successfully made.` is the authoritative check. |

Reinstalling replaces the file the running postmaster is executing.
`install-bin` (`src/backend/Makefile:269-270`) uses `$(INSTALL_PROGRAM)`, which
unlinks and recreates `$GPHOME/bin/postgres`, so a process started from the old inode
keeps running the old code until restarted. `$GPHOME/bin/postmaster` is only a symlink
to `postgres`.

## "Did the binary actually change?" — the recipe

Run this before you believe any test result.

```sh
source $GPHOME/greengage_path.sh
source gpAux/gpdemo/gpdemo-env.sh

# 1. What flags produced the installed tree? (not what you think you typed)
$GPHOME/bin/pg_config --configure

# 2. Is the installed binary the one you just linked?
cmp $GPHOME/bin/postgres src/backend/postgres && echo INSTALL_OK || echo STALE_INSTALL

# 3. Is the running coordinator that binary? A replaced file reads "(deleted)".
pid=$(head -1 $COORDINATOR_DATA_DIRECTORY/postmaster.pid)   # 6.x: MASTER_DATA_DIRECTORY
readlink /proc/$pid/exe          # ends in "(deleted)" -> restart needed

# 4. Is your new symbol in the binary at all?
# (plain `make install` leaves INSTALL_STRIP_FLAG empty; only `install-strip` adds -s)
nm -C $GPHOME/bin/postgres | grep -w <your_new_function>

# 5. Is this the assert build you meant to test?
psql -d postgres -c 'SHOW debug_assertions'   # tracks USE_ASSERT_CHECKING, guc.c:1365

# 6. Version and catalog identity
$GPHOME/bin/postgres --gp-version                 # "postgres (Greengage Database) ..."
$GPHOME/bin/postgres --catalog-version
```

`--catalog-version` and `--gp-version` are Greengage additions
(`src/backend/main/main.c:176`, `:181`). All segments of a demo cluster execute the same
`$GPHOME`; on a multi-host cluster `make install` must run on **every** host, or you get
a mixed-version cluster with no warning.

## Never `make clean` to "force a rebuild"

`clean-local` (`src/backend/common.mk:43-45`) removes `objfiles.txt`, every `.o` and every
`.bc` in the subtree. ORCA (`src/backend/gporca`, 2200+ C++ sources and headers, compiled
with `-Werror -Wextra -Wpedantic` per `src/backend/gporca/gporca.mk`) is the largest
subtree under `src/backend` and is linked *into* the `postgres` binary —
`postgres: $(OBJS)` linked with `$(CXX)` (`src/backend/Makefile:100-101`), not a shared
library. Cleaning it costs a full C++ rebuild and buys nothing. To force a rebuild, delete
objects in the subtree you touched, or `touch` its sources.

**The ORCA relink trap.** `objfiles.txt` is regenerated only when a prerequisite *other
than the objects* is newer:

```make
objfiles.txt: Makefile $(SUBDIROBJS) $(OBJS)
	$(if $(filter-out $(OBJS),$?),( ... )>$@,touch $@)     # src/backend/common.mk:23-25
```

`src/backend/optimizer/plan/Makefile:23-25` adds `orca.o` to `OBJS` only when
`$(enable_orca)` is `yes`, and that variable arrives from `src/Makefile.global` — which is
**not** a prerequisite of `objfiles.txt`. So reconfiguring a `--disable-orca` tree to
`--enable-orca` regenerates `Makefile.global` and builds `orca.o`, but nothing in the rule
above is newer except an object, so the list is only `touch`ed: `orca.o` stays out of the
existing `src/backend/optimizer/plan/objfiles.txt`, and the link fails with
`undefined reference to 'optimize_query'` (declared `src/include/optimizer/orca.h:24`,
called from `src/backend/optimizer/plan/planner.c:380`). Fix by forcing that one list to
regenerate:

```sh
rm src/backend/optimizer/plan/objfiles.txt && make -j8
```

The same shape bites any directory whose `OBJS` membership is decided by a configure
variable. Symptom to recognise: a link error naming a symbol whose `.o` you can see on
disk.

Do **not** reach for `-j` as the explanation. `common.mk:35` carries the upstream
parallel-make ordering hack (`$(SUBDIROBJS): $(SUBDIRS:%=%-recursive) ;`); the README
prescribes `make -j8` and CI builds with `PARALLEL_MAKE_OPTS=-j$(nproc)`
(`concourse/scripts/compile_gpdb.bash:47`).

`make distclean` (README) is the only full reset, and it is what you want before changing
`--enable-orca`, `--with-blocksize` or `--with-llvm`.

## Root-owned artifacts poison the next build

Building once as root leaves root-owned `.o`, `.bc` and `.deps/` files, plus a root-owned
`$GPHOME`. The next build as a normal user dies on the first object it must overwrite. Add
`--with-llvm` and the surface doubles: `%.bc : %.c` and `%.bc : %.cpp`
(`src/Makefile.global.in:1170-1174`) emit a bitcode file next to every object, so every
root-owned `.o` has a root-owned `.bc` beside it.

```sh
sudo mkdir -p /usr/local/gpdb && sudo chown "$(id -un)" /usr/local/gpdb   # once, up front
sudo chown -R "$(id -un):$(id -gn)" <srcdir> /usr/local/gpdb              # to repair
```

Never `sudo make` or `sudo make install`. Pre-create and chown the prefix instead;
`--prefix` defaults to `/usr/local/gpdb` on both branches (`AC_PREFIX_DEFAULT`,
`configure.in:34`), so this bites even when you pass no `--prefix` at all.

## The `ci/Dockerfile*` images and what each is for

| File | Base | Purpose |
|---|---|---|
| `ci/Dockerfile.ubuntu` | `ubuntu:22.04` | The main build + test image. Multi-stage `base`/`build`/`code`/`test`. Runs `README.Ubuntu.bash` for deps. (6.x: same name, but `ARG OS_VERSION=22.04` and `README.ubuntu.bash`.) |
| `ci/Dockerfile` | `rockylinux:8.8` | Same shape for Rocky 8. **On 6.x this same path is `centos:centos7`** — do not assume the base from the filename. |
| `ci/Dockerfile.linter` | `ubuntu:22.04` | ORCA clang-format check (`clang-format-11`). `ENTRYPOINT src/tools/fmt gen && git diff --exit-code && src/tools/fmt chk` — **fails on any uncommitted change**, so stage or commit first. |
| `ci/Dockerfile.ubuntu.clang-check` (7.x) | `ubuntu:22.04` | Compile-only warning sweep with clang at `-O0`. Carries the broadest configure flag set in the tree; the compile is the last `RUN`, so the image is disposable (`ci/readme.md`). |
| `ci/Dockerfile.pg_upgrade` (7.x) | `ggdb6_ubuntu` + `ggdb7_ubuntu` GHCR images | Two installations side by side (`/usr/local/greengage-db-6X` and `/usr/local/greengage-db-devel`) for upgrade testing. |
| `ci/Dockerfile.rockylinux` (6.x) | `rockylinux:${OS_VERSION}` | 6.x's Rocky image, `ARG OS_VERSION=8`; pass `--build-arg OS_VERSION=9` for Rocky 9. `ci/Dockerfile.centos` next to it is only a **symlink to `ci/Dockerfile`**, not a separate image. |

```sh
docker build -t gpdb7_u22:latest -f ci/Dockerfile.ubuntu .        # ci/readme.md
docker build -t gpdb7_regress:latest -f ci/Dockerfile .
docker build -t orca-linter:test -f ci/Dockerfile.linter . && docker run --rm -it orca-linter:test
```

Any container that will run a cluster needs
`--sysctl "kernel.sem=500 1024000 200 4096"`; add `--privileged` to use gdb inside.

## What CI compiles is not what the test container configures

1. `ci/Dockerfile.ubuntu` build stage sets
   `CONFIGURE_FLAGS="--enable-debug-extensions --with-gssapi --enable-cassert --enable-debug --enable-depend"`
   and runs `concourse/scripts/compile_gpdb.bash`.
2. That script builds via `gpAux`: `make GPROOT=/usr/local PARALLEL_MAKE_OPTS=-j$(nproc) -s dist`
   (`compile_gpdb.bash:47`), installing into `/usr/local/greengage-db-devel`, then runs
   `make GPROOT=/usr/local -s unittest-check` unless `SKIP_UNITTESTS` is set (`:75`, `:149`),
   then tars the prefix into `bin_gpdb.tar.gz`.
3. `unittest-check` is `$(MAKE) CFLAGS=-DUNITTEST -C src/backend unittest-check` plus the
   same for `src/bin` (`GNUmakefile.in:239-241`). It stops at the first failing suite, so
   run it locally in full before pushing.
4. On a pull request, `.github/workflows/greengage-ci.yml` delegates the build to the
   pinned reusable workflow `greengagedb/greengage-ci/.github/workflows/greengage-reusable-build.yml`.
   Nothing in this repository compiles directly on a PR.

**The trap:** inside a test container, `install_and_configure_gpdb`
(`concourse/scripts/common.bash:154`) *unpacks* `bin_gpdb.tar.gz` into
`/usr/local/greengage-db-devel` and then re-runs `./configure`. That configure exists only
so the top-level Makefile can decide which test targets to offer — it does **not** rebuild
or reinstall the server. Its flags (`--disable-orca --enable-gpcloud --enable-orafce
--enable-tap-tests …`) therefore do not describe the binary under test. Read
`$GPHOME/bin/pg_config --configure` if you need to know what the binary actually is.

## What not to do

- Do not run `make check` or plain `make installcheck`. The README states neither works:
  `check` never creates a cluster, and `installcheck` includes tests known to fail.
  Use `make installcheck-world` — see [greengage-testing](../greengage-testing/SKILL.md).
- Do not hand-edit or hand-merge `configure`. It is generated and checked in;
  `configure.in` (not `configure.ac`) is the source. Regenerate with `autoconf && autoheader`
  at the repo root. The autoconf 2.69 pin is commented out on both branches
  (`configure.in:27-30`), so a newer autoconf works.
- Do not pass `--enable-nls`. The option is commented out of `configure.in` on both
  branches, so `configure` answers `WARNING: unrecognized options: --enable-nls` and
  `enable_nls` is never substituted into `src/Makefile.global` (`:217` is commented out) —
  the `ifeq ($(enable_nls), yes)` block at `:1070` can never fire.
- Do not assume `--enable-debug` gives you a debuggable build: with GCC the compiler flags
  end up `-O3 -g`. Pass `CFLAGS='-O0 -g3' CXXFLAGS='-O0 -g3'` explicitly. See
  [reference/configure-options.md](reference/configure-options.md).
- Do not chase a `libcurl is required by gpcloud` or `static zstd library not found`
  configure abort as a code problem — they are dependency errors from
  `--enable-gpcloud` and `--with-zstd` respectively.
- Do not test ORCA changes against a `--disable-orca` build: `SET optimizer=on` fails with
  `ORCA is not supported by this build` (`src/backend/utils/misc/guc_gp.c:5110`) and the
  `optimizer` GUC silently defaults to `false`.
- ORCA's own unit tests are a separate CMake build, not part of `make`:
  `cmake -GNinja -H. -Bbuild && ninja -C build && cd build && ctest -j8 --output-on-failure`
  from `src/backend/gporca` (`src/backend/gporca/README.md`).

Full option inventory with defaults, 6.x/7.x deltas and the CFLAGS derivation:
[reference/configure-options.md](reference/configure-options.md).

See also: [greengage-testing](../greengage-testing/SKILL.md) (running the suites against
the binary you just built), [greengage-ci](../greengage-ci/SKILL.md) (the GitHub Actions
jobs and how to reproduce them), [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)
(demo cluster, restart, environment files), [greengage-debug](../greengage-debug/SKILL.md)
(assert builds, gdb, instrumentation rebuilds), [greengage-internals](../greengage-internals/SKILL.md)
(what the pieces you are rebuilding do).
