# Demonstration Script

A 10-minute walkthrough for a viva or project review, with the questions
examiners actually ask and honest answers to them.

---

## Before you start (5 minutes ahead)

```bash
# Terminal 1
python run_backend.py

# Terminal 2
npm run dev --prefix frontend
```

Open <http://localhost:5173> and confirm:

- [ ] Header shows **Live** (green) and **numpy**
- [ ] Mode is **Demo**, scenario **Evening Peak**, speed **1×**
- [ ] Numbers in the top row are moving
- [ ] **Ground truth** toggle in the Appliance Detection card is **on**

Then press **Reset** so the run starts at 18:00:00 with the examiners watching.

> Use **Demo mode** for the presentation. It plays a fixed, seeded timeline — the
> same events in the same order every single time. Save Simulation mode for the
> "does it handle something unscripted?" question.

---

## 1. The problem (45 seconds)

> "Utility meters tell you that the house used 300 units. They don't tell you the
> air conditioner was 60 % of it. Sub-metering every socket is expensive and
> invasive. Non-Intrusive Load Monitoring identifies individual appliances from a
> *single* measurement at the mains — one clamp sensor for the whole house."

Point at the **Raw Waveform** card.

> "This is all the system gets. One current waveform. Everything else on this
> screen is inferred from it."

---

## 2. The signal is real physics (90 seconds)

Stay on the **Raw Waveform** card. Note the current is *not* a clean sine wave —
it's distorted, with a crest factor above 1.41.

> "The waveform is synthesised at 2 kHz — 40 samples per mains cycle — from real
> appliance models. Crucially, power factor is split into two independent causes:
> displacement and distortion."

Switch the **Live Measurements** card to the **Quality** tab.

> "A ceiling fan is an induction motor: clean sinusoid, lagging the voltage. Poor
> power factor from *displacement*. A TV power supply draws a spiky pulse roughly
> in phase with the voltage: poor power factor from *distortion*, with 68 % THD.
>
> Two appliances can have identical RMS current and identical power factor and
> still be completely separable in the harmonic domain. That is the entire
> physical basis of this project."

**If asked "did you just make these numbers up?"**

> "No — every appliance is defined by its nameplate, and the simulator synthesises
> the waveform and then *measures* it back the way firmware would. The test suite
> asserts that measured RMS current, real power, power factor and THD all match
> the nameplate to within 0.5 %. If they ever diverge, the tests fail."

---

## 2b. The house (90 seconds)

Open the **3D Home** page.

> "This is the household the system is monitoring. It is not a diagram — the
> fan blades are spinning at a speed proportional to the power it is drawing,
> and the refrigerator is lit because its compressor is running right now.
> Every room reports its own load, so you can see at a glance which room is
> costing money."

Click an appliance — the microwave is a good one, it is large and unmistakable.

> "I have just switched that on at the socket. The detector doesn't get told
> that. It has to work it out from the change in the mains current alone."

Watch it appear in the grid and the event timeline within a second or two.

> "Two seconds, because the classifier reads an eight-second window."

If ground truth is on, point at any red or amber ring on the floor.

> "And where the model is wrong, it shows up in the house: a red ring means an
> appliance is running that we missed, amber means we detected something that
> isn't actually on."

**Worth doing if you have time:** switch the scenario to **Night**. The scene
lighting follows the simulated clock, so the house genuinely goes dark and the
only light left comes from appliances that are really drawing power.

## 3. Detection in action (2 minutes)

Set speed to **5×**. Watch the **Appliance Detection** grid and the
**Event Timeline** together.

At 18:00 the fan comes on, then lights at 18:01, the TV at 18:03, the AC at 18:05.

> "The event timeline on the right is the simulator telling us what it did. The
> grid in the middle is what the AI worked out, seeing only the aggregate
> waveform. The green ticks are agreements."

Point at the **AC** card as it starts.

> "There's the air conditioner. 1.5 kW, and the estimate lands within a few watts
> of the truth. Notice the confidence bar — the small white tick is that
> appliance's decision threshold, tuned per appliance on validation data, not a
> blanket 0.5."

Point at the **Detector Accuracy** panel.

> "Precision, recall and F1, computed live by comparing against ground truth the
> model never sees. It moves as the scenario gets harder."

**If the fan or a lamp shows a red ✗ — do not hide it. Use it:**

> "There — the 9 W LED under a 3 kW load. That's a genuine miss, and it's the
> honest limit of single-point NILM. Our F1 on the air conditioner is 1.000; on
> the LED lamp it's 0.89. Any NILM project claiming 99 % on a 9 W load under 3 kW
> is measuring something other than what it claims."

---

## 4. Disaggregation and billing (90 seconds)

Point at the **Energy Breakdown** donut.

> "Classification says *which* appliances. This says *how much*. It solves a
> non-negative least-squares problem on complex harmonic phasors — because
> Kirchhoff's law applies per harmonic, currents add as phasors, and the problem
> becomes exactly linear in the unknown appliance scale factors. RMS magnitudes
> don't add that way, which is where naive approaches drift."

Note the **Unattributed** slice.

> "We show what we couldn't confidently attribute rather than hiding it. A
> dashboard that always sums to a tidy 100 % isn't being honest about its
> uncertainty."

Move to **Electricity Cost**.

