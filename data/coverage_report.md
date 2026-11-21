# Phase 1 coverage report

## Signals per window and language

| window | split | total | sq | sr-Latn | sr-Cyrl | ru | en | unknown | bg |
|---|---|---|---|---|---|---|---|---|---|
| banjska | train | 3804 | 1857 | 1346 | 511 | 0 | 90 | 0 | 0 |
| quiet_2024_04 | train | 3275 | 1834 | 1032 | 339 | 0 | 70 | 0 | 0 |
| quiet_2025_04 | train | 2988 | 1793 | 933 | 193 | 0 | 69 | 0 | 0 |
| quiet_2025_08 | train | 2966 | 1814 | 924 | 151 | 0 | 77 | 0 | 0 |
| election_2025_12 | train | 3770 | 1938 | 1221 | 403 | 0 | 138 | 0 | 70 |
| quiet_2026_01 | train | 3128 | 1845 | 909 | 182 | 0 | 130 | 0 | 62 |
| quiet_2024_10 | val | 2989 | 1816 | 886 | 196 | 0 | 91 | 0 | 0 |
| canal_2024_11 | val | 3509 | 1843 | 1184 | 376 | 0 | 106 | 0 | 0 |
| gazimestan_2026 | test | 3095 | 1848 | 897 | 325 | 0 | 25 | 0 | 0 |
| quiet_2026_10 | test | 3289 | 2063 | 963 | 175 | 0 | 88 | 0 | 0 |
| **all** | | **32813** | 18651 | 10295 | 2851 | 0 | 884 | 0 | 132 |

## Signals per source

