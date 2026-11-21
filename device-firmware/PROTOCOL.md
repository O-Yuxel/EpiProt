# EpiProt headband: Bluetooth LE protocol

**Status:** specification, version 1.1 (1.1 adds the contact check). Hardware: see [HARDWARE.md](HARDWARE.md).

## Summary

| | |
|---|---|
| Link | Bluetooth LE 5, 2 Mbit/s radio mode, long-range mode as fallback, MTU 247 |
| Security | Encrypted and bonded (LE Secure Connections, 6-digit passkey from the user manual in the box). Only the paired phone is accepted. |
| Data | One notify characteristic carries EEG, movement and status packets |
| Rate | 16 EEG + 5 movement + 1 status packets/s, about 3.7 KB/s |
| Delay | Sample to phone in under 0.2 s (the phone allows 2 s) |
| No data loss | Every packet has a sequence number. The phone confirms what it received; anything not confirmed is kept (RAM, then 8 MB flash, about 40 minutes) and sent again after a reconnect. |
| Timing | EEG samples are counted at exactly 256/s; every packet also carries the headband's crystal clock, so EEG, movement and the watch line up on the phone |

## Design rules

| # | Rule | Why |
|---|---|---|
| P1 | **Raw values, no processing on the headband** | The phone converts to µV, g and °/s with constants the headband reports. Nothing on the headband can change the data in a way the model did not see in training. |
| P2 | **Every sample is numbered** | The phone can tell exactly which samples are missing and marks them as missing, never guesses. Missing data is something the phone already handles (backup models, sensor warnings). |
| P3 | **Live data first, catch-up data second** | After a reconnect, detection needs the newest data at once. Stored data follow in the background; they fill the model's memory of the recent past and the recorded alarm signals. |
| P4 | **Nothing is deleted before the phone confirms it** | A sudden disconnect never loses the last seconds in flight. |
| P5 | **Everything encrypted, one bonded phone** | Health data; nobody nearby can read or inject data. |
| P6 | **Versioned** | The phone reads the protocol version and refuses an unknown major version instead of misreading the data. |

## GATT layout

Base UUID `e0b1xxxx-279b-48d0-a8ab-c8630521d53c`.

| Service / characteristic | UUID | Properties | Content |
|---|---|---|---|
| **EpiProt Headband service** | `e0b10001-…` | | |
| Data | `e0b10002-…` | Notify | EEG, movement and status packets (below) |
| Control | `e0b10003-…` | Write | Commands from the phone (below) |
| Device info | `e0b10004-…` | Read | Versions and conversion constants (below) |
| Battery Service (standard) | `0x180F` | Read, Notify | Battery % for the phone's system settings |
| Device Information (standard) | `0x180A` | Read | Manufacturer, model, serial, firmware revision |

All EpiProt characteristics require an encrypted, bonded link.

## Packets on the Data characteristic

All numbers are little-endian. Every packet starts with the same 6-byte header:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `type`: 0x01 EEG, 0x02 movement, 0x03 status, 0x04 contact check |
| 1 | 1 | `flags`: bit 0 = catch-up (stored) data, bit 1 = EEG measured during a contact check (not for the model), bits 2–7 reserved (0) |
| 2 | 4 | `seq`: packet number, +1 for every packet of any type, never reused within a session |

### EEG packet (type 0x01), 208 bytes, 16 per second

| Offset | Size | Field |
|---|---|---|
| 6 | 4 | `sample_index` of the first sample: counts EEG samples since power-on, exactly 256 per second |
| 10 | 4 | `t_dev`: headband clock at the first sample, 1/32768 s ticks (32.768 kHz crystal) |
| 14 | 1 | `n`: samples per channel in this packet (16) |
| 15 | 1 | `lead_off`: bit per electrode, 1 = no contact. Bit 0 L-top, 1 L-bottom, 2 R-top, 3 R-bottom, 4 bias |
| 16 | 192 | Samples: for each of the 16 time points, channels 1–4 as signed 24-bit ADC codes (3 bytes each) |

