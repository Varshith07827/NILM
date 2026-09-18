# Architecture Notes

Design decisions and the reasoning behind them. The README covers *what* the
system does; this covers *why it is built the way it is*.

---

## 1. The boundary that matters

Exactly one line in this codebase separates "simulated hardware" from "real
implementation":

```python
window: RawWindow = self.house.step(1.0)     # backend/app/services/pipeline.py
```

Above that line is `simulator/`, which stands in for an SCT-013 clamp, an ESP32
ADC and a household. Below it, every layer receives nothing but arrays of voltage
and current samples and has no idea where they came from.

Replacing the simulator with real hardware means replacing that one call with an
ADC read plus a calibration constant. Feature extraction, the model, the
disaggregator, billing, storage, the API and the dashboard are untouched.

That boundary is enforced structurally, not by convention: `simulator/` imports
nothing from `ai/` or `backend/`, and the per-appliance ground truth travels on a
separate object (`RawWindow.ground_truth`) that is never passed into feature
extraction or inference.

---

## 2. Why the simulator synthesises waveforms instead of numbers

The cheap approach is to emit `power = 75 W + noise` per appliance. It produces a
dashboard that looks identical to this one and teaches nothing, because the AI has
nothing to learn — appliances are already separated in the data.

Synthesising the actual 50 Hz waveform forces the problem to be real:

- The features are *measured*, not asserted. RMS, real power, power factor and THD
  all fall out of `mean(v·i)` and an FFT, exactly as firmware computes them.
- Appliances become genuinely confusable. A 9 W lamp added to a 1.5 kW compressor
  changes the aggregate waveform by less than the sensor noise floor — which is
  why the model's F1 on that lamp is 0.89 and not 1.00.
- Physical effects fall out for free: two loads in quadrature draw 1.41 A, not
  2 A; voltage sags under load; harmonics from different appliances interfere
  constructively or destructively depending on phase.

### Self-consistency by construction

The synthesis model is

```
i(t) = A · Σ_h  c_h · cos( h·(ωt − φ) )        A = √2 · I_rms / ‖c‖
```

where `‖c‖ = √(Σ c_h²)`. That normalisation makes the synthesised RMS exactly
`I_rms`, and because the fundamental RMS is then `I_rms · (c₁/‖c‖) = I_rms ·
PF_distortion`, the measured real power works out to

```
mean(v·i) = V_rms · I_rms · PF_distortion · PF_displacement = V_rms · I_rms · PF_total
```

So the waveform agrees with the nameplate *by construction*, not by tuning. The
test suite asserts it to within 2 % for all twelve appliances; measured worst-case
error is under 0.5 %.

### Sampling rate: 2 kHz, and why not 1 kHz

An earlier draft used 1 kHz. That was wrong: the catalogue models harmonics to the
13th (650 Hz), and at 1 kHz Nyquist is 500 Hz — the 13th harmonic would alias down
to 350 Hz and masquerade as the 7th, corrupting exactly the features the model
depends on. 2 kHz puts Nyquist at 1 kHz with room to spare, and is still
comfortably within what an ESP32 ADC with DMA can sustain.

### No FFT window function

The acquisition window is exactly 50 complete mains cycles, so every harmonic of
50 Hz lands precisely on an FFT bin and there is no spectral leakage to suppress.
Applying a Hann window here would smear energy across neighbouring bins and make
the harmonic ratios *less* accurate. This is a case where the textbook default is
the wrong choice and the reason has to be understood rather than copied.

---

## 3. Feature design

34 features, chosen so that a microcontroller could actually afford them: one real
FFT, a few dot products, and some per-cycle bookkeeping.

The deliberate omission is **time of day**. Real NILM systems do use temporal
context, and adding an `hour_sin`/`hour_cos` pair would measurably raise the
accuracy figures. It would also let the model learn "it is 8 pm, so the television
is probably on" — which is household-habit prediction, not disaggregation. For a
project whose claim is that appliances are identified from their electrical
signature, including it would make the headline number dishonest.

### Sub-second structure is preserved

Inrush is resolved *inside* the window, not as a per-second scalar. A
refrigerator's locked-rotor surge lasts a few hundred milliseconds; averaging it
across a second would erase the single most recognisable feature a compressor has.
The `inrush_ratio` and `cycle_rms_*` features are computed from per-cycle RMS
values within the window, preserving that structure at a cost of one reshape.

---

## 4. Why the model input is `(8, 34, 1)`

Not an image, but a **feature-time tensor**: eight consecutive one-second windows
stacked against the 34 features of each.

A single window can say "something drawing 150 W with low THD just appeared". Only
a sequence can say "something drawing 150 W with a 7× inrush spike appeared, held
steady for six seconds, and has the duty signature of a compressor rather than a
motor" — which is how a refrigerator is told apart from a washing machine starting.

