# Recovery: signatures, ladder, ordering

Lookup material for "the cluster is unwell". Diagnose with the queries in `../SKILL.md`
first — the fix depends entirely on which signature you have.

---

## Failure signatures

| What you see | What it means | What to run |
|---|---|---|
| `status = 'd'`, `role = preferred_role` | Instance is down in its own role. Its mirror took over, or (no mirror) that content is unavailable | `gprecoverseg` |
| `status = 'u'`, `role <> preferred_role` | Failover completed. Nothing is broken; two primaries share a host | `gprecoverseg -r` |
| `status = 'u'`, `mode = 'n'`, `content > -1` | Pair is up but not streaming — a recovery is in flight, or the mirror is behind | Wait. Do not rebalance |
| `mode = 'n'` on `content = -1` | Normal. The coordinator row always reads `n` | Nothing |
| Every segment `mode = 'n'`, no mirror rows exist | Mirrorless cluster | Nothing. `gprecoverseg` will refuse: `GPDB Mirroring replication is not configured for this Greengage Database instance.` |
| `gpstart`: `Do not have enough valid segments to start the array.` | Some `content` has neither a live primary nor a live mirror | Fix the host/disk first; no utility can recover a content with no surviving copy |
| `gpstate`: `DATABASE IS PROBABLY UNAVAILABLE` | The coordinator cannot form a gang | `gpstate -s`, then this table |
| Query fails with `failed to acquire resources on one or more segments` | A segment died mid-query or is unreachable (`src/backend/cdb/dispatcher/cdbgang_async.c`) | Check `gp_segment_configuration`; FTS may not have caught up — `SELECT gp_request_fts_probe_scan();` |
| `gpstart`: `Catalog Versions are incompatible` | Binaries and data directory are from different builds | Not a recovery problem — see [greengage-build](../../greengage-build/SKILL.md) |

Timeline questions ("when did this start") are answered by `gp_configuration_history`, not
by `gp_segment_configuration`.

---

## The ladder, in order

Every rung assumes `COORDINATOR_DATA_DIRECTORY` (7.x) / `MASTER_DATA_DIRECTORY` (6.x) and
`PGPORT` are exported and the coordinator is up. `gprecoverseg` runs **on the
coordinator**, not on the failed host.

### 1. Incremental — the default

```sh
gprecoverseg -a
```

Runs `pg_rewind` against the live copy, then lets the segment stream WAL to catch up
(`IncrementalRecovery` in `gpMgmt/sbin/gpsegrecovery.py`). Cheapest, and correct whenever
the failed data directory is intact. Options come from
`gpMgmt/bin/gppylib/programs/clsRecoverSegment.py`.

### 2. Differential

```sh
gprecoverseg --differential -a
```

`rsync`-based: copies only files that differ, without recreating the data directory. In
between incremental and full in cost. **Requires rsync ≥ 3.1.0** — otherwise:
`To perform a differential recovery, a minimum rsync version of 3.1.0 is required.`
Present on both 6.x and 7.x.

### 3. Full

```sh
gprecoverseg -F -a
```

Deletes the failed data directory and rebuilds it with `pg_basebackup`. Use when the data
directory is gone, corrupt, or when an interrupted recovery left it in an unknown state.
On 7.x add `--max-rate <rate>` to cap the transfer and keep the network usable — 7.x only,
6.x's `gprecoverseg` has no such option. It applies to full recovery and nothing else:
combined with `-r` or `-o` it is dropped with
`-r flag does not support the use of --max-rate, hence --max-rate will be ignored`, and on
an incremental or differential run you get ` --max-rate flag is only supported with
segments undergoing Full recovery (-F).`

### 4. Rebalance — last, and only when everything is `mode = 's'`

```sh
gprecoverseg -r -a
```

Stops the out-of-place primaries, promotes the mirrors sitting in their preferred primary
role, and resyncs. **This is the only rung that interrupts running work**, which is why it
prompts with:

```
This operation will cancel queries that are currently executing.
Connections to the database however will not be interrupted.
```

---

## The ordering constraint

**Recover first. Wait for `mode = 's'` on every pair. Then rebalance.**

`gprecoverseg -r` does not fail when pairs are not ready — it silently skips them and
finishes "successfully" with a partial result. From
`gpMgmt/bin/gppylib/operations/rebalanceSegments.py`:

```
Not rebalancing primary segment dbid %d with its mirror dbid %d because one is either
down, unreachable, or not synchronized
```

and, if any primary refuses to stop:

```
%d segments failed to stop.  A full rebalance of the system is not possible at this time.
Please check the log files, correct the problem, and run gprecoverseg -r again.
gprecoverseg will continue with a partial rebalance.
```