Conversion on the phone: **µV = code × `eeg_lsb_nV` / 1000**. With gain 12 and the 4.5 V reference
`eeg_lsb_nV` = 44.7 (9 V / 12 / 2^24). A code at the 24-bit limit (±8 388 607/8 388 608) means the
input saturated; the phone treats the sample as bad.

Channels: 1 = L-top − L-bottom (model input "left same-side"), 2 = L-top − R-top (model input
"cross-head"), 3 = R-top − R-bottom (backup), 4 = L-bottom − R-bottom (backup).

### Movement packet (type 0x02), 71 bytes, 5 per second

| Offset | Size | Field |
|---|---|---|
| 6 | 4 | `t_dev` of the first sample (1/32768 s ticks) |
| 10 | 1 | `n`: samples (5, at 25 Hz) |
| 11 | 60 | Samples: for each time point acc x, y, z and gyro x, y, z as signed 16-bit raw values |

The motion sensor is clocked from the radio crystal (HARDWARE.md, D13), so it samples at exactly
25 Hz; `t_dev` places the samples on the EEG timeline and the phone puts each one in its 25 Hz slot
without resampling.
Conversion: g = raw / `acc_lsb_per_g`, °/s = raw / `gyr_lsb_per_dps` (from Device info). Axes: x to
the right ear, y to the front, z up, when the band is worn.

### Status packet (type 0x03), 26 bytes, once per second and at once on any change

| Offset | Size | Field |
|---|---|---|
| 6 | 4 | `t_dev` |
| 10 | 2 | Battery voltage, mV |
| 12 | 1 | Battery % |
| 13 | 1 | State bits: 0 charging, 1 charger attached (EEG off), 2 streaming, 3 low battery |
| 14 | 1 | `lead_off` (as in the EEG packet) |
| 15 | 1 | Pod temperature, °C (signed) |
| 16 | 4 | Stored packets not yet confirmed by the phone |
| 20 | 2 | Error bits: 0 EEG saturation in the last second, 1 motion-sensor FIFO overflow, 2 flash full (oldest data overwritten), 3 restarted after watchdog, 4 restarted after low voltage, 5 EEG chip not responding, 6 motion sensor not responding |
| 22 | 4 | Uptime, seconds |

### Contact check packet (type 0x04), 20 bytes, every 10 minutes

Every 10 minutes the EEG chip sends a tiny 64 Hz current (6 nA) through each electrode for 2 s and
measures the contact impedance (HARDWARE.md, D15). The EEG packets of those 2 s carry flag bit 1 and
the phone leaves them out of detection. The result follows in one packet:

| Offset | Size | Field |
|---|---|---|
| 6 | 4 | `t_dev` at the end of the check |
| 10 | 10 | Contact impedance in kOhm, u16 each: L-top, L-bottom, R-top, R-bottom, bias. 0xFFFF = no contact |

The phone asks the patient to replace a pad when its impedance is above 150 kOhm or it has no contact.

## Commands on the Control characteristic

| Byte 0 | Command | Payload | Effect |
|---|---|---|---|
| 0x01 | START | none | Start streaming (default after connecting and bonding) |
| 0x02 | STOP | none | Stop streaming; sensors sleep |
| 0x03 | ACK | `seq` u32 | Phone has received everything up to and including `seq`; the headband may free it |
| 0x04 | RESEND | `from_seq` u32, `to_seq` u32 | Send these packets again (after a gap the phone noticed) |
| 0x05 | IDENTIFY | none | Blink the LED for 5 s, so the patient can tell which band is connected |
| 0x06 | STATUS | none | Send a status packet now |
| 0x07 | CONTACT_CHECK | none | Run a contact check now (e.g. right after the patient replaced pads) |

The phone sends ACK every 5 seconds.

## Device info (read)

