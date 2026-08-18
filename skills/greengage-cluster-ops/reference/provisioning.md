# Provisioning and connecting

Lookup material for the three modes of the gate in `../SKILL.md`. Pick one; do not mix.

---

## Route A — attach to an existing cluster

### Standard libpq variables

Greengage inherits PostgreSQL's connection environment unchanged. Nothing Greengage-specific
is needed to reach the coordinator.

| Variable | Notes |
|---|---|
| `PGPORT` | Coordinator port. `gpdemo-env.sh` sets it; `greengage_path.sh` does not |
| `PGHOST` | Omit for a local Unix socket |
| `PGDATABASE` | `postgres` and `template1` exist after `gpinitsystem` |
| `PGUSER` | The cluster owner, conventionally `gpadmin` |
| `PGOPTIONS` | The only Greengage-relevant one — see utility mode below |

```sh
pg_isready -h "${PGHOST:-localhost}" -p "${PGPORT:-5432}"   # ships in src/bin/scripts on both lines
psql -c "SELECT current_setting('data_directory'), current_setting('port'), version();"
```

`version()` prints the PostgreSQL base and the Greengage version in one string — the fastest
way to confirm which line you are on (7.x is PostgreSQL 12.22, 6.x is 9.4.26).

### Where the segments are

```sql
SELECT dbid, content, role, preferred_role, mode, status, hostname, address, port, datadir
FROM   gp_segment_configuration
ORDER  BY content, preferred_role DESC;
```

`port` and `hostname` here are what you pass to a utility-mode `psql`.

### Utility mode: read-only inspection of a single instance

```sh
# Works on 6.x and 7.x. Prefer this form.
PGOPTIONS='-c gp_session_role=utility' psql -h <hostname> -p <segment_port> -d <db>
```

**`gp_session_role=utility` is the portable spelling; `gp_role=utility` is 7.x-only.**
On 6.x both GUCs exist and default to `dispatch`, but `assign_gp_session_role`
(`src/backend/cdb/cdbvars.c:477`) sets *both* `Gp_session_role` and `Gp_role`, while
`assign_gp_role` (`:519`) sets only `Gp_role` — leaving `Gp_session_role` at `dispatch`,
which `src/backend/utils/init/postinit.c:1196` rejects with
`FATAL: connections to primary segments are not allowed`. On 7.x the standalone
`gp_session_role` GUC is gone, but `src/backend/utils/misc/guc.c:4761` keeps it as a
**rename alias onto `gp_role`**, so the 6.x spelling keeps working; 7.x's own tooling uses
it too (`src/bin/pg_dump/pg_backup_db.c:176`, `src/bin/pg_upgrade/server.c:80`).

`gp_role` is `PGC_BACKEND` on both lines: it must be set at connection time, via
`PGOPTIONS` or the connection string. `SET gp_role = utility` after connecting is a
one-way downgrade at best — on 7.x `check_gp_role()` (`src/backend/cdb/cdbvars.c`) allows
only `utility` once a role is established and never allows going back. On 6.x that hook is
not wired to `gp_role` at all (`guc_gp.c` passes `NULL` for it; the check hook belongs to
`gp_session_role`), so do not rely on the server to stop you.

**Utility mode is for reading. Never write in it.**

A utility-mode session talks to one instance with the dispatcher switched off. Writes
there are invisible to the rest of the cluster: the tuple exists on one segment with no
matching distributed transaction, and the next `gpcheckcat` or mirror resync surfaces it
as corruption. `assign_gp_role()` even clears `MyProc->mppIsWriter` for the session — the
server does not consider you a writer, but nothing stops the SQL.

Connecting to a primary *without* utility mode is refused, with the exact text:

```
FATAL:  connections to primary segments are not allowed
DETAIL: This database instance is running as a primary segment in a Greengage cluster and
        does not permit direct connections.
HINT:   To force a connection anyway (dangerous!), use utility mode.
```

(`src/backend/utils/init/postinit.c`.) Two more `FATAL`s from the same file are worth
recognizing: `maintenance mode: connected by superuser only` — the GUC is spelled
**`maintenance_mode`** (`PGC_POSTMASTER`; `gpstart -U maintenance` sets it by passing `-m`
to `postgres`), and getting in also needs a superuser *and* `gp_maintenance_conn` —
and `System was started in single node mode - only utility mode connections are allowed`.

Legitimate uses: reading a segment's `postgresql.conf` values, inspecting one instance's
`pg_stat_activity`, checking a data directory's `pg_controldata`, confirming a mirror is
replaying. Everything else goes through the coordinator.

