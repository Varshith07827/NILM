# Edge AI-Based Non-Intrusive Load Monitoring for Low-Cost Smart Metering

A complete, working smart-energy platform that figures out **which appliances are
running in a house, and how much each one is costing**, from a *single* current
measurement at the mains — no per-socket sensors, no smart plugs.

A virtual household is simulated down to the 50 Hz waveform. A MobileNetV3-derived
classifier, running on a dependency-free NumPy kernel, disaggregates that one
aggregate signal into twelve appliances in about **2 ms per second of data**.

> **This is a software simulation of the proposed hardware project.** There is no
> physical ESP32, Raspberry Pi or SCT-013 clamp. Every layer above the sensor —
> signal processing, feature extraction, inference, disaggregation, billing,
> storage, dashboard — is the real implementation and would run unchanged against
> a real ADC feed. See [What is real and what is simulated](#what-is-real-and-what-is-simulated).

---

## Contents

- [What it does](#what-it-does)
- [Results](#results)
- [Architecture](#architecture)
- [How the physics works](#how-the-physics-works)
- [How the AI works](#how-the-ai-works)
- [Installation](#installation)
- [Running it](#running-it)
- [The three modes](#the-three-modes)
- [The dashboard](#the-dashboard)
- [API reference](#api-reference)
- [Project layout](#project-layout)
- [Retraining the model](#retraining-the-model)
- [Testing](#testing)
- [What is real and what is simulated](#what-is-real-and-what-is-simulated)
- [Known limitations](#known-limitations)
- [Future scope](#future-scope)

---

## What it does

Twelve appliances — ceiling fan, LED light, tube light, television, refrigerator,
mixer grinder, washing machine, air conditioner, laptop, mobile charger, microwave
and induction stove — share one simulated mains feed. The system sees only the
combined current waveform and must work out the rest:

| | |
|---|---|
| **Detect** | Which appliances are drawing power right now, with a confidence per appliance |
| **Disaggregate** | How many watts each one is drawing, summing back to the metered total |
| **Account** | Energy per appliance per hour, day and month |
| **Bill** | Cost under real Indian telescopic slab tariffs |
| **Alert** | High load, approaching sanctioned limit, budget exceeded, appliance started |
| **Report** | Daily / weekly / monthly reports, exportable to CSV and PDF |
| **Stream** | Everything live over WebSocket to a dark-mode dashboard |

---

## Results

All figures below were produced by the evaluation scripts in this repository, not
estimated. Reproduce them with `python -m ai.train` and the test suite.

### Detection accuracy

Held-out validation, split **by episode** (never by window — adjacent seconds are
near-identical and splitting on them would inflate the score):

| Metric | Value |
|---|---|
| Macro F1 | **0.913** |
| Micro F1 | **0.910** |
| Hamming accuracy | **0.925** |
| Exact-match (all 12 correct simultaneously) | 0.489 |

Across all six behavioural scenarios in both Demo and Simulation mode
(14,000 windows, full pipeline, scored against hidden ground truth):

| Metric | Value |
|---|---|
| Micro F1 | **0.941** |
| Macro F1 (11 classes with non-zero support) | **0.938** |
| Normalised disaggregation error (NDE) | **5.86 %** |
| Per-appliance power error, mean (as share of house load) | **0.69 %** |
| Detected-but-assigned-zero-power | 0.47 % |

Per appliance, cross-scenario:

| Appliance | Precision | Recall | F1 |
|---|---|---|---|
| Air Conditioner | 1.000 | 1.000 | **1.000** |
| Refrigerator | 1.000 | 1.000 | **1.000** |
| Microwave Oven | 1.000 | 1.000 | **1.000** |
| Induction Stove | 1.000 | 1.000 | **1.000** |
| Mixer Grinder | 0.998 | 1.000 | 0.999 |
| Television | 0.981 | 0.969 | 0.975 |
| Ceiling Fan | 0.918 | 0.906 | 0.912 |
| Tube Light | 0.846 | 0.977 | 0.907 |
| LED Light | 0.912 | 0.873 | 0.892 |
| Laptop | 0.776 | 0.900 | 0.833 |
| Mobile Charger | 0.734 | 0.885 | 0.803 |

The ordering is the honest one and worth reading: large, electrically distinctive
loads are solved. A 9 W LED lamp or a 12 W phone charger hiding underneath a
1.5 kW air conditioner sits near the sensor noise floor, and the model says so.
Any NILM project reporting 99 % on a 12 W load under a 3 kW background is
measuring something other than what it claims.

### Model and runtime

| | |
|---|---|
| Architecture | MobileNetV3-derived CNN (depthwise separable, inverted residual, squeeze-excite, hard-swish) |
| Parameters | 104,446 |
| Size | 408 KB float32 · **222 KB TFLite float16** · 102 KB if int8-quantised |
| Input | 8 seconds × 34 electrical features |
| Inference latency | **0.96 ms median, 2.6 ms p95** per window (NumPy kernel) |
| Backend startup | < 1 s (no TensorFlow import) |

**Cross-backend agreement**, verified automatically at export time:

| Comparison | Max absolute difference |
|---|---|
| Keras → NumPy kernel | **8.3 × 10⁻⁶** |
| Keras → TFLite (float16) | 8.4 × 10⁻³ |

The NumPy kernel is numerically the same graph as the trained Keras model
(the residual is float32 rounding). The TFLite gap is the expected cost of
float16 quantisation. `ai/train.py` **refuses to ship a model** whose NumPy
runtime disagrees with Keras by more than 1 × 10⁻³.

### Simulator fidelity

Every synthesised appliance waveform measures back to its own nameplate:

| Quantity | Worst error across all 12 appliances |
|---|---|
| RMS current, real power, power factor, THD | **< 0.5 %** |
| Aggregate power vs sum of per-appliance truth | **< 0.05 %** |

Throughput: **~400× real time** (2.5 ms to synthesise and analyse one second),
so the 10× demo speed has a 40× margin.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  VIRTUAL HOUSE                          simulator/                  │
│  12 appliances · state machines · duty cycles · scenarios           │
└────────────────────────────────┬────────────────────────────────────┘
                                 │  per-appliance current waveforms
┌────────────────────────────────▼────────────────────────────────────┐
│  WAVEFORM SYNTHESIS                     simulator/waveform.py       │
│  50 Hz · 2 kHz sampling · harmonics · inrush · sag · sensor noise   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │  ONE aggregate current signal
                                 │  (everything below sees only this)
┌────────────────────────────────▼────────────────────────────────────┐
│  FEATURE EXTRACTION                     ai/features.py              │
│  RMS · P/Q/S · PF · FFT harmonics · THD · per-cycle · Δ-features    │
│  → 34 features × 8-second sliding window                            │
└────────────────────────────────┬────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────┐
│  INFERENCE                              ai/runtime.py               │
│  MobileNetV3-derived CNN · BN folded · NumPy kernel · ~2 ms         │
│  → probability per appliance, per-appliance tuned thresholds        │
└────────────────────────────────┬────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────┐
│  DISAGGREGATION                         ai/disaggregate.py          │
│  Non-negative least squares on complex harmonic phasors             │
│  → watts per appliance, summing to the metered total                │
└────────────────────────────────┬────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────┐
│  ENERGY · COST · ALERTS                 backend/app/services/       │
│  Wh integration · telescopic slab billing · rules engine            │
└────────────────────────────────┬────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────┐
│  PERSISTENCE                            SQLite + SQLAlchemy         │
│  per-second readings · hourly buckets · events · notifications      │
└────────────────────────────────┬────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────┐
│  API                                    FastAPI · REST + WebSocket  │
└────────────────────────────────┬────────────────────────────────────┘
┌────────────────────────────────▼────────────────────────────────────┐
│  DASHBOARD              React · TypeScript · Tailwind · shadcn/ui   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## How the physics works

This is what separates the project from a random-number generator, so it is worth
stating precisely.

### Power factor is split into two independent causes

A real load's power factor is the product of two unrelated effects:

```
PF_total = PF_displacement × PF_distortion        PF_distortion = 1 / √(1 + THD²)
```

- A **ceiling fan** (induction motor) draws a near-perfect sinusoid that *lags*
  the voltage. Its imperfect PF is almost entirely **displacement**.
- An **LED driver** or a **TV power supply** draws a spiky, non-sinusoidal pulse
  roughly *in phase* with the voltage. Its poor PF is almost entirely
  **distortion**.

Two loads can have identical RMS current *and* identical power factor and still be
trivially separable in the harmonic domain. **That is the entire physical basis
for appliance disaggregation from one sensor.** You can see it directly in the
extracted features:

| Appliance | Crest factor | THD | Spectral centroid |
|---|---|---|---|
| Ceiling Fan | 1.50 | 4 % | 59 Hz |
| Air Conditioner | 1.59 | 8 % | 69 Hz |
| Television | 2.55 | 68 % | 155 Hz |
| Mobile Charger | 2.92 | 112 % | 218 Hz |

### The waveform is synthesised, then *measured*

Rather than asserting "the fan draws 0.33 A", the simulator synthesises

```
i(t) = A · Σ_h  c_h · cos( h·(ωt − φ) )          A = √2 · I_rms / ‖c‖
```

and the feature extractor then measures RMS, real power and power factor from the
samples exactly as firmware would. Because of the `‖c‖` normalisation it can be
shown that `mean(v·i) = V_rms · I_rms · PF_total` — the waveform is consistent
with the nameplate *by construction*, and the test suite asserts it to 2 %.

Also modelled: exponentially-decaying inrush resolved **inside** the window (a
refrigerator's locked-rotor surge lasts a few hundred milliseconds — a per-second
scalar would erase the single most recognisable feature it has), thermostatic duty
cycling, slow load random-walk, supply voltage sag through a 0.35 Ω source
impedance, background grid distortion, and an 8 mA sensor noise floor.

### Sampling rate

2 kHz — 40 samples per mains cycle, Nyquist at 1 kHz. The catalogue models
harmonics to the 13th (650 Hz), so nothing aliases. The window is exactly 50
complete cycles, which puts every harmonic precisely on an FFT bin; that is why
**no analysis window function is applied** — a Hann window here would smear energy
across neighbouring bins and make the harmonic ratios *less* accurate.

---

## How the AI works

### Features (34 per second)

Three families, all cheap enough for a microcontroller — one real FFT, a few dot
products, some per-cycle bookkeeping:

- **Steady state** — RMS/peak/mean current, crest factor, form factor, V_rms,
  real/reactive/apparent power, total and displacement power factor. *Separates
  loads by size.*
- **Harmonic** — amplitude of harmonics 3–13 as both absolute currents and ratios
  to the fundamental, THD, spectral centroid. *Separates loads by type.*
- **Transient** — per-cycle RMS statistics, inrush ratio, and Δpower, Δreactive,
  ΔI, ΔTHD against the previous window. *Detects switching events.*

**The vector contains no time-of-day information, deliberately.** Letting the
model learn "it is 8 pm, so the television is probably on" would inflate the
accuracy figures without demonstrating any actual disaggregation.

### Classifier

The input is not an image but a **feature-time tensor** of shape `(8, 34, 1)`:
eight consecutive one-second windows against the 34 features of each. Convolving
over that rectangle lets the network learn both what a signature looks like and
how it *evolves* — which is how a refrigerator compressor starting is told apart
from an air conditioner doing the same thing.

Topology (`ai/architecture.py` is the single source of truth, consumed by both the
Keras builder and the NumPy runtime so they cannot drift apart):

```
stem     conv 3×3 ×16, stride (1,2), hard-swish
bneck1   expand 48  → out 24, stride (1,2), ReLU
bneck2   expand 72  → out 24, stride (1,1), ReLU          + residual
bneck3   expand 96  → out 40, stride (2,2), SE, hard-swish
bneck4   expand 120 → out 40, stride (1,1), SE, hard-swish + residual
bneck5   expand 144 → out 56, stride (1,1), SE, hard-swish
head     conv 1×1 ×192, hard-swish
         global average pool → dense 128 → dropout 0.3 → dense 12 → sigmoid
```

Strides are asymmetric on purpose: the feature axis (34 wide) carries far more
independent information than the time axis (8 deep), so downsampling happens
mostly along the features.

Training uses **per-appliance positive class weighting** — a microwave draws power
a couple of percent of the day, so unweighted cross-entropy would score 98 % by
predicting "off" forever — and **per-appliance decision thresholds tuned on the
validation split** rather than a blanket 0.5.

### The edge deployment path

```
train in TensorFlow  →  fold BatchNorm into conv  →  export  →  run in NumPy
                                                  ↘  export  →  .tflite (float16)
```

Importing TensorFlow costs ~28 seconds and hundreds of megabytes on this machine.
A one-second inference loop cannot pay that — and neither could the ESP32 the
project models, which is exactly why TensorFlow Lite for Microcontrollers exists.
So the backend never imports TensorFlow at all. It executes the trained graph
through a hand-written NumPy interpreter (`ai/runtime.py`) over batch-norm-folded
weights: the same arithmetic, the same weights, verified at export time to agree
with Keras to 8 × 10⁻⁶.

Folding BatchNorm is the same optimisation a real edge converter performs. Since
`y = γ(conv(x) − μ)/√(σ²+ε) + β` and convolution is linear, the scale pushes
straight into the kernel and the constant becomes an ordinary bias. The deployed
graph therefore has no BN layers left at all.

### Disaggregation: why phasors

Classification says *which* appliances run; it does not say how many watts each
draws. That is solved as a constrained least-squares problem on **complex harmonic
phasors**, because Kirchhoff's current law applies per harmonic:

```
I_h(total) = Σ_i  a_i · I_h(appliance i at rated power)
```

RMS magnitudes emphatically do *not* add like that — two 1 A loads in quadrature
draw 1.41 A together, not 2 A — which is why naive "subtract the known loads"
approaches drift. In the complex plane the problem is exactly linear in the
unknown scale factors. Seven harmonic orders × (real, imaginary) gives fourteen
equations for at most twelve unknowns, solved by **non-negative** least squares
(`scipy.optimize.nnls`); non-negativity matters physically, since without it the
solver cancels one appliance against another to fit sensor noise.

The classifier's confidence enters as a Tikhonov prior **centred on the confidence
itself**, not on zero. This detail was a real bug found during development: with a
zero-centred prior, two loads with near-identical harmonic shape (an LED lamp and
a tube light) are nearly collinear columns, and least squares resolved the
ambiguity by driving the smaller one to exactly **0 W while still reporting it as
detected** — worse than either answer alone. Centring at the confidence encodes
the right belief — *"if the model is 95 % sure it is running, expect it near rated
draw, but let the harmonic evidence override"* — and cut such collapses from
widespread to 0.47 % of detections. There is a regression test for it.

---

## Installation

**Prerequisites:** Python 3.11+ and Node.js 18+.
(Developed and verified on Python 3.13.14 and Node 22.23.2.)

```bash
git clone <your-repo-url> NILM
cd NILM
```

**Backend** — note that TensorFlow is *not* required to run the dashboard:

```bash
python -m pip install -r requirements.txt
```

**Frontend:**

```bash
cd frontend && npm install
```

(On Windows, `npm install --prefix frontend` looks for `package.json` in the
project root and fails; installing from inside `frontend/` works everywhere.)

**Admin account** — needed only to change the house, ratings, tariff or alert
thresholds; watching the dashboard needs no login:

```bash
python -m backend.manage set-admin-password
```

It prompts for a password (twice, without echo). There is no default password.
For a scripted setup, `NILM_ADMIN_PASSWORD` in `.env` creates the account on
first start if none exists yet.

**Optional — only if you want to retrain the model.** A trained model is already
included in `ai/artifacts/`:

```bash
python -m pip install -r requirements-train.txt
```

---

## Running it

Two terminals.

**Terminal 1 — backend** (starts on <http://127.0.0.1:8000>):

```bash
python run_backend.py
```

**Terminal 2 — dashboard** (starts on <http://localhost:5173>):

```bash
npm run dev --prefix frontend
```

Open <http://localhost:5173>. The simulation starts automatically in the Evening
Peak scenario; interactive API docs are at <http://127.0.0.1:8000/docs>.

For a production build of the dashboard:

```bash
npm run build --prefix frontend
```

### Configuration

Any setting can be overridden with an `NILM_`-prefixed environment variable or a
`.env` file in the project root:

```bash
NILM_DEFAULT_SCENARIO=festival
NILM_DEFAULT_SPEED=10
NILM_INFERENCE_BACKEND=tflite     # auto | numpy | tflite | heuristic
NILM_SANCTIONED_LOAD_W=7000
NILM_DAILY_COST_ALERT_INR=150
NILM_AUTOSTART=false
```

---

## The three modes

| Mode | Behaviour | Use it for |
|---|---|---|
| **Demo** | Plays a fixed, hand-authored timeline of appliance events. Seeded — every run is byte-for-byte identical. | Presenting. Nothing surprises you. |
| **Simulation** | No script. Each appliance decides for itself when to switch on, from its hourly usage profile and the scenario's activity level. | Showing the system handles genuinely unseen behaviour. |
| **Replay** | Re-runs a saved recording through the live pipeline. | Repeating a demonstration exactly, even after retraining. |

Replay stores the **appliance amplitude track** — for each simulated second, what
fraction of rated power each appliance drew — not the raw waveform. That is about
100 bytes/s instead of 16 KB/s, a 150× saving, and more importantly the recording
is replayed *through the same synthesis code*, so it exercises the full pipeline
rather than replaying a cached answer. Retrain the model and the same recording
shows the new model's behaviour on identical input.

### Scenarios

| Scenario | Starts | What happens |
|---|---|---|
| Morning Rush | 06:30 | Lights, induction stove, mixer bursts, washing machine |
| Afternoon Heat | 13:00 | Air conditioner and fans dominate, someone on a laptop |
| **Evening Peak** | 18:00 | Everyone home — lights, fan, TV, AC, cooking. Hardest case for NILM |
| Night | 22:30 | Lights go off one by one; fan, AC, fridge, chargers overnight |
| Festival Evening | 19:00 | Everything at once, load approaches the sanctioned limit |
| Vacation | 10:00 | Empty house — only the fridge cycling and standby draw |
| Custom | 12:00 | Nothing automatic; you switch every appliance by hand |

---

## The dashboard

Every aspect of the dashboard has its own page, grouped in the sidebar. The
WebSocket connection lives above the router, so navigating between pages never
drops the stream or resets the charts, and the top bar keeps the live clock,
power, cost and the notification bell visible whichever page you are on.

| Group | Page | What it is for |
|---|---|---|
| Monitor | **Overview** | Headline metrics, the devices drawing most, load by room |
| | **Live Charts** | Current, voltage, power and power factor over time |
| | **Energy Breakdown** | How the metered power splits across devices |
| | **Waveform** | Raw waveform oscilloscope, harmonic fingerprints |
| Home | **3D Home** | The house in three dimensions; click a device for its usage and cost |
| | **Rooms & Devices** | Rooms and the devices in each; admins add, move and remove them |
| | **Appliances** | Every device with detection, confidence and power |
| | **Appliance detail** (`/appliances/:id`) | One device's live power and current, energy, cost today and this month, cost by hour |
| Money | **Billing** | Cost, telescopic slab breakdown, cost per device |
| | **Reports** | Daily / weekly / monthly reports with CSV and PDF export |
| System | **Simulation** | Start / pause / reset, scenario, speed, record and replay |
| | **Model Accuracy** | Live detector accuracy, classifier output per type, model card |
| | **Events** | Every switch-on and switch-off, and whether it was detected |
| | **Notifications** | Every alert, with read / unread state and optional desktop pop-ups |
| | **Admin** | Log in; edit the tariff, each device's power rating, alert thresholds |

Every route except Overview is code-split. Three.js — by far the heaviest
dependency — sits in its own chunk (248 KB gzipped) that is only downloaded
when someone actually opens the 3D page.

### Rooms, devices and same-type appliances

The house is a set of **rooms** holding **devices**. The default house is the
original twelve appliances plus a ceiling fan in every room; admins can add
rooms (up to 12) and devices, move devices between rooms, and change any
device's power rating (50–200% of the catalogue rating, the range the model
was trained around). Changes reach the running simulation on the next window.

Several devices of one type -- five ceiling fans -- raise a problem a single
sensor cannot dodge: two identical fans draw identical waveforms, so "the
bedroom fan is on" and "the study fan is on" are literally the same signal.
The system handles it in two parts:

- **Each extra device of a type gets a slightly different electrical
  signature** (a phase shift of its current, like a different fan model with a
  different run capacitor), so the devices are physically distinguishable.
  This is internal; devices are named by room, e.g. "Bedroom Ceiling Fan".
- **Which device is running is decided at switching events.** In steady state
  the difference between two fans is buried under the fluctuation of a running
  microwave, but at the moment one switches, everything else cancels and the
  step matches that one device ([ai/device_tracker.py](ai/device_tracker.py)).

The classifier still recognises *types*; how much of a type is running comes
from the steady-state disaggregation, and which devices from the tracker. At
most five devices of one type are allowed. Measured accuracy, and why it is
lower than for the single-device house, is under [Known limitations](#known-limitations).

### Notifications

Alerts are stored in SQLite as they fire. The bell in the top bar shows the
unread count; the Notifications page lists every alert with read / unread
state. Desktop pop-ups (browser notifications, off by default) can be turned on
from that page, for warnings only or for every alert. They work while the
dashboard is open in a tab, including a background one.

### The 3D house

The house replaces what used to be a grid of toggle switches. It is an
isometric cutaway of the simulated household, built entirely from primitives
(boxes, cylinders, cones) rather than loaded from a model file — so there are
no binary assets to ship and no licensing questions.

**Appliances show their state physically rather than through a label.** Fan
blades spin at a speed proportional to the power drawn, the induction hob glows
and pulses as its inverter modulates, the washing-machine drum turns, the TV
backlight flickers, and the tube light genuinely illuminates the kitchen. All of
it is driven by the same numbers as the rest of the dashboard, so the picture
and the figures cannot disagree.

- **Click any device** to see its power, current, energy, and cost today and
  this month, with a link to its detail page. Switch it at the socket from
  there; the detector then has to work out what you did from the mains current
  alone.
- **Scene lighting follows the simulated clock.** Switch to the Night scenario
  and the house genuinely goes dark; the only light left comes from appliances
  that are really drawing power.
- **Detection errors are visible in space.** With ground truth revealed, a red
  ring on the floor marks an appliance that is running but was missed, and an
  amber ring marks a false positive.
- **Rooms report their own load,** so "which room is costing me money" is
  legible at a glance. Appliances are grouped the way a household groups them:
  the kitchen holds the refrigerator, microwave, mixer, induction stove and tube
  light; the bedroom holds the air conditioner and phone charger; and so on.
- **Rooms added from the admin pages appear east of the original house**, and
  devices are placed automatically on the ceiling, a wall, the floor or a small
  table according to their type.
- Camera presets (isometric, front, top-down) plus orbit, pan and zoom.

## API reference

Full interactive docs at `/docs`. Summary:

### Live state

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/live` | Most recent processed window (same shape as the WebSocket frame) |
| `GET` | `/api/status` | Simulation state, model card, throughput stats |
| `GET` | `/api/buffer` | In-memory ring buffer, chart-ready series |
| `GET` | `/api/appliances` | Appliance catalogue with every derived electrical quantity |
| `GET` | `/api/scenarios` | Available scenarios |
| `GET` | `/api/model` | Model card and per-appliance thresholds |
| `GET` | `/api/model/signatures` | The harmonic signature matrix |
| `GET` | `/api/alerts` · `/api/events` | Recent notifications / switching events |
| `GET` | `/api/health` | Health check |

### Control

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/simulation/start` · `pause` · `resume` · `stop` | Transport |
| `POST` | `/api/simulation/reset` | Restart, optionally with a new scenario/mode/seed |
| `POST` | `/api/simulation/speed` | 1×, 2×, 5×, 10×, 20×, 60× |
| `POST` | `/api/simulation/scenario` | Switch scenario |
| `POST` | `/api/simulation/mode` | Demo / Simulation / Replay |
| `POST` | `/api/simulation/appliance` | Switch one appliance by hand |
| `GET` `POST` | `/api/simulation/recordings[/start\|/stop]` | Record and list runs |

### Cost, history, reports

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/cost` · `/api/tariffs` · `/api/settings` | Cost breakdown, tariffs, settings |
| `POST` | `/api/settings/tariff` | Select a preset or install a custom slab structure (admin) |
| `POST` | `/api/settings/alerts` | Adjust alert thresholds live (admin) |
| `GET` | `/api/history` | Persisted readings, decimated in SQL to a chart-sized response |
| `GET` | `/api/reports?period=daily\|weekly\|monthly&format=json\|csv\|pdf` | Reports |

### House, devices, admin, notifications

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Admin username + password → bearer token |
| `GET` | `/api/auth/status` · `/api/auth/me` | Whether an admin exists · the logged-in admin |
| `GET` | `/api/house` | Rooms, devices and the types that can be added |
| `POST` · `PATCH` · `DELETE` | `/api/house/rooms[/{id}]` | Add, rename, remove a room (admin) |
| `POST` · `PATCH` · `DELETE` | `/api/house/devices[/{id}]` | Add, rename / move / re-rate, remove a device (admin) |
| `GET` | `/api/devices/{id}/history` | One device's power and current per second, energy and cost per hour |
| `GET` | `/api/notifications` | Stored alerts, newest first, with unread count |
| `POST` | `/api/notifications/read` | Mark some, or all, read |

Admin routes need `Authorization: Bearer <token>`. Settings changed by the
admin (tariff, alert thresholds, the house) are saved and restored on restart.

### WebSocket `/ws`

On connect the server sends a `status` frame and a `snapshot` of the ring buffer,
so a client joining mid-run has populated charts before the next tick. Then it
streams one `frame` per processed window. Clients may send `{"type":"ping"}` or
`{"type":"resync"}`.

---

## Project layout

```
NILM/
├── simulator/              The virtual house — no AI in here
│   ├── appliances.py       Catalogue: ratings, PF decomposition, harmonics, duty cycles
│   ├── waveform.py         50 Hz synthesis, inrush, sag, sensor noise
│   ├── devices.py          Rooms, devices, same-type signature variants
│   ├── house.py            Device state machines, aggregation, ground truth
│   ├── scenarios.py        Six behavioural scenarios + demo scripts
│   └── replay.py           Recording and playback
│
├── ai/                     The edge pipeline
│   ├── features.py         34-feature extraction, sliding window
│   ├── architecture.py     Topology spec — single source of truth
│   ├── model.py            Keras builder            (training only)
│   ├── dataset.py          Training data generation (training only)
│   ├── train.py            Train, tune thresholds, evaluate, export, verify
│   ├── export.py           BatchNorm folding, TFLite + NumPy bundle export
│   ├── runtime.py          Dependency-free NumPy interpreter  ← runs in production
│   ├── inference.py        Backend selection + classical NNLS baseline
│   ├── disaggregate.py     Non-negative harmonic phasor attribution, per device
│   ├── device_tracker.py   Which same-type device is on, from switching events
│   ├── evaluate_devices.py Accuracy on multi-device houses
│   └── artifacts/          Trained weights, thresholds, training report
│
├── backend/
│   ├── app/
│   │   ├── main.py         FastAPI app and lifespan
│   │   ├── core/config.py  Pydantic settings
│   │   ├── api/routes/     live · simulation · history · cost · reports · ws ·
│   │   │                   auth · house · notifications
│   │   ├── schemas/        Pydantic request/response models
│   │   ├── db/             ORM models, session, repositories
│   │   └── services/       pipeline · energy · cost · notifications · reports
│   └── tests/              195 tests
│
├── frontend/               React + TypeScript + Vite + Tailwind + shadcn/ui
│   └── src/
│       ├── pages/          One file per route (15 pages, all but Overview code-split)
│       ├── components/
│       │   ├── house/      The 3-D house: layout, appliance models, scene
│       │   ├── layout/     App shell, sidebar, page header
│       │   └── ui/         shadcn/ui primitives
│       ├── state/          LiveProvider — one WebSocket for the whole app
│       ├── hooks/          useLiveSocket
│       ├── lib/            api · charts · icons · utils
│       └── types/          Wire types mirroring the backend frame
│
├── database/               SQLite database and recordings
├── reports/                Exported CSV/PDF reports
└── docs/                   Architecture notes, model card, demo script
```

---

## Retraining the model

```bash
python -m pip install -r requirements-train.txt
python -m ai.train                      # ~11 min: 3 min data, 7 min training
python -m ai.train --smoke              # ~1 min, checks the plumbing only
python -m ai.train --windows 120000 --epochs 30
```

The script generates data, splits by episode, trains, tunes per-appliance
thresholds, prints a full per-appliance evaluation, exports all artefacts, and
then **verifies that Keras, TFLite and the NumPy runtime agree** — refusing to
ship a model whose NumPy runtime disagrees with Keras by more than 1 × 10⁻³.

---

## Testing

```bash
python -m pytest                 # 195 tests, ~12 s
python -m pytest -v              # verbose
npm run build --prefix frontend  # frontend type-check + build
```

Coverage: appliance physics and self-consistency, waveform synthesis and
measurement, house state machine and determinism, scenario integrity, feature
extraction, runtime activations, inference engine, harmonic disaggregation
(including the zero-collapse regression), telescopic tariff arithmetic, energy
accounting and rollovers, the notification rules engine, recording/replay
round-trips, every API endpoint, and the WebSocket protocol.

---

## What is real and what is simulated

Being precise about this is the point — a demonstration that blurs the line is
worth less, not more.

**Simulated:** the ESP32, the SCT-013 current clamp, the ADC, and the household
itself. `simulator/` replaces the sensor by synthesising the waveform that clamp
would have produced.

**Real, and unchanged if hardware were attached:** everything downstream of the
sensor. Feature extraction, the trained neural network, the NumPy inference
kernel, harmonic disaggregation, energy integration, slab billing, the alert
rules, SQLite persistence, the REST/WebSocket API, and the dashboard. The
pipeline's input is an array of voltage and current samples; where those samples
come from is not something any layer above `simulator/` knows or cares about.

To run this against real hardware you would replace `VirtualHouse.step()` with a
read from the ADC and supply a calibration constant. Nothing else changes.

The model is trained on simulated data, so its accuracy figures describe how well
it solves *this* disaggregation problem. Real mains carries interference,
appliance-to-appliance variation and ageing that this model has never seen —
those numbers should not be quoted as expected real-world performance.

---

## Known limitations

Stated plainly, because a reviewer will find them anyway:

1. **Small loads under large ones are genuinely hard.** A 9 W lamp beside a 1.5 kW
   air conditioner is close to the sensor noise floor. F1 for the LED light and
   mobile charger (0.80–0.89) is markedly below the large appliances (1.000). This
   is a real physical limit, not a tuning oversight.
2. **Trained on simulated data.** See above.
3. **Identical appliances are indistinguishable.** Two identical ceiling fans
   present as one fan at double amplitude. Single-point NILM cannot separate them
   even in principle.
4. **Exact-match accuracy is 0.489.** Getting all twelve appliances simultaneously
   correct is a strict metric; per-appliance Hamming accuracy is 0.925. Both are
   reported rather than only the flattering one.
5. **A fixed appliance catalogue.** The model classifies the twelve appliances it
   was trained on; a new appliance requires retraining.
6. **Steady-state disaggregation.** Attribution uses harmonic phasors from the
   current window. Transients inform *detection*, and which of several same-type
   devices is on, but not the watt-level split.
7. **Several devices of one type cost accuracy.** The classifier was trained with
   one device per type. With a ceiling fan in each of five rooms
   (`python -m ai.evaluate_devices`), type-level F1 is 0.95-0.96 in the evening
   scenario but 0.83 in the afternoon, when four or five fans run together and
   the model partly reads 300+ W of fan load as a refrigerator compressor. The
   right fan is identified in ~98% of windows when the type is detected
   correctly and the house is quiet, and in ~73-80% with the shipped classifier.
   Retraining on multi-device houses is the fix; it was not done here.
8. **At most five devices per type.** Signature variants have to fit in a
   limited range of phase angles; beyond five they would be too close to tell
   apart.

---

## Future scope

- **Real hardware** — swap `VirtualHouse.step()` for an ADC read; the rest stands.
- **Transfer learning to real data** — pre-train here, fine-tune on REDD/UK-DALE.
- **Int8 quantisation and TFLite-Micro** — the model is already 102 KB at int8,
  within an ESP32-S3's budget; add a representative dataset for full integer quantisation.
- **Appliance discovery** — cluster unexplained residual current to propose
  appliances not in the catalogue.
- **Sequence-to-point regression** — a second head predicting watts directly,
  removing the need for the NNLS stage.
- **Fault and anomaly detection** — a fridge whose compressor duty cycle is
  creeping up is a fridge about to fail.
- **Tariff optimisation** — with time-of-use tariffs, advise on shifting the
  washing machine and water heater to off-peak hours.
- **Multi-phase and three-phase** support for larger premises.

---

## Acknowledgements

Built as a final-year project. Appliance ratings, power factors and harmonic
signatures are drawn from typical published characteristics of Indian domestic
appliances; the tariff structures are representative of Indian domestic slab
tariffs and are illustrative, not an authority on any utility's current rates.
