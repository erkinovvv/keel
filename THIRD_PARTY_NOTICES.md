# Third-party software, data and fonts

Keel is our own work. This file lists every third-party component it uses and the terms
it is used under, as the competition rules require (section 8, "Integrity and IP").

## Software

| Component | Use | License |
|---|---|---|
| FastAPI, Starlette | Web server | MIT, BSD-3-Clause |
| Uvicorn | ASGI server | BSD-3-Clause |
| Pydantic | Request and data validation | MIT |
| NumPy | Portfolio, Monte Carlo and stress calculations | BSD-3-Clause (with bundled MIT/Zlib/CC0 parts) |
| openai (Python SDK) | Client for the Groq OpenAI-compatible API | Apache-2.0 |
| web3.py, eth-account | Signing and sending audit-anchor transactions | MIT |
| python-dotenv | Loading local configuration | BSD-3-Clause |
| Rich | Command-line output | MIT |
| FISCO BCOS 3.x (run as a separate local chain, not bundled) | Consortium chain for audit anchoring | Apache-2.0 |
| Playwright (development only) | Screenshots and UI checks | Apache-2.0 |
| pptxgenjs (development only) | Building the presentation deck | MIT |

Hosted models used at run time through the Groq API (optionally Cerebras): `openai/gpt-oss-120b` and `openai/gpt-oss-20b`
(Apache-2.0 open weights), `qwen/qwen3.8-27b` (Apache-2.0), `meta-llama/llama-prompt-guard-2-86m`
(Llama 4 Community License). Use of the API is subject to the Groq terms of service.

## Fonts (loaded from Google Fonts)

| Font | License |
|---|---|
| Inter | SIL Open Font License 1.1 |
| Noto Sans SC | SIL Open Font License 1.1 |
| IBM Plex Mono | SIL Open Font License 1.1 |

## Data

| Dataset | Where used | Terms |
|---|---|---|
| Kenneth R. French Data Library: US market and risk-free returns | Crash Rehearsal (2007–2013 replay), historical stress scenarios | Made publicly available by Prof. Kenneth R. French for research use; attributed in the UI and in `data/rehearsal_2008.json` |
| FRED series GS10 (Board of Governors of the Federal Reserve System) | Bond returns | Public-domain US government data, cited per FRED guidance |
| World Bank Commodity Price Data ("Pink Sheet"), via `datasets/gold-prices` | Gold returns | World Bank data under CC BY 4.0; repackaged dataset under ODC-PDDL |
| Public fund information (fund names, codes, NAV, fees, risk ratings) for 24 Chinese public mutual funds, from East Money / Tiantian Fund public pages via the method of the open-source AkShare library (MIT) | Product catalog (`data/products_cn.json`) | Publicly disclosed fund facts used for non-commercial demonstration only. We keep a small dated snapshot, link every fund to its public page, and redistribute no bulk data. The app also runs on a fully synthetic catalog (`data/products.json`, the default when `WEALTH_ADVISOR_CATALOG` is not `cn`). |

Fund names and codes belong to their respective fund managers. Nothing in Keel is investment
advice; all accounts and orders are simulated.
