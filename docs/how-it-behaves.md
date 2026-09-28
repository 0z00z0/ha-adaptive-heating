# How it behaves

What to expect from the heating once it is set up.

## The five modes

Every room runs the mode in force over the whole house.

| Mode | What it is for |
|---|---|
| Away | What the house stands at with nobody there. It is the frost protection, and nothing falls below it |
| Night | People there and asleep |
| Home | People there and awake. A calendar arrival warms to this one |
| Boost | A warmer spell, chosen on the settings page |
| Day profile | Hands the day to the periods on the **Day profile** tab, chosen on the settings page |

A mode is a name. What it is worth in a room is the number typed against it on the **Modes** tab, and
there are no built-in temperatures anywhere.

## Presence, and a mode chosen by hand

The presence dropdown picks the mode, through the rows on the **Presence options** tab.

- Away, planned to arrive and no evidence either way all mean the away mode.
- Night means the night mode.
- Everyday, guest, temporarily away and on the way all mean the home mode. Re-warming a cold house
  costs more than holding a warm one, so a short absence stays warm.
- An option with no row of its own reads as everyday, so as home.
- Where no presence dropdown is named at all, every room holds its away temperature.

No presence state selects boost or the day profile. Those two are reached only by choosing a mode on
the **Mode now** tab.

A mode chosen by hand wins over the one presence picks, and only until the hours it was given run out.
Then presence answers again on its own. The field starts at 12 hours, the shortest choice is 1 hour and
the longest a week. Nothing has to be cleared, so a house left behind is not heated until the next
visit.

Inside a room, a temperature set by hand stands until a schedule boundary or a mode change names a
different one. Saving the settings page replaces it. A running warm-up wins over everything, and an
unexpired hold comes next.

## Why a heater switches on and off

A paced room runs a fifteen-minute cycle and holds its heater on for part of it. How large that part
is follows how far the room is from its target and how cold it is outside. So the room climbs to its
target across several cycles instead of overshooting in one, and it settles a shade above the target
rather than below it.

A heater changes state at most once every five minutes. What one cycle can deliver is therefore a
third of it to two thirds: a smaller part is dropped to nothing, and a larger one is rounded up to the
whole cycle. A room asking for very little gets no heat at all, drifts down, and is answered once the
distance from its target is worth a cycle.

In Home Assistant the thermostat reads **Heating** while its heater is on and **Idle** while it is
off, so a room below its target reads Idle for part of every cycle. The settings page says the same
under a room's **Now**: what it reads, what it is told, and whether the heater is on.

A room set to a plain band switches at the edges of its band instead, with no cycle.

## When a sensor fails

A sensor leaves a room's average when it has been quiet for longer than the freshness window, when it
has held one value for hours, when it sits further from the room's other readings than the allowed
spread, or when it is the outlier among three or more. The reading is the average of what is left. All
four windows are on the **Rooms** tab.

A room that loses every reading keeps heating. It repeats the fraction of a cycle it was holding at
that temperature, for up to a day, and then falls back to 15 % of each cycle. A missing reading never
switches a heater off.

A room set up with no sensor of its own and no neighbour to borrow from is a different thing, and is
never reported as a fault. It is switched on and off, one state per mode, and nothing more. There is
no band, no cycle and no target, so Home Assistant's own set-temperature action is refused on it, as
are warming to a temperature by a time, holding a temperature, and setting the warming rate. It
reports no warming rate, because it can never measure one.

## Warm-ups, and the arrival calendar

A warm-up heats a room flat out to be at a temperature by a given time. The start is worked back from
the room's warming rate at the outdoor temperature expected, at four fifths of that rate, so a room
warming as fast as it has been arrives early rather than late. A room that cannot make its deadline
starts at once and heats anyway, and a notification says the temperature it will actually reach.

The arrival calendar is where a visit is written down. Every room is at its home temperature by the
start of an entry, whatever mode is in force. Entries are read a fortnight ahead and re-read every
quarter of an hour. An all-day entry is not an arrival and is skipped, because reading it as midnight
would heat the house a day early. Any calendar will do.

Each room's warming rate, its band and how hard it fires to hold are worked out from what the room
does, and each errs towards heating the room. Setting one by hand on the **Rooms** tab uses that value
instead. Clearing it hands back the number the measurements have reached in the meantime; resetting it
drops the measurements and starts again.

## The record calendar

One entry per finished warm-up: the room, when it ran, and whether it reached the temperature or fell
short. It has to be a calendar Home Assistant keeps itself. Nothing can take an entry out of a
calendar again, which is what makes it a record rather than a working note.

## What a notification means

The add-on raises a Home Assistant notification only for what it cannot put right itself. Each kind
replaces its own earlier notification rather than stacking a second one.

| Notification | What it means |
|---|---|
| A room cannot reach a temperature | The deadline cannot be made however early the room starts. The message says the temperature it will reach |
| Outdoor sensors all out | Every chosen outdoor sensor failed the check. The message says whether the forecast took over |
| Presence not recognised | The dropdown holds an option no row maps. The rooms read it as somebody being home |
| Arrival calendar missing | The calendar named in the settings is not in Home Assistant. No arrival is read |
| A warm-up was not recorded | The record calendar is unset or gone. The warm-up ran; nothing was written down |
| Household clock not set | The time zone did not resolve. Every time shown is wrong until it is put right |

A Home Assistant restart clears the notifications. Anything still true is raised again once the add-on
is talking to Home Assistant again.
