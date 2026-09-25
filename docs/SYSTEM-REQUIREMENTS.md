# System requirements

<p align="center">
  <a href="../README.md"><img alt="YaeMiko wordmark" src="assets/wordmark-dark.svg" width="420"></a>
</p>

Back to [README](../README.md).

## Contents

- [Three tiers at a glance](#three-tiers-at-a-glance)
- [What is measured and what is estimated](#what-is-measured-and-what-is-estimated)
- [Minimum](#minimum)
- [Recommended](#recommended)
- [Best](#best)
- [System packages](#system-packages)
- [Network and bandwidth](#network-and-bandwidth)
- [Database sizing](#database-sizing)
- [Where the resource weight comes from](#where-the-resource-weight-comes-from)
- [How to measure your own usage](#how-to-measure-your-own-usage)
- [Scaling down](#scaling-down)
- [Troubleshooting resource problems](#troubleshooting-resource-problems)

## Three tiers at a glance

| | Minimum | Recommended | Best |
| --- | --- | --- | --- |
| **CPU** | 1 shared vCPU | 1 dedicated vCPU | 2 dedicated vCPU |
| **RAM** | 512 MB | 1 GB | 2 GB |
| **Disk** | 5 GB | 10 GB | 20 GB |
| **Swap** | 1 GB | none needed | none needed |
| **OS** | Debian 12, Ubuntu 24.04, or any Docker host | same | same |
| **Python** | 3.14.7 | 3.14.7 | 3.14.7 |
| **Network** | 1 Mbps up, 5 GB per month | 10 Mbps up, 100 GB | 25 Mbps up, unmetered |
| **Groups served** | 1 to 3 | 10 to 30 | 100 or more |
| **Platform fit** | Render `0.5c-512mb` | Render `1c-2g`, Railway, 1 GB VPS | 2 GB VPS or better |

Minimum means the bot starts, connects, and answers commands. It is not comfortable: the first ONNX
inference and the first ffmpeg frame extraction are slow on 512 MB, and a busy group can push it into
swap. Recommended is the tier most deployments should pick. Best is for large groups, media heavy
groups, and anyone running the anti-NSFW checks on every image.

## What is measured and what is estimated

Being precise about this, because the numbers below drive real hosting choices.

| Figure | Source |
| --- | --- |
| Repository size, 9.2 MB without `.git` | `du -sh --exclude=.git .` on this checkout |
| 129 Python files, 38,708 lines | `find ... | wc -l` on this checkout |
| 65.4 MB of direct dependency wheels | wheel sizes read from the PyPI JSON API for every pin in `requirements.txt` |
| ONNX Runtime 1.30.0 wheel, 22.5 MB | `https://pypi.org/pypi/onnxruntime/1.30.0/json` |
| opennsfw-onnx 0.1.0 wheel, 20.9 MB | same API, the wheel ships the model |
| Pillow 12.3.0 wheel, 6.8 MB | same API |
| Kurigram 2.2.26 wheel, 5.8 MB | same API |
| `concurrent_updates(64)` | `Mikobot/__init__.py:296` |
| 20 second HTTP timeout | `Mikobot/state.py` |
| Disk figures | Wheel sizes plus the source tree, with room for logs, temp media and the pickle file |
| **RAM figures** | **Estimates.** Not measured on a live bot, see below |

The RAM numbers are the one part that is judgement rather than measurement. They are derived from the
process count, the ONNX Runtime arena, and Pillow buffers. Verify with the commands in
[How to measure your own usage](#how-to-measure-your-own-usage) before paying for more than you need.

## Minimum

Barely enough to run. Good for a single group or a test instance.

```text
CPU    1 shared vCPU
RAM    512 MB
Disk   5 GB free
Swap   1 GB configured
Python 3.14.7
```

What you give up:

- The anti-NSFW module loads a 20.9 MB model into an ONNX Runtime session on first use. On 512 MB
  this is the largest single allocation in the process.
- ffmpeg frame extraction for video and animated stickers is CPU bound, and one shared vCPU means
  commands queue behind it.
- `concurrent_updates(64)` allows many updates in flight. Under load on one core, the event loop
  spends its time context switching rather than replying.

## Recommended

The default choice. Handles a normal group with media, the AI commands, and the anti-NSFW check.

```text
CPU    1 dedicated vCPU
RAM    1 GB
Disk   10 GB free
```

One dedicated vCPU matters more than the clock speed. The bot is I/O bound most of the time, waiting
on Telegram, the database, and outbound HTTP, so a shared vCPU that is throttled alongside other
tenants adds latency to every reply. A dedicated core removes that.

1 GB leaves room for the ONNX session, Pillow buffers, and the connection pool while still keeping
the process well clear of swap.

## Best

For large groups, heavy media, or an instance that also serves as a development machine.

```text
CPU    2 dedicated vCPU
RAM    2 GB
Disk   20 GB free
```

What the second core buys:

- ONNX Runtime defaults to one thread per core. With the anti-NSFW check active on every image in a
  busy group, image classification is the hottest path in the process.
- ffmpeg runs as a subprocess, so it competes for CPU while the bot keeps serving commands.
- Media modules, the AI commands, and speedtest already offload to threads through
  `asyncio.to_thread`. More cores means those threads finish sooner.

What the extra disk buys: rotating logs, temp media from `TEMP_DOWNLOAD_DIRECTORY`, and the
`ptb_persistence.pickle` context store all live on the same volume. On a platform with an ephemeral
disk the pickle is recreated on every deploy, which is a correctness issue rather than a capacity
one. See [DEPLOYMENT.md](DEPLOYMENT.md).

## System packages

| Package | Required | Why |
| --- | --- | --- |
| `ffmpeg` | Yes, for media features | Frame extraction in `Mikobot/plugins/antinsfw.py` and thumbnail generation in `Mikobot/plugins/anime.py` |
| `libgomp1` | Yes, for the NSFW check | OpenMP runtime that ONNX Runtime links against |
| `curl` | Yes, in the Docker image | Health probes and downloads |
| `git` | Only for a source install | Not needed in the container |
| `tmux` | Optional | Only for running without systemd |

On Debian and Ubuntu:

```bash
sudo apt-get install -y ffmpeg libgomp1
```

The [Dockerfile](../Dockerfile) already installs all three in the runtime stage.

## Network and bandwidth

YaeMiko makes only outbound connections. No inbound port has to be open.

| Item | Direction | Volume |
| --- | --- | --- |
| Bot API long polling | Outbound, persistent | Roughly 1 to 3 MB per day per group |
| MTProto session | Outbound, persistent | A few hundred KB per day |
| Media upload and download | Both | Dominated by images and video in chat |
| Speedtest | Outbound | Bursts of tens of MB while `/speedtest` runs |
| AI calls | Outbound | Small, prompt sized, rate limited by Google |

The long polling connection is a constant low volume stream, not a burst workload. A 1 Mbps uplink is
enough for the polling itself. The bandwidth that matters is media: a group that passes 100 MB of
video a day will use it, and `/speedtest` will saturate the link while it runs.

## Database sizing

Both stores are small unless the group is large. This is the least demanding part of the deployment.

| Store | Minimum | Comfortable | What grows it |
| --- | --- | --- | --- |
| PostgreSQL | 1 GB | 5 GB | One row per warning, lock, note, rule, and filter |
| MongoDB | 512 MB shared | 5 GB | User profiles, chat metadata, AFK entries, whispers, karma |

Atlas M0 gives 512 MB, Render Free Postgres gives 1 GB, and both are enough for a small group. The
connection pool is the thing to watch rather than the data volume: `pool_pre_ping=True` and
`pool_recycle=1800` in `Database/sql/__init__.py` keep the pool healthy on managed platforms that drop
idle connections.

## Where the resource weight comes from

Measured wheel sizes for the dependencies that actually matter:

| Dependency | Wheel | Why it is heavy |
| --- | --- | --- |
| onnxruntime | 22.5 MB | Native inference engine, the largest single wheel |
| opennsfw-onnx | 20.9 MB | Ships the pre trained model inside the wheel |
| Pillow | 6.8 MB | Native image codecs |
| Kurigram | 5.8 MB | MTProto implementation |
| SQLAlchemy | 4.6 MB | Includes the native C extensions |
| pymongo | 1.1 MB | BSON and the wire protocol |
| google-genai | 1.1 MB | The AI client and its models |
| python-telegram-bot | 0.7 MB | Pure Python, small |
| All 24 direct dependencies | 65.4 MB | Download size, excluding transitive dependencies |

So the install is roughly 65 MB of wheels plus transitive dependencies, and the runtime memory is
dominated by two things: the ONNX session and the two concurrent clients, PTB and Kurigram, each
holding its own connection state.

Two things are lazy on purpose, so you are not paying for them at startup:

- The ONNX classifier is imported inside the function that needs it, not at module import, so the
  20.9 MB model is only loaded when an anti-NSFW check actually runs.
- The MTProto and Bot API clients both start, because both are always needed, but no other heavy work
  happens during import.

## How to measure your own usage

Do not trust the table above for your own instance. Measure it.

```bash
# Resident memory of the running bot, sampled once
ps -o pid,rss,vsz,%cpu,etime -C python

# Or follow it live
watch -n 2 "ps -o pid,rss,%cpu,etime -C python"

# Linux specific: peak memory recorded by the kernel
grep VmHWM /proc/$(pgrep -f "python -m Mikobot" | head -1)/status

# Disk used by the checkout, the virtual environment and the pickle
du -sh /path/to/YaeMiko
du -sh /path/to/YaeMiko/.venv
ls -lh /path/to/YaeMiko/ptb_persistence.pickle
```

`VmHWM` is the high water mark, which is the number that matters when sizing. `RSS` is the current
usage and can look fine right after startup.

Take the measurement after a normal day of use in your group, not at boot. The ONNX session, the log
handlers, and the connection pool all fill in over time.

## Scaling down

If you are over budget, in order of impact:

1. Trim the plugin list with `NO_LOAD`. Each skipped module drops an import chain at startup. The
   heaviest are `sangmata` (Pillow plus image work), `cosplay` (image search and download),
   `imagegen` (image generation, currently flagged off in the module display name) and `reverse`
   (reverse image search). See [PLUGINS.md](PLUGINS.md) for what each one pulls in.
2. Set `GEMINI_API_KEY` to empty. The AI client and its transitive dependencies are no longer
   imported.
3. Set `LOGGER=False` and `LOG_LEVEL=WARNING`. The rotating file handler stops writing.
4. Lower `concurrent_updates` in `Mikobot/__init__.py` from 64 to 16. Fewer updates in flight means a
   smaller working set under burst.
5. Move PostgreSQL to a managed instance. The local server process and its page cache are otherwise
   counted against the same vCPU and RAM as the bot.

## Troubleshooting resource problems

| Symptom | Cause | Fix |
| --- | --- | --- |
| Bot starts, then the worker is killed | Out of memory, the platform sends SIGKILL | Move up one tier, or apply the scaling down steps |
| First anti-NSFW check takes many seconds | ONNX session loading on a cold, small instance | Expected once. Pin the class in a warm instance, or disable the module |
| Replies lag, CPU pegged at 100 percent | ffmpeg or ONNX saturating one shared core | Move to a dedicated vCPU |
| Container restarts without a traceback | OOM kill, not an application error | Check the platform dashboard for an out-of-memory event |
| Swap in use, everything slow | Memory pressure from the pickle store or logs | Check `VmHWM`, then trim logs and temp media |
| Speedtest never finishes | Uplink too slow or heavily throttled | Not a bot problem, the test measures the line |
