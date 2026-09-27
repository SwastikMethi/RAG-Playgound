# Oracle Always Free public beta

This deploys the existing app and worker together on one ARM VM, behind Caddy
HTTPS. PostgreSQL, Qdrant, uploaded files, exports, model assets and TLS state
persist on a dedicated data volume. Only ports 80 and 443 are public. Local
`start.sh` / `stop.sh` and the existing local database are separate.

**Not deployed yet:** the owner has no Oracle account or VM. Cloud provisioning,
real DuckDNS/TLS/Turnstile checks and an OCI backup/restore drill remain launch
gates. No paid resource or fallback has been provisioned.

## Free-service choice and limits

Oracle currently documents an Always Free ARM allowance equivalent to **2 OCPUs
and 12 GB RAM**, **200 GB combined boot/block storage**, and **five volume
backups**. Use the home region, a 50 GB boot volume and one 150 GB data volume;
confirm every resource is marked Always Free in the console before creating it.
Account verification requires a card; capacity can be unavailable and idle VMs
can be reclaimed. Keep a copy of recovery configuration outside the VM.
[Oracle limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

Render's free service has ephemeral storage and its free PostgreSQL database
expires after 30 days. Vercel functions have duration and request-size limits
that do not fit this persistent worker/upload stack. Neither is the selected
host. [Render free services](https://render.com/docs/free),
[Vercel function limits](https://vercel.com/docs/functions/limitations).

DuckDNS supplies the hostname, Caddy obtains HTTPS certificates, and Cloudflare
Turnstile protects public account forms. Users pay OpenAI for their own API
usage; free hosting does not include model credits. There is no shared server
OpenAI key, email/password reset service, automatic paid upgrade or managed SLA.

## 1. Account, network and volume

1. Create an Oracle Always Free account and an Ubuntu 24.04 ARM instance using
   `VM.Standard.A1.Flex`, 2 OCPUs and 12 GB RAM. If free capacity is unavailable,
   stop and wait; do not substitute a paid shape. Use SSH keys and retain the
   private key locally.
2. Create and attach the 150 GB block volume in the same availability domain.
   Follow Oracle's attachment instructions. Identify its device using `lsblk -f`;
   format **only the new empty data volume**, never a boot/existing device.
   Mount it at `/srv/ragplayground`, with an `/etc/fstab` entry using its UUID.
   The deployment wrapper refuses to run unless that path is a mount point.
3. In the OCI security list and host firewall allow TCP 80/443 from the internet,
   and SSH 22 only from your administrator IP. Do not publish 5432, 6333, 6334,
   8000 or 8780. Docker publishes only Caddy in production. Restrict IPv6 too
   if enabled. Do not use `--forwarded-allow-ips '*'`.
4. Install Docker Engine and the Compose plugin using the
   [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
   Give only the administrator Docker access. Choose a non-conflicting subnet
   if `172.30.77.0/24` is already used; update both Compose and API proxy trust
   together if it changes.
5. Register `your-name.duckdns.org` and point it to the VM's public IPv4 in the
   DuckDNS dashboard. Leave AAAA unset unless IPv6 is configured. Keep the
   assigned IP stable, or update DNS after changing the instance/IP.
6. Create a free **managed Turnstile widget** restricted to that hostname.
   Keep production test/bypass keys out of this deployment. The server validates
   hostname and `register`, `login` or `recover` action as well as success.

## 2. Install and configure

Copy/clone the reviewed `codex/free-hosting` release onto the VM. Use a fresh
cloud volume/database. Do not copy local uploads, `.env`, database volumes or
owner credentials. From the checkout:

```sh
sudo install -d -m 0700 -o 10001 -g 10001 /srv/ragplayground/artifacts /srv/ragplayground/models /srv/ragplayground/vectors
sudo install -d -m 0700 /srv/ragplayground/postgres /srv/ragplayground/caddy
sudo install -d -m 0700 -o "$USER" /srv/ragplayground/restore
python3 deploy/configure.py
./deploy/compose.sh config --quiet
./deploy/compose.sh build
./deploy/compose.sh up -d postgres qdrant
./deploy/compose.sh run --rm migrate
./deploy/compose.sh run --rm --no-deps worker python tools/prepare_models.py --reranker --pdf
./deploy/compose.sh up -d
./deploy/compose.sh ps
```

`configure.py` asks for the public hostname, TLS contact email and Turnstile keys,
then writes `.env.production` with mode 0600 and fresh random database/Fernet
keys. It refuses to overwrite an existing file. Save an encrypted copy outside
the VM **before** accepting users. Never regenerate the master key after saving
credentials: doing so makes stored OpenAI and database credentials unreadable.
Keep this file out of shell output, screenshots, Git and support logs. Do not run
`docker compose config` without `--quiet` around other people: it expands secrets.

The initial model-asset download is several GB and can take time. The ARM image
includes Docling, Torch, the cross-encoder reranker and PageIndex. Profiles live
in `deploy/profiles.yaml`: GPT-6 Luna with `max_completion_tokens` and
`reasoning_effort: none`, and `text-embedding-3-large` (3,072 dimensions).
Changing model identity requires preparing new indexes where applicable.

Production uses two worker slots, one active comparison, and two concurrent
generation/embedding requests. Each account gets five projects, 500 MiB raw
uploads, 2 GiB artifacts, 100,000 vector points and 64 queued jobs. The whole
queue caps at 256; writes stop below a 20 GiB free-disk reserve. Keep the 50-file
corpus cap. Metadata admission uses a short global database lock; this is an
intentional small-beta throughput limit. New instances are not horizontally
scalable without revisiting volume/worker coordination.

PostgreSQL snapshot sources remain supported but disabled until the operator
sets both exact `RAG_DATABASE_HOST_ALLOWLIST` and relation/column policy in
`.env.production`. Follow document 17 for a read-only source login. Never allow
arbitrary user hosts, cloud metadata addresses or the application database.

## 3. Launch checks

- Visit `https://your-name.duckdns.org/api/v1/health`; require valid public TLS
  and `status: ok`. HTTP must redirect to HTTPS. Public `/api/v1/projects` must
  return 401. Origin spoofing or missing CSRF on an authenticated write must fail.
- Create two real accounts through Turnstile. Save each single-use recovery code
  in a password manager. Passwords are Argon2id-hashed; Fernet is authenticated
  encryption for provider/database keys, not password hashing.
- Save an OpenAI key in each account's Setup page. A key is never displayed back.
  Without a key, live techniques are unavailable. The server cannot fall back to
  an administrator's environment key. API calls are billed to the key owner.
- Upload an authored test file, prepare all six techniques and ask a bounded
  question. Inspect evidence, individual status/timing, event replay and one
  standalone export. Check login, logout, password change and recovery; old
  sessions must lose data access. The second account must see none of the first
  account's projects, files, events, vector hits or exports.
- Restart the stack and confirm users, prepared indexes and files remain.
  Confirm anonymous access to API/Qdrant/PostgreSQL ports from outside the VM is
  impossible. Review desktop/mobile, keyboard operation and reduced motion.
- Complete the backup setup and an isolated restore check before inviting users.
  Passing a local fixture is not evidence that public TLS, Turnstile or a cloud
  restore has been verified.

## 4. Consistent backups

Back up the **entire data volume at one quiescent point**. Independently timed
PostgreSQL, Qdrant and file copies can disagree. This small beta accepts a nightly
maintenance window: `deploy/backup.py` stops the stack, flushes the filesystem,
waits up to 30 minutes for an OCI volume backup, and restarts services even if
backup creation fails. Inform users of the window; interrupted jobs may fail and
need a manual rerun. No provider request is automatically retried on restart.

Install the [OCI CLI](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)
on the VM. Put only this VM in a dynamic group. In a dedicated application
compartment grant that group `use volumes`, `manage volume-backups` and
`inspect boot-volume-backups`; review these policies against the
[Core Services IAM reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm).
The script uses instance-principal authentication; do not put an OCI signing key
in the app. Add the data-volume and compartment OCIDs to `.env.production`.

```sh
python3 deploy/backup.py
```

The script stores release commit, profiles and a 0600 copy of configuration on
the data volume. Only a backup that reaches `AVAILABLE` while services remain
stopped receives `rag-playground=consistent-v1`. A failed/timed-out attempt stays
`pending-v1`: inspect it manually and do not treat it as a valid checkpoint.
Retention deletes only older available `consistent-v1` backups for this exact
volume, after a successful replacement, retaining three. It never deletes an
unrelated/boot backup to make room.

Before scheduling, ensure **across the tenancy** that there is room for a fourth
temporary data backup within the five-backup free allowance. The script counts
its own compartment; other compartments must be checked in the console. Use an
unupgraded Always Free account and do not enable paid cross-region copies or
extra backup policies. On quota failure, review capacity; do not enable billing.
Oracle volume backups are encrypted at rest. [Backup behavior](https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumebackups.htm).

After the first successful backup, schedule the same command at a quiet time,
for example `15 3 * * * cd /path/to/checkout && /usr/bin/python3 deploy/backup.py >> /path/to/backup.log 2>&1`
in the administrator's crontab, with the installed `oci` on PATH. Rotate that log
and check success daily; the application does not send backup alerts.

## 5. Restore and updates

1. Keep public traffic and workers stopped. Select an `AVAILABLE` backup tagged
   `consistent-v1`, and create/attach a restored volume using the Oracle console.
   Stay inside the combined 200 GB allowance. A full second 150 GB volume will
   exceed it with the current layout: do not buy temporary capacity implicitly.
   In a real failure, replacing the failed original volume is a deliberate
   operator action, taken only after confirming a usable backup. Never delete
   the only healthy copy to perform a drill.
2. Mount the restored volume at `/srv/ragplayground` on the isolated recovery
   VM/host. Read `restore/release.json`, check out that exact commit and use its
   image versions. Restore `.env.production` (0600) and `deploy/profiles.yaml`
   from `restore/`; compare with your encrypted off-VM copy. Do not rotate the
   master key. Do not point DNS at the recovery host yet.
3. Start storage only, then check integrity without starting the public app:

   ```sh
   ./deploy/compose.sh up -d postgres qdrant
   ./deploy/compose.sh run --rm --no-deps api python deploy/verify_restore.py
   ./deploy/compose.sh exec -T postgres psql -U rag -d ragplayground -c 'DELETE FROM auth_sessions;'
   ./deploy/compose.sh up -d
   ```

   The read-only verifier checks every artifact hash, credential decryption and
   each ready vector scope's point count. Then log in and exercise a stored run,
   source download and fresh question with an authorized test account. Revoke
   restored sessions as above so old backup cookies cannot regain access.
4. Switch DNS/reopen traffic only after the checks pass. Keep the last good
   checkpoint until the recovered system is verified. An OCI-native restore
   cannot be rehearsed on this machine without the account/volume; local isolated
   restore evidence is recorded separately in IMPLEMENTATION_STATUS.md.

Before every update, take a successful consistent backup, stop API/worker/Caddy,
check out the reviewed commit, build, migrate and start. Migrations run before
API/worker startup. If migration fails, keep public traffic stopped. Restore the
previous complete checkpoint and its matching code when rollback requires it;
never run old code against an unreviewed newer schema. Use
`./deploy/compose.sh stop` to stop without deleting data. Never use `down -v` or
format a volume as part of a routine update.
