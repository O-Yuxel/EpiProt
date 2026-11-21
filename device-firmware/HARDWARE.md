# EpiProt headband: hardware design

**Status:** designed on paper. No physical prototype is built in this project, so nothing here has
been measured on a real device. Sources are marked: **[DS]** datasheet, **[EST]** our estimate,
**[MODEL]** required by the detection model on the phone.

## Summary

| | Choice |
|---|---|
| Job | Measure and send. The phone runs detection, alarms and storage. |
| Electrodes | 4 semi-dry hydrogel pads behind the ears (mastoids) + 1 bias electrode under the right pads |
| EEG front-end | TI ADS1299-4: 4 channels, 24-bit, EEG-grade (1 µV noise) |
| Sample rate | Exactly 256 samples/s per channel, the model's rate |
| Movement | TDK ICM-42688-P, 3-axis accelerometer + 3-axis gyroscope, exactly 25 Hz (clock locked to the radio crystal) |
| Radio / processor | Raytac MDBT50Q module (Nordic nRF52840), Bluetooth LE 5, pre-certified |
| Backup memory | 8 MB flash, about 40 minutes when the phone is out of reach |
| Battery | 700 mAh rechargeable LiPo (603040: 6 x 30 x 40 mm), about 2 days, magnetic charging |
| Wearing | Two one-piece side bodies (ear hook + electrode module + pod) joined by a beta-titanium spring band at the nape; 58 g; sizes S (children from about 6 years), M and L (D16, D21) |
| Data rate | About 3.7 KB/s ([PROTOCOL.md](PROTOCOL.md)) |
| Parts cost | About $60–77 per headband [EST] |

## Design decisions and why

Every choice was made against one question: **does it protect the patient and the quality of the
data?** Cheaper parts were rejected when they put the data at risk; more expensive parts were
rejected when they would not change the result.