Strides are asymmetric (`(1,2)`, `(1,2)`, `(2,2)`, then `(1,1)`) because the
feature axis carries far more independent information than the time axis; the time
axis is left largely intact until the final pool.

---

## 5. Why the backend never imports TensorFlow

On this machine `import tensorflow` takes 28 seconds and hundreds of megabytes of
RSS. The pipeline has a one-second budget per window and the API is expected to
start promptly. More to the point, the ESP32 the project models could not host
TensorFlow either — which is precisely why TensorFlow Lite for Microcontrollers
exists.

So the project follows the real edge deployment path:

```
train (TensorFlow)  →  fold BatchNorm  →  export weights  →  NumPy interpreter
                                       ↘  export          →  .tflite (float16)
```

`ai/runtime.py` implements conv2d, depthwise conv2d, squeeze-excite, hard-swish,
hard-sigmoid, global pooling, dense layers and residual connections in ~250 lines
of NumPy, including TensorFlow's asymmetric `SAME` padding rule reproduced exactly
rather than approximately.

### BatchNorm folding

At inference time BN is a fixed affine map per channel:

```
y = γ(conv(x) − μ)/√(σ²+ε) + β  =  conv(x)·s + (β − μ·s),   s = γ/√(σ²+ε)
```

Convolution is linear, so `s` pushes straight into the kernel and the constant
becomes an ordinary bias. The deployed graph has no BN layers at all, needs one
fewer pass over the activations, and is numerically identical. This is the same
optimisation every real edge converter performs.

### Guarding against drift

The risk of hand-writing an interpreter is that it silently diverges from the
trained model — a wrong padding rule, a missed residual, a botched fold — and
produces quietly wrong predictions rather than an error.

Two structural defences:

1. **One source of truth for the topology.** `ai/architecture.py` is a declarative
   spec consumed by *both* the Keras builder and the NumPy runtime. Neither can
   add a layer the other does not know about.
2. **Verification at export.** `verify_export` runs 256 validation sequences
   through Keras, TFLite and NumPy and compares. `ai/train.py` refuses to ship a
   model whose NumPy output differs from Keras by more than 1 × 10⁻³. Measured:
   8.3 × 10⁻⁶.

---

## 6. Disaggregation: the phasor argument

Classification gives a set of appliances; the dashboard needs watts.

The key observation is that Kirchhoff's current law applies **per harmonic**, so
at each harmonic order the appliance currents add as *complex phasors*:

```
I_h(total) = Σ_i  a_i · I_h(appliance i at rated power)
```

RMS magnitudes do not add that way — two 1 A loads in quadrature draw 1.41 A
together — which is where "subtract the known loads" heuristics accumulate error.
In the complex plane the system is exactly linear in the unknown scale factors
`a_i`.

Seven harmonic orders (1, 3, …, 13) × (real, imaginary) gives fourteen equations
for at most twelve unknowns: overdetermined, solved by **non-negative** least
squares. Non-negativity is not cosmetic — without it the solver happily assigns
one appliance a negative current to cancel another and fit sensor noise.

### The prior, and a bug worth documenting

The classifier's confidence enters as a Tikhonov prior. The first implementation
centred it at **zero** — penalise appliances the model is unsure about, so weak
detections need strong evidence. That is a reasonable-sounding idea and it was
wrong.

An LED lamp and a tube light are both non-PFC lighting drivers with nearly
identical harmonic shape, so their columns in the signature matrix are nearly
collinear. Least squares resolves near-collinearity by favouring one column; with
a zero-centred penalty it drove the smaller load to **exactly 0 W** while the
classifier still reported it as detected. The dashboard showed "LED Light —
detected, 100 % confidence, 0.0 W", which is worse than either being wrong or
being right.

Centring the prior on the confidence itself encodes the correct belief:

> *If the model is 95 % sure this appliance is running, expect it near its rated
> draw — but let the harmonic evidence override that.*

The penalty is weighted by each appliance's own column norm, so a 9 W lamp and a
1.5 kW compressor are nudged with equal *relative* force rather than in raw amps.
Collapses fell to 0.47 % of detections, and there is a regression test.

### Honest residuals

The attribution is rescaled so the parts sum to the metered whole, but the
correction is **clamped to ±40 %**. If the fit is wildly off, the difference is
reported as *Unattributed* rather than smeared across appliances to fake a perfect
balance. That slice is shown on the dashboard on purpose.

---

## 7. Backend concurrency and storage

### Simulated time is the unit of account

Running at 10× produces simulated seconds ten times faster in wall-clock terms,
but each one still represents exactly one watt-second. That is what makes "a full
day of household usage in 2.4 minutes" a meaningful statement rather than a
tenfold billing error. There is a test for it.

### Write batching

At 10× the pipeline produces 10 readings and ~130 bucket updates per second.
Committing each individually would spend all its time in `fsync`. Rows accumulate
in memory and are flushed in one transaction via `asyncio.to_thread`, keeping the
event loop free. SQLite runs in WAL mode with `synchronous=NORMAL` so the
dashboard can read history while the loop writes.