| source | tier | lang | total | banjska | quiet_2024_04 | quiet_2025_04 | quiet_2025_08 | election_2025_12 | quiet_2026_01 | quiet_2024_10 | canal_2024_11 | gazimestan_2026 | quiet_2026_10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Insajderi | 1 | sq | 3000 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 |
| Lajmi.net | 3 | sq | 3000 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 |
| Reporteri | 3 | sq | 2999 | 299 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 | 300 |
| Kallxo (BIRN Kosovo) | 1 | sq | 2999 | 300 | 300 | 300 | 300 | 299 | 300 | 300 | 300 | 300 | 300 |
| Gazeta Express | 1 | sq/en | 2997 | 300 | 299 | 300 | 300 | 299 | 300 | 300 | 300 | 300 | 299 |
| KoSSev | 1 | sr | 2685 | 300 | 266 | 249 | 251 | 300 | 230 | 271 | 261 | 300 | 257 |
| Klan Kosova | 1 | sq | 2408 | 247 | 236 | 236 | 239 | 245 | 240 | 242 | 243 | 240 | 240 |
| Kosovo Online | 3 | sr/en/sq | 2320 | 200 | 250 | 249 | 250 | 248 | 250 | 250 | 374 | 0 | 249 |
| Radio KiM | 1 | sr | 2205 | 300 | 276 | 147 | 169 | 300 | 174 | 181 | 195 | 243 | 220 |
| In4s | 3 | sr | 1609 | 300 | 214 | 123 | 78 | 234 | 75 | 106 | 184 | 192 | 103 |
| RT Balkan | 3 | sr | 816 | 120 | 114 | 63 | 61 | 77 | 60 | 77 | 88 | 91 | 65 |
| RFE/RL Serbian | 1 | sr | 611 | 181 | 86 | 41 | 37 | 79 | 37 | 35 | 48 | 35 | 32 |
| Blic | 1 | sr | 528 | 123 | 61 | 41 | 44 | 35 | 21 | 47 | 63 | 46 | 47 |
| Periskopi | 1 | sq/en | 527 | 0 | 0 | 0 | 0 | 220 | 208 | 0 | 0 | 0 | 99 |
| Vreme | 1 | sr | 525 | 120 | 67 | 41 | 35 | 53 | 28 | 53 | 49 | 40 | 39 |
| Alo | 3 | sr | 479 | 112 | 58 | 44 | 42 | 38 | 25 | 38 | 48 | 43 | 31 |
| N1 Srbija | 1 | sr | 373 | 0 | 0 | 44 | 37 | 27 | 35 | 71 | 80 | 48 | 31 |
| Telegraf | 1 | sr | 356 | 57 | 35 | 31 | 42 | 31 | 28 | 36 | 49 | 24 | 23 |
| Kurir | 3 | sr | 322 | 0 | 0 | 72 | 52 | 47 | 31 | 0 | 73 | 47 | 0 |
| Hibrid.info | 1 | sq/sr/en | 310 | 36 | 39 | 18 | 17 | 60 | 28 | 26 | 36 | 24 | 26 |
| Sputnik Srbija | 3 | sr | 307 | 78 | 2 | 1 | 2 | 69 | 40 | 2 | 94 | 19 | 0 |
| Kosovo Police | 0 | sq/sr/en | 247 | 35 | 23 | 8 | 30 | 49 | 31 | 6 | 18 | 24 | 23 |
| Nova | 1 | sr | 238 | 0 | 0 | 32 | 41 | 28 | 25 | 0 | 50 | 32 | 30 |
| The Geopost | 1 | sq/en | 192 | 27 | 11 | 5 | 4 | 47 | 11 | 5 | 6 | 46 | 30 |
| Koha (Koha Ditore) | 1 | sq | 159 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 159 |
| Prishtina Insight (BIRN) | 1 | en | 136 | 13 | 16 | 13 | 12 | 28 | 10 | 13 | 12 | 5 | 14 |
| Standard (Novi Standard) | 3 | sr | 102 | 13 | 9 | 6 | 10 | 20 | 6 | 11 | 10 | 13 | 4 |
| Insajder | 1 | sr | 75 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 39 | 36 |
| Kosovo Dispatch | 1 | en | 42 | 0 | 0 | 0 | 0 | 9 | 25 | 0 | 0 | 6 | 2 |
| Kosovo MoD / KSF | 0 | sq/en | 40 | 7 | 0 | 3 | 2 | 3 | 0 | 7 | 2 | 11 | 5 |
| bne IntelliNews | 1 | en | 38 | 10 | 3 | 6 | 3 | 6 | 3 | 0 | 4 | 1 | 2 |
| NATO HQ news | 0 | en | 31 | 3 | 3 | 1 | 0 | 5 | 1 | 6 | 4 | 2 | 6 |
| Danas | 1 | sr | 28 | 10 | 0 | 1 | 2 | 3 | 1 | 2 | 2 | 5 | 2 |
| Istinomer | 1 | sr | 26 | 6 | 3 | 1 | 3 | 2 | 0 | 0 | 4 | 1 | 6 |
| Pravda network (Albanian) | 3 | sq | 22 | 0 | 0 | 8 | 0 | 0 | 3 | 0 | 4 | 7 | 0 |
| Serbia Office for Kosovo-Metohija | 0 | sr | 18 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 | 10 | 4 |
| Tango Six | 2 | sr | 16 | 2 | 2 | 2 | 1 | 0 | 0 | 2 | 5 | 0 | 2 |
| Raskrikavanje (KRIK) | 1 | sr | 11 | 0 | 2 | 1 | 2 | 3 | 0 | 1 | 0 | 0 | 2 |
| FakeNews Tragač | 1 | sr | 10 | 3 | 0 | 1 | 0 | 1 | 1 | 0 | 3 | 0 | 1 |
| Balkan Security Network | 2 | sr | 3 | 2 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| AdriaDefense | 2 | en | 3 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 |

## Gaps

Verified sources with zero backfilled signals (25):

