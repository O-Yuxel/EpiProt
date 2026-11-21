# Privacy and consent in the EpiProt phone app

**Status: draft.** The texts must be reviewed by a lawyer (and the data controller and contact filled in) before real
use. This is not legal advice.

## Rules followed

| Rule | Source | In the app |
|---|---|---|
| Health data are special-category data; processing needs explicit consent (or another art. 6(3) ground) | KVKK art. 6 (as amended by Law 7499, 2024), GDPR art. 9 | `HEALTH_DATA` consent; without it nothing is processed and monitoring cannot start |
| Information (privacy notice) before processing, covering the art. 10 points | KVKK art. 10, Communiqué on the obligation to inform | Setup step 3 + Settings → Privacy & consents → Privacy notice |
| Notice and consent must be separate texts; reading the notice is not consent | KVKK Board principle decision 2026/347 (Official Gazette 24.03.2026) | Notice step only has "I have read it, continue", labelled "this is not a consent"; consents are separate screens |
| Consent: specific, informed, freely given; each purpose separately; nothing pre-selected | KVKK art. 3, GDPR art. 4(11), 7 | One screen per consent, equal "I agree" / "I do not agree" buttons, consequences of both answers shown |
| Transfer of health data to third persons (caregivers) needs consent | KVKK art. 8 | Separate `CAREGIVER_SMS` consent + per-caregiver "agreed" confirmation |
| Withdrawal at any time, as easy as giving | GDPR art. 7(3), KVKK | Settings → Privacy & consents → each consent → Withdraw (confirmation shows the consequences) |
| Proof of consent | GDPR art. 7(1), KVKK (burden of proof on the controller) | Consent history: every decision with time, text version and the person deciding |
| Rights: information, copy, correction, erasure | KVKK art. 11, GDPR art. 15–20 | Download my data (JSON in Downloads), Delete all my data, editable settings |
| Children: the legal representative consents; the child can ask for withdrawal | Turkish Civil Code, KVKK practice, GDPR art. 8 | "Who is setting up" step: patient 18+, parent, legal guardian |
| Prominent in-app disclosure before sensitive permissions; a way to decline; back / leaving is not consent | Google Play User Data and Health apps policies | Permission step explains each permission before Android asks; only permissions of agreed features are requested; no permission is requested at app start |
| SEND_SMS is a restricted permission on Google Play | Play SMS/Call Log policy ("physical safety / emergency alerts" exception) | To do before publishing: permissions declaration form, or send through the default SMS app |

## Countries / regions

The first setup step asks where the patient lives (guessed from the SIM / network / locale country, the user
confirms). It decides the texts (`assets/legal/texts_<region>_<language>.json`) and the emergency number used in the
emergency SMS. The consent model, the screens and the gates are the same everywhere.

| Region | Texts based on | Emergency | Specifics |
|---|---|---|---|
| Türkiye | KVKK (art. 5, 6, 8, 10, 11; Law 7499; Board decision 2026/347) | 112 | Turkish and English texts |
| EU / EEA, UK, Switzerland | GDPR (art. 6, 7, 8, 9, 15–22) | 112 | child = under 16 (or the national age, min. 13); complaint to the national supervisory authority |
| United States | FTC Act s.5, FTC Health Breach Notification Rule, state consumer-health laws (Washington My Health My Data Act, Nevada, Connecticut), state privacy laws for sensitive data (CA, CO, VA, TX ...), COPPA | 911 | "consent to collect" and separate "consent to share"; no sale, no advertising; HIPAA statement (generally not applicable to a direct-to-consumer app); FDA statement (not cleared); **patient under 13: parent signs a parental consent (COPPA)**, monitoring stays off without it |
| Another country | GDPR texts (strictest common baseline) | "your local emergency number" | the user is asked to check the local law |

US to do before a public release: an FTC-approved method to verify the parent (COPPA; the prototype records a typed
signature), a separate consumer-health-data privacy policy linked from the store page (Washington), and review by a
US attorney. Turkish-language US texts are not written (the English ones are shown).

## The consents

| Consent | Needed? | If given | If not given |
|---|---|---|---|
| Processing health data to detect seizures | for monitoring | monitoring can run, records kept, sensor warnings | monitoring cannot start; only demo and information screens; home screen shows "Monitoring needs your consent" |
| SMS to caregivers in an alarm | optional (recommended) | caregivers who agreed get the alarm messages | alarm only on phone and watch; permanent "caregivers will not be alerted" card; SMS permission is not requested |
| Location in the alarm SMS | optional, only with the SMS consent | location read once at an alarm and added as a map link | SMS say "location not shared"; the location is never read; no location permission requested; the foreground service does not use the location type |
| Signals around each alarm (2 min before – 5 min after), for the doctor report | optional, only with the health-data consent | EEG, movement and heart rate around alarms kept encrypted (max. 12 months) and shown as graphs in the doctor report | nothing is kept; the report has no graphs; withdrawing deletes every stored signal |
| Anonymised data for research | optional, off by default | nothing today (no data leave the phone); you may be asked in detail if a study starts | nothing changes |

Acknowledgements (not consents): the privacy notice was shown; the limits were read and understood (not a medical device,
can miss seizures, call 112 in an emergency).

## Protection of the stored data