**The completion line does not tell you whether anything moved.**
`The rebalance operation has completed with WARNINGS. Please review the output in the
gprecoverseg log.` appears only when a primary failed to stop — that is the single case
`rebalance()` returns false (`return allSegmentsStopped`). When every unbalanced pair was
skipped for being unsynchronized, the run logs `No segments to rebalance` and then prints
`The rebalance operation has completed successfully.` Re-read `gp_segment_configuration`
afterwards; never take the completion line as proof.

If there was nothing to do in the first place you get
`No segments are running in their non-preferred role and need to be rebalanced.`
(`gpMgmt/bin/gppylib/programs/clsRecoverSegment.py:398`).

### The replay-lag guard

Before promoting, `-r` connects to each out-of-place **primary** in utility mode and runs
`select pg_wal_lsn_diff(flush_lsn, replay_lsn) from pg_stat_replication` — the primary's
row describes its mirror — then **aborts** when that lag reaches `ALLOWED_REPLAY_LAG`,
default **10 GB** (`gpMgmt/bin/gppylib/commands/gp.py:60`):

```
<n> bytes of wal is still to be replayed on mirror with dbid <d>, let mirror catchup on
replay then trigger rebalance. Use --replay-lag to configure the allowed replay lag limit
or --disable-replay-lag to disable the check completely if you wish to continue with
rebalance anyway
```

`--replay-lag <GB>` raises the ceiling; `--disable-replay-lag` removes the check and is
**7.x only**. **6.x has no default ceiling at all**: its `--replay-lag` defaults to `None`
and `rebalanceSegments.py` runs the check only `if self.replay_lag is not None`, using the
9.4 spelling `pg_xlog_location_diff(flush_location, replay_location)`. On 6.x an
unguarded `-r` will promote a mirror that is gigabytes behind. Waiting is almost always
cheaper than that.

### Waiting correctly

```sql
-- Poll until this returns zero rows
SELECT content, role, preferred_role, mode, status
FROM   gp_segment_configuration
WHERE  content > -1 AND (mode <> 's' OR status <> 'u');
```

`gpstate -e` is the utility equivalent and exits non-zero while anything is outstanding,
so it scripts cleanly:

```sh
until gpstate -e | grep -q 'All segments are running normally'; do sleep 30; done
```

---

## `gprecoverseg` option reference

| Option | Effect | Line |
|---|---|---|
| *(none)* | Incremental, in place | both |
| `--differential` | rsync delta, in place | both |
| `-F` | Full rebuild via `pg_basebackup` | both |
| `-r` | Rebalance to preferred roles | both |
| `-p <hosts>` | Recover onto spare hosts | both |
| `-o <file>` | Write a sample recovery config instead of recovering | both |
| `-i <file>` | Recover from a config file (from `-o`, edited) | both |
| `-a` | Do not prompt | both |
| `-B <n>` | Hosts in parallel. Default 16, max 64 | both |
| `-b <n>` | Segments per host in parallel. Default 64, max 128 | both |
| `--replay-lag <GB>` | Rebalance lag ceiling. Default `10` on 7.x; **no default on 6.x**, where the check runs only if the flag is given | both |
| `--disable-replay-lag` | Skip the lag check | **7.x only** |
| `--max-rate <rate>` | Throttle a full recovery | **7.x only** |
| `--hba-hostnames` | Write hostnames instead of CIDR into `pg_hba.conf` | both |
| `-s` / `--no-progress` | Sequential progress / no progress | both |