| # | Decision | Reason |
|---|---|---|
| D1 | **Semi-dry electrodes**, not gel and not dry | Gel gives the best signal but needs new adhesive pads every day and irritates the skin over weeks. Dry electrodes need no consumables but are noisy and furthest from the training data; we cannot test them, so they are too risky. Semi-dry pads give a signal close to gel, with no adhesive, and last several days. Dry electrodes remain a later option once they can be tested. |
| D2 | **ADS1299-4 instead of ADS1292** | With semi-dry electrodes the contact noise is low, so the chip's own noise matters. The ADS1292 (an ECG chip, 8 µV peak-to-peak) could pollute the weakest band the model uses (30–60 Hz) and push the data away from the training data. The ADS1299 is built for EEG (1 µV peak-to-peak [DS]) and its 4 channels give backup channels if a pad loses contact. |
| D3 | **nRF52840 instead of nRF52832** | The head and body absorb 2.4 GHz radio; with the phone on a bedside table the link can weaken. The nRF52840 transmits up to +8 dBm instead of +4 dBm and supports Bluetooth "long range" (Coded PHY) for weak links [DS]. Four times the RAM and twice the flash also leave room for safe firmware updates. |
| D4 | **External crystal clocks** | The EEG chip's internal clock is only accurate to ±0.5 % at room temperature and ±2.5 % over temperature [DS]: wrong sample rates and time stamps that drift away from the watch. A crystal oscillator is accurate to about 0.002 %. It is also chosen so the chip runs at exactly 256 samples/s (see EEG section), so the phone receives the model's rate without resampling. |
| D5 | **8 MB backup flash instead of 2 MB** | The 4-channel stream fills 2 MB in about 10 minutes; 8 MB holds about 40 minutes, so a longer gap in the connection loses no data. |
| D6 | **Flexible shielded cables with strain relief** between the ear pads and the pod | During a convulsion the band bends hard; a broken wire is the most likely cause of a silent, bad connection. Shielding also keeps mains hum out of the small EEG signal. |
| D7 | **Low-noise power supply** for the EEG chip | The ADS1299 needs a clean 5 V supply [DS]; supply noise goes straight into the EEG. A low-noise boost converter is followed by a low-noise regulator. |
| D8 | **700 mAh battery** | The ADS1299-4 uses about 22 mW [DS], so the whole headband draws about 11 mA. 700 mAh gives about 2 days, comfortably above the 24-hour minimum. |
| D9 | ~~Kept: BMI270 motion sensor~~ | Replaced by D13 after the simulator showed a problem with its clock. |
| D10 | **Kept: Bluetooth integrity as designed** | Bluetooth already checks every packet and resends damaged ones. We add a sequence number and time stamp to every packet, so the phone sees any missing data. |
| D11 | **Pre-certified radio module** | No separate radio certification for the headband: less cost, less risk. |
| D12 | **No processing on the headband** | The phone already runs the model and has the watch data; the headband stays simple, which means fewer things that can go wrong. |
| D13 | **ICM-42688-P motion sensor with its clock locked to the radio crystal, instead of BMI270** (found with the simulator) | A motion sensor with its own internal clock (BMI270, and the ICM-42688-P's own clock is only ±1 % accurate) does not sample exactly 25 times per second, so the phone has to shift samples onto the model's 25 Hz grid. In the simulator with real seizure recordings this distorted exactly the movement features that carry the convulsion signature (3–12 Hz shaking): typical error 0.57 (log scale) in the 8–12 Hz band. The ICM-42688-P accepts an external clock (CLKIN); the nRF52840 feeds it 32.000 kHz made from its own crystal, so the sensor samples at exactly 25 Hz and no shifting is needed. Typical error drops to 0.03–0.04, about 15 times smaller (2 patients, 15 min each). Cost: ~+$2, ~+0.7 mA. |
| D14 | **Movement converted to the SeizeIT2 "group B" scale on the phone** (found in the training data) | SeizeIT2 recorded movement with two device settings, a factor 3 apart (1 g = 0.5 or 0.167 units; gyroscope ~365 or ~1016 °/s per unit), measured from the data itself. 43 of the 55 tonic-clonic seizures the model learned from are in group B, so the headband's g and °/s are converted to that scale. Tool: `python -m epiprot.headband.calibration`. |
| D15 | **Contact check every 10 minutes**, so the phone knows when a pad must be replaced (found with the simulator) | A semi-dry pad dries out slowly. While it dries the signal gets noisier, but it still looks like EEG, so neither the phone's signal check nor the lead-off detection notices until contact is completely lost. Until then noisy data go to the model unnoticed (risk of false alarms and of missed seizures). Every 10 minutes the EEG chip passes a tiny current (6 nA) through each electrode for 2 s and measures its contact impedance; those 2 s of EEG are flagged and not used by the model (0.3 % of the data). Above 150 kOhm the phone asks the patient to replace that pad. In the simulator a pad drying over 40 minutes was reported 36 minutes before contact was lost. Uses a built-in function of the ADS1299; no extra parts. |

| D16 | **One-piece side bodies + spring band at the nape, built on real heads** (replaces the elastic band) | An elastic band cannot press the pads reliably and the pods hung on cables. Now each side is one moulded body: ear hook over the ear root, electrode module on the mastoid, pod on the side of the neck; a thin spring band joins the two pods around the nape (like a bone-conduction sports headset). Modelled on the NIOSH digital headforms (5 head shapes, 527–565 mm circumference). Numbers below are calculated, not measured. |
| D17 | **Beta-titanium spring wire 1.3 mm** (nickel-free), not nitinol or steel (found with `cad/headform/mechanics.py`) | The pads sit ~57 mm above the band, so the band carries a large bending moment. For 1.5 N per side, every nitinol wire went past its linear limit (450 MPa) while the band is opened to put it on, and every steel wire past its yield (1100 MPa); then the force on the head becomes unpredictable or the band bends for good. Beta-titanium 1.3 mm stays at 815 MPa (allowable 900). It is also nickel-free (nickel allergy is common) and proven in orthodontic wires and eyewear frames. The ear hooks get a separate, thinner 1.0 mm wire so they let go at ~5 N each. |
| D18 | **Pod positions calculated against the pillow** (`cad/headform/pod_placement_study.py`) | Positions tested on the real head with a pillow 20 mm deep: pods at 76° from the back centre, 64 mm below the ear centre touch the pillow by 0 mm lying on the back and lying on the side. |
| D19 | **Battery size corrected to 603040 + 0.6 mm swelling room** | The first model used a 603450 cell, which is ~1000 mAh; 700 mAh is the 603040. LiPo cells swell up to ~10 % of their thickness over their life, so the carrier leaves 0.6 mm above the cell. |
| D21 | **Child size S** (decided with the user) | The phone app supports patients under 13, so the headband must fit children too. NIOSH has no child heads, so the small adult head was scaled to a 505 mm circumference (about 6–8 years; an approximation: children have a larger skull for their face and a shorter neck). On it the M size does not fit (pads 11 mm off the mastoid, the left body 2.6 mm into the skin); the model rebuilt for this head fits: everything inside, 0.9 mm closest gap, no pillow contact for the pods, nape band 114 mm (M: 118–123). Same parts and battery; clamping force set to 1.2 N for children (18 mmHg). The 58 g is the same as for adults: a lighter version with a smaller battery is a possible later step. Not for children under 6. |
| D22 | **One RGB status light instead of a single-colour LED** (found while writing the user manual) | A patient must see at a glance whether the band works. With one colour, eight states (on, connected, searching, pairing, low battery, charging, full, fault) would need eight blink rhythms nobody remembers. An RGB LED (about $0.10 more) gives: green = all fine, yellow = not connected / charging, blue = pairing, red = battery or fault. Same light pipe, same current budget (short flashes). Table: PROTOCOL.md "Status light". |
| D20 | **Switched off only in the phone app, never by the button** (decided with the user) | The worst failure is a band that switches off while the patient sleeps: a pillow or a convulsion can press a button. So the band switches on by itself off the charger and connects by itself; it is switched off only in the app (with a confirmation) or by the charger. The single, recessed button is only for pairing. The watch says at once when detection is off because of this. Details: PROTOCOL.md "Switching on and off". |

## Electrodes and channels

SeizeIT2, the data the model was trained on, recorded EEG with electrodes on the mastoid bone
behind the ears (two left, one right), giving "one left same-side channel and one cross-head
channel" (SeizeIT2 paper, arXiv 2502.01224). The headband keeps that layout and adds backups:

| Electrode | Position |
|---|---|
| L-top, L-bottom | Behind the left ear, upper and lower mastoid |
| R-top, R-bottom | Behind the right ear, upper and lower mastoid |
| Bias | Behind the right ear, below the R-bottom pad (14 mm pad on the right electrode module; D16). Drives the body to the amplifier's mid voltage, cancels mains hum |

| Channel | Electrodes | Use |
|---|---|---|
| 1 | L-top − L-bottom | Model input: left same-side |
| 2 | L-top − R-top | Model input: cross-head |
| 3 | R-top − R-bottom | Backup: right same-side (SeizeIT2 used this for right-sided seizures) |
| 4 | L-bottom − R-bottom | Backup: second cross-head channel if L-top loses contact |

The phone switches to channels 3 and 4 by itself when a pad of channel 1 or 2 loses contact (`Channels.kt`).

**Pads:** semi-dry hydrogel pads click onto the band's snap studs and are pressed onto the skin by
the band. The patient replaces them every few days. A contact check every 10 minutes (D15) measures
each pad's contact impedance; above 150 kOhm the phone asks the patient to replace that pad, before
the signal is lost.

## EEG front-end: TI ADS1299-4

| Setting | Value | Source |
|---|---|---|
| Channels, resolution | 4, 24-bit | [DS] |
| Noise | 1 µV peak-to-peak (0.01–70 Hz) | [DS] |
| Gain | 12, so the input range is ±375 mV (±4.5 V reference / 12) and one bit is about 0.05 µV | [DS] |
| Input bias current, input impedance | ±300 pA, 1000 MΩ | [DS] |
| Mains rejection (CMRR) | −110 dB | [DS] |
| Supply, power | 5 V analog + 3.3 V digital, about 22 mW | [DS] |
| Electrode contact | Built-in lead-off detection | [DS] |
| Clock | External 2.097152 MHz (a 4.194304 MHz crystal oscillator divided by 2) | [DS] range 1.5–2.25 MHz |

**Exactly 256 samples/s:** the chip's slowest rate is its clock divided by 8192 (250 samples/s at
the standard 2.048 MHz [DS]). With a 2.097152 MHz clock, inside the allowed range, the same setting
gives exactly 256 samples/s. The model's sampling rate comes straight from the hardware.