* **Encryption at rest:** the event log is an SQLCipher database (AES-256); its random passphrase and the personal
  settings (patient name, caregiver numbers, doctor e-mail, the person deciding, the COPPA signature, the consent
  history) are encrypted with an AES-256-GCM key in the Android Keystore (`privacy/Vault.kt`). Older plaintext logs
  are converted once.
* **No backups / device transfer:** `allowBackup=false` and `data_extraction_rules.xml` (phone and watch).
* **App lock:** History and Settings open only with the phone's screen lock / fingerprint (on by default when the
  phone has a screen lock); alarms always show on the home screen.
* **Data in transit, headband:** Bluetooth LE with LE Secure Connections; the headband is bonded once with the
  6-digit passkey from its user manual, so only this phone can connect, nobody nearby can read the brain signals and
  nobody can inject fake data (`device-firmware/PROTOCOL.md`). The second-phone test headband used in development
  cannot bond; the button to connect it without encryption appears only in development (debug) builds.
* **Caregiver mode and replies:** on a caregiver's phone EpiProt reads only SMS ending with an EpiProt tag
  ([EP:x]) from the patient numbers entered there; on the patient's phone it reads only the "I am going" tag
  ([EP:C]) from the caregiver numbers entered there. Every other SMS is ignored and nothing is stored from it.
* **Watch:** the phone tells the watch whether the consent allows monitoring; without it the watch does not run its
  sensors (off until the phone says yes) and shows why.

## Scenarios

1. **First start:** the setup is shown before anything else; no sensor data are processed and no permission is requested
   before it. Leaving the app keeps the answers given so far; back goes to the previous step and is never a decision.
2. **Health-data consent declined:** a dialog repeats the consequences ("go back" / "continue without monitoring").
   The app works in limited mode (demo, texts, settings).
3. **SMS consent declined:** alarms are shown only on the phone and the watch; messages are logged as "not sent (no SMS
   consent)". The location step is skipped and recorded as not given.
4. **SMS consent given but a caregiver not marked as agreed:** that number gets nothing ("not sent (caregiver not
   confirmed)"); the home checklist shows it.
5. **Location consent declined:** SMS without a location.
6. **A consent is withdrawn:** takes effect immediately and is recorded; withdrawing the health-data consent stops the
   monitoring service at once. Data already recorded stay until deleted.
7. **Change during an alarm or the post-seizure follow-up:** blocked for safety, with an explanation.
8. **Texts change (new `TEXT_VERSION`):** the setup is shown again and every decision asked again.
9. **The patient turns 18 / a new guardian:** Privacy & consents → "Change who decides / do the setup again".
10. **Delete all my data:** two-step confirmation; stops monitoring and erases events, messages, sensor warnings,
    settings, PIN and consents with their history; the setup starts again. SMS already sent cannot be recalled.
11. **Download my data:** one JSON file in Downloads (settings, consents and history, the whole log).
12. **App uninstalled / new phone:** all data are on the phone only; nothing is transferred; the setup runs again.
13. **Permission refused in Android:** the related feature does not work; Settings → Phone permissions shows each state
    and opens the system page when a permission was refused for good.
14. **Doctor report (History → "Send a report to my doctor"):** the patient chooses the period (since the last
    report, 30 days, 3 months, everything; demo events only if switched on), sees what is and is not shared
    (shared: name, period, each alarm with type / duration / PIN / caregiver alerted / > 5 min / answer, summary,
    charts, sensor problems; not shared: location, caregiver numbers, messages, consents, raw signals), can look at
    the PDF first, confirms, and sends it with any app (Android share sheet: WhatsApp, e-mail ...). Each sharing is
    its own decision and is recorded in the consent history; the PDF is a temporary file in the app's cache
    (FileProvider, read access only for the chosen app), replaced by the next report and removed by "Delete all".
    With the signals consent the report adds one page per alarm (newest 12) with the EEG, movement and heart-rate
    graphs from 2 min before to 5 min after the alarm, marking the estimated start, the alarm and the estimated end.
15. **Parent sets up for a child:** the patient's year of birth is asked; a plain-language page for the child follows
    ("please read this together"; also in Privacy & consents). When the child turns 18 the home screen asks for the
    setup to be done again by the patient.
16. **A caregiver is added (with the SMS consent):** they get one information SMS (who added them, what they will
    receive, how to opt out).
17. **Demo:** replays a recorded SeizeIT2 patient, works without the health-data consent; demo SMS follow the same SMS
    rules and are marked [DEMO].

## Where things are

* Code: `app/src/main/java/org/epiprot/phone/privacy/` (`Consents.kt`: model, rules, store, history;
  `LegalTexts.kt`), screens `ui/Onboarding.kt`, `ui/Privacy.kt`; gates in `comm/Comm.kt` (SMS, location),
  `PhoneMonitor.kt` (monitoring, delete, export), `service/MonitoringService.kt` (location service type).
* Texts (to be reviewed): `app/src/main/assets/legal/texts_tr_tr.json`, `texts_tr_en.json` (Türkiye),
  `texts_eu_en.json`, `texts_eu_tr.json` (EU and other countries), `texts_us_en.json` (US).
* Tests: `app/src/test/java/org/epiprot/phone/ConsentTest.kt`.
