# Automations and voice

Bus Monitor doesn't speak by itself. It fires an event for each alert, and an automation decides
where the words go. Each sample below is one paste away from working.

**How to paste an automation:**
1. Settings → Automations & scenes → **Create automation** → **Create new automation**.
2. Top-right ⋮ menu → **Edit in YAML**.
3. Select everything, replace it with the sample, change the values listed, and **Save**.

**How to paste a script:** the same steps from the **Scripts** tab (**Create script**).

**Finding the values to change:**

| Value | Where to find it |
|---|---|
| `profile` | Bus Monitor → the profile's ⋮ menu → **Reconfigure** → **Edit the profile**. The screen shows `profile: ...`. It's usually the profile name in lowercase with underscores. |
| TTS entity (`tts.…`) | Settings → Voice assistants, or Developer tools → States, filtered by `tts.` |
| Speaker (`media_player.…`) | Developer tools → States, filtered by `media_player.` A speaker group announces in every room. |
| Echo (`notify.…_speak` / `notify.…_announce`) | The **Alexa Devices** integration creates these. Developer tools → States, filtered by `notify.` |

Test an alert without waiting for the bus: Developer tools → Events → **Fire an event**, event type
`bus_monitor_alert`, with this data:

```yaml
kind: checkpoint
profile: morning
bus: Bus 12
message: Bus 12 is about 10 minutes away.
```

Don't test with an automation's **Run** button: it has no alert to read, so the message is empty.

## Announcements

### Every alert on Google Home / Nest speakers
```yaml
alias: Bus alerts on speakers
description: Speaks each bus alert.
mode: queued
triggers:
  - trigger: event
    event_type: bus_monitor_alert
actions:
  - action: tts.speak
    target:
      entity_id: tts.google_translate_en_com
    data:
      media_player_entity_id: media_player.kitchen_speaker
      message: "{{ trigger.event.data.message }}"
```

### One profile only, without "running late"
Use this pattern to choose which alerts are spoken. `kind` is `checkpoint`, `arrived`, `late` or
`offline`.

```yaml
alias: Morning bus alerts on speakers
description: Speaks checkpoint and arrival alerts for one profile.
mode: queued
triggers:
  - trigger: event
    event_type: bus_monitor_alert
    event_data:
      profile: morning
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.kind in ['checkpoint', 'arrived'] }}"
actions:
  - action: tts.speak
    target:
      entity_id: tts.google_translate_en_com
    data:
      media_player_entity_id: media_player.kitchen_speaker
      message: "{{ trigger.event.data.message }}"
```

### Every alert on an Amazon Echo
Needs the built-in **Alexa Devices** integration. Use the `_announce` entity for a chime first, or
`_speak` for no chime.

```yaml
alias: Bus alerts on Echo
description: Announces each bus alert on an Echo.
mode: queued
triggers:
  - trigger: event
    event_type: bus_monitor_alert
actions:
  - action: notify.send_message
    target:
      entity_id: notify.kitchen_echo_announce
    data:
      message: "{{ trigger.event.data.message }}"
```

### Every alert on a phone
Change `notify.mobile_app_my_phone` to your phone's action, listed under Developer tools → Actions.

```yaml
alias: Bus alerts on phone
description: Sends each bus alert to a phone.
mode: queued
triggers:
  - trigger: event
    event_type: bus_monitor_alert
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: School bus
      message: "{{ trigger.event.data.message }}"
```

## "Where is the bus?" by voice

The answer sounds like: *"Bus 12 is on Oak Avenue between 3rd Street and 5th Street, heading north,
about 0.8 miles from your stop, roughly 6 minutes away."*

| Assistant | Who speaks the answer | Needs |
|---|---|---|
| Assist (Home Assistant's own) | The device you asked | Nothing extra |
| Google | The speakers listed in the script, in a TTS voice | Home Assistant Cloud or a manual Google project |
| Alexa | The Echo listed in the script | Home Assistant Cloud or a manual Alexa skill, plus Alexa Devices |

Google and Alexa can't read an answer back from Home Assistant, so your phrase runs a script and
the script does the talking. A script can't tell which speaker you spoke to, so it always uses the
speakers you list.

### Assist
Paste this automation, then ask "where is the bus" from a voice device or the Assist button.

```yaml
alias: Assist - where is the bus
description: Answers "where is the bus" in Assist.
mode: single
triggers:
  - trigger: conversation
    command:
      - "where is the bus"
      - "where's the bus"
actions:
  - action: bus_monitor.describe_location
    data:
      profile: morning
    response_variable: bus
  - set_conversation_response: "{{ bus.text }}"
```

### "Hey Google, where is the bus?"
1. Paste this script:

```yaml
alias: Where is the bus
description: Says where the bus is on the speakers.
icon: mdi:bus-school
mode: single
sequence:
  - action: bus_monitor.describe_location
    data:
      profile: morning
      tts_entity: tts.google_translate_en_com
      media_player_entity:
        - media_player.kitchen_speaker
```

2. Open it and press **Run** to check you hear the answer.
3. Expose it to Google: Settings → Home Assistant Cloud → Google Assistant, or use a manual Google
   Assistant project. Say "Hey Google, sync my devices". Scripts appear in Google as **scenes** and
   don't show on the main Google Home dashboard.
4. **Assign the script to an area.** Other members of your Google household can't use it otherwise.
5. In the Google Home app, create a **Household** routine. Set the starter to the voice phrase
   `where is the bus` and the action to run the **Where is the bus** scene.

### "Alexa, where is the bus?"
1. Set up the **Alexa Devices** integration, then paste this script:

```yaml
alias: Where is the bus (Alexa)
description: Says where the bus is on an Echo.
icon: mdi:bus-school
mode: single
sequence:
  - action: bus_monitor.describe_location
    data:
      profile: morning
    response_variable: bus
  - action: notify.send_message
    target:
      entity_id: notify.kitchen_echo_speak
    data:
      message: "{{ bus.text }}"
```

2. Open it and press **Run** to check you hear the answer.
3. Expose it to Alexa: Settings → Home Assistant Cloud → Alexa, or use a manual Alexa skill.
4. In the Alexa app, create a routine. Set the trigger to the voice phrase `where is the bus` and the
   action to run the script from your smart home devices.

Menu names in the Google Home and Alexa apps change often. If a step looks different, look for the
option that runs a scene or script from a spoken phrase.

## Alert data

Every `bus_monitor_alert` event carries:

| Field | Meaning |
|---|---|
| `message` | The sentence to speak. Use this unless you want your own wording. |
| `kind` | `checkpoint`, `arrived`, `late` or `offline` |
| `type` | For checkpoints: `time` or `street` |
| `bus`, `profile`, `profile_name`, `device_id` | Which bus and profile |
| `label`, `minutes`, `street` | The checkpoint's name, minutes and street |
| `time`, `latitude`, `longitude` | When and where |
| `checkpoint`, `due`, `minutes_late` | Late alerts: the missed checkpoint and how late |

## Notes
- Street names come from OpenStreetMap and are cached along the route. If a lookup fails, the answer
  still works but doesn't name the street.
- "Minutes away" uses the last checkpoint the bus passed and its recorded timings, or the
  checkpoint's nominal minutes until there are recorded trips.
- These samples work the same with every provider.