## Movement sensor: TDK ICM-42688-P

3-axis accelerometer and 3-axis gyroscope, 16-bit, both at 25 Hz [DS]. Ranges ±8 g and ±2000 °/s
(4096 LSB/g, 16.4 LSB/(°/s)), so a convulsion never clips [EST]. About 0.88 mA in low-noise mode [DS].

**Clock (D13):** the sensor's CLKIN input (31–50 kHz allowed [DS]) gets 32.000 kHz from the
nRF52840: a timer toggles a pin every 250 ticks of its 16 MHz crystal clock. 32.000 kHz, not the
32.768 kHz watch crystal, because the sensor's rates scale with the input clock and 32.768 kHz would
give 25.6 instead of 25 samples/s.

**Units (D14):** the phone converts g and °/s to the SeizeIT2 group-B scale (1 g = 1/6 unit,
1 unit = ~1016 °/s).

**Position (validation risk):** in SeizeIT2 the recorder whose motion sensor gives the model's "head movement"
input was worn at the **back of the neck** (SeizeIT2 file metadata: "Back of the neck (EEG SD)"). In the v3
design the sensor sits in the left pod on the **side of the neck** (76° from the back centre, 64 mm below the ear
centre), held by the ear hooks, so it follows the head more than a recorder stuck on the neck would. The model
uses only the size of the movement (acceleration / rotation magnitude, its 0–3, 3–8, 8–12 Hz power and
rhythm), so the sensor's orientation does not matter, but its amplitude can differ. How much depends on it:
with movement 54/55 seizures, without any movement 49/55 at the same 0.24 false alarms/day (cross-validated,
`audit_no_movement.json`). So the movement input is worth 5 of 55 seizures and must be checked with
recordings from the real headband; if head movement turns out to raise false alarms, the phone can fall back
to the EEG + heart-rate model or the model is retrained on headband data.