> "Indian domestic tariffs are telescopic — the bands apply progressively, like
> tax brackets. So the cost of the *next* unit depends on how much has already
> been used this month. The highlighted row is the active band. We charge each
> second at the marginal rate, which is what a real bill does."

Switch the tariff to **TNEB Domestic (subsidised)** in the dropdown and watch the
figures reprice live.

---

## 5. The Edge AI claim (90 seconds)

This is the part examiners probe hardest. Open the **Detector Accuracy** panel's
model card.

> "MobileNetV3-derived: depthwise separable convolutions, inverted residual
> bottlenecks, squeeze-and-excitation, hard-swish. 104,000 parameters — 408 KB as
> float32, 222 KB as a float16 TFLite file, about 100 KB at int8. That fits an
> ESP32-S3."

Point at the inference latency (~2 ms).

> "Two milliseconds per second of data. And note what the backend does *not*
> import: TensorFlow. Importing it takes 28 seconds and hundreds of megabytes —
> a one-second inference loop can't pay that, and neither could a
> microcontroller. That's exactly why TFLite-Micro exists.
>
> So we follow the real deployment path: train in TensorFlow, fold BatchNorm into
> the convolutions, export the weights, and execute the graph with a hand-written
> NumPy interpreter. At export time we verify all three backends agree — the
> NumPy kernel matches Keras to 8 × 10⁻⁶. The training script refuses to ship a
> model that fails that check."

**If asked "so is it really running the neural network, or a shortcut?"**

> "It's the same graph and the same weights, operation for operation — conv,
> depthwise conv, squeeze-excite, hard-swish, residuals. We wrote the interpreter
> instead of importing one. That's what TFLite-Micro is: a small interpreter for
> exported weights. Ours is in Python instead of C++."

---

## 6. It handles unscripted behaviour (60 seconds)

Switch mode to **Simulation**.

> "Everything so far was a scripted timeline, so you might reasonably suspect the
> results are staged. This mode has no script at all — each appliance decides for
> itself when to switch on, from its own hourly usage profile. Different every
> run."

Let it run 20 seconds at 5×, and watch F1 hold up.

Then switch scenario to **Vacation**.

> "Empty house. Only the refrigerator cycling and standby draw. The system
> correctly reports a nearly empty house instead of hallucinating appliances —
> which is a failure mode worth testing for."

Then go to **Custom** scenario and switch an appliance on by hand from the grid.

> "And I can drive it manually. Watch the detector pick it up."

---

## 7. Data, reports and repeatability (45 seconds)

Scroll to **Reports**. Switch between Daily / Weekly / Monthly. Click **Export PDF**.

> "Everything persists to SQLite — per-second readings plus hourly per-appliance
> energy buckets, so a monthly report is one indexed aggregate query rather than
> a scan of millions of rows. Reports export to CSV and PDF."

Point at the **Recorder** in Simulation Control.

> "And any run can be recorded and replayed. The recording stores the appliance
> amplitude track, not the waveform — 100 bytes a second instead of 16 KB — and
> replays it *through the same pipeline*, so it's not a cached answer. Retrain the
> model and the same recording shows the new model's behaviour on identical input."

---

## 8. Close (30 seconds)

> "To summarise: micro-F1 of 0.94 across every scenario, normalised
> disaggregation error under 6 %, 2 ms inference on a 100 KB model, and
> 139 tests covering the physics, the maths and the API.
>
> The hardware is simulated — there is no ESP32 here. But everything above the
> sensor is the real implementation. To run this on real hardware you'd replace
> one function, `VirtualHouse.step()`, with a read from the ADC. Nothing else
> changes."

---

## Questions you should expect

**"How do I know the AI isn't just reading the ground truth?"**
> The ground truth lives on a separate object (`RawWindow.ground_truth`) that is
> never passed into feature extraction or the model. The model's only input is a
> 34-feature vector computed from the voltage and current arrays. It's also worth
> noting the feature vector deliberately contains no time-of-day information —
> letting it learn "it's 8 pm so the TV is probably on" would inflate accuracy
> without demonstrating disaggregation.

**"Why did you train on simulated data? Isn't that circular?"**
> It's a limitation and I'd state it as one. The model learns to solve *this*
> disaggregation problem. Real mains has interference and appliance ageing this
> model has never seen, so these numbers shouldn't be quoted as real-world
> performance. The realistic path is pre-train here, then fine-tune on a real
> dataset like REDD or UK-DALE.

**"Why is exact-match accuracy only 49 %?"**
> Because it requires all twelve appliances to be simultaneously correct — one
> mistake on a 9 W lamp fails the whole window. Per-appliance accuracy is 92.5 %.
> We report both rather than only the flattering one.

**"Could it tell two identical fans apart?"**
> No — and neither could any single-point NILM system, even in principle. Two
> identical fans present as one fan at double amplitude. You'd need a second
> sensor or a distinguishing characteristic.

**"What's the hardest appliance and why?"**
> The mobile charger, at F1 0.80. It's 12 W. When the air conditioner is running,
> its contribution to the aggregate current is well under a percent — close to
> the sensor noise floor we model at 8 mA. It's easy to detect in a quiet house
> and near-impossible under a heavy load.

**"What would you do differently?"**
> Add a regression head predicting watts directly, so disaggregation and
> classification are learned jointly instead of the NNLS stage being a separate
> classical step. And fine-tune on real measured data.