- Albania Ministry of Defence (`src_off_al_mod`, tier 0): http=200; robots_ok=True; wp_api=False
- Army Recognition (`src_web_armyrecognition`, tier 2): http=200; robots_ok=True; wp_api=False
- B92 (`src_web_b92`, tier 3): http=200; robots_ok=True; wp_api=False
- Balkan Spectator (`src_web_balkanspectator`, tier 2): http=200; robots_ok=True; wp_api=False
- BalkanWeb (AL) (`src_web_balkanweb`, tier 1): http=200; robots_ok=True; wp_api=False
- Bota Sot (`src_web_botasot`, tier 1): http=200; robots_ok=True; wp_api=False
- EULEX (`src_off_eulex`, tier 0): http=200; robots_ok=True; wp_api=False
- Informer (`src_web_informer`, tier 3): http=200; robots_ok=True; wp_api=False
- Kosovo 2.0 (`src_web_kosovo20`, tier 1): http=200; robots_ok=True; wp_api=False
- Nacionale (`src_web_nacionale`, tier 3): http=200; robots_ok=True; wp_api=False
- Office of the Prime Minister (KS) (`src_off_ks_pm`, tier 0): http=200; robots_ok=True; wp_api=True; ConnectError: [Errno 61] Connection refused
- Pravda network (Serbian/other) (`src_mir_pravda_other`, tier 3): http=200; robots_ok=True; wp_api=False
- RTK / RTK2 (`src_web_rtk`, tier 1): http=200; robots_ok=True; wp_api=False
- RTS (`src_web_rts`, tier 1): http=200; robots_ok=True; wp_api=False
- Serbian Armed Forces (`src_off_rs_vs`, tier 0): http=200; robots_ok=True; wp_api=False
- Serbian MoD (`src_off_rs_mod`, tier 0): http=200; robots_ok=True; wp_api=False; RemoteProtocolError: Server disconnected without sending a response.
- Shqiptarja (AL) (`src_web_shqiptarja`, tier 1): http=200; robots_ok=True; wp_api=False
- TV Pink (`src_web_pink`, tier 3): http=200; robots_ok=True; wp_api=False
- Tanjug (`src_web_tanjug`, tier 1): http=200; robots_ok=True; wp_api=False
- Telegrafi (`src_web_telegrafi`, tier 1): http=200; robots_ok=True; wp_api=False
- Top Channel (AL) (`src_web_topchannel`, tier 1): http=200; robots_ok=True; wp_api=False
- UNMIK (`src_off_unmik`, tier 0): http=200; robots_ok=True; wp_api=False
- UNMIK Media Observer (`src_web_unmik_observer`, tier 1): http=200; robots_ok=True; wp_api=False
- Večernje novosti (`src_web_novosti`, tier 3): http=200; robots_ok=True; wp_api=False
- Zëri (`src_web_zeri`, tier 1): http=200; robots_ok=True; wp_api=False

Sources not collected in the MVP (37):

- **blocked:dns** (3): Kosova24 (Prizren), Radio Kontakt Plus, Srpski telegraf
- **blocked:http403** (5): DSCA Major Arms Sales, KFOR, Politika, Srbija Danas, Srbin.info
- **blocked:no-url** (4): Eagle Eye Explore, Gračanica Online, Mreža Most (TV Most, TV Puls, Radio Mitrovica, Radio Gračanica), Radio Mitrovica Sever
- **blocked:robots** (1): Balkan Insight (BIRN)
- **later** (7): Balkan Spectator (Telegram), BulgarianMilitary.com (Telegram), REN TV news, Russian MFA, TASS world, balkan_pro, balkanar
- **phase2** (17): Army Recognition, Balkan Security Network, Bellingcat, Benjamin Strick, Calibre Obscura, Defence Blog, KFOR (X), KSF social accounts, Luka | Дунав Intel, OSINTtechnical, Oryx, Petar Vojinović, Rob Lee, Tango Six portal, r/CredibleDefense, r/LessCredibleDefence, r/WarCollege
