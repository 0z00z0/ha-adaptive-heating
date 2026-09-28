# Adaptive Heating

Room-by-room heating for Home Assistant. Each room gets a thermostat of its own, and a planner warms
it in time for the moment it is wanted.

[![HACS custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5.svg)](https://hacs.xyz/)
[![Home Assistant add-on](https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5.svg)](https://www.home-assistant.io/apps/)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-informational.svg)](LICENSE)

![The settings page, showing what each mode is worth in each room](docs/images/settings-page-modes.png)

The rooms and figures above are an example, not a live house.

## What it does

Two halves. The integration gives each room a thermostat and runs the heating. The add-on holds the
modes, the day's plan and the settings page. Install the integration first: the add-on drives the
thermostats the integration creates.

The integration:

- Builds a thermostat per room from that room's switched heaters and its own temperature sensors.
- Lets a room with no sensor of its own borrow a neighbouring room's reading.
- Stops heating while a window sensor says open.
- Refuses a heater another room already drives.
- Confirms a heater actually ran, in a room with a power meter.
- Offers five actions to automations: `warm_room_by`, `hold_temperature`, `set_warming_rate`,
  `set_regulation` and `return_to_target`.

The add-on:

- Holds five modes — away, night, home, boost and day profile — and what each is worth in each room.
- Moves every room at each boundary of the day's profile.
- Starts a warm-up early enough for a room to reach its temperature by a set time.
- Measures each room's warming rate and how hard it must fire to hold, and writes both back.
- Reads whether anybody is home from one Home Assistant dropdown.
- Warms the house ahead of an arrival in a calendar, and writes each finished warm-up to a second
  calendar as a record.

## Installing the integration

HACS has to be installed first. [hacs.xyz](https://hacs.xyz/) says how.

[![Open HACS and add this repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=0z00z0&repository=ha-adaptive-heating&category=integration)

The badge opens HACS with the repository filled in. Steps 1 and 2 do the same by hand.

1. Open HACS and choose **Custom repositories** from the menu in the top right.
2. Paste `https://github.com/0z00z0/ha-adaptive-heating`, pick **Integration** as the type, and select
   **Add**. Close the dialog.
3. Search HACS for **Adaptive Heating** and open it.
4. Select **Download**.
5. Restart Home Assistant. The integration is not available until the restart finishes.
6. Go to **Settings → Devices and services → Add integration** and pick **Adaptive Heating**.
7. Fill in the dialog and submit it. That adds one room, which appears as a `climate` entity named
   after it.

Repeat steps 6 and 7 for every further room.

## Installing the add-on

The add-on needs the Supervisor. A Home Assistant Container install has no app store and cannot run it.

[![Add this add-on repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2F0z00z0%2Fha-adaptive-heating)

The badge opens the store with the repository filled in. Steps 1 and 2 do the same by hand.

1. Go to **Settings → Apps** and select **Install app**. Home Assistant calls the same two things
   **Add-ons** and **Add-on store** on an older install.
2. Choose **Repositories** from the menu in the top right, paste
   `https://github.com/0z00z0/ha-adaptive-heating`, select **Add**, and close the dialog.
3. Reload the store page. A card for this repository appears, holding **Adaptive heating**. Open it.
4. Select **Install**. The Supervisor builds the add-on on the box rather than pulling a ready-made
   image, so the install is not instant.
5. Open the **Configuration** tab and name the presence dropdown, the outdoor temperature sensors, and
   a weather entity to fall back on when every outdoor sensor is out. All three are optional. Save. The
   presence dropdown is any entity offering a list of options, usually an `input_select` helper. Create
   one under **Settings → Devices and services → Helpers** first.
6. Back on the **Info** tab, turn on **Show in sidebar** and **Watchdog**. Both start off. The sidebar
   entry is the only way to the settings page, and the watchdog restarts the add-on when its page
   stops answering.
7. Select **Start**.
8. Open **Heating** in the sidebar. The page is for administrator accounts only.

## Setting it up

**A room needs at least one heater.** Any `switch` or `input_boolean` will do, and one control loop
runs per heater. Everything else in the dialog is optional: the room's own temperature sensors, a
neighbour to borrow a reading from, a window sensor, an outdoor sensor and a power meter.

**Type a temperature against each mode before expecting one to hold.** The mode table on the **Modes**
tab starts empty, and a room whose mode carries no temperature keeps whatever target it already had.
Fill the table room by room.

A room set up with no sensor of its own and no neighbour to borrow from is switched on and off
instead. Its away cell starts on and every other cell off, because the dial on the heater is the only
frost protection such a room has.

**Check the presence rows.** The add-on reads whether anybody is home from one Home Assistant
dropdown, and one row per option says what that option means. The rows are seeded once, at set-up,
from the option text, against a vocabulary of English and Norwegian words. An option renamed later
keeps the state it was mapped to, so change the text on the **Presence options** tab to match.

Three states carry no word in the vocabulary — planned to arrive, on the way, and temporarily away —
so an option meaning one of those lands on the wrong row and has to be put right by hand. An option
the words cannot place is left unmapped, and an unmapped option reads as somebody being home, which is
the expensive answer.

**Two calendars, both optional**, on the **Calendars** tab. One holds arrivals: an entry with a start
time warms every room to its home temperature in time for it, and an all-day entry is skipped. Any
calendar will do. The other holds the record, one entry per finished warm-up, and must be a calendar
Home Assistant keeps itself.

## Requirements

| What | Value |
|---|---|
| Home Assistant core | Tested on 2026.9.3 |
| Supervisor, for the add-on | Tested at 2026.09.3 |
| Board, for the add-on | `aarch64` or `amd64`. A 32-bit board is not covered |
| HACS, for the integration | Any version that takes a custom repository |

## Where to find the rest

| Path | Holds |
|---|---|
| `docs/how-it-behaves.md` | What each mode is for, why a heater cycles, what a room does when a sensor fails, and what a notification means |
| `adaptive_heating/README.md` | The add-on's manifest, and what survives an update |
| `custom_components/adaptive_heating/` | The integration |
| `addon/` | The add-on's source. `AdaptiveHeating.slnx` is the solution |
| `LICENSE` | MIT |