---

## Route B — the local demo cluster

### Create it

```sh
source /usr/local/gpdb/greengage_path.sh     # or your $prefix
export LANG=en_US.UTF-8                      # tests require a UTF-8 locale
make create-demo-cluster                     # from the source checkout root
source gpAux/gpdemo/gpdemo-env.sh
```

**Go through `make`, never `./demo_cluster.sh` directly.** `gpAux/gpdemo/Makefile`
`export`s the variables `demo_cluster.sh` reads — `DEMO_PORT_BASE`,
`NUM_PRIMARY_MIRROR_PAIRS`, `WITH_MIRRORS`, `WITH_STANDBY`, `BLDWRAP_POSTGRES_CONF_ADDONS`,
`DEFAULT_QD_MAX_CONNECT` — and it derives `WITH_STANDBY` from `WITH_MIRRORS`. Run the
script directly and it inherits whatever happens to be in your shell: a different port
base, `DEFAULT_QD_MAX_CONNECT=25` instead of `150`, and no standby.

Targets (`gpAux/gpdemo/Makefile`). Only the first two are surfaced at the top level
(`GNUmakefile.in:153-157`); run the others as `make -C gpAux/gpdemo <target>`, because
top-level `make check` is a *different* target that bootstraps a cluster and runs
`installcheck`.

| Target | Does |
|---|---|
| `create-demo-cluster` / `cluster` | `./demo_cluster.sh` |
| `destroy-demo-cluster` / `clean` | `./demo_cluster.sh -d` — stops everything and deletes `$DATADIRS` |
| `check` | `./demo_cluster.sh -c` — port availability only, creates nothing |
| `probe` | `./probe_config.sh` — connects with `PGOPTIONS="-c gp_role=utility"` and dumps `gp_segment_configuration`, `gp_pgdatabase` and `gp_version_at_initdb` from the coordinator, then `gp_version_at_initdb` from each primary. The canonical read-only utility-mode example in the tree |

### Tuning variables

| Variable | Default | Effect |
|---|---|---|
| `PORT_BASE` | `7000` on 7.x, **`6000` on 6.x** (`gpAux/gpdemo/Makefile`) | Coordinator port. Exported to the script as `DEMO_PORT_BASE` |
| `NUM_PRIMARY_MIRROR_PAIRS` | `3` | Segments. The README recommends an **odd** number so data-distribution bugs surface |
| `WITH_MIRRORS` | `true` | `false` halves the instance count and disables recovery testing |
| `WITH_STANDBY` | `true` when `WITH_MIRRORS=true` | Standby coordinator. Not independently settable through the Makefile |
| `DATADIRS` | `gpAux/gpdemo/datadirs` | Where everything lands. Point it at fast local disk |
| `BLDWRAP_POSTGRES_CONF_ADDONS` | empty | Appended to every `postgresql.conf` via `clusterConfigPostgresAddonsFile`. `fsync=off` is the common one — never in production |
| `DEFAULT_QD_MAX_CONNECT` | `150` (Makefile); `25` if the script runs bare | Coordinator `max_connections` |

```sh
DATADIRS=/tmp/gpdb-cluster PORT_BASE=5555 NUM_PRIMARY_MIRROR_PAIRS=1 WITH_MIRRORS=false \
  make create-demo-cluster
PGPORT=5555 make installcheck-world
```

### Port map

`demo_cluster.sh` allocates from `PORT_BASE` in a fixed order:

| Instance | Port | With defaults (`PORT_BASE=7000`, 3 pairs) |
|---|---|---|
| Coordinator | `PORT_BASE` | 7000 |
| Standby coordinator | `PORT_BASE + 1` | 7001 |
| Primaries | `PORT_BASE + 2` … | 7002, 7003, 7004 |
| Mirrors | `PORT_BASE + 2 + NUM_PRIMARY_MIRROR_PAIRS` … | 7005, 7006, 7007 |

The arithmetic is identical on 6.x; only the base moves, so the same layout starts at 6000.

### Data directory layout

Under `$DATADIRS` (default `gpAux/gpdemo/datadirs`), with `SEG_PREFIX=demoDataDir`:

```
qddir/demoDataDir-1            coordinator      (content -1)
dbfast1/demoDataDir0           primary          (content 0)
dbfast2/demoDataDir1           primary          (content 1)
dbfast3/demoDataDir2           primary          (content 2)
dbfast_mirror1/demoDataDir0    mirror           (content 0)
dbfast_mirror2/demoDataDir1    mirror           (content 1)
dbfast_mirror3/demoDataDir2    mirror           (content 2)
standby/                       standby coordinator
gpAdminLogs/                   gpinitsystem and utility logs
```