## Radio and processor: Raytac MDBT50Q (Nordic nRF52840)

Arm Cortex-M4F, 1 MB flash, 256 KB RAM, Bluetooth LE 5 with 2 Mbit/s and long-range (Coded) radio
modes, up to +8 dBm [DS]. Pre-certified module (FCC, CE and others). A 32.768 kHz crystal keeps the
time stamps accurate; the 32 MHz radio crystal also clocks the motion sensor (D13).

## Power

| Part | Current from the battery | Source |
|---|---|---|
| ADS1299-4 (4.06 mA at 5 V via the boost converter, 0.54 mA at 3.3 V) | ~7.0 mA | [DS] + 85 % converter efficiency [EST] |
| ICM-42688-P | ~0.9 mA | [DS] |
| nRF52840, streaming ~3.7 KB/s | ~1.0 mA | [EST] |
| Processing, regulators, clocks (incl. radio crystal kept on for the sensor clock) | ~0.6 mA | [EST] |
| **Total** | **~9.5 mA, ~11.4 mA with 20 % margin** | |

That is about 275 mAh a day, so **700 mAh lasts about 2 days**. Charging takes about 2 hours.
During charging the band is off the head and **seizure detection is not working** (every model needs the brain
signal; a watch-only model was considered and not built). The watch shows "headband charging", so the best time to
charge is during the day while someone is around, e.g. while showering. The phone reminds the patient when the battery is low.