| Field | Size | Value in version 1 |
|---|---|---|
| Protocol version, major / minor | 1 + 1 | 1 / 1 |
| Firmware version | 3 | major, minor, patch |
| Serial number | 8 | |
| EEG sample rate, Hz | 2 | 256 |
| EEG channels | 1 | 4 |
| `eeg_lsb_nV` | 4 (float32) | 44.7 |
| Movement rate, Hz | 1 | 25 |
| `acc_lsb_per_g` | 2 | 4096 (±8 g range) |
| `gyr_lsb_per_dps` | 4 (float32) | 16.4 (±2000 °/s range) |
| Electrode layout version | 1 | 1 (layout in HARDWARE.md) |

The conversion constants come from the headband, not from the phone app, so a later headband with
other settings needs no app change (rule P1).

## How it works over time

### Pairing (once)

1. In the phone app the patient taps "Connect headband" and holds the band's button for 2 s.
2. The phone finds the band, the patient types the 6-digit passkey printed in the user manual that
   comes in the box (or scans the QR code next to it). The headband has no screen, so the passkey
   comes from paper; it is not on the device itself.
3. The link is encrypted and both sides store the bond. From now on the band only accepts this
   phone. Holding the button for 10 s deletes the bond (new phone).

### Connection settings

| Setting | Value | Why |
|---|---|---|
| Radio mode | 2 Mbit/s; long-range (Coded) if the signal is weak and the phone supports it | Less radio-on time; long range keeps the link through the body at night |
| ATT MTU / data length | 247 / 251 bytes | One EEG packet fits in one radio packet |
| Connection interval | 30–50 ms | One or two packets per interval; low power |
| Supervision timeout | 4 s | A real disconnect is noticed quickly, short dropouts survive |

Throughput needed is about 3.7 KB/s; the link can carry well over 50 KB/s, so a backlog of 40
minutes is caught up in a few minutes.

### Disconnect and reconnect

1. The link drops (phone out of range, Bluetooth off, phone restart).
2. The headband keeps sampling. Unconfirmed packets stay in RAM (about 30 seconds) and spill into
   the 8 MB flash (about 40 minutes). If the flash fills, the oldest data are overwritten and the
   "flash full" error bit is set.
3. The headband advertises, every 100 ms for the first 30 s, then every 1 s to save battery.
4. The phone reconnects by itself (background connection from the monitoring service).
5. The headband sends live packets immediately, and the stored packets with the catch-up flag in
   between.
6. On the phone, live packets go to detection. Catch-up packets arrive too late for detection
   windows; the phone rebuilds the past windows from them and (a) the detector replaces the stand-in
   values it used during the gap, so a seizure soon after the gap is detected as fast as without it,
   and (b) a running alarm recording gets the real signals for the doctor report.
   Not done yet: a seizure that started and ended entirely inside a gap is not detected afterwards.

### Time alignment

- **EEG** time comes from `sample_index`: exact, because the EEG chip runs from a crystal.
- **Headband clock to phone clock:** the phone records `t_dev` and its own arrival time for every
  packet. Radio delay only ever adds time, so the phone fits a line through the earliest arrivals
  (the lower edge). This gives the offset and the small drift between the two crystals without any
  extra messages, and lines up the headband with the watch data.

### Missing data

The phone looks at `seq` and `sample_index`. A gap that is not filled within 2 s by RESEND or
catch-up packets is marked as missing in the detection windows (rule P2). The phone's existing
signal check then decides between "brain signal weak", "head movement missing" or "headband
missing" and warns the patient as it does today.

## Timing budget

| Step | Time |
|---|---|
| Filling one EEG packet (16 samples) | 62.5 ms |
| Waiting for the next connection event | up to 50 ms |
| Radio and phone Bluetooth stack | ~20 ms |
| **Sample to phone** | **under 0.2 s** |
| Phone waits for late packets before closing a 5 s window | 2 s |

## Data rate

| Packet | Size × per second | Bytes/s |
|---|---|---|
| EEG | 208 × 16 | 3328 |
| Movement | 71 × 5 | 355 |
| Status | 26 × 1 | 26 |
| **Total** | | **~3.7 KB/s**, plus a little radio overhead |
