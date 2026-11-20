# EpiProt headband: hardware design

**Status:** designed on paper. No physical prototype is built in this project, so nothing here has
been measured on a real device. Sources are marked: **[DS]** datasheet, **[EST]** our estimate,
**[MODEL]** required by the detection model on the phone.

## Summary

| | Choice |
|---|---|
| Job | Measure and send. The phone runs detection, alarms and storage. |
| Electrodes | 4 semi-dry hydrogel pads behind the ears + 1 bias electrode at the nape |
| EEG front-end | TI ADS1299-4: 4 channels, 24-bit, EEG-grade (1 µV noise) |
| Sample rate | Exactly 256 samples/s per channel, the model's rate |
| Movement | Bosch BMI270, 3-axis accelerometer + 3-axis gyroscope, 25 Hz |
| Radio / processor | Raytac MDBT50Q module (Nordic nRF52840), Bluetooth LE 5, pre-certified |
| Backup memory | 8 MB flash, about 40 minutes when the phone is out of reach |
| Battery | 700 mAh rechargeable LiPo, about 2 days, magnetic charging |
| Data rate | About 3.7 KB/s ([PROTOCOL.md](PROTOCOL.md)) |
| Parts cost | About $58–74 per headband [EST] |

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
| D8 | **700 mAh battery** | The ADS1299-4 uses about 22 mW [DS], so the whole headband draws about 10 mA. 700 mAh gives about 2 days, comfortably above the 24-hour minimum. |
| D9 | **Kept: BMI270 motion sensor** | Good quality, runs at exactly the 25 Hz the model uses, ranges set so convulsions never clip. A better sensor would not change the data. |
| D10 | **Kept: Bluetooth integrity as designed** | Bluetooth already checks every packet and resends damaged ones. We add a sequence number and time stamp to every packet, so the phone sees any missing data. |
| D11 | **Pre-certified radio module** | No separate radio certification for the headband: less cost, less risk. |
| D12 | **No processing on the headband** | The phone already runs the model and has the watch data; the headband stays simple, which means fewer things that can go wrong. |

## Electrodes and channels

SeizeIT2, the data the model was trained on, recorded EEG with electrodes on the mastoid bone
behind the ears (two left, one right), giving "one left same-side channel and one cross-head
channel" (SeizeIT2 paper, arXiv 2502.01224). The headband keeps that layout and adds backups:

| Electrode | Position |
|---|---|
| L-top, L-bottom | Behind the left ear, upper and lower mastoid |
| R-top, R-bottom | Behind the right ear, upper and lower mastoid |
| Bias | Nape of the neck, under the electronics pod (drives the body to the amplifier's mid voltage, cancels mains hum) |

| Channel | Electrodes | Use |
|---|---|---|
| 1 | L-top − L-bottom | Model input: left same-side |
| 2 | L-top − R-top | Model input: cross-head |
| 3 | R-top − R-bottom | Backup: right same-side (SeizeIT2 used this for right-sided seizures) |
| 4 | L-bottom − R-bottom | Backup: second cross-head channel if L-top loses contact |

Using channels 3 and 4 as replacements needs a small change in the phone app; it is planned for
the phone integration step.

**Pads:** semi-dry hydrogel pads click onto the band's snap studs and are pressed onto the skin by
the band. The patient replaces them every few days. When a pad dries out, the EEG chip's lead-off
detection and the phone's signal check notice it and the phone asks the patient to replace the pad.

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

## Movement sensor: Bosch BMI270

3-axis accelerometer and 3-axis gyroscope, 16-bit, both at 25 Hz [DS]. Ranges ±8 g and ±2000 °/s,
so a convulsion never clips [EST]. About 0.42 mA at 25 Hz [DS, to confirm].

The phone converts g and °/s to the scale used in SeizeIT2 (see `Calibration` in the phone app).

> **Known difference from the training data.** In SeizeIT2 the recorder whose motion sensor gives
> the model's "head movement" input was worn **on the upper back**, with cables to the ear
> electrodes. The headband's motion sensor therefore sits in the pod **at the back of the head,
> close to the neck**, as near to that position as a headband allows. The phone has backup models
> that work without head movement if this input turns out to be unreliable.

## Radio and processor: Raytac MDBT50Q (Nordic nRF52840)

Arm Cortex-M4F, 1 MB flash, 256 KB RAM, Bluetooth LE 5 with 2 Mbit/s and long-range (Coded) radio
modes, up to +8 dBm [DS]. Pre-certified module (FCC, CE and others). A 32.768 kHz crystal keeps the
time stamps accurate.

## Power

| Part | Current from the battery | Source |
|---|---|---|
| ADS1299-4 (4.06 mA at 5 V via the boost converter, 0.54 mA at 3.3 V) | ~7.0 mA | [DS] + 85 % converter efficiency [EST] |
| BMI270 | ~0.45 mA | [DS] |
| nRF52840, streaming ~3.7 KB/s | ~1.0 mA | [EST] |
| Processing, regulators, clocks | ~0.3 mA | [EST] |
| **Total** | **~8.8 mA, ~10.5 mA with 20 % margin** | |

That is about 250 mAh a day, so **700 mAh lasts about 2 days**. Charging takes about 2 hours.
During charging the band is off the head and the phone keeps monitoring with the watch-only backup
models. The phone reminds the patient when the battery is low.

**Why rechargeable:** a coin cell cannot deliver 10 mA continuously, AAA batteries are too heavy
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

## Mechanical

Soft elastic band around the back of the head, above the ears. Two small arms behind the ears
carry the pad studs. The electronics pod sits at the back of the head near the neck (about
45 × 30 × 14 mm with the battery). Total weight target under 40 g [EST]. One button, one LED.
Sweat-resistant, not for showering.

## Cost estimate [EST]

| Part | USD |
|---|---|
| MDBT50Q radio module | 10–12 |
| ADS1299-4 | 25–32 |
| BMI270 | 2–3 |
| 8 MB flash, crystals | 2 |
| Power supply, charger, protection, passive parts | 3–4 |
| LiPo 700 mAh | 3 |
| Shielded cables, strain relief | 2 |
| Circuit board and assembly | 5–7 |
| Band, pod housing, snap studs, charging cable | 6–9 |
| **Total** | **~58–74** |
| Running cost: semi-dry pads | a few pads every few days |

## Open points

| Point | Step |
|---|---|
| Packet format, Bluetooth services, reconnect, security | BLE protocol |
| Phone use of backup channels 3 and 4 | Phone integration |
| Exact prices and the BMI270 25 Hz current | Check with distributors / datasheet |