**Why rechargeable:** a coin cell cannot deliver 11 mA continuously, AAA batteries are too heavy
for the head, and body-heat or motion harvesting gives far too little power.

**Charging:** magnetic pogo-pin connector (no open USB port, sweat-proof), Microchip MCP73831
charger. While the charger is attached the firmware switches the EEG chip off, so the patient is
never connected to a mains-powered charger.

## Data rate

| Stream | Calculation | Rate |
|---|---|---|
| EEG | 4 channels × 256 samples/s × 3 bytes, in 16 packets/s | 3328 B/s with headers |
| Movement | 6 axes × 25 samples/s × 2 bytes, in 5 packets/s | 355 B/s with headers |
| Status | 1 packet/s | 26 B/s |
| **Total** | | **~3.7 KB/s (~30 kbit/s)** |

Well within Bluetooth LE. Packet format: [PROTOCOL.md](PROTOCOL.md).

## Safety

- Battery powered, radio link only: no wired path from mains to the patient.
- A series resistor on every electrode limits current if a fault happens; ESD diodes protect the
  inputs.
- Charging lockout (see Power). LiPo with built-in protection (over-charge, over-discharge, short
  circuit).
- Medical-grade silicone band.
- A real product would be tested against IEC 60601-1 and IEC 60601-1-11 (home use). Not done here.

## Mechanical (3D model: `cad/`, decisions D16–D19)

Each side is one soft body: **ear hook** (6 x 4 mm, flat underside on the ear root) → **electrode module** on
the mastoid (upper + lower 18 mm pad; on the right also the 14 mm bias pad; same mould both sides, a blank cap
on the left) → **pod** on the side of the neck (right: battery, left: electronics; 34 x 50 mm, 10 / 7 mm thick).
A **beta-titanium spring band** (5.5 x 4 mm silicone over a 1.3 mm wire) joins the pods around the nape and
presses the pads; a **magnetic clasp** at the back opens at 5 N. Inside each pod a rigid carrier (two halves,
snapped together, then overmoulded) holds the cell or the board. The flex cable runs inside the body and band.

**Calculated on the NIOSH headforms** (`cad/headband_checks.json`, `cad/headform/mechanics_results.json`):

| Check | Result |
|---|---|
| Battery, carrier, board inside the body | 100 % |
| Closest point to the skin (hook / band / pods) | 0.9 / 2.4 / 2.5 mm: nothing presses except the pads |
| Pad pressure (medium head) | 22 mmHg (skin limit ~32 mmHg) |
| Ear-root pressure, all weight on the hooks | 19.5 mmHg |
| Weight | 58 g [EST] |
| Pillow, lying on the back | pods 0 mm, nape band 1.7 mm |
| Pillow, lying on the side | pods 0 mm; module and hook behind and over the ear ~14 mm (like a glasses temple) |
| Clamping force on 5 heads with one size | 1.32–1.59 N; large head 2.37 N, so it needs size L |
| Sizes | **S** fits the child head (505 mm, band 114 mm); **M** fits small, medium, long-narrow (band 118–123 mm); **L** fits large and short-wide (band 137–189 mm, pads ~10 mm lower and further back). The model rebuilds itself for any head (`EPIPROT_HEAD=...`) |

**Choosing the size** (user manual): measure the head circumference just above the eyebrows and the ears:
under 52 cm → S, 52–56 cm → M, over 56 cm → L. Then check on the head: with the hooks resting on the ears, the pads
must sit on the bone just behind the ear, not on the ear and not on the neck; if not, try the other size.