### Two storage shapes, chosen by read pattern

| Table | Granularity | Read by |
|---|---|---|
| `readings` | one row per second | live charts, history endpoint |
| `energy_buckets` | per appliance per hour | reports |

A month of simulated time is ~2.6 million readings but only ~720 buckets, so a
monthly report is a single indexed aggregate rather than a full scan. The history
endpoint decimates **in SQL** (`WHERE id % stride = 0`) rather than fetching
everything and thinning in Python.

### WebSocket fan-out drops rather than blocks

A backgrounded browser tab stops draining its queue. Blocking the simulation loop
on it would stall the entire system, so a full queue loses its oldest frame. This
is live telemetry: a stale frame is worth less than a current one.

---

## 8. Frontend structure

The dashboard is seven routed pages behind a persistent sidebar. Two decisions
shape it:

**One WebSocket for the whole application.** The connection lives in a context
provider *above* the router. A per-page hook would tear down and re-handshake
the socket on every navigation, dropping the accumulated chart history each
time.

**Everything except Overview is code-split.** Three.js is by far the heaviest
dependency in the project — 935 KB raw, 248 KB gzipped — and it is needed on
exactly one page. Lazy-loading keeps it out of the initial download for anyone
who never opens the 3-D view.

### The 3-D house

Built from primitives rather than loaded from a GLTF file: no binary assets, no
licence questions, no loading state, and at this scale a stylised low-poly look
reads better than a detailed model would. `layout.ts` holds the floor plan as
plain data and imports nothing from Three.js, so the layout can be reasoned
about independently of the renderer.

The important design principle is that **appliances show their state physically
rather than through a label**: blade rotation speed, hob glow, drum rotation and
screen flicker are all driven by the same numbers the charts use, so the picture
and the figures cannot drift apart. Detection errors are shown in space too — a
red floor ring for a missed appliance, amber for a false positive — which makes
"the model got this wrong" a spatial fact rather than a row in a table.

## 8b. Four bugs worth recording

Each of these was found by looking at the running system rather than by reading
the code, and each has a general lesson.

**`h-full` on stacked cards.** Cards in a block column inside a stretched grid
row resolve `height: 100%` against the *row* height, not their own content.
Every card ballooned to 2269 px. `h-full` is correct only for the side-by-side
pair that genuinely are grid items.

**Wildcard icon import.** `import * as Icons from "lucide-react"` defeats
tree-shaking and pulled in over a thousand components to use twelve. The bundle
dropped from 1.37 MB to 640 KB after switching to an explicit registry.

**Physically-correct lighting.** Since three.js r155 light intensity is in
photometric units, and the legacy mode has been removed entirely. The
conventional "0.5 ambient, 1.0 sun" values from older three.js examples render
an almost-black scene. This was diagnosed by reading the framebuffer directly —
`gl.readPixels` inside a `requestAnimationFrame` showed the scene *was*
rendering, with a maximum luminance of 29 out of 255 — which distinguished "not
drawing" from "drawing too dark". Intensities are now roughly 3x the legacy
values.

**One missing field blanked the entire app.** A backend field was renamed while
an older backend process was still running, so a number came through as
`undefined`, `.toFixed()` threw inside the app shell, and React unmounted the
whole tree to a white page — with the real cause visible only in the console.
The fix was an error boundary plus defensive reads on live-wire numerics. The
general lesson is that a live dashboard's worst failure mode is going blank: it
tells the viewer nothing and hides the cause. It should degrade to showing the
error while the rest of the application keeps working.

### Render throttling

At 10x the backend emits ten frames per second. Pushing every frame into React
state would re-render the whole dashboard ten times a second and make the charts
stutter. The split: **the latest frame is React state** (so headline numbers are
instant), while **history accumulates in a ref** and a single 250 ms interval
publishes a snapshot for the charts. Chart.js runs with `animation: false` and
`pointRadius: 0` — animating each transition would queue more work than the
browser can retire, and the chart would visibly lag the numbers beside it.

## 9. What would need to change for real hardware

1. Replace `VirtualHouse.step()` with an ADC read returning voltage and current
   sample arrays.
2. Add a calibration constant (clamp turns ratio × burden resistor) to convert ADC
   counts to amps.
3. Handle mains frequency drift — the FFT bin alignment assumes exactly 50.00 Hz.
   A zero-crossing-locked window or a short interpolation would be needed.
4. Fine-tune the model on real measurements. The synthetic-trained weights are a
   starting point, not a deployable classifier.
5. For on-device inference, quantise to int8 (~102 KB) and port `ai/runtime.py` to
   C, or use TFLite-Micro directly with the exported `.tflite`.

Nothing in `ai/`, `backend/` or `frontend/` changes structurally.
