# Requirements and audit

The requirements come from the team plan (*Multiplayer Maze Arena: Team Plan*, Computer
Networks Project #2, demo **Fri 13 Nov 2026**). There is no separate grading rubric with
points; this file lists what the plan says must be delivered, then audits the project
against it.

## 1. Requirements

**Deliverables**

| ID | Requirement |
|---|---|
| D1 | Competitive multiplayer game, client-server: **1 server + 3 clients on 4 different computers** |
| D2 | Two versions of the same game, **TCP only** and **UDP only**: identical rules, only the transport changes |
| D3 | **5-7 slides** comparing TCP vs UDP with our own metrics |
| D4 | Source code + run instructions (no written report) |
| B1 | **Bonus**: play across different networks (not all on the same Wi-Fi/hotspot) |

**Mandatory in both versions**

| ID | Requirement |
|---|---|
| M1 | Login (LOGIN_OK / LOGIN_FAIL when the name is taken) |
| M2 | Lobby + room creation (LIST_ROOMS, CREATE_ROOM, ROOM_LIST) |
| M3 | Join / leave room, READY (ROOM_UPDATE) |
| M4 | Game start / end (GAME_START, GAME_OVER) |
| M5 | Real-time actions (INPUT {dir}; server authoritative at ~10 ticks/s, full STATE broadcast) |
| M6 | Scores + ranking + winner |
| M7 | Detection of unexpected disconnections **without crashing**; others get PLAYER_LEFT, game continues, one player left ends it |

**Game rules (plan §2)**

| ID | Requirement |
|---|---|
| G1 | Pacman-style maze on a grid (20x15), our own maze, 3 colored players |
| G2 | Pellet +10; power pellet +50 and lets you eat an opponent for 5 s (victim loses points, respawns) |
| G3 | Ends when all pellets are eaten or the timer runs out; highest score wins |
| G4 | Clients only send a direction; shared game logic, only the network layer differs |

**Transport (plan §4)**

| ID | TCP version | UDP version |
|---|---|---|
| T1 | Message boundaries: newline-delimited JSON (one recv ≠ one message) | One datagram = one message |
| T2 | Reliability built in | seq + ACK + retransmit for login, create/join/leave, start, game over |
| T3 | Real-time state | STATE unreliable; tick number drops old/out-of-order snapshots |
| T4 | Duplicates impossible | Last seq per client, repeats ignored (no double JOIN) |
| T5 | One socket per client | One socket, (ip, port) → session map |
| T6 | recv() b'' / error + heartbeat for half-open connections | Heartbeat every 1 s, silent 3-5 s = disconnected |
| T7 | One thread per client (or selectors) | One receive loop + one game-tick thread |
| T8 | (testing trick) `--drop` option on UDP to show/measure loss live | |

**Metrics (plan §7)**

| ID | Requirement |
|---|---|
| X1 | RTT (PING with timestamp), averaged over a game |
| X2 | Lost / late updates (STATE tick gaps; inter-update time, TCP bursts) |
| X3 | Behaviour at 0 %, 10 %, 30 % loss |
| X4 | Disconnection detection time per version; number of UDP retransmissions |

## 2. Audit (2026-11-07)

Strict rule: **anything not yet run on 4 real computers is "not verified yet"**, even if
automated tests pass. The 4-computer rehearsal is [FOUR_PC_TEST.md](FOUR_PC_TEST.md). So far the
team has run **2 real computers** (server + 1 client, reported working; protocol not recorded).

Legend: **Tested** = automated tests and/or a real multi-process run on one machine pass ·
**4 PCs: not verified yet** = still to be shown on 4 laptops · **Missing** = not done.

| ID | TCP | UDP | Evidence | Still missing |
|---|---|---|---|---|
| D1 | Tested · 4 PCs: **not verified yet** | Tested · 4 PCs: **not verified yet** | 3 separate bot processes + server per protocol: `tests/chaos_test.py`, `metrics/run_benchmark.py`; `test_three_clients_from_the_same_ip` (tcp, udp); 2-PC run reported by the team | Run [FOUR_PC_TEST.md](FOUR_PC_TEST.md) steps 1-6 and keep the 4 zips from `collect_logs` |
| D2 | Tested | Tested | Shared `common/` (`game.py`, `rooms.py`, `server_core.py`); `tests/test_format_parity.py` (both deliver identical messages) | 4 PCs: not verified yet |
| D3 | Done | Done | 20 slides + 3 backup slides `slides/maze_arena_tcp_vs_udp.pptx` (20-minute talk with live demo), built by `slides/build_slides.py` from `metrics/results.csv`; script [presentation_script.md](presentation_script.md) (~17.5 min); demo steps [demo_scenarios.md](demo_scenarios.md) | Team names: `.venv/bin/python slides/build_slides.py --team "A,B,C,D"`; re-run after LAN/internet measurements |
| D4 | Done | Done | `README.md` (install, run, flags, Windows), `docs/JOIN.md`, `docs/demo_day_sheet.md`, launchers | — |
| B1 | Partial · real remote player **not verified yet** | **Not done** | TCP: Cloudflare quick tunnel up; full games through the public link from the server Mac (browser client, 2026-11-06/07); `scripts/join_tcp.*`, `docs/cloudflare_tunnel.md`. UDP: playit agent online, **no UDP tunnel created** (skipped 2026-11-07) | TCP: one real player on another network (phone hotspot) plays a full game, proof with `curl -4 ifconfig.me`. UDP: create the playit UDP tunnel, then the same |
| M1 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `test_login_and_duplicate_name` (tcp), `test_login_duplicate_and_full_game` (udp), `test_valid_name` | 4 PCs |
| M2 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `tests/test_rooms.py` (10 tests); chaos test "mallory" lobby-rule checks | 4 PCs |
| M3 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `test_join_and_update`, `test_leave_and_empty_room_deleted`, `test_start_needs_two_ready_players`, `test_retransmitted_join_when_ack_lost_joins_once` | 4 PCs |
| M4 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `test_full_game_ticks_and_game_over` (tcp), `test_login_duplicate_and_full_game` (udp); live 3-bot game ended `GAME_OVER ... tick=600` at 60 s (2026-11-06) | 4 PCs |
| M5 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `test_moves_one_cell_per_tick`, server at 10 ticks/s, full STATE each tick (`test_state_is_json_and_matches_contract`); benchmark 2400 STATEs / 120 s at 0 % loss | 4 PCs |
| M6 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `test_ranking_and_winner`, `test_tie_for_first_place_has_no_winner`; GAME_OVER ranking in server log | 4 PCs |
| M7 | Tested · 4 PCs: not verified yet | Tested · 4 PCs: not verified yet | `test_disconnect_mid_game_others_continue`, `test_last_player_wins_when_other_leaves`, `test_heartbeat_timeout_closes_silent_client` (tcp); `test_silent_client_times_out_and_others_get_player_left` (udp); `tests/chaos_test.py` (SIGKILL + garbage, server alive); detection: TCP FIN 0-4 ms, UDP heartbeat ~4.0-4.5 s (`metrics/results.csv`) | 4 PCs: kill a client (FIN) **and** Wi-Fi off (heartbeat) on real laptops |
| G1 | Tested | Tested | `test_maze_shape`, `test_every_floor_cell_reachable`, `test_players_get_spawn_and_color` | — |
| G2 | Tested | Tested | `test_pellet_scores_10_and_disappears`, `test_power_pellet_scores_50_and_powers_for_50_ticks` (50 ticks = 5 s), `test_powered_player_eats_opponent_on_same_cell`, `test_victim_loses_power_on_respawn` | — |
| G3 | Tested | Tested | `test_timer_ends_game_after_600_ticks`, `test_game_ends_when_all_pellets_eaten`. **Deviation**: the timer is **60 s** (plan: 2 min), shortened for the demo; `--game-seconds 120` restores it | — |
| G4 | Tested | Tested | Clients send only `INPUT {dir}`; `common/` has no networking imports (CLAUDE.md rule 1); one pygame UI for both (`client_ui/connect.py`) | — |
| T1 | Tested | Tested | `test_tcp_message_split_across_two_recvs`, `test_tcp_three_messages_in_one_recv`, `test_tcp_byte_by_byte_including_utf8` · `test_udp_roundtrip_with_transport_fields`, `test_udp_too_large` | — |
| T2 | Built in | Tested | `test_lost_message_is_retransmitted_after_rto`, `test_everything_arrives_exactly_once_in_order_under_30_percent_loss`, `test_lobby_and_game_work_with_20_percent_loss_both_ways` | 4 PCs: step 4 (`--drop 0.3`) |
| T3 | Head-of-line blocking measured | Tested | UDP: `test_late_state_is_counted_late_not_lost`, `test_in_order_delivery_when_datagrams_swap`; TCP freezes measured (X2) | — |
| T4 | n/a (TCP) | Tested | `test_duplicate_is_dropped_but_acked_again`, `test_retransmitted_join_when_ack_lost_joins_once`, `test_forged_huge_seq_cannot_poison_the_channel` | — |
| T5 | Tested | Tested | `test_three_clients_from_the_same_ip` (both servers); UDP session per (ip, port) | 4 PCs: three different IPs in the log |
| T6 | Tested | Tested | TCP: FIN/RST + 5 s watchdog (`test_heartbeat_timeout_closes_silent_client`); UDP: PING 1 s, 4 s timeout | 4 PCs: Wi-Fi-off step (FOUR_PC_TEST step 6) |
| T7 | Done | Done | `tcp/server.py`: one reader thread per client + watchdog + game thread; `udp/server.py`: one receive loop + timer + game thread | — |
| T8 | n/a | Done | `udp.server --drop`, `client_ui.ui --drop`, `test_drop_only_affects_outgoing` | — |
| X1 | Measured | Measured | `metrics/results.csv`: RTT 0.88 ms (TCP, 0 %), 30.2 / 199.2 ms (TCP, 10 / 30 % kernel loss); 0.79 / 0.83 / 0.90 ms (UDP 0 / 10 / 30 %) | LAN/4-PC numbers (optional: `run_benchmark.py --host S_IP --network lan`) |
| X2 | Measured | Measured | TCP: 0 % STATEs missing at any loss, max gap 498 / 1002 ms, 61 / 269 freezes > 250 ms; UDP: 9.0 / 30.5 % missing, max gap 399 / 903 ms; charts `inter_update*.png` | — |
| X3 | Measured | Measured | 0 / 10 / 30 % rows in `metrics/results.csv`. **Caveat**: TCP loss = kernel (`--loss-method os`, `scripts/tcp_loss_benchmark.sh`), UDP loss = app `--drop`; same rates, different method | Optional: `bash scripts/tcp_loss_benchmark.sh --with-udp` for UDP under kernel loss too |
| X4 | Measured | Measured | Detection: TCP 0 / 4 / 95 ms (FIN/RST), UDP 4004 / 4508 / 4446 ms (heartbeat); UDP retransmissions 6 (10 %) and 48 (30 %), 0 gave up; chart `detection*.png`, `udp_loss.png` | — |

### Summary

- **Code, rules and both transports: complete and tested.** 118 automated tests pass
  (`python -m pytest -q`), plus the chaos test with real processes (SIGKILL, garbage, rule
  breaking, 30 % UDP loss) on both protocols.
- **Metrics: complete** for 0/10/30 % loss, both protocols (different loss methods, see X3).
- **Not verified yet on 4 real computers**: every requirement above. Run
  [FOUR_PC_TEST.md](FOUR_PC_TEST.md) and keep the `collect_logs` zips as evidence.
- **Slides (D3): done**, 7 slides generated from the metrics (see section 3).
- **Bonus (B1)**: TCP path works through the public tunnel but no real remote player has
  finished a game yet; UDP across networks not done (no playit UDP tunnel).
- Extra, not graded by the plan: a 3D browser client (TCP only, through `web/bridge.py`),
  clearly labelled as such; the pygame clients are the official TCP and UDP clients.

## 3. Presentation format (D3)

- 20 minutes including the live demo: 20 slides + 3 backup (measured charts, for questions): the demo is slides 11-16 (3 tests over Tailscale + Wireshark), TCP vs UDP comparison slides 17-18.
- Built by `slides/build_slides.py` from `metrics/results.csv` and `metrics/charts/`
  (re-run it after new measurements); output `slides/maze_arena_tcp_vs_udp.pptx`.
  Rebuild (once: `.venv/bin/pip install -r slides/requirements.txt`):
  `.venv/bin/python slides/build_slides.py --team "Name 1,Name 2,Name 3,Name 4"`
  (speaking order: Baya slides 1-4 and 17-18, Mohamed Aziz 5-10, Yahia 11-16, Yassine 19-20).
- Speaker notes and timings: [presentation_script.md](presentation_script.md).

## 4. Technical explanation (what the slides must show)

| # | Sentence from the plan | Slide |
|---|---|---|
| S1 | Present the socket architecture of each version. | 2 (TCP), 3 (UDP) |
| S2 | Show how each version uses TCP or UDP. | 2, 3 |
| S3 | Compare the two versions with our own metrics. | 5 |
| S4 | Explain the friction points we met. | 6 |
| S5 | Say where each protocol performed best. | 5 (takeaway), 6 |
| S6 | Explain the technical differences between TCP and UDP. | 6 |
| S7 | Explain how simultaneous players are handled in each version. | 4 |
| S8 | Explain how disconnections are handled in each version. | 4 |
| S9 | Bonus: show the setup for playing across different networks. | 7 |