**Staying on.** It can only come off if hooks or band are forced over the ear or the back of the head:
down = carried by both hooks; forward = band behind the neck; backward/up = both hooks must lift (10.8 N);
sideways = far hook must lift (5.9 N, the weakest). Inertial load of the 58 g device: walking 0.85 N, running or
convulsion (3 g) 1.7 N, safety factor 3.4; fall with the head hitting the bed (6 g) 3.4 N, factor 1.7. The clasp
(5 N) stays shut under all of these (largest pull 1.7 N) but opens before a snag can drag the hooks off the
ears (10.8 N). The band is open at the front: it cannot form a loop around the neck.

**Scenarios and material choices**

| Scenario | Risk | Answer in the design |
|---|---|---|
| Sweat, rain, washing the face | water in the electronics, corrosion | carriers sealed and overmoulded (IP67 target); gold-plated charging contacts; 316L steel pad snaps |
| Nickel allergy | rash | no nitinol: nickel-free beta-titanium, fully inside silicone; skin touches only medical-grade silicone (ISO 10993) and the pads |
| Lying on the back / side | pressure, pain, waking up | pods placed by calculation (0 mm pillow contact); thin band at the nape; module and hook in soft silicone (Shore 30A) |
| Convulsion, fall | device flies off, data lost; part breaks | stays on up to 3 g with factor 3.4; clasp holds; PC carriers; protected LiPo with swelling room |
| Snag on a bed rail or a hand | pull on the ears or neck | clasp opens at 5 N; open at the front, no loop around the neck |
| Bent, sat on, children | permanent bend, broken cable | wire stays below its yield even when opened to put on; flex cable in a serpentine layout on the band's neutral axis |
| Hair | bad contact | pads on the mastoid behind the ear, where there is almost no hair |
| Glasses | hook and temple on the same ear root | flat 4 mm hook sits next to a temple; to be checked on people |
| Pad change, charging | handling | snap-on pads; magnetic pogo contacts at the bottom of the battery pod |
| MRI, X-ray | metal | take the headband off (not MRI-safe) |

**Manufacturing.** Production: injection-moulded PC carriers, beta-titanium wire bent and inserted, liquid
silicone overmould. Prototype: carriers 3D-printed (PA12 or tough resin; `cad/export/carrier_*.stl`), wire bent
cold (beta-titanium needs no heat treatment, unlike nitinol), silicone cast in 3D-printed moulds made from
`cad/export/side_body_*.stl` / `nape_band.stl` (or a direct TPU 85A print for a fit test).

**Not verified (needs a real prototype):** signal quality of the pads on the mastoid, the clamping force with a
force gauge, comfort overnight, the fit on real people (the NIOSH heads have no hair or glasses).

## Cost estimate [EST]

| Part | USD |
|---|---|
| MDBT50Q radio module | 10–12 |
| ADS1299-4 | 25–32 |
| ICM-42688-P | 3–5 |
| 8 MB flash, crystals | 2 |
| Power supply, charger, protection, passive parts | 3–4 |
| LiPo 700 mAh | 3 |
| Shielded cables, strain relief | 2 |
| Circuit board and assembly | 5–7 |
| Beta-titanium wire, carriers, silicone overmould, snap studs, clasp magnets, charging cable | 7–10 |
| **Total** | **~60–77** |
| Running cost: semi-dry pads | a few pads every few days |

## Open points

Done: packet format, Bluetooth services, reconnect and passkey pairing (PROTOCOL.md); backup channels 3 and 4,
movement conversion (D14) and slot placement (D13) on the phone; mechanical design and 3D model (D16–D19);
switching on / off (D20).

| Point | Step |
|---|---|
| Circuit board, firmware (Zephyr / nRF Connect SDK) | Prototype |
| Movement sensor on the side of the neck vs. SeizeIT2's at the back of the neck (worth 5 of 55 seizures) | Recordings with the real headband |
| Pad signal quality behind the ear, clamping force with a force gauge, overnight comfort, fit on real people | Prototype tests |
| IEC 60601-1 / -1-2 / -1-11, ISO 10993, IEC 62133, IP67 | Certification tests (docs/EpiProt-uygulamaya-gecis-yapilacaklar.md 2.6) |
| Exact prices | Check with distributors |