Reference: [gprecoverseg](https://greengagedb.org/en/docs-gg/current/reference/utils/gprecoverseg.html),
[Check and recover segments](https://greengagedb.org/en/docs-gg/current/check_recover_segments.html).

---

## Never interrupt a recovery halfway

`gprecoverseg` installs a SIGINT handler that asks you to reconsider, in these words:

```
It is not recommended to terminate a recovery procedure midway. However, if you choose to
proceed, you will need to run either gprecoverseg --differential or gprecoverseg -F to
start a new recovery process the next time.
```

That is the real cost: an aborted recovery leaves the target data directory in a state
plain incremental recovery cannot resume from. It ignores `SIGHUP` on purpose, so an SSH
drop will not kill it — run it under `tmux`/`nohup` anyway.

Failure exits are distinguishable:
`gprecoverseg failed. Please check the output for more details.` versus
`gprecoverseg differential recovery failed. Please check the gpsegrecovery.py log file and
rsync log file for more details.` Success prints `Segments successfully recovered.`

`Heap checksum setting differences reported on segments` means the failed instance and the
cluster disagree on `data_checksums`. That is a build/initdb mismatch, not something
recovery can fix.

---

## The standby coordinator

### Create or replace one

```sh
gpinitstandby -s <standby_host> -P <port> -S <standby_datadir> -a
gpinitstandby -r          # remove the standby recorded in the catalog
gpinitstandby -n          # start the existing standby; do not touch the catalog
```

`-n` dispatches to `check_and_start_standby()` — use it when the standby row is correct but
the process is not running. It is mutually exclusive with `-s` and `-S`
(`Options -s and -n cannot be specified together.`). `-r` "will need to shutdown the GPDB
array to be able to complete the request" (its own help text) — it is not a no-downtime
operation.

### Promote one

```sh
gpactivatestandby -d <standby_data_directory> -a
```

Preconditions, enforced by `gpMgmt/bin/gpactivatestandby`:

- **Run it on the standby host.** It checks for `standby.signal` in the given data
  directory and refuses otherwise:
  `Critical required file on standby "<path>" is not present.`
  **6.x delta:** 6.x is PostgreSQL 9.4 and looks for `recovery.conf`, not
  `standby.signal`.
- **The old coordinator must not be running.** If a postmaster answers on the original
  coordinator's port it aborts with `Active postgres process on coordinator` (6.x:
  `Active postgres process on master`), having first told you to stop it (and to remove
  stale `/tmp/.s.PGSQL.<port>*` files if that is all that is left).
- If the standby postmaster is not running: `Standby postmaster is not running.` /
  `Use -f option to bring the system anyway`. `-f` is a real data-loss risk, not a
  formality.

Afterwards the utility prints the things that are easy to forget:

- `Do not re-start the failed coordinator while the fail-over coordinator is operational,
  this could result in database corruption!`
- `COORDINATOR_DATA_DIRECTORY is now <path>` and `COORDINATOR_PORT is now <n>` (6.x:
  `MASTER_DATA_DIRECTORY is now <path>`) — update every script and every exported
  environment that named the old ones.
- `Query planner statistics must be updated on all databases following standby coordinator
  activation.` — run `ANALYZE` against every user database, or
  `vacuumdb --all --analyze-only --jobs=5`, which is what `installcheck-analyze` uses.

The promoted standby has **no standby of its own**. Run `gpinitstandby -s <host>` again to
restore redundancy.

References:
[gpactivatestandby](https://greengagedb.org/en/docs-gg/current/reference/utils/gpactivatestandby.html),
[gpinitstandby](https://greengagedb.org/en/docs-gg/current/reference/utils/gpinitstandby.html).

---

## `gpcheckcat` — catalog consistency

```sh
gpcheckcat -O <dbname>              # only the checks marked "online": True in all_checks
gpcheckcat -A                       # every database (what `make installcheck-gpcheckcat` runs)
gpcheckcat -g /tmp/repair <dbname>  # generate repair SQL into /tmp/repair
gpcheckcat -l                       # list the available tests
gpcheckcat -R <test> | -s <test>    # run only / skip these tests
```

Options are documented in the usage block at the top of `gpMgmt/bin/gpcheckcat`.

- **Restart into restricted mode first for a full run.** The docs say it outright:
  "Restart the database in restricted mode when running `gpcheckcat`, otherwise
  `gpcheckcat` might report inconsistencies due to ongoing database operations rather than
  the actual number of inconsistencies." `-O` exists precisely because the full set is not
  online-safe. `gpstart -R` gives you superuser-only access.
- **`-g` writes SQL, it does not run it.** Read every generated statement before applying
  anything. Catalog repair applied blind is worse than the inconsistency.
- **It refuses to run during an expansion**:
  `ERROR: Usage of gpcheckcat is not supported while the cluster is in a reconfiguration
  state, exit gpcheckcat` (`conflict_with_gpexpand()`, `gpMgmt/bin/gppylib/commands/gp.py:1377`).

Reference: [gpcheckcat](https://greengagedb.org/en/docs-gg/current/reference/utils/gpcheckcat.html).

---

## When to stop debugging and recreate

On a **demo or test** cluster, recreating is usually cheaper than the third recovery
attempt. Recreate rather than debug when any of these hold:

| Condition | Why debugging loses |
|---|---|
| Two or more contents have no surviving copy | Nothing can be recovered from |
| An interrupted `gpexpand` left `gpexpand.status` and `gpexpand --rollback` also fails | The catalog is mid-reconfiguration; every other utility refuses to run |
| `gpcheckcat` reports inconsistencies you did not cause and cannot explain | Repair SQL on a cluster you do not need is pure risk |
| The data directories are on a disk that filled and you cannot say what got truncated | Silent partial writes |
| You are chasing a test failure and the cluster is a means, not the object | The cluster is not the artifact |

```sh
make destroy-demo-cluster && make create-demo-cluster && source gpAux/gpdemo/gpdemo-env.sh
```

On a **production** cluster this trade does not exist. `gpdeletesystem -d <datadir>`
destroys the cluster and `-f` makes it ignore backup files; there is no undo and no
partial mode.

See [reference/provisioning.md](provisioning.md) for what recreation actually costs, and
[greengage-backup-restore](../../greengage-backup-restore/SKILL.md) before you delete
anything you want back.
