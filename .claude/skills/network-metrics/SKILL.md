---
name: network-metrics
description: What Maze Arena measures (RTT via PING timestamps, STATE tick gaps, inter-update time/jitter, disconnection detection time, UDP retransmission count), how to measure each correctly, and the CSV format written to metrics/. Use when adding instrumentation, writing metric/plot code, or comparing the TCP and UDP versions.
---

# Network metrics

Goal: compare TCP vs UDP with numbers, under the same game and same tick rate.

## Clock rules

- Intervals (RTT, gaps, detection time): `time.monotonic()` — never
  `time.time()` (wall clock can jump).
- Never subtract timestamps taken on two different machines.
- The `ts` column in CSV is `time.time()` (wall clock) only for ordering/plotting.

## What we measure

| metric | where | how | unit |
|--------|-------|-----|------|
| `rtt` | client | send `PING {t: monotonic()}` every 1 s; on `PONG` → `now - t` | ms |
| `tick_gap` | client | on each STATE: `tick - last_tick - 1` (0 = nothing missed, >0 = lost STATEs, <0 = reordered/old, dropped) | ticks |
| `inter_update` | client | arrival time between consecutive accepted STATEs (ideal 100 ms; spread = jitter) | ms |
| `disconnect_detect` | server | `detected_at - last_seen_at` for the client when PLAYER_LEFT is emitted; `extra` = `fin`, `rst`, `timeout` | ms |
| `retransmit` | UDP sender (both sides) | one row per retransmission; `value` = attempt number, `extra` = `TYPE:seq` | count |
| `retransmit_fail` | UDP sender | reliable msg given up after 16 tries; `extra` = `TYPE:seq` | count |

Expected story for the report:
- TCP: `tick_gap` always 0, but `inter_update` spikes under loss (head-of-line blocking).
- UDP: `tick_gap` > 0 under loss, `inter_update` stays smooth, retransmissions only for reliable messages.
- Detection: TCP crash (`kill -9`) ≈ instant via FIN/RST; frozen/unplugged TCP clients ≈ 5 s heartbeat timeout; any UDP client ≈ 4 s heartbeat timeout.

## CSV format

One file per process per run:
```
metrics/<proto>_<role>_<name>_<YYYYmmdd-HHMMSS>.csv
e.g. metrics/udp_client_alice_20261110-143012.csv
     metrics/tcp_server_server_20261110-143010.csv
```
Header and rows (long format — one row per sample, easy to filter/plot):
```csv
ts,proto,role,node,metric,value,extra
1794839412.512,udp,client,alice,rtt,3.41,
1794839412.600,udp,client,alice,inter_update,101.7,
1794839412.600,udp,client,alice,tick_gap,0,
1794839418.200,udp,server,server,retransmit,2,ROOM_UPDATE:57
1794839421.004,udp,server,server,disconnect_detect,3012.5,timeout
```
- `proto` ∈ `tcp|udp`, `role` ∈ `client|server`, `node` = player name or `server`.
- `value` is a number (float ok), `extra` may be empty.
- Write with `csv.writer`, flush every write (or every second) so a killed
  process still leaves data. Metrics logging must never raise into game code.
- Raw CSVs are git-ignored; commit only final plots/summary tables used in the report.

## Benchmark and charts (implemented)

```bash
python metrics/run_benchmark.py                     # tcp+udp x 0/10/30 %, 120 s games, ~9 min
python metrics/run_benchmark.py --protos udp --loss 0.3 --game-seconds 30   # quick
python metrics/make_charts.py                       # re-draw charts from results.csv
# against a server already running elsewhere (no loss injected, no kill):
python metrics/run_benchmark.py --host xxx.at.ply.gg --port 41234 --network playit --protos udp
python metrics/run_benchmark.py --host H --port P --network lan --rtt-only   # PING only -> rtt_paths.csv
python metrics/packet_sizes.py                      # bytes per message type -> packet_sizes.csv
```
- Bots write the long-format CSV above with `--metrics-csv` (metrics `rtt`,
  `inter_update`, `tick_gap`, plus `total_*` counters at exit). Samples are
  taken on the transport's network thread at arrival (`Transport.rtt_log`,
  `Transport.state_arrivals`), not when the UI/bot polls.
- Raw: `metrics/raw/<proto>_<method>_loss<NN>_<node>.csv|.log` (git-ignored).
- Summary: `metrics/results.csv`, one row per (network, proto, loss_pct, loss_method);
  re-runs replace matching rows. `network` = loopback (local runs; older rows without
  the column count as loopback), lan, cloudflare, playit; remote rows have
  loss_method `none` and no detect/server columns (the server log isn't local).
  `charts/networks.png` compares networks at 0 % loss. Committed together with `metrics/charts/*.png`.
- Detection = SIGKILL wall time → timestamp of the server's `PLAYER_LEFT` log
  line (same machine, so wall clocks are comparable). Under UDP loss it can be
  < 4 s: the heartbeat clock starts at the last datagram *received*, and
  carol's last PINGs before the kill may have been lost.
- Charts follow the dataviz skill: TCP = `#2a78d6`, UDP = `#eb6834` (validated),
  one y-axis per chart, legend + direct labels, look at every PNG after rendering.

## Packet loss for TCP (OS level)

`--drop` only exists for UDP: TCP never loses data, so app-level dropping is
meaningless. Real loss must happen below TCP:

| Platform | Apply | Undo |
|---|---|---|
| macOS (dummynet, loopback, one port) | `sudo sh metrics/netloss_mac.sh on 5061 0.1` | `sudo sh metrics/netloss_mac.sh off` |
| Linux (netem, all of loopback) | `sudo tc qdisc add dev lo root netem loss 10%` | `sudo tc qdisc del dev lo root` |
| macOS Network Link Conditioner | GUI (Xcode Additional Tools), "Packets Dropped %" | switch it OFF |

`run_benchmark.py --loss-method os` drives the macOS helper itself (run
`sudo -v` first; it uses `sudo -n`). Use the same OS-level loss for UDP rows
when comparing protocols side by side (`--loss-method os` covers both).