### `gpdemo-env.sh`

Written by `demo_cluster.sh` at the end of a successful run, into `gpAux/gpdemo/`. Its
entire contents on 7.x:

```sh
export PGPORT=7000
export COORDINATOR_DATA_DIRECTORY=<DATADIRS>/qddir/demoDataDir-1
export MASTER_DATA_DIRECTORY=<DATADIRS>/qddir/demoDataDir-1
```

6.x omits the `COORDINATOR_DATA_DIRECTORY` line. The file is git-ignored
(`gpAux/gpdemo/.gitignore`, alongside `datadirs`, `clusterConfigFile`,
`clusterConfigPostgresAddonsFile`, `hostfile`, `certificate`). Its absence means there is
no cluster to attach to.

### Disk

`gpAux/gpdemo/README` asks for 700 MB of free space. That is enough to *create* the
cluster and nothing more — a full `installcheck-world` run needs far more, and spill files
from a single large query can exceed it on their own. Point `DATADIRS` at real capacity.

### Exit codes

`demo_cluster.sh` exits 0 when `gpinitsystem` returned 0 **or** 1 — `gpinitsystem`
reports warnings as exit code 1 and the script deliberately swallows that. A warning is
not a failure; check `gpstate -e` rather than the exit status.

### Destroy it

```sh
make destroy-demo-cluster
```

This stops every process **and** removes `$DATADIRS`, `gpdemo-env.sh` and
`optimizer-state.log`. There is no undo.

---

## Route C — docker

Commands verbatim from `ci/readme.md`.

### Build

```bash
docker build -t gpdb7_u22:latest -f ci/Dockerfile.ubuntu .        # Ubuntu 22.04
docker build -t gpdb7_regress:latest -f ci/Dockerfile .           # Rocky Linux
```

Build from a checkout with no objects from a previous host build in it. On 6.x the Rocky
file is `ci/Dockerfile.rockylinux`.

### The `--sysctl` flag is mandatory

```
--sysctl "kernel.sem=500 1024000 200 4096"
```

Every `docker run` that will host a cluster needs it. Without it cluster creation fails
while the segment postmasters start: several postmasters on one host exhaust the
container's default SysV semaphore limits. `ci/readme.md` states the reason outright: "we
need to increase semaphore amount to be able to run demo cluster".

### A cluster by hand inside a container

```bash
docker run --name gpdb7_demo --rm -it \
  --sysctl 'kernel.sem=500 1024000 200 4096' gpdb7_u22:latest bash
```

then, inside:

```bash
source gpdb_src/concourse/scripts/common.bash
install_and_configure_gpdb                        # unpacks to /usr/local/greengage-db-devel/
gpdb_src/concourse/scripts/setup_gpadmin_user.bash
make_cluster
su - gpadmin -c '
source /usr/local/greengage-db-devel/greengage_path.sh;
source gpdb_src/gpAux/gpdemo/gpdemo-env.sh;
psql postgres'
```

Note that both scripts get sourced here too — the same two-script rule as on the host.

**6.x delta:** the container has no running sshd and the `gp*` utilities need one even on
a single host — 6.x's `ci/readme.md` lists "we need running ssh server to be able to run
demo cluster" and wraps every `docker run` accordingly. Start it yourself:
`bash -c "ssh-keygen -A && /usr/sbin/sshd && bash"`.
Reference: [Build a Docker image](https://greengagedb.org/en/docs-gg/current/use_docker.html).

### A whole test suite in one shot

```bash
docker run --name gpdb7_opt_on --rm -it -e TEST_OS=ubuntu \
  -e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on' installcheck-world" \
  --sysctl "kernel.sem=500 1024000 200 4096" gpdb7_u22:latest \
  /home/gpadmin/gpdb_src/concourse/scripts/ic_gpdb.bash
```

`TEST_OS=centos` for the Rocky image. `ic_gpdb.bash` builds the demo cluster and runs
`MAKE_TEST_COMMAND` against it. See [greengage-testing](../../greengage-testing/SKILL.md)
for the suites and [greengage-ci](../../greengage-ci/SKILL.md) for what actually runs on
pull requests.

Add `--privileged` when you need `gdb` inside the container.
`ci/docker-compose.yaml` defines a four-host cluster (`cdw`, `sdw1`, `sdw2`, `sdw3`) for
behave scenarios that a single host cannot express.
