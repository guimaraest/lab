# Power tracking

Power records are stored as JSON Lines in `cli/power.log`. This file is the sole
input to `lab power report`; the report does not read historical usage from
system sensors or another database.

The initial meter reads cumulative energy counters exposed by Linux powercap.
Those counters are commonly CPU package domains, so the result is metered-domain
energy and may not represent whole-system or wall power. The power module has a
`PowerMeter` interface that also supports instantaneous-watt readings from a
future backend. Counter readings are totaled by deltas; watt readings are
integrated between samples.

## Commands

```sh
python3 /path/to/lab/cli.py record periodic
python3 /path/to/lab/cli.py record shutdown
python3 /path/to/lab/cli.py record poweron
python3 /path/to/lab/cli.py power report
python3 /path/to/lab/cli.py power report --month 2026-11
```

The report month is UTC. The default report month is the current UTC month.

`record periodic` requires at least one readable supported energy counter and
fails explicitly when none is available. The shutdown and poweron commands
still record their events when a meter is unavailable; their measurements will
be empty. The next periodic sample after a recorded poweron establishes a new
counter baseline so a reboot reset is not counted as negative or fictitious
energy.

## Cron sampling

Add this line to the crontab for a user that can read the host powercap counters:

```cron
*/5 * * * * /usr/bin/python3 /path/to/lab/cli.py record periodic
```

This samples every five minutes. Change `*/5` to the desired cron minute
interval, for example `*/10` for every ten minutes. Replace `/path/to/lab` with
the repository's absolute path. The CLI writes directly to `cli/power.log`; no
crontab or cron configuration is installed by the CLI.

## systemd hooks

Create these unit files manually, replacing `/path/to/lab` with the repository's
absolute path.

`/etc/systemd/system/lab-record-poweron.service`:

```ini
[Unit]
Description=Record lab power-on event
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/lab/cli.py record poweron

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/lab-record-shutdown.service`:

```ini
[Unit]
Description=Record lab shutdown event
DefaultDependencies=no
Before=shutdown.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/lab/cli.py record shutdown

[Install]
WantedBy=shutdown.target
```

After creating or editing unit files, apply them manually with:

```sh
sudo systemctl daemon-reload
sudo systemctl enable lab-record-poweron.service lab-record-shutdown.service
```

The shutdown unit is ordered before `shutdown.target`, which systemd uses for
poweroff, halt, and reboot. Neither unit is installed or enabled automatically.
