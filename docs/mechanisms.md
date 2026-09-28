# Mechanisms

How each half behaves, and where each number in it comes from. The specification is
`2026-09-24-1545-plan-division-of-work.md`, held outside this repository.

## The core takes numbers and returns numbers

Nothing in `addon/src/AdaptiveHeating.Planner/` reads a clock, opens a file, or names a Home
Assistant type. Every moment a calculation needs arrives as a parameter. That is what makes a learnt
value inspectable: it can be recomputed from its inputs at any time.

## Learning errs towards heating the room

Each learnt number has a safe end, and the safe end is the one that costs electricity rather than a
cold room.

| Number | Safe end | What the safe end does |
|---|---|---|
| The warming rate | Slower | Starts the warm-up earlier. |
| The outdoor part of the holding duty | Higher | Fires the room harder while it holds. |
| The band around the target | Narrower | Brings the heat back sooner. |

One rule covers all three. A measurement moving a number towards its safe end is taken on the spot.
A measurement moving it away is taken only after five in a row agree.

## The numbers, and which the specification states

Each lives in `PlannerDefaults`.

| Number | Value | Source |
|---|---|---|
| Fraction of the measured rate a warm-up is planned on | 0.8 | Stated: four fifths. |
| The smallest rise worth a warming-rate measurement | 0.5 degrees, 15 minutes | Chosen here. |
| The draw at which a heater counts as having run | 10 W | Stated. |
| How long a room must sit settled before its shortfall counts | 30 minutes | Chosen here. |
| Margin above the fitted outdoor holding term | 1.1 | Stated: a tenth above. |
| Outdoor holding term at the start | 0.005 of full output per degree | Stated: half a per cent per degree. |
| The band at the start | 0.5 degrees | Stated. |
| The band ceiling | 1.0 degrees | Stated: never widens past 1 degree. |
| Measurements in a row before a number moves away from its safe end | 5 | Stated. |
| How far a fresh reading may sit from the others in its room | 2.0 degrees | Stated, and settable per room. |
| How recently a room sensor must have reported | 1 hour | Chosen here. One hour is stated for an outdoor sensor and nothing for a room's own. |
| How long a reading may sit at one value before it reads as stuck | 6 hours | Chosen here. The specification says hours and names no figure. |
| How long a measurement takes to count for half | 30 days | Chosen here. The specification says recent measurements count for more and names no figure. |

## The warm-up arithmetic

A warm-up is planned on four fifths of the measured rate, so the planned duration is a quarter
longer than the rise should actually take. A room behaving as measured arrives with a fifth of the
planned time to spare, which is a quarter of the time the rise takes. The specification's sentence
naming a quarter of the planned time names the wrong one of the two.
`WarmUpPlan.SpareIfTheRoomBehavesAsMeasured` carries the figure the arithmetic gives.

A room that cannot make its deadline starts at once and heats anyway. The plan then carries the
temperature it will actually reach and how far short it falls, which is what the cannot-reach report
names.

## Estimating the warming rate at an outdoor temperature

The specification puts the rate in degrees per hour against the outdoor temperature and names no way
to turn a set of measurements into an estimate. What is built:

- With no measurements, the hand-set figure, reported as not measured.
- With measurements at fewer than two distinct outdoor temperatures, their recency-weighted mean.
- Otherwise a recency-weighted least-squares line through them, read at the outdoor temperature
  asked about.

The estimate is held to no more than the fastest rate ever measured in that room. A line
extrapolated past the weather it was fitted in must never promise a rate the room has never managed,
because a rate too high starts a warm-up too late.

## What a mode is worth in a room

A mode is a name. What it is worth in a room is the number typed against it on the settings page, and
no table of fixed temperatures exists anywhere. `ModeTable.For` answers with one instruction per room:
a temperature where the room has a reading, and on or off where it has none.

A room the integration reported for the first time has nothing typed against any mode, and nothing
here can invent a number for a house. Such a room is left alone until somebody types one.

A room with no reading at all starts with its away cell on and every other cell off, because the dial
on the heater is the only frost protection such a room has and a cabin left with the relay open has
none at all.

Which mode a presence state means is `Presence.ModeFor`. Away, planned to arrive and no evidence at
all mean the away mode; night means night; everyday, guest, temporarily away and on the way all mean
home, because re-warming a cold cabin costs more than holding a warm one. **No presence state selects
boost or the day profile**, so those two are reached only by a mode chosen on the settings page, which
holds for the hours it was given and then lets go.

**Where no presence helper is named, every room holds its away temperature.** That is the lean the
specification takes towards an empty cabin, and it is what a house with nothing configured will do.

## The day's profile against the clock

`DayProfile` places every entry on the household's own clock, sorts them, and answers which one is in
force and when the next boundary falls. Before the first boundary of the day, yesterday's last entry
is the one still running. A wall clock the spring-forward gap swallows arrives at the first minute
that does exist.

The placement, the wrap, the next-boundary walk and that spring-forward rule are taken from the
lighting engine's `CircadianCalculator`, and the clock-or-sun anchoring from its `PeriodStart`, both
read on 2026-09-24. **Its `PeriodTracker`, 466 lines, does not transfer**: it is bound to the lighting
host's Home Assistant context, its house-mode rules, its motion latch and its period select, none of
which heating has. The two copies drift, and a fault found in either is carried across by hand.

**A boundary's temperature is stamped with the moment the boundary arrived**, never with the moment
somebody edited the entry. That is what makes it replace a hand change made before it and stand aside
for one made after it. A mode's own temperature is stamped the moment the mode came into force
whenever the mode changes while the add-on is running, and with its typed stamp otherwise, so
re-asserting after a restart never overwrites a change made at a card while the add-on was away.

## The order a room's temperature is chosen in

A running warm-up wins outright. An unexpired timed hold comes next. Below those, the most recently
set of the mode temperature, the schedule boundary in force and a hand change wins, by the stamp
each carries.

That is what makes a hand change stand until the next boundary naming a different temperature, and
what makes saving the settings page replace it. A boundary is offered to the rule only while the
ordinary mode is in force, which is what keeps a slot silent under another mode.

Nothing clamps a temperature. The away mode's temperature is the frost protection and is not a
floor: a temperature set below it is accepted and reaches the room.

## The mode a person chooses, and when it lets go

A mode chosen on the settings page wins over the one presence selects, and only while it is unexpired.
`ModeByHand` carries the mode and the moment it ends, and `UnexpiredAt` is the whole rule — the same
shape as a timed hold on one room, which is the pattern it follows rather than a second one.

Both failures this avoids are real. A chosen mode that held until somebody cleared it heats the cabin
until the next visit whenever it is forgotten on the way out. A chosen mode that presence overruled at
once would make the day profile and boost unreachable, because no presence state selects either.

| Number | Value | Why |
|---|---|---|
| What the hours field starts on | 12 hours | An evening and a night, so a choice made on arrival lasts until morning. A choice forgotten on the way out costs half a day of heating and not a week. |
| The shortest a choice may be given | 1 hour | Below that the pass a minute is most of the life of the choice. |
| The longest | 168 hours | A week is longer than any stay the cabin sees, and it is still an end. |

An expired choice is left in the settings file rather than cleared, so nothing is written on the pass
that notices it. The page states what is in force, what chose it and when it lets go, so an expired row
in the file is never what a person reads.

**The moment the mode in force changes is what stamps the mode temperature**, and a choice letting go is
such a change. Without that a hand change made on a room under one mode would outlive the switch away
from it.

A choice made while the clock is unset carries its end moment forward with its stamp when the clock is
set from the network. Otherwise the hours it was given would have elapsed before the cabin knew the date.

## Stamps, and a cabin that came back on the wrong clock

Every number both halves hold carries the moment it was set and whether the clock had been set from
the network. A stamp written against an unset clock loses to one written with a good clock, whatever
the two times read, so a change made during an outage never displaces one made with a good clock.
The moment the clock is set, every marked stamp becomes that moment, which puts the outage's change
newer than everything before it and older than everything after it.

Two stamps reading exactly alike resolve in favour of the settings page, because that is where the
number is edited.

## Where a learnt number tracks while a person holds it

A value set by hand is the value in force and the system stops using its own. The system's own
number keeps following the measurements underneath, so clearing the set value hands back a number
informed by everything measured since, rather than the starting value. A reset is the other act: it
drops the measurements and returns the system's number to its starting value.

## What the add-on measures, and what it throws away

Two watchers run per room, one pass a minute, on what that room's thermostat publishes.

**The warming rate** takes a point from every rise a room makes towards a higher temperature,
whether a warm-up planned it or a boundary simply raised the temperature. A rise begins where the
room sits at least half a degree below its target and ends where it arrives; a target lowered
part-way through ends it with nothing recorded. A paced rise spends part of its time with the relay
open, so the rate measured is at or below what the room can manage, which is the safe end.

Three kinds of rise teach nothing and are thrown away:

- One where the heater was never commanded on. That rise is the weather's, and believing it would
  read the rate high, which starts the next warm-up late.
- One where the heater was commanded on, the room has a meter, and the meter never moved. A room
  that fails to warm because its own switch is off would otherwise teach itself a false rate, and
  that number would stay after somebody switched the heater back on.
- One shorter than half a degree or fifteen minutes. Both figures are chosen here: a wobble divided
  by a couple of minutes is arithmetic, not a measurement.

**A rise with no outdoor reading beside it still counts.** It joins the recency-weighted mean and
takes no part in the fitted line, because a line needs two distinct outdoor temperatures.

**The outdoor part of the holding duty** is taken from how far below its target a room settles. One
measurement is taken per settled stretch of half an hour, from the mean shortfall over it, and a
target change or a warm-up starts the stretch again. The correction is the duty that would have
closed the shortfall, spread over the degrees the room sits above the weather:
`shortfall / (full output below × (target − outdoor))`. A room short of its target takes the tenth
margin above that; a room that overshot takes the correction plain, because a margin there would err
away from the end that keeps the room warm. Applying the margin to the value already in force would
ratchet the term up a tenth every half hour in a room with no shortfall at all.

A stretch with no outdoor reading yields nothing, because it says nothing about the outdoor
relationship. `FullOutputBelow` in `PlannerDefaults` mirrors the figure the integration's loop holds
and is used for nothing else.

## What the core does not do

- No file is written. The specification's persistence copy is a later step.
- A borrowed reading is not resolved here. A room borrowing its neighbour's temperature is the
  integration's arrangement; this core reads one room's own sensors.
- The duty a room holds at is not computed here. The core carries the outdoor term and its learning;
  the loop that uses it runs in the integration.

---

# The settings page

## Where the page is served from, and what is a copy

The page is a Razor Class Library with no host of its own, `addon/src/AdaptiveHeating.Page/`. Two
hosts serve the same markup: the add-on, `addon/src/AdaptiveHeating.AddOn/`, and the render host,
`addon/tools/pagehost/`. A change looked at in one is the change the other serves.

The components, the colour tokens, the light-and-dark script, the root component and the base-address
helper are copies of the lighting engine's second design, not a reference to it. Referencing it would
pull in the lighting engine, its configuration reader and the NetDaemon packages. The two copies
drift, and a fault found in either is carried across by hand.

## The base address is resolved per request

`IngressBasePath` reads `X-Ingress-Path`, adds the trailing slash the header omits, and answers with
the plain site root when no header arrives or when the value is outside a narrow shape. Without the
trailing slash the last segment of the prefix drops off every relative link on the page.

Nothing writes a base address into the markup, no link is rooted, and no absolute address is built.
Measured on the served page: with the header it declares the prefix, without it declares `/`, and the
two responses are otherwise identical apart from the per-request render identifiers.

Home Assistant strips its prefix before the request arrives, so there is no path-base middleware
anywhere. Stripping it again would strip a prefix that has already gone.

## One way in is told from the other by the socket

`WayIn.IsIngress` compares `Connection.LocalPort` against the port the manifest names. The identity
headers are read only after that check has passed, because a header is something a caller writes and
a socket is not. One authentication scheme carries who is signed in as an ordinary principal, and no
page and no endpoint asks which way the request came in.

One listener exists. A second way in is a second port and a second entry in `WayIn`; Kestrel's option
delegates are additive, so the first listener is untouched. Nothing else on the page changes.

Only Home Assistant's own sign-in provider is documented to carry a user name, so a person signed in
another way takes their display name and then their identifier. A header the gateway sent twice names
nobody: the gateway sets exactly one, so two copies are a caller pushing values in.

## The page carries its own words

Home Assistant translates an integration's own surfaces and an add-on's configuration options, and
translates nothing inside a page an add-on serves. So the page's words live in
`Resources/PageStrings.resx`, it picks its language from what the browser asks for, and it falls back
to English. `PageLanguages.Available` reads the cultures off disk rather than from a written-down
list, so a language is added by dropping a resource file in.

The lighting engine has no resource file and no localiser anywhere; its page text is literal in its
components. This arrangement is therefore new work rather than a copy.

## What was chosen where the specification is silent

| Choice | What was taken | Why |
|---|---|---|
| Where the five mode names live | With the planner, beside the profile entry and its two meanings | The planner resolves a mode to an instruction and places a boundary on the clock, so the rules and the vocabulary sit together and the page only edits them. |
| How many palettes | Two, plus follow-the-device | Heating has one design. A second palette per theme is what reached a live house half-changed. |
| Fonts | The system stack, no web font | The cabin may have no line up, and 19 font files is a large image for a settings page. |
| The number field's precision | Five decimals | The outdoor holding term is thousandths of full output per degree. One decimal wrote it as zero. |

## Three things that look like a broken page and are not

- **`blazor.web.js` lives in `Microsoft.AspNetCore.App.Internal.Assets`**, not in the shared framework
  and not in the SDK. Without that package reference the page renders once and no circuit opens, so
  nothing responds. Measured here: 404 before, 200 with a real body after.
- **`UseStaticWebAssets()` is explicit.** Static web assets are wired up automatically only in
  Development, and without them the library's `_content/**` 404s and the page renders unstyled.
- **An `sr-only` cell in a grid leaves no track.** It is absolutely positioned, so every row after it
  shifts a column. The mode table's last heading is an empty cell instead.

---

# The settings that survive a restart

## The file, and what is a copy

Five files under `addon/src/AdaptiveHeating.AddOn/Persistence/` are copies of the lighting engine's
`src/AdaptiveLighting/Persistence/`, taken on 2026-09-24 at 678 lines: the atomic writer with its
backup slot, the note helper over it, the store, the store declaration and the store registry. The
four stores beside them there are lighting's own and none is copied. The two copies drift, and a
fault found in either is carried across by hand.

Two things were specialised as the copy landed.

- The registry drives its flusher on a `TimeProvider` rather than a Reactive scheduler. Taking it as
  written would add System.Reactive to an add-on that has nothing else to use it for.
- The registry is keyed on heating's own document path, `/data/heating.json` unless configuration
  says otherwise, so the notes sit in `/data/state/` beside it. That directory is the one thing on
  the box an add-on update does not replace.

The settings are written the moment a save is accepted rather than coalesced: a person has just
pressed save and a restart is about to need the number.

## The rules stay where they were

`DurableSettingsStore` wraps the store that holds the settings in memory and adds a file. Every rule
about the settings, the stamp contest included, stays in the store it wraps. A save that is refused
writes nothing.

## What survives, and what does not

- Every room's temperature for every mode, each with the stamp that decides the next contest.
- The day's profile, the per-room sensor values, the three learnt numbers per room, and which room
  borrows from which.
- Which thermostat each room's actions target, and the name the integration gave the room.

The versions each half runs do not survive, and are not meant to: the add-on's own is this build's,
and the integration's is null again until a thermostat is read. Anything the file carries that this
build does not know is ignored, which is what lets a file written by a newer build still restore
everything this one understands.

**A struct reading a file gets its parameterless constructor** unless the real one is named, so the
stamp and the stamped value both carry that attribute. Without it every restored stamp would read as
the start of time, and every restored number would then lose every contest against a fresh one.

## A cabin that came back on the wrong clock

A stamp is marked as made against an unset clock while the clock reads earlier than the moment the
add-on's own assembly was written to disk. A clock reading from before the software existed cannot
have been set from the network, and that claim rests on nothing that needs measuring. The moment the
clock crosses that floor it is announced once, and every marked stamp in the settings becomes that
moment.

**What this does not catch is a hardware clock holding a plausible but wrong time.** What would settle
whether that case is worth building for: running a power-cut scenario once, with the network link down,
and reading what time the box comes back on.

---

# The two halves talking

## The add-on reaches Home Assistant through the Supervisor

The add-on declares the core-API permission, so the Supervisor proxies Home Assistant's websocket at
`ws://supervisor/core/websocket` on the token in the add-on's environment. The manifest carries that
permission although no ordinary web request is made: the Supervisor's own proxy refuses the websocket
address to an add-on without it. No user and no long-lived token exists anywhere, and an outside
caller sees no difference between these actions and a built-in one.

**Everything the add-on asks of Home Assistant goes over the one connection**, and everything Home
Assistant reports arrives on it. Nothing reaches Home Assistant any other way, and the add-on holds
no HTTP client of its own.

One connection for the life of the process, so an action reported as unknown is reported once across
the whole add-on rather than once per caller.

## The connection is NetDaemon's client, and what is still the add-on's

`NetDaemon.Client` 26.36.0 holds the connection. It is pinned exactly, at the number
AdaptiveLighting pins and the newest published. Neither `NetDaemon.Runtime` nor `NetDaemon.AppModel`
is referenced, so no version here has to match a version a house pins: the add-on is its own process
and talks to Home Assistant directly. Its own entity model is not referenced either, because
initialising that also fetches the entity, device, area, label and floor registries, none of which
the heating reads.

What the client carries: the handshake, the token, the numbering of messages and the matching of
answers to them, message coalescing, the reconnection and its wait, the subscription, and the read of
every entity. What is still written here is below.

**The wait between attempts is a flat 80 seconds.** Measured on the cabin on 2026-09-25 across a core
restart: the Supervisor's proxy answers a websocket upgrade with 502 while the core is away, the
client reports the failure and prints the same 80 seconds five times over, then reopens and reads the
whole house again unprompted. So a core that comes back is followed by up to 80 seconds in which the
add-on is still blind, on top of however long the core took. What that costs, and what a shorter first
attempt would buy, has not been measured.

- **The action call.** The client's own call reports no reason a call failed: the context's call
  returns nothing, its fire-and-forget extension only logs, and its helper that returns a result
  throws with the error folded into a sentence of its own. The add-on has to tell an absent action
  from a room's refusal from everything else by the code, so the call is sent as a plain message and
  the answer is read off the client's own raw message stream, matched by the number the client
  assigned. That is the pattern the client's own ping uses.
- **The table of what the house holds**, because the client's entity model is not referenced.
- **A call made while the connection is not usable is lost, not queued.** It answers at once saying
  there is no connection, and the caller carries on. A pass over the rooms works out afresh what each
  room should be doing, so what is lost is at most one pass of instruction. A call already sent when
  the connection ends is answered the same way rather than left waiting out the twenty seconds a
  message waits for an answer.
- **Starting the client again after it gives up.** It stops retrying for good on a token Home
  Assistant will not take. The Supervisor rotates the add-on's token, so the token is read afresh and
  the client started again five seconds later.

Nothing is stored to be sent later and nothing is retried in a loop.

**The connection counts as usable only once three things have happened**: Home Assistant answered
that it is running, which the client asks and refuses the connection without; the subscription is in
place; and the whole house has been read. A core still coming up hands nothing over, so a call made
then is refused at once rather than spent and lost.

## The rooms say when something happens

A subscription reports only what changes after it starts, so a fresh connection reads the whole
house once and the table is replaced by what came back. From then on nothing is asked for: Home
Assistant reports each change as it happens and the table follows it. A room follows its sensor
within seconds.

- **Every event in the house arrives whatever type is asked for.** That is a measured defect in the
  client at 26.36.0: the event type never reaches the outgoing message. Asking for a name buys a
  second subscription carrying exactly the same traffic, so nothing is named and the filtering is
  this side's — first the event type, then the entity.
- **The heating reads its own thermostats, Home Assistant's sun entity and the presence helper, and
  nothing else.** `WhatTheHeatingReads` is that one predicate and it does two jobs: what is kept as
  the house changes, and which change is worth a pass over the rooms. A house raises hundreds of
  changes a minute and the heating reads a handful of entities, so without it the rooms would be
  driven on somebody else's doorbell.
- **A change arriving while the house is being read is held and applied after it.** The read carries
  the house as Home Assistant served it, so applying it over a newer change would put an older value
  back and leave it there until that entity next changed.
- **An entity that reports no new state is dropped.** A room removed in the integration reports one
  of those, and keeping it would drive a room that is gone.
- **What is lost while the connection is down cannot be caught up**, which is why every reopening
  reads the whole house again unconditionally.

## A missing action is absent, not fatal

An action the integration does not have answers with the code `not_found`. That reads as the action
being absent: the first one is a warning naming what stands unused, every one after it is a debug
line, and the caller carries on with everything else it was doing. Nothing is queued and nothing is
retried in a loop, because the next save makes the same call again.

`CoreConnection` names `service_validation_error` as the one code marking a refusal the room itself
made, and treats everything else — no connection, no answer at all, a field out of bounds — as a
failure, losing the call and carrying on.

**A refusal arrives under that code.** `climate.py:_act` raises the platform's `ServiceValidationError`
from the integration's own `Refused`, and the websocket answers that as `service_validation_error`, so
a room's own refusal is classified as a refusal and reaches the activity record carrying its reason. A
field outside its bound is a `vol.Invalid` from the field's own validator and answers `invalid_format`,
which keeps the two apart by the code alone. Which shape falls to which code is settled under *The code
an answer arrives under*.

**Measured against the cabin's core, Home Assistant 2026.9.1.** How a missing action reads depends
on which way in the caller uses.

- Over the websocket the answer carries a code and a sentence. An action nobody registered gives
  the code `not_found` with a message naming the domain and the action. A registered action handed
  a field outside its bounds gives `invalid_format` and names the field. **The two are told apart
  by the code**, which is what makes treating one as absent and the other as a failure safe.
- Over the HTTP interface both answer a bare bad request, with no body beyond the status line.
  **Nothing in that answer says the action was not found**, and nothing separates an absent action
  from a bad field. A caller that reads the body for the reason has nothing to read there.
- A domain no integration registered at all reads the same way as a missing action in a domain
  that exists: `not_found` over the websocket, a bare bad request over HTTP.

## Which saves reach which action

| Saved on the settings page | The action called |
|---|---|
| The warming rate, set by hand or reset | Set how fast the room warms |
| The band, set by hand or reset | Set how the room is regulated |
| The outdoor part of the holding duty | Set how the room is regulated |

Only the field that changed is sent. Everything the action does not carry stays as the loop has it.

A save must not wait on Home Assistant, so what to send is queued and a pump sends it in the order
the saves were made. A room the integration has not reported has no thermostat to write to: the
number is held and goes out when the room is found.

## What asks for a pass over the rooms

Three things do, and one pass is pending at a time.

- **A change to an entity the heating reads.** That is what takes the reading off the clock.
- **The next schedule boundary**, one second past it, so the pass reads a clock on the new entry's
  side of the boundary rather than resolving the entry going out.
- **The clock, a minute at a time**, behind both as the safety net. A room is driven by the clock as
  well as by its sensors: a warm-up deadline and a timed hold still have to come round.

**Anything asking for a pass while one is running collapses into the single pass after it**, and
nothing is lost by the collapse: a pass reads the whole table when it runs and carries no queue and
no delta, so one trailing pass sees the newest value of each entity. That matters because the
add-on's own commands change the thermostats it watches, and every one of those changes comes back as
an event.

**No shortest interval between passes is chosen.** The collapse bounds how many passes a burst can
cause, and what a pass costs against what a live house raises has not been measured.

## The timer at each schedule boundary

`BoundaryTimer` arms a one-shot one second past the next boundary and re-arms itself for the one
after. Every pass arms it again, which picks up a boundary the sun has moved and a profile a save has
rebuilt; arming for the boundary already waited for changes nothing, so a pass a second cannot push
it back. A boundary only bites under the day profile, so under any other mode nothing is armed and
the pass a minute is what notices the mode changing back.

The file is a copy of the lighting engine's own, read on 2026-09-25. The two copies drift, and a
fault found in either is carried across by hand. It schedules on System.Reactive's scheduler as the
original does, which the persistence copy did not: that one swapped the scheduler for the clock
abstraction because nothing else in the add-on would have used System.Reactive, and the client brings
it now.

The pass a minute is the safety net behind the timer, so a timer that never fires costs lateness and
not correctness.

## What one pass over the rooms does

`DrivesTheRooms` runs on the table of what the house holds. Nothing in it
decides a rule: the mode table, the precedence order, the boundary placement, the warm-up arithmetic
and the two learning watchers all live in the planner, and this reads the thermostats, hands the
planner numbers and calls the actions its answers name.

- The mode in force is resolved, and with it one instruction per room.
- A room with a reading has its temperature resolved against the boundary in force, any hand change
  and whatever the room is already running, and Home Assistant's own climate action carries the
  answer. **A boundary naming the temperature the room is already holding replaces nothing**, which
  falls out of sending only where the two differ.
- A room with no reading is switched on or off through the regulation action, and nothing else is
  done to it.
- Where a warm-up is due, the warm-by action is called at the moment the planner says the heating
  has to begin, and once per deadline. The integration then solves backwards again from the rate it
  holds, which is why the two agree about when the heater comes on. **That moment is found by the
  pass a minute and not by a timer**: a timer is armed for a boundary, and a warm-up starts before
  one, at a moment that moves with the rate the room has learnt.
- What the room taught is written back through the rate action and the regulation action.

**A target this pass did not ask for was set at the room's card.** That is how a hand change is
recognised: the published target differs from the last temperature the add-on sent, and it carries
the moment the integration recorded. While a warm-up or a hold runs the published target is theirs,
so nothing is read as a hand change then, and nothing is sent.

**Two of the five actions are still called by nothing**: holding a temperature until it expires, and
returning a room to its target. Both are built and callable, and no rule in the specification asks
for either yet.

## How the add-on finds the rooms

A room is set up in the integration, so the add-on learns one exists from the climate entities Home
Assistant holds: the whole house comes back in one answer as the connection opens, and after that a
new room arrives as a change like any other. Every thermostat of this integration publishes its room
identifier, the integration's own version and its vocabulary version; nothing else in a house
publishes them, so a
climate entity carrying them is one of ours and one carrying none is not. A thermostat naming a room
of its own is exactly the case a looser test would claim, and the mutation run is what found the
first test not proving it.

A room already held is kept whatever the entities say. A core that is down, or still coming up,
answers nothing and costs nobody the temperatures they typed. A pass that learns nothing asks for no
write.

A room seen for the first time arrives with no temperature against any mode, because a temperature
for a mode is typed on the settings page once and nothing here can invent one.

## What the add-on says, and the three places it says it

Every report goes to all three at once: the activity record, the log, and — for the few reports a
person has to see — a card in Home Assistant. Nothing the add-on does is said in only one of them.

The activity record keeps the newest **500 reports** and drops the oldest. It is journalled into a
file beside the settings document, declared in the registry the settings file already uses, so one
flusher covers both and a burst of reports costs one write a minute rather than one write a report. A
restart reads the file and carries the running count on from where it stopped, so no number is ever
reused. The record holds each room by its identifier and never by its name, and what a person calls a
room is looked up when the words are built — a rename then shows at once and cannot split one room's
history in two.

**A card is raised only for what the add-on cannot put right itself**: a room that cannot reach a
temperature by its deadline, and every chosen outdoor sensor being out. A card for each temperature a
room is told would train a household to dismiss them. The card's identifier comes from its title, so
raising the same problem again replaces its own card instead of stacking one.

The outdoor-sensor card is raised once while the condition holds, and again the next time it becomes
true. Without that, a cabin whose sensors are all dead would raise the same card every minute.

The activity record, its journal, the notifier and the durable log below are the lighting engine's own
code, read at `e6966f4` on 2026-09-25. The two copies drift, and a fault found in either is carried
across by hand.

## The durable copy of the log

The Supervisor's own log buffer holds only the newest lines and two restarts overwrite it, so every
line is also written beside the settings document: **one file a day, 4 MB before the day rolls early,
15 files kept, 14 days**. The count times the size caps the disk; the days are what a reader gets.

Each line is rendered from the message template rather than from the finished message, because the
finished message is the interpolated string, credentials and all. Every value goes through one place
that replaces a property whose name reads as a credential, and replaces the credential-shaped part of
a value: a JWT, a `password=` pair, a URI's user info, a long opaque mixed-case run. Entity ids and
paths survive both, being lower case.

Levels are set in code and never read from configuration. This logger replaces the one the host built
from `Logging:LogLevel`, and Serilog's own configuration reader wants a section this add-on does not
carry, which would leave Information and silently drop every debug line.

A failing file sink reports only through Serilog's own self-log, which nothing else turns on. It is
turned on here and routed to standard error, with a repeat of the same message held back for five
minutes: a house at the rate measured in the lighting engine loses around a dozen events a minute
when a sink fails, each with a stack trace.

## The outdoor temperature is the add-on's own reading

One or more outdoor sensors are chosen on the add-on's configuration page. They go through the same
check a room's own sensors do: a sensor quiet for longer than the freshness window is out, one sitting
at a single value is out as a dying battery, a disagreeing pair loses both, and an outlier among three
or more loses itself. The reading is the average of what is left.

**Where that leaves nothing, the forecast takes over** — the weather entity's own temperature
attribute. Where no forecast is named either, the answer is nothing, never the last value a dead
sensor reported.

Where nothing at all is chosen, each room runs on the outdoor figure its own thermostat publishes.
That is the shipped default, so a cabin whose form has never been opened keeps working.

A sensor's own timestamps are what the check needs: Home Assistant's `last_updated` says when it was
last heard from, and `last_changed` says when its value last moved, which is what a stuck reading is
measured against. A state that is not a number, unavailable or unknown among them, counts as a sensor
that never reported.

## What is in force, and what each room is actually doing

Two things reach the settings page beside a room's settings, and neither is a setting.

The record of what is in force holds the temperature each room is being told and the mode over the
whole cabin, each carrying the moment it was set. This pass's instructions are merged into it once,
and the merge refuses a change carrying an older stamp than the one held — the same rule every number
in this system follows. A temperature that has not moved is not offered, because the contest would
refuse the same number arriving again as a change and every steady minute would then read as a
refusal.

The record also carries what chose the mode, decided by the one pass that resolves it. A page working
that out for itself needs a clock of its own, and would then disagree with the mode it is drawing for
as long as a pass takes.

The live reading holds what each thermostat reads, what it holds, whether its relay is closed, and
when it was read. It is what tells a room holding steady apart from one that has stopped.

**The options the presence dropdown offers reach the page the same way.** The settings page draws one
row per option, and an option the words could not tell apart has no stored row to draw, so without the
live list there is nothing on screen to map. The list is a reading like the others: never written to the
settings file, because a stored copy goes stale against the helper it came from.

**Neither is written to the settings file.** Both are worked out afresh on the next pass, within a
minute of a restart, and the temperatures the in-force record mirrors are already in the file. Both
reach the page through the change event the store raises, which is the right mechanism while one
process hosts both halves.

## The number field declares no grain where the value has none

A browser marks a number invalid when it is not an exact multiple of the field's step, and its arrows
snap such a value onto the grid. All three learnt numbers are fitted from measurements and land
wherever the fit puts them, so all three declare `step="any"`. Measured on the rendered page before
the change: of 27 number inputs one reported itself invalid, the outdoor term, holding 0.0072 against
a step of a thousandth.

The guard is the lighting engine's, read at `e6966f4`. Its plus-and-minus control did not come with
it: the heating grid puts one number per cell and has no room for a three-part control.

## The manifest's watchdog and its configuration form

The Supervisor opens a plain TCP connection to the page's own port and restarts the add-on when
nothing answers. A crashed or hung process is otherwise dead until somebody notices, and nobody is at
a cabin to notice. A connect and not an HTTP request, because the page sits behind the ingress sign-in
and a listening socket is exactly what a crash takes away.

The configuration form carries the presence helper, the chosen outdoor sensors and the forecast
entity. The Supervisor renders it from the manifest's schema and writes the answers to
`/data/options.json`, which the process reads through the configuration provider it already has,
after the defaults, so what a person typed wins over what the image carries. Every one of those three
was a literal in a file before, which meant naming an entity needed a deploy.

**An optional option cannot be cleared to nothing.** `forecast_entity` is declared `str?` and carries
no default, and the Supervisor still refuses a write that sets it to null, answering that the required
option is missing. Measured on the cabin at Supervisor 2026.09.3. An optional key may be absent from
the stored options; it may not be present and empty. So the form has no way to take a forecast entity
back out once one is typed, short of editing the stored options.

Read against Home Assistant's own add-on documentation as it stood on **2026-09-17**, which documents
the three watchdog URL forms and the `[HOST]` and `[PORT:nnnn]` substitutions, and states that an
optional schema type ends in `?` and must then carry no default. It states no poll interval and no
behaviour on failure.

**The watchdog toggle is off until somebody turns it on.** So is the sidebar panel. Both are
per-installation settings the Supervisor defaults to false whatever the manifest declares, and a
freshly installed add-on therefore has no watchdog and no entry in the sidebar. Measured on the cabin
on 2026-09-25, straight after the install.

**`[PORT:8099]` resolves to 8099 although 8099 is in no `ports` map, and the watchdog acts on it.**
Measured on the cabin on 2026-09-25, in both directions. Pointing the same placeholder form at a dead
port in no map, `tcp://[HOST]:[PORT:9099]`, brought the Supervisor's own warning that it had found a
problem with the application, followed by stopping and starting the container, three minutes after the
manifest took effect and again four minutes after that. Left on 8099, where the page is listening,
nothing was restarted across twenty minutes with the toggle on, nor in the five minutes after the
manifest went back. So the placeholder substitutes the number written in it rather than a mapped port,
a dead socket is picked up within about three minutes, and the check keeps repeating rather than
giving up after one restart.

**The version the add-on reports is the assembly's, not the manifest's.** A manifest at
`0.1.0-preview.2` was reported by the Supervisor as that version while the process announced
`0.1.0-preview.1` in its own first log line, because the assembly version is fixed where the build
reads it and the manifest's `version` is only what the Supervisor tags the image with. So the log line
answers which build is running and the Supervisor answers which manifest, and the two can disagree.

## Installing the add-on on a box by hand

The published image does not exist yet, so the only way onto a box is as a local add-on, built there.
Measured end to end on the cabin on 2026-09-25 at Supervisor 2026.09.3, amd64.

- **The folder is `/addons/<slug>/`**, holding `config.yaml` and `Dockerfile` at its root with the
  `addon/` source tree beside them, because the Supervisor builds a local add-on with the add-on's own
  folder as the build context and the Dockerfile's `COPY addon/…` lines are written against the
  repository root.
- **Take the files with `git archive` from the repository root**, naming `adaptive_heating` and
  `addon` as paths, then lift the contents of `adaptive_heating/` to the archive root. Archiving from
  the root is what applies `.gitattributes`: the Dockerfile and the YAML arrive with no carriage
  returns and the C# arrives with them, checked by counting carriage-return bytes rather than by
  `grep`, which reports carriage returns in a file that has none.
- **The `image` key must go.** With it present the Supervisor pulls even for a local add-on: it asks
  ghcr.io for a token, is refused, and the install fails with a generic unknown error naming nothing.
  The store's own `build` field is the discriminator — false with the key, true without it.
- **No `build.yaml` is read and no `BUILD_FROM` is supplied.** The Supervisor runs
  `docker buildx build` with `--platform linux/amd64 --pull` and passes `BUILD_VERSION` and
  `BUILD_ARCH`, so both stages naming their own base image is what the manifest needs.
- **The build takes 52 seconds** on an Intel i5-8365U with eight cores, against the over-thirty
  minutes recorded on a Raspberry Pi 3B+.
- **The store must be reloaded** before the add-on appears, and the slug the API answers to is
  `local_<slug>`.
- **`/core/info` reports a null state** at this Supervisor version, so it says nothing about whether
  the core is up. Readiness is whether `/core/api/` answers. A `POST /core/restart` blocks until the
  core is back: nearly seven minutes on the cabin.

## The page can be reached without Home Assistant's sign-in

The add-on's own port answers to anything on the Supervisor's own network, and `WayIn.IsIngress`
compares the local port, so a request arriving straight at 8099 is treated as an ingress request.
Another add-on reaches it at `local-<slug>:8099` with no token and no sign-in, and the page renders.
The authentication handler reports the request as not authenticated and the page is served anyway,
which is what having no login of its own means. Nothing maps 8099 out of the container, so the only
route from outside is Home Assistant's, and that one signs a person in.

This is also the one way to look at the page from a session, and what it cannot do is open a fold: a
fold is opened by the circuit and a circuit needs a browser. What can be checked is that the document
comes back, that the base address follows the header, that the stylesheet, the theme script and
`blazor.web.js` all come back with a body, and that the circuit's negotiate endpoint hands out a
connection token.

---

# The integration

## The sensor check runs in both halves, on purpose

A room keeps its reading when the add-on is away. The check that produces that reading therefore
cannot live in the add-on, so it lives in the integration beside the control loop: dropping a sensor
that has gone quiet, one stuck at a value, one sitting far from the others, and settling a
disagreeing pair or a majority.

The add-on keeps its own check for the outdoor sensors, which are its own, under the same rules.
`RoomSensors.Read` in the planner and `core/sensors.py` in the integration are two implementations
of one set of rules, and neither is generated from the other.

The two copies drift. A fault found in either is fixed in both and carried across by hand, exactly
as the specification already arranges for the files that survive a restart.

## The rules import nothing from Home Assistant

`custom_components/adaptive_heating/core/` takes numbers and times as parameters and returns
decisions. The climate entity is the adapter above it: it reads states, sends commands and writes
the file. Two things follow.

- The rules are exercised on any machine with a Python interpreter, with no Home Assistant install.
- A rule proved by a test is the rule that runs, because the entity holds none of its own.

## One evaluation of a room at a time

A room's heaters are in the list it watches, so a relay it closes raises a state change that lands
back on the room that closed it. An evaluation changes the heater loops and the power watch, then
awaits one command per heater, so that change arrives inside the await. Two evaluations running
across each other would both read, change and write the same relay state and the same last-change
time. `core/serialisation.py` is the gate that stops it, and every way into an evaluation goes
through it.

**A sensor change or a clock tick asks for one more pass and returns.** Where a pass is already
running, the gate records that another is wanted and the running pass runs it when it finishes. Any
number of changes arriving during one pass collapse into that single trailing pass, and nothing is
lost by the collapse: an evaluation reads every sensor from the state machine when it runs and
carries no queue and no delta, so one trailing pass sees the newest value of each.

**A person's action waits its turn instead.** The change the action makes and the store write that
records it both have to land before the call returns, so a coalesced action would defer the write it
exists to make durable. The action's own change to the thermostat runs inside the gate as well, not
in front of it, because it writes the fields an evaluation writes.

**A room going away closes its gate and cancels the pass in flight.** The entity keeps the handle of
every pass it starts. Without that, a pass outliving its entity writes the state of an entity that
has gone and saves to a store entry that has gone with it.

**Home Assistant's own debouncer is not what carries this**, read at tag `2026.9.0`. It holds an
execution lock and coalesces, which is most of the answer, and three things rule it out here.

- A queued trailing pass is discarded where a pass outlasts the cooldown. `_handle_timer_finish`
  clears the wanted-another-pass flag before it tests whether the lock is held, and returns while it
  is held, so the flag is already gone. The helper's own comment states the assumption behind that —
  a call already in progress is as good as the one wanted — which holds for a coordinator fetching
  from an endpoint and not here, because the running evaluation read the room before the change
  arrived. An evaluation awaits a blocking action call per heater, so a slow relay integration can
  outlast a short cooldown.
- `async_call` returns without running whenever a timer is armed from the previous run, which is the
  ordinary case inside the cooldown. That is the action path's durable store write deferred.
- The gate is exercised on any machine with a Python interpreter, as everything in `core/` is. A
  guard built on the platform helper could not be run here at all, so its mutations could not be
  proved.

## What a switched-off thermostat does

The specification decides this, and the code follows it without re-deriving it. `RoomThermostat`
holds the off state, and `_stop` is the only path a switched-off room takes.

- The relay is opened once on the way into off. `HeaterLoop.open_once` reports a change only where
  the relay was actually closed, so nothing is commanded afterwards — including where something
  else closed the relay in the meantime.
- The room's average, the freshness record and the snapshot keep moving, and the entity keeps
  publishing them.
- The temperature the room would hold is what the card shows.
- `_reports_a_problem` is the one place that leaves a switched-off room out of the report. An
  earlier arrangement passed that decision in as an argument as well, which left the rule itself
  unreachable; the mutation run is what found it.

**Nothing with a time in it is queued while a thermostat is off.** Switching off ends any running
warm-up and any timed hold, and both actions are refused while it is off, carrying the one refusal
reason from `core/reasons.py`. The two actions that only write numbers — the warming rate and the
regulation settings — are accepted while off, because neither queues anything: they change what the
loop uses whenever it next runs. The specification does not separate the five that way, and this is
where that separation was decided.

## How a refusal is raised, and what each way in makes of it

A refusal is the integration's own `Refused`, a plain exception written once in `core/reasons.py`.
`climate.py:_act` is the one point every action reaches a thermostat through, and it turns that into the
platform's `ServiceValidationError`. The code each shape answers under is settled under *The code an
answer arrives under*; what differs between the two ways into an action is what survives the trip.

- **Over the websocket the code and the sentence both arrive.** A refusal answers
  `service_validation_error` carrying the reason, which is the route the add-on uses and the one where a
  refusal, a missing action and a field out of bounds are told apart by the code alone.
- **Over the ordinary web request route a refusal answers 500.** The services view catches `vol.Invalid`
  and `ServiceNotFound`, and a `ServiceValidationError` is neither, so it leaves the handler as a server
  fault with a traceback for a room behaving correctly. A field out of bounds answers a bad request with
  no reason in it, because Home Assistant discards the message for every invalid field.

Both routes were measured at the cabin, under *What the cabin showed when the refusal code arrived*,
which also carries the prefix Home Assistant puts in front of the sentence. A caller that needs the
reason uses the websocket. The refusal is written once and the entity's handlers let it leave as it is,
rather than turning it into something one route cannot carry.

## A deadline written as a time alone

`by_time` takes a full date and time, or a clock time by itself, which means the next time that clock
time comes round. A time alone is how a person writing a call by hand writes one, and how every trial
so far has called it; before this it was thrown out naming neither the field nor the reason. The
picker still supplies a full date and time and is unchanged. A value neither shape can read answers
with what was wanted: a time like 06:00, or a full date and time.

The next occurrence is worked out the way the planner resolves a profile entry's boundary: today
where the time is still ahead, tomorrow otherwise.

## A room with no temperature reading at all

A room set up with a heater, no sensor of its own and no neighbour to borrow from is its own kind of
room, told apart by how it was set up and never by a sensor going quiet. The two look alike for one
evaluation and are different situations: one is a fault and the other is not.

- It is switched on and off and nothing more. There is no band, no duty and no cycle, because each
  of those needs a reading.
- **Until the planner has said which, the relay is left exactly as it was.** The fallback that never
  stops heating has no duty to repeat here.
- The card offers no target and no temperature, and the thermostat declares no temperature feature,
  so Home Assistant itself refuses the standard action that would set one. A number there would be
  one nothing in the room can perceive.
- It is left out of the problem report for having no reading. A room that never had one is not a
  room that lost one, and naming it would name it for ever with nothing to go and look at.
- The three actions that need a number are refused with one reason: warming to a temperature by a
  time, holding a temperature until it expires, and setting how fast the room warms.
- **It reports no warming rate as measured.** A room that can never measure a rise must not claim
  one, and the claim is cleared on the next ordinary evaluation rather than on a restart, because a
  room told a rate before the refusal existed cannot be corrected by the action that set it.

**The state where the relay is left exactly as it was is the state before anything has told the
room, and there is no way back to it.** Every mode cell holds on or off, so the planner always has
one of the two to send, and a call naming no value leaves the last instruction standing. That is
decided rather than missing: nothing needs to return a room to not having been told.

**Measured at the cabin on 2026-09-24, before this was built.** Such a room paced the ordinary
fifteen-minute cycle at a duty worked out from a target it cannot perceive and an outdoor
temperature it has never seen and assumes to be −10 °C. It reported a problem permanently, showed a
target of 2.0, and accepted all three actions. Warming by a time was the worst of them: with no
reading the rise works out at nothing, the start time lands on the deadline, the warm-up can never
run, and it still reported reaching the temperature with nothing short.

## What one cycle can deliver, and what it rounds to

**The deliverable band is the shortest time between relay changes divided by the cycle length.** At
the shipped fifteen minutes and five minutes that is one third to two thirds. A transition the guard
would not let finish is **skipped rather than stretched**: a duty below the floor rounds to nothing,
one above the ceiling rounds to full output, and one inside the band is paced as asked.

So a room reaches its target across cycles rather than over-delivering in each one, and the contacts
stay still while it does. The cost is named rather than hidden: **below the floor, demand becomes
nothing.** A room asking for a tenth of a cycle gets no heat, falls, and is answered when the
distance carries it into the band or into full output.

Measured before the rounding was built, on this loop at the shipped settings over twelve hours of
ten-second ticks: a duty of 0.05 held the relay closed for a third of every cycle and a duty of 0.95
for two thirds, in both cases while the card reported the figure asked for. Measured at the cabin on
2026-09-24, the same fault from the other side: six per cent of a cycle asks for fifty-four seconds
of heat and the relay stayed closed for five minutes to the second, twice running.

**The published duty is what the relay was held for.** The request stands beside it under its own
name, because the request is what the next evaluation acts on and what makes the two-stage law
readable, while the delivered figure is what anything learning from a cycle must be fed. Where the
guard overrides a transition the delivered figure is the relay's own state, and a separate flag says
the guard is holding.

**The delivered figure decides nothing about whether a cycle is running.** Only the clock rolls a
cycle over. A fraction that came out at nothing is a cycle running at nothing, and reading that as no
cycle at all is the fault that cost upstream a release: one set of fields held both the running
cycle's parameters and the next cycle's, a recalculation clamped to nothing wrote "nothing next
time", a later one read that as "no cycle is running", and the relay opened mid-cycle while a person
watched a configured minimum on-time being broken.

## The duty a room holds at

The specification says the duty follows how far the room is from its target and how cold it is
outside, and names neither formula. What is built:

- At or beyond the distance that runs full output, the whole cycle.
- Otherwise the distance from target as a fraction of that distance, plus the outdoor term, clamped
  to one whole cycle.
- The distance term goes negative above the target, so a room that has overshot falls to nothing
  rather than firing on the outdoor term for ever. The room therefore settles a shade above its
  target rather than below it, which is the safe end.

## What the cycle does when the numbers underneath it change

The cycle is the rhythm a paced room runs on, and nothing more. The duty it is read against is the
one computed on the evaluation being made, never one fixed when the cycle began. The cycle's start
still moves only when the cycle rolls over, so the rhythm is intact; what follows the room is the
fraction of it the relay is asked to hold.

What protects the relay is the shortest time between changes. That is a stated setting, it is the
mechanism the specification names for the purpose, and it bounds switching on its own: inside one
fifteen-minute cycle it allows at most three changes however the numbers move. A latched duty adds
nothing to that guard and costs the whole remainder of a cycle every time a person sets a
temperature.

Both directions were measured at the cabin on 2026-09-24, and both are wrong:

- A target raised by hand took **12 minutes 46 seconds** to bring any heat, which was the remainder
  of a cycle that had begun at no duty at all.
- A target lowered by hand left the relay closed for **5 minutes 18 seconds** while the published
  duty read zero and the room sat 3.8 degrees above its target. That one delivers heat to a room
  that has already overshot, and it makes the card disagree with the relay.

Reading the duty live settles both, and settles the card with them: the duty a room publishes and
the relay it is holding now say the same thing.

A room below its target and resting in the off-phase of its cycle is not at its temperature, and
says so. Below the target is the test rather than the duty: the outdoor term keeps the duty above
nothing in a settled room, and that room really is at its temperature, so reading the duty would
make *At temperature* a phrase almost nothing could say. The loop is the only thing that knows
which of the two a room is in, so the word travels up from it rather than being worked out again
above it. A band room has no off-phase, so the pacing word never reaches one.

## The outdoor temperature reaches the integration through its own configuration

The specification gives the outdoor sensors to the add-on and gives the integration a duty term that
needs the current outdoor temperature, and none of the five actions carries that number. The
integration therefore names an outdoor sensor of its own in configuration, like every other entity
it reads.

Where no reading is available, the term is applied at the coldest outdoor temperature the room has
seen in the past day, which is what the specification says to do when a chosen sensor has failed.
Where none has ever been seen, it is applied at -10 °C. That figure is chosen here and is
deliberately cold: the room fires harder than it needs rather than settling below its target.

## When a sensor last reported, and why the answer is not the integration's own watching

A sensor dead for a year still has its last value served, and it is served from the first second.
Taking the age of a reading from when this integration first noticed it therefore counts a corpse
as having just spoken. At the cabin on 2026-09-24 that cost a room its temperature outright: a
sensor last alive in 2024 was believed at 10.7 alongside a healthy one at 18.6, the two were 7.9
degrees apart, and both were dropped as a disagreeing pair. Nought of three, in the room chosen to
show the opposite.

So the age comes from what the platform records. `last_reported` moves on every report, one
repeating the value already held included, and is the answer to *when did this sensor last actually
report*. `last_updated` stands in for it on a core older than 2024.4. `last_changed` answers a
different question and is kept for the one it answers: when the value last moved, which is what the
stuck rule reads.

**A restart re-stamps every sensor in the house at once, and both times collapse to it.** The
lighting engine measured this and records it in its own notes: after a restart a week-dead sensor
and a healthy one are indistinguishable by either field. So a stamp at or before the restart is not
evidence, and `when_it_reported` returns nothing for one. The integration knows it is inside a
restart because the core is still coming up when the thermostat is added; a thermostat added to a
core already running is a reload, and the times it reads are the sensors' own.

What fills the gap is the record this integration already writes down, which crosses the cut. Two
rules make it outrank a collapsed stamp, and both apply only while the value has not moved:

- The report time moves forward but never backward, so an ordinary report still refreshes it.
- The moved-at time moves backward but never forward, so a restart cannot hand a stuck reading a
  fresh start.

A sensor with nothing written down and nothing believable from the platform is *unknown*, and
unknown counts as stale. The room leaves it out and carries on with whatever is left, which is the
safe end: a room that repeats its holding duty keeps heating, and a room that believes a corpse
does not.

The specification's rule that nothing judges a reading's age from the platform's own times is
honoured by its reason rather than its letter. The reason is that a restart forges them, and the
restart is exactly the case this refuses to read.

The lighting engine solves the same problem by watching the shape of the whole population: a
restart is declared when every sampled time in a house of at least ten entities falls inside one
short window. That cannot transfer here. A room names one to three sensors, which is far below any
population a collapse could be read from.

## The band is measured either side of a switch

The band that would have caught an observed drift is twice that drift, and that is the measurement
`BandLearning.observe` takes. It narrows on the spot and widens only after five in a row agree,
never past the ceiling. A band set by hand locks it, and clearing the set value hands back the
number the measurements have reached in the meantime.

## Numbers chosen in the integration

Each lives in `core/defaults.py`.

| Number | Value | Source |
|---|---|---|
| The cycle a paced room runs on | 15 minutes | Chosen here. |
| How far below target the room runs flat out | 1.5 degrees | Chosen here. |
| The shortest time between relay changes | 5 minutes | Chosen here. |
| The delay before an open window stops the room, and before a closed one resumes it | 2 minutes each way | Chosen here. The specification says the delay is adjustable per room and names no figure. |
| How long a freshness record is kept | 7 days | Stated. |
| The outdoor temperature applied where none has ever been seen | -10 °C | Chosen here. |
| The thermostat's own bounds | 2 °C to 30 °C, half-degree steps | Chosen here. The lower bound sits below any frost setting, because a temperature set below the away mode's is accepted and must reach the room. |
| The warming rate a room starts on | 0.5 degrees an hour, reported as not measured | Chosen here. |
| What a room drives at blind with nothing remembered | 15 % of a cycle | Stated. |
| How long a remembered fraction may be repeated blind | 24 hours | Stated, as the stretch the fraction is measured over. |
| The band one cycle can deliver | the guard over the cycle, so one third to two thirds | Derived from the two above it, not chosen. |

## The actions are declared once

`core/actions.py` holds the five actions and their fields. The registered schema is built from that
table, and `services.yaml` and the English strings are checked against it, so a field cannot appear
in the action picker without a label or reach a handler without a bound.

The schema removes a field it does not know rather than refusing the call, which is what lets a
newer add-on talk to an older integration without either half gating on a version.

## How an entity action is declared, and the one way it can be got wrong silently

Read from Home Assistant's own source at the 2026.9.3 tag and from its developer documentation.

**Only Home Assistant's own builder produces a schema it will accept.** A schema is registered
through `cv.make_entity_service_schema`, or as a plain dictionary of field validators for the
helper to build from. A hand-made `vol.Schema` is refused whatever it contains, because the check
tests for a marker the builder sets and never looks at the fields. The refusal reads *registers an
entity service with a non entity service schema*, and it is raised by
`_validate_entity_service_schema` in `homeassistant/helpers/service.py`.

**The target fields are the builder's to add**, and adding them by hand achieves nothing: the
builder spreads its own `entity_id`, `device_id`, `area_id`, `floor_id` and `label_id` last, over
any copy. It also insists on at least one of them, so an action that can be called without naming a
room cannot be declared at all.

**The builder refuses an unknown field by default**, so the tolerance this project wants is asked
for: `extra=vol.REMOVE_EXTRA`. Nothing in the platform-side registration call can pass that, which
is the reason the schema is built here rather than handed over as a dictionary.

**The registration lives in `async_setup`, not in the climate platform.** Home Assistant's own
guidance, from 2025-09-25, is `async_register_platform_entity_service` called from the integration's
own setup, so the actions exist even where no room loads and an automation naming one can be
validated. That needs a core carrying that helper; it has been there since 2025.10.

**A failed registration is invisible from the interface.** The raise leaves the platform's setup
through a bare handler that logs and returns false, and the config entry stays loaded regardless,
because the forwarding code ignores what the forwarded setups return. So the entry reports itself
loaded, the thermostat appears and works, every later registration in the same loop is skipped, and
the only signal is one line in the log. That is what happened at the cabin on 2026-09-24. A test
that asserts an entry loads cannot catch it; the test has to ask the registry.

## A room that borrows its neighbour's reading

A room with no sensors of its own reads the reading its named neighbour published. A room that is
itself borrowing refuses to lend, so no reading travels two steps, and a lender with no reading
lends nothing. The borrowing room's reading carries the room it came from, which is what the card
names.

## What a power reading can confirm, and what it cannot

The specification's heater-not-running fault is the relay closed, the room below its target, and
the power under 10 W for 15 minutes. The clause that carries the weight is the middle one, and it
is there because a heater with a thermostat of its own draws nothing once its own dial is
satisfied.

Measured at the cabin on 2026-09-24: the relay was closed for five minutes at 20.75 °C and the
meter never left zero, where three earlier closes each drew about 425 W within a second. The room
was above its target, so the specification's rule raises nothing, which is the right answer.

What the measurement adds is the limit of the rule. **The system knows its own target and not the
heater's dial, and it is the dial that decides whether power should be drawn.** Where a dial is set
below the target the room can sit below its target, draw nothing for a perfectly good reason, and
be named as a fault. That case has not been measured and cannot be ruled out by anything the system
reads. It is also why the fault is worded as the heater having drawn nothing rather than as a
certain fault.

A second consequence, and the one that costs most: **a commanded relay is not evidence that heat
was delivered.** Anything that learns from a period the heater was commanded on has to read the
meter, not the command.

## The meter, and the one room where it is the only evidence there is

A room names a power meter in its own configuration, like every other entity the system reads.
`PowerWatch` watches it against what the relay has been doing since the last evaluation, and raises
one of two faults.

- **The heater drew nothing**: the relay closed, the room below its target, and the draw under 10 W
  for fifteen minutes.
- **The relay is drawing power while it should be open**: the same two numbers read the other way.

Both are worded as what was seen rather than as a certain fault, because a heater with a dial of its
own draws nothing once that dial is satisfied and nothing the system reads tells that from a switch
turned off at the wall.

**In a room with no reading the middle clause cannot be asked at all**, and that is exactly the room
where the meter is the only evidence available. The clause is dropped there and the answer waits six
hours instead of fifteen minutes. Six hours is chosen here.

Measured at the cabin on 2026-09-24, in such a room: one close drew 615 W for four minutes and then
about 1 W with the relay still shut, and the next close drew 1.2 W for its whole five minutes. The
dial governs what the room costs, not the duty.

A meter that has not reported inside its window is out, exactly as any other sensor is, and neither
fault is raised while it is quiet. **An unreadable meter is never evidence that a heater is off**,
and a room whose meter has gone quiet heats exactly as a room with no meter does.

## Driving a room whose sensors have all gone quiet

A room that loses every reading keeps heating, on the fraction it was holding at that temperature.
Four rules bound what it may repeat.

- **Only a paced cycle enters the memory, and only what it delivered.** Full output is not holding
  time: the law's own full-output stage and a paced cycle rounded up to the whole of it both heat flat
  out, and repeating either blind leaves the relay closed for as long as the room stays quiet. An
  explicit warm-up returns before the memory is written, so a planned warm-up cannot poison it either.
- **The fraction is capped at the top of the deliverable band** on the way out of the memory as well
  as on the way in, so a stored file written by an older version cannot reintroduce full output.
- **A remembered fraction stands for twenty-four hours of blind driving**, the stretch it is measured
  over. Past that the room falls to the fixed last resort of 15 %. The spell survives a restart, so a
  box restarting every hour cannot repeat one fraction for a week.
- **Blind driving rounds up to the bottom of the band rather than down to nothing.** Ordinary driving
  rounds a too-small duty to nothing; a missing reading may not switch a heater off, so the fallback
  rounds the other way. At the shipped cycle and guard the 15 % last resort is shorter than the guard,
  and without this rule a room blind for a day would deliver no heat at all.

A band room keeps no fraction, having none, and falls to the last resort when it goes blind.

Measured before this was built: a room 3 °C below its target computed a duty of 1.0, remembered it,
and with every sensor quiet a minute later held the relay closed for 100 % of six hours.

## The relay's own state reaches the decision

Each pass reads every heater switch out of the state machine and gives the loop the switch's own state
and the switch's own last-changed stamp, before anything is decided from either.

- **A state that is unknown or unavailable is never acted on.** A relay off the mesh is left alone
  rather than fought, and the loop keeps what it last commanded.
- **The guard is read against the switch's stamp**, not against a time this integration stores. So the
  guard is right when a person flips a wall switch, and nothing has to survive a restart for it to be
  right. A switch whose stamp is the restart moment holds the guard for one period after a restart.
- **A relay that did not take a command is commanded again on the next pass the guard allows**, which
  is at most once per guard period. There is no attempt counter and no backoff, because no relay has
  been observed refusing a command here.
- A heater found closed in a room that heats nothing is opened, which is the one path a room with no
  reading had no way to reconcile.

## Refusing a heater another room already drives

The setup dialog refuses a heater that appears in another room's entry, and the refusal names the room
holding it. Both the first dialog and the change dialog check it, and a room's own entry is left out of
the check so changing a room does not read its own heaters as somebody else's.

Measured on this loop: two rooms holding at different duties over one relay send 384 commands a day
against the 192 a single loop sends, and 96 of 191 gaps between commands are shorter than the
five-minute guard, the shortest being nothing at all. Each loop counts only its own changes, so the
contact protection is defeated outright.

## What was taken from Versatile Thermostat, and what was not

Versatile Thermostat is MIT, copyright 2022 Jean-Marc Collin, as this project is MIT. Two mechanisms
are taken as mechanisms and written here in this project's own terms; **no lines were copied, so no
notice travels with them.** Read at its default branch on 2026-09-25.

- **Skipping an undeliverable transition, and publishing the realised fraction**, from
  `cycle_tick_logic.py`. It answers each tick with turn on, turn off or skip, carries the skipped
  duration as a penalty, and publishes the penalty as the fraction delivered. Its accumulating penalty
  is not taken: the rounding here is decided from the duty before the transition, which reaches the
  same figures at the extremes without carrying a debt between cycles.
- **Taking the time a switch has held its state from the entity's own last-changed stamp**, from the
  `last_change` property in `underlyings.py`, which falls back to nothing where the entity has no
  state.

Deliberately not taken: its keep-alive and its repair manager, which re-send commands; its safety
mode, which reduces heat and declines to act below half duty, the opposite of what a cabin needs; and
its load shedding.

## What the integration does not do yet

- The mode table inside the integration's own dialog is not built, and neither is the rule that
  switches it off the moment the add-on connects.
- The config flow is exercised only as far as compiling. The entity and the action registration are
  proved against a running Home Assistant; the rest of the rules are proved on their own.
- **Nothing here has been run against a live core since the power meter, the third kind of room and
  the refusals were built.** The rules are proved on their own, and the cabin is where they are
  proved as a house.

## What each option of the presence dropdown means

The heating reads one Home Assistant dropdown to learn whether anybody is at the cabin. What each of
its options means is a stored mapping: one row per option, carrying the option text exactly as Home
Assistant reports it and the state that option stands for. A read of the dropdown is a lookup in that
mapping and nothing else.

**The state side of a row is an identifier, and the text side is free to change.** `PresenceState`
pins its ordinals and no member may be renamed or removed, because the settings file carries the
member's own name. The option text belongs to whoever edits the helper, so renaming an option in Home
Assistant costs the text in one row and leaves the state it stands for untouched.

**Words are read once, at setup, and never on a read.** `PresenceVocabulary` holds the lighting
engine's vocabulary, word for word: four groups of words in English and Norwegian, matched as a
substring of the lower-cased option text, with an unmatched option classifying as everyday. A test
asserts the two copies are still identical, so a word added on one side and not the other is a
failure rather than a drift. The words cover four of the states. Planned to arrive, on the way and
temporarily away carry no word, so an option meaning one of those is picked by hand on the settings
page.

**`SetsUpThePresenceMap.FromTheOptionsItOffers` is the one place a word is read**, it runs only while
nothing is mapped, and it reads the dropdown's own `options` attribute. It refuses to map a helper
whose options it cannot tell apart: the bar is an everyday option and at least two states between
them, so a helper offering eco, comfort and boost is left for a person. That is the lighting engine's
own bar, and it is there because a mapping guessed from words that mean nothing on this helper would
pause or heat a cabin on no evidence.

**A value no row names still selects the home mode**, which is the expensive one. The alternative
lean, reading an unmapped value as away, takes a cabin with people in it cold. What the fall-through
costs is therefore paid deliberately, and it is reported rather than silent: the value itself reaches
the activity record and a card in Home Assistant, named beside the helper it came from, so the option
to map is readable without a log. The card is latched on the value and not on a flag, so the same
value every minute raises one card while a second, different value raises its own. Mapping the
dropdown clears the latch, because the value that was refused a moment ago may now have a row.

**An unmapped dropdown is the expensive state, not a neutral one.** Every value it reports falls
through to the home mode, so an empty cabin is heated while nothing on any screen says why. That is
what the card exists to make visible, and it is why mapping runs on the first pass that can see the
options rather than waiting for somebody to open the settings page.
## The code an answer arrives under

Three answers a call can get, and each arrives under a code of its own. The codes are what tells them
apart, so nothing has to read the sentence.

| Case | Code | Raised as |
|---|---|---|
| An action that is not registered | `not_found` | the platform's `ServiceNotFound` |
| A field outside its bound | `invalid_format` | a `vol.Invalid` from the field's own validator |
| A room's own refusal | `service_validation_error` | `ServiceValidationError`, from `Refused` |

`Refused` is a plain exception carrying the one reason, so it stays clear of the `vol.Invalid` shape a
bad field raises. `climate.py:_act` is the one point every action reaches the thermostat through, and
it is where a refusal becomes the platform's `ServiceValidationError`. A second conversion elsewhere
would let one route answer under a different code than the rest, which is why there is exactly one and
a test holds it to that function.

The order is Home Assistant's own, read from `websocket_api/commands.py` at 2026.9.1: `ServiceNotFound`
first, then `vol.Invalid`, then `ServiceValidationError`. `ServiceNotFound` sits under
`ServiceValidationError`, so that order is load-bearing — reversing the last two would answer a missing
action under the refusal's code.

The sentence is unchanged in every case. A switched-off room still answers "The room is switched off."
and a room with no reading still answers "The room has no temperature reading."

What this buys: the add-on reads `service_validation_error` as the marker of an answer the room itself
gave, so a refusal now reaches the activity record carrying its reason instead of being discarded as a
failure. The add-on's marker needs no change.

The classification is proved against a replica of that ordered handler, written into
`tests/test_what_each_answer_is_told_apart_by.py`. A replica settles which code each shape falls to and
never what goes on the wire; the wire is settled at the cabin.

---

# What the cabin showed on the presence mapping

Measured on the cabin on 2026-09-25 at Supervisor 2026.09.3, amd64, with the add-on at `f25dfa9` and
the integration left where it was at 0.1.0. Two rooms are under the integration, Cloakroom and
Bedroom, and no mode carries a typed temperature.

## The mapping is made once, written where it is made, and readable from the log

The cabin's dropdown offers five Norwegian options. The first pass that could see them mapped all
five, and the line names the entity and every row: `Borte=Away`, `Planlagt=Everyday`,
`På vei=Everyday`, `Tilstede=Everyday`, `Midlertidig borte=Away`. So the whole mapping is readable
without the settings page.

**A restart settles both halves of the rule.** The settings file's own save stamp is the minute the
mapping was made, and the pass after a restart writes no mapping line and no unrecognised value. The
words are read while nothing is mapped and never again, measured in both directions on one house.

**The mapping line carries the caller's logger category**, `Driving.DrivesTheRooms`, because the logger
is handed in. Searching a log for the class that reads the words finds nothing.

## Two of the cabin's five rows carry the wrong state, and that is the vocabulary's limit

| Option | Seeded state | Mode that follows | What the option means | Agrees |
|---|---|---|---|---|
| Borte | Away | Away | away | yes |
| Planlagt | Everyday | Home | planned to arrive, which means away | no |
| På vei | Everyday | Home | on the way, which means home | yes, by coincidence |
| Tilstede | Everyday | Home | at the cabin | yes |
| Midlertidig borte | Away | Away | temporarily away, which means home | no |

Planned to arrive, on the way and temporarily away carry no word in the lighting engine's vocabulary,
so an option meaning one of those falls through to everyday or, where another group's word occurs
inside it, to that group. `Midlertidig borte` contains `borte`, which is why it reads as away.

**The two that disagree err in opposite directions**, so neither is a safe default: `Planlagt` heats a
cabin nobody has reached, and `Midlertidig borte` cools a cabin somebody stepped out of. Both need a
row corrected on the settings page, which is what the page is for.

**A seeded mapping is a starting point and not an answer.** On a five-option Norwegian helper, three
rows landed right and two did not, and the log is the only place that difference is visible.

## A room with no reading at all is never driven

**The strongest finding of the visit, and it belongs to neither half's newest change.** A room with no
reading carries its away cell on, because the dial on the heater is the only frost protection such a
room has. Under the away mode that cell never fires.

The chain is three steps and each is measurable. `ThermostatNow.From` answers null where the climate
entity publishes no `temperature` attribute. A pass keys its thermostat table on what that projection
answers. A room missing from the table is skipped before the driven count reaches it.

**The integration publishes no target for a room with no reading**, which closes the chain:
`climate.cloakroom` carries a `temperature` attribute and `supported_features` 385, `climate.bedroom`
carries no `temperature` attribute and `supported_features` 384. Bedroom held "Off, the mode says
so." unbroken across the mode moving to away.

So the whole on-or-off path is unreachable on a real house, and the room that most needs frost
protection is the one that cannot get it. What would settle the fix is whether the projection should
treat a missing target as no target rather than as no thermostat.

## A pass runs before the connection opens, and reports on an empty house

Between "Connecting to Home Assistant websocket" and "The connection to Home Assistant is open" one
pass runs over an empty state table. Measured on all four starts in one day's log. It reports the away
mode, which is what no evidence means, and "Outdoor sensors all out. No forecast chosen", which is
wrong on a house that has a forecast entity configured: the pass cannot see the entity yet.

**That pass's card is lost and never retried.** `persistent_notification.create` is refused with
`no_connection`, the log says the card did not arrive and the report is still in the record, and the
latch that stops the same card every minute is set by the attempt rather than by the success. The next
pass, with the connection open and the sensors still out, says nothing. The one standing card on the
cabin dates from a moment the sensors went out while the add-on was already running.

So a start with the outdoor sensors already out leaves no card at all, and the add-on's first word
about a house is about no house.

## A local rebuild takes 16 seconds with warm layers, and the version cannot tell builds apart

The first install measured 52 seconds. A rebuild of the same folder with only the source changed
measured 16 seconds, because every layer up to the source copy is cached. The manifest version and the
assembly version are both fixed, so neither answers which build is running.

**A behaviour only the new code can produce is what answers it.** Here that is the mapping line: it
cannot be written by a build that reads words on every pass.

---

# What the cabin showed when the refusal code arrived

Measured on the cabin on 2026-09-25, core 2026.9.1, Supervisor 2026.09.3, amd64. The integration went
from `b1265e4` to `d49ae92`; the add-on was left where it was.

## The three codes hold on the websocket, and the sentence does not survive it

| Case | Before | After |
|---|---|---|
| A room's own refusal | `invalid_format` | `service_validation_error` |
| A field outside its bound | `invalid_format` | `invalid_format` |
| An action that is not registered | `not_found` | `not_found` |

Both directions were measured against the same house, the first three before the overwrite and the
second three after it, so the refusal is separable by its code where it was not before.

**Home Assistant prepends "Validation error: " to a `ServiceValidationError`.** The sentence the
integration raises is unchanged, and what a caller reads on the wire is
`Validation error: The room has no temperature reading.` A reader matching the sentence exactly finds
nothing.

## A refusal over the ordinary web request route answers 500

The websocket is not the only way into an action, and the other way is where this costs something.

| Case | Web request route |
|---|---|
| A room's own refusal | **500, "Server got itself in trouble", full traceback in the core log** |
| A field outside its bound | 400 Bad Request |
| An action that is not registered | 400 Bad Request |

The services view catches `vol.Invalid` and `ServiceNotFound` and answers a bad request. A
`ServiceValidationError` is neither, so it leaves the handler as a server fault. The traceback ends at
`climate.py` where the refusal is converted, and the room is behaving correctly throughout.

**What settles it is a route that answers under a code and a status at the same time.** The websocket
needs `ServiceValidationError` to separate a refusal from a bad field, and the services view needs
`vol.Invalid` to answer anything but 500. Nothing in the platform is both today.

## The add-on reconnects in place, and its wait is the whole delay

Measured across one core restart. The restart was asked for at 19:45:36 UTC and the core answered
again at 19:52:30, 6 min 54 s later. The add-on retried at 19:49:31, 19:50:51 and 19:52:11, each 80 s
apart and each a 502 from the Supervisor's websocket proxy, then connected at 19:53:31 — **61 seconds
after the core was ready**, because the flat wait is what decides when the next attempt lands.

The add-on's process survived. Where the log says the connection went down "(Error)" it retries in
place; where it says "(Client)" the process ends and the Supervisor starts it again. Both shapes
occurred on one day.

## Asking the Supervisor to restart the core blocks until it is back

The restart call does not return until the core answers, so it cannot time anything. Poll the core's
own address from a second call instead.

## A git archive from a Windows checkout writes CRLF into every file

`git archive` on a checkout with `core.autocrlf` true converted every file to CRLF, including files
the box already held byte-identically, and `.gitattributes` pinning `*.py text eol=lf` did not stop
it. Hashing the staged copy against the repository's own blob hashes is what caught it: 0 of 21
matched. Copying the working-tree files gave 21 of 21.

## A core restart clears the cards, and the latch does not put them back

Home Assistant held one card before the restart and none after it. The condition behind it, every
chosen outdoor sensor being out, was still true. The latch that stops the same card every minute is
set for as long as the condition holds, so nothing raises it again, and the cabin is left with no card
for a condition that has not gone away.

**Anything that restarts the core therefore costs every standing card.** Raising a card again after a
reconnection is what would close it.

---

# A room with no target, and a card that did not arrive

## What tells a room with no target from a thermostat that is not ours

Two attributes mark one of this integration's thermostats: `integration_version` and `room`. Nothing else
in a house publishes them, and `RoomsFromTheIntegration.Ours` already finds the rooms by that pair. The
projection in `ThermostatNow.From` now refuses a state on the same pair and on nothing else, so a room the
projection answers for is a room the settings hold.

**A missing `temperature` attribute is a value that is absent, never a room that is absent.** The
integration answers no target for a room set up with no sensor of its own and no neighbour to borrow from,
because its heater's own dial holds one, and it publishes the same fact beside it as `no_reading_at_all`.
Both come from one field of one thermostat, so within one state they cannot disagree.

`ThermostatNow.Target` is therefore `double?`. That is what makes the fault unrepeatable: every path that
reads a target now has to say what it does when there is none, and the compiler refuses the ones that do
not.

**What a room with no reading does under the away mode.** Its away cell reaches the heater as a switch,
which is the frost protection such a room has. The cell is one per mode, so moving the house off away
switches the room off again.

Three paths answer for an absent target. The hold does nothing, because it weighs candidates against the
temperature the room is holding and there is none. The learning does nothing, because both watchers measure
against the temperature the room was asked to hold. What the settings page shows under a room's "Now"
leaves the room out, because that block is temperature-shaped and a zero in it would read as a temperature.

## A pass runs only once the connection is usable

A pass reads whatever the last thing heard from Home Assistant left behind, so a pass before the connection
opens reads an empty table. It reports no presence, every outdoor sensor out and no forecast chosen, none of
which it can see yet, and on a house with a forecast entity configured all three are wrong.

`ConnectionToTheIntegration.OnePassAsync` now runs no pass while `CoreConnection.IsOpen` is false. Nothing
is lost by the skip: opening the connection raises `SomethingChanged`, which asks for a pass of its own, and
the pass a minute is behind that. The request made as the add-on starts is kept, because it is what covers a
connection that opened before the subscription to that event was in place.

## A card refused for want of a connection is raised again

Every chosen outdoor sensor failing is said once while it stays true, and again the next time it becomes
true. The latch behind that is now set by the card arriving and never by the attempt:
`ReportsWhatHappened.ReportAsync` answers whether anything about the report is outstanding, false only where
a card was needed and did not reach Home Assistant, and `DrivesTheRooms.ReportTheOutdoorSensorsAsync` sets
its latch from that answer.

**What the old order cost:** a cabin whose sensors were already out when the add-on started got no card at
all. The first pass raised one, the connection was not open, the call answered `no_connection`, and the
latch was already set, so every later pass stayed silent while the report sat in the record nobody reads.

## A card lost to a core restart is put back

Home Assistant holds no cards after a core restart, and this side cannot see what it is still
showing. So the latch has three cases to serve, not two: a card refused for want of a connection is
raised again by the next pass, a card that arrived is not repeated every minute, and a card whose
condition still holds is raised again once the connection comes back.

`CoreConnection.TimesOpened` counts the connections that have opened and read the house, and
`ConnectionToTheIntegration` compares it against the number it last saw. **Counted rather than
watched for:** a connection that went and came back between two passes leaves no transition to see,
and the reconnection measured on the cabin took 61 seconds against a pass a minute.

The first pass over a connection this loop has not seen before calls
`DrivesTheRooms.TheConnectionCameBack`, which clears the outdoor-sensor latch. Re-raising a card
replaces its own card rather than stacking a second, because every card this add-on raises carries a
stable id built from its title.

## Two calendars: one holds the arrivals, the other is the record

Home Assistant lets anything do exactly two things with a calendar. `calendar.create_event` adds an entry, and
`calendar.get_events` reads the entries between two moments. There is no action that changes an entry and none
that removes one, confirmed against `calendar/services.yaml` and the integration's own documentation page on
2026-09-25. **That absence is what makes a calendar a record**: an entry written there cannot be quietly
rewritten by the software that wrote it.

**The arrivals are read over a stretch of time and never off the entity's state.** The state is on or off for
an event happening now, and its attributes describe the next event alone. A cabin with two visits ahead of it
would therefore show one and hide the other. `calendar.get_events` is registered with
`supports_response=SupportsResponse.ONLY`, so the websocket call carries `return_response: true` and the answer
comes back under `result.response`, keyed by the entity it came from, each holding an `events` list. An event
in that list carries `start`, `end`, `summary`, `description` and `location` and **no identifier at all**, which
is why nothing downstream can key on a read entry.

**The stretch is 14 days.** The longest warm-up a room can plan is bounded by the lowest rate a room starts on,
0.5 °C an hour, planned at four fifths of it: sixteen degrees of rise is forty hours. Fourteen days clears that
several times over, and a longer stretch costs nothing, because only the nearest arrival is planned against and
`WarmUp.DueNow` refuses to start until its own moment comes round.

**The reading is taken again every 15 minutes, not on every pass.** A pass runs once a minute and an arrival
moves when a person edits a calendar, so reading per pass would be 1440 calls a day. A change this misses by a
quarter of an hour is a change made too late to plan a warm-up around. A read that does not go through leaves
the last one standing: an arrival already known is a better deadline than none while the connection is away.

**An entry written as a whole day is not an arrival.** Such an entry comes back as a date with no time, and
reading it as midnight would start the heating the night before and waste a day of electricity. It is skipped,
and the setting's own help says so.

**A calendar arrival warms each room to its home temperature, whatever mode is in force.** An arrival is people
coming to a cabin that has been standing cold, so the mode that will be in force when they are there is the one
the room is warmed to. The day profile's own `WarmBy` entries are untouched and still run only under that mode.

### Which calendar may hold the record

The record goes to a calendar Home Assistant keeps itself and no other. **Capability cannot say which one that
is**: a local calendar declares create, delete and update, and other platforms declare create as well, so a
feature list does not separate them. The entity registry does — `RegistryEntry.as_display_dict` carries the
entity id as `ei` and the integration behind it as `pl` — and `config/entity_registry/list_for_display` serves
it, leaving out disabled entities.

That read is taken once per connection and **only where the house reports a calendar at all**, so a cabin with
none never sends it. A read that does not go through leaves the platforms unknown, and an unknown platform
reads as not local: the record setting then offers nothing rather than offering something it cannot vouch for.

### How a warm-up already recorded is known

**A finished warm-up cannot be seen from outside.** The integration clears the thermostat's `warm_up` attribute
the moment the deadline passes (`_retire_finished_work` in `core/thermostat.py`) and keeps its verdict in
`last_warm_up`, which it publishes nowhere. So the add-on remembers what it asked for instead, in a note beside
the settings, and a restart between the asking and the deadline is exactly what that note exists to survive.

A row is keyed on **the room id and the deadline**. Asking twice for one warm-up therefore replaces a row
rather than adding one, and the row is removed only once its entry is in the calendar. An entry cannot be taken
out of a calendar again, so a second one would stand for ever.

**The entry is created before the row is removed**, in that order. A failure between the two writes a second
entry after a restart; the reverse order loses an entry whenever the connection is down, which is routine where
a failed write to `/data` is not.

**The verdict is taken on the first pass that sees the deadline gone**, and then kept on the row. A write
retried hours later would otherwise record a temperature the room reached long after it was due.

A row nobody could write down is dropped after 7 days, which bounds the note while the connection stays away.
A calendar that answers `not_found` or refuses the entry is never going to take it, so the row is dropped and
one card is raised; anything else is the connection, and the row waits for the next pass.

### What happens when a calendar is unset or gone

- **No arrival calendar**: no deadline is planned against, nothing is asked of Home Assistant, and the
  calendars tab shows the setting as not chosen. The pass over the rooms is unaffected.
- **An arrival calendar the house does not report**: one card, said once while it stays true and again the next
  time it becomes true, latched on the card arriving in the same way as the outdoor-sensor card.
- **No record calendar, or one the house does not report**: a finished warm-up writes nothing, one card is
  raised, and the row is dropped. Said once, not once a minute.

### The chosen values

| Value | What it is | Why it is that number |
|---|---|---|
| 14 days | how far ahead arrivals are read | past the 40-hour worst-case warm-up several times over |
| 15 minutes | how long a reading stands | a change missed by this much is too late to plan around anyway |
| 7 days | how long an unwritten row is kept | bounds the note across a long outage |
| `local_calendar` | the platform the record may use | the integration Home Assistant keeps a calendar under itself |
---

# What the cabin showed when the mode control arrived

Measured on the cabin on 2026-09-25 at Supervisor 2026.09.3, core 2026.9.1, amd64, with the add-on at
`046df7c` and the integration left where it was at 0.1.0.

## The add-on runs on UTC, and the household's clock is taken from it

`Program.cs` reads the household's zone as `TimeZoneInfo.Local`, and inside the container that is UTC.
Two measurements agree. A mode chosen for one hour at 21:05:39 UTC drew its expiry as `Fri 22:05`,
which is 00:05 on the cabin's own clock. The add-on stamps a log line 21:05:39 where the Supervisor
stamps the same event 23:05:39.

The runtime base is Alpine and the Dockerfile adds `icu-libs` alone, so no zone database is present and
no zone name can be resolved whatever the Supervisor passes in.

**Every wall time in the day profile is therefore placed two hours off in summer**, and the expiry a
person reads is two hours early. What would settle it is the zone database in the image, or the
household's zone read from Home Assistant's own configuration rather than from the process.

## A save on a real house works end to end, and both directions were timed

| Step | Measured |
|---|---|
| The store accepting a mode chosen by hand | The save button returns to disabled with no refusal |
| The pass that follows it | 35 s, reporting `Mode: DayProfile` |
| The pass that lets go after the mode is put back | 30 s, reporting `Mode: Away` |

**The save reaches the file and not only the store held in memory.** The start report names the settings
file's own save stamp, and across a restart taken four minutes later it had moved from 19:13:26Z to
21:07:07Z, the moment of the save, with the mode reading back as the one presence answers.

The page states the mode, its source and the expiry from the record one pass writes, so the readouts
stand still until that pass runs: for 35 seconds after a save the card says the old mode is in force,
and it is right.

**The report names the enum member and the page names the words.** A log line and a card say
`DayProfile` where the page says `Day profile`.

## A mode change drives nothing until a mode carries a temperature

No mode on this house has a temperature typed against it, and neither room moved across a mode taken to
the day profile and back: a 17.0 °C target held throughout in the room with a reading, and no target was
published at all in the room without one. So a mode chosen by hand is safe to try on a house whose mode
table is empty, and proves nothing about what a mode is worth in a room.

## The page answers its own port with nobody signed in

A request to the add-on's port from another add-on container is served in full, and the log records
`AuthenticationScheme: HomeAssistant was not authenticated` for it. No page and no endpoint carries an
authorisation requirement: the identity supplies a display name and nothing more, and the guard is the
container network rather than the sign-in. That is the route a session reads and drives the page by, and
it is also what the manifest's missing ports key is holding shut.

**The box refuses SSH port forwarding**, `AllowTcpForwarding no` in the terminal add-on's own
configuration, so a browser on another machine reaches the page over a remote pipe per connection rather
than a forwarded port.

## Reading the add-on's own files needs Docker, and Docker is refused

The terminal add-on runs in protection mode, so `docker` is refused and `/mnt/data` is not mounted. The
add-on's `/data` cannot be read or written from a session at all. The settings file, reported at start as
`/data/state/heating-settings.json`, is therefore readable only through the page, and the page is the only
window onto what a save wrote.

## The household clock, and what happens when its zone will not resolve

Every wall time is decided on and shown in one zone, read once in `Program.cs` and handed to everything that
needs it as `TheHouseholdClock`. The zone id comes from the `TZ` variable the Supervisor sets in every add-on
container from its own timezone value. `TimeZoneInfo.Local` is not the read: it resolves from the same variable
and falls back to UTC without saying so, which is the fault this arrangement removes.

**The image needs `tzdata`.** The runtime base is a Microsoft .NET Alpine image, and those stopped bundling the
zone database. Home Assistant's documentation promises the database is present in Alpine add-on images, and that
promise covers Home Assistant's own base images rather than this one. Without the package every zone name fails to
resolve, so the zone arrives set and unusable. 1.5 MiB installed.

**A zone that does not resolve raises a card and never becomes UTC quietly.** The report is
`HouseholdZoneNotResolved`, it names the zone it was given, and it says times will be wrong until it is fixed. A
zone nothing named at all is unresolved too, so a Supervisor that stopped setting the variable is not silence. The
card is raised from the pass over the rooms rather than at start-up, latched on the card arriving rather than on
the attempt, because at start-up the connection to Home Assistant is not open yet and the card would never arrive.
The clock still runs meanwhile, on the process's own zone, and says so.

**A stored instant is never converted.** Every recorded moment stays the instant it was, and the household's zone
is a rendering applied where a person reads one or where a wall-time rule is decided against one. A boundary, a
warm-up deadline, a hand-set mode's expiry and a room's reading time are renderings; the journal, the settings
document and the warm-up notes are instants.

**The log carries the household's clock and an offset.** One enricher puts two stamps on every event: the console
template prints the date, the time and the offset to the second, and the durable file keeps its milliseconds. Both
are rendered invariantly, because a log line is read by a machine as often as by a person. `DurableLogFormatter`
therefore differs from the lighting engine's copy in one place, its timestamp, and the two are otherwise still kept
in step by hand.

**A mode and a temperature's source read as words.** The report keeps the enum member's own name, because the
activity journal holds it and a change to the words must not split one history in two; the words are looked up in
`ReportWords` when the report becomes a line. That lookup returns nothing for a member it has no words for, so a
member added without words fails a test rather than falling through the describing switch's catch-all arm and
reading as a presence fault.

---

# Reaching the cabin from a network that is not its own

Measured 2026-09-27 from the other house's network. The cabin was on core 2026.9.1 and the other
house on 2026.9.3, which is what made the two separable below.

## The cabin's subnet is not routable, and no box on the other network bridges it

The cabin's address answers on neither its SSH port nor its core's port. The workstation's routing
table carries the default route, the local network and nothing for the cabin's. **The other house's
own box is no use as a jump host**: its table holds the default, its local network and its two
container networks, and no route to the cabin either.

The cabin's websocket interface does answer over its own tunnel, so what a visit from the other
network lacks is not a route. It lacks a credential the cabin accepts, because the add-on's token
belongs to a user carrying Home Assistant's local-only restriction and is refused from away, and it
lacks a shell, which no interface provides.

## The version greeting separates the two houses at no cost

The two public hostnames are easily confused, and the shared credentials document pairs the cabin
with the wrong one. **The websocket greeting names the core version before any credential is sent**,
so it identifies a box without spending one of the five refusals that earn a ban: a connection to
`/api/websocket` answers `auth_required` carrying `ha_version`, and the two houses were on different
core versions.

`/auth/providers` does not separate them. Its `preselect_remember_me` reads false through a public
hostname and true on a local address, which is a property of where a request comes from rather than
of the box it reaches.

## The add-on's token is refused off the cabin's own network

The token the add-on authenticates with carries Home Assistant's local-only restriction on its user.
Over the websocket the answer is `auth_invalid` with `User cannot authenticate remotely`; over the
ordinary web request route it is 401. **Both count towards the ban**, so a token tried from the wrong
network costs two of five and answers nothing about the house.

## No interface writes a file, so a token is not a substitute for a shell

Staging a commit into the add-on folder and rebuilding the add-on both need a shell on the box.
Nothing in Home Assistant's API or the Supervisor's writes a file, so an authenticated session from
away would carry the reading but not the deployment. The terminal add-on's own page is reached
through the frontend and needs a sign-in, which is a person's step.

**A deployment to the cabin is therefore gated on being on its network**, and the check that settles
it before anything else is attempted is whether the cabin's address answers on its SSH port.

---

# What the home house showed on the first install there

Measured on the home house on 2026-09-27: core 2026.9.3, Supervisor 2026.09.3, Home Assistant OS
18.2, generic-x86-64, amd64, Docker 29.6.2. Both halves at `e750fd7`, whose bytes under `integration`,
`adaptive_heating` and `addon` are the same as `6dd91eb`. 4999 entities, 8 climate entities, 304
switches, 80 temperature sensors, 17 calendars. No room was set up, because no heater on this house is
free to drive.

## The household's zone resolves, and the clock is the household's

The add-on was asked to start at 12:45:11Z and its first log line is stamped
`2026-09-27 14:45:12+02:00`. The offset is the household's and the instant is the Supervisor's stamp
of the same event, so the zone database in the image resolves `Europe/Oslo` and no
`HouseholdZoneNotResolved` card is raised. The add-on's container carries `TZ=Europe/Oslo`.

## The minutes a visit costs are the box's, not the design's

| Step | Home house | Cabin |
|---|---|---|
| Building the local add-on | 43.3 s | 52 s |
| The core away, measured by polling its own address once a second | 94 s | nearly seven minutes |

The outage is the interval between the last answer and the next: the core's own address answered at
12:48:11Z, refused from 12:48:12Z to 12:49:44Z, and answered again at 12:49:45Z. A blocking restart
call reported 1 min 37 s for the same event, which includes the Supervisor's own work either side.

## The reconnection wait escalates rather than holding at 80 seconds

Across one core restart the client waited 10 s, then 20 s, then 40 s, then 80 s, each attempt
answering 502 from the Supervisor's websocket proxy. A measurement taken during a seven-minute outage
sees only the last of those, which is why the wait reads as flat there.

The consequence survives the shorter outage: the core was ready at 14:49:45 and the add-on connected
at 14:50:47, **62 seconds later**, because by then the wait was already 80 s.

## On a house with no room, the five actions do not exist

`async_setup` declares the five actions, and doing it there rather than from the climate platform is
what is meant to make them exist where no room loads. A house with no room at all does not reach that
function: `CONFIG_SCHEMA` is `config_entry_only_config_schema` and nothing names the domain in YAML,
so the component is never set up and `get_services` carries no `adaptive_heating` entry.

So the guarantee covers a room whose entry fails to load, and not a fresh install. An automation
naming an action is validated against nothing until the first room exists.

## A standing card is not an entity, so one kind of check cannot fail

Home Assistant's notifications stopped being entities. A look for `persistent_notification.*` in the
state list answers zero whatever is standing, so a check written that way passes on a house with cards
and on a house without. `persistent_notification/get` over the websocket is the read that answers.

Read that way, the card the add-on raises is there: `adaptive_heating_outdoor_sensors_all_out`,
titled `Outdoor sensors all out`, raised on the first pass that had a connection and a reason.

## An empty outdoor sensor list is not the same as every sensor out

With `outdoor_sensors: []` the pass says nothing about outdoor sensors at all. With one name that
resolves to no entity it reports them all out and raises the card. Every earlier measurement was taken
on a house with sensors named, so the empty list had never been exercised.

## The name another add-on reaches the page by turns every underscore into a dash

`local-adaptive-heating:8099` answers. `local-adaptive_heating:8099` and `local_adaptive_heating:8099`
do not resolve. The container is `app_local_adaptive_heating`.

The document is 6771 bytes and titled `Heating settings`, the stylesheet 16323 bytes, the theme script
3263 bytes and `blazor.web.js` 200538 bytes. The circuit's negotiate endpoint hands out a connection
token, and each of the five settings sections answers 200.

## The cache-busting token is the same for every build of one version

The served document names the stylesheet `heating.css?v=0.1.0-previe`. `AssetToken` reads what follows
the plus sign in the informational version and cuts it to twelve characters, so that two deploys off
one preview do not share a URL. Nothing appends a commit sha: `addon/Directory.Build.props` sets
`Version` alone and no source revision is included, so the token is the version number cut to twelve
characters.

A browser holding that stylesheet keeps it across a rebuild, which is the case the token exists to
cover.

## This house heats by ways this design does not drive

The design drives a heater as a relay on a duty cycle, from the switch or input boolean domains. What
this house has:

- **A heat pump**, behind `climate.office_heat_pump` over an infrared bridge. Its only switch,
  `switch.office_heat_pump`, is the main breaker and sits in the garage area. Cycling a heat pump on
  a relay is not what a heat pump is for, and that switch cuts it.
- **Waterborne and underfloor heating** behind climate entities of their own,
  `climate.cellar_bathroom_underfloor` on a Z-Wave relay and `climate.cellar_playroom_thermostat`.
  This design neither drives nor reads a climate entity that is not its own.
- **One panel heater on a plain switch with power measurement**, `switch.annexe_kitchen_heater` with
  `sensor.annexe_kitchen_heater_current_power`, which is the cabin's shape exactly. Two thermostats
  already drive it: Home Assistant's own generic thermostat and `better_thermostat`.
- **Two terrace heaters on switches**, outdoors, where no room temperature is held.

So the shape the design assumes is the cabin's, and on this house the one heater that matches it is
claimed twice over. What a room would need here is a way to hold a target through a climate entity
somebody else owns, which is a different mechanism from a relay and a duty cycle.

## The claim check sees only this integration's own rooms

`heater_already_claimed` compares a heater against the heaters of this integration's other rooms and
against nothing else. A switch already driven by Home Assistant's generic thermostat, or by
`better_thermostat`, is therefore claimable with no warning, and three loops would fight over one
relay. A house where every heater is free cannot show this.

## A temperature sensor can report an impossible value, and no rule catches it

`sensor.garage_door_air_temperature` reports 127.68 degrees Celsius with device class
temperature, an uninitialised Zigbee attribute rather than a reading. The sensor picker offers every
sensor of that device class, so a room can be built on it.

The check carries no absolute bound. Its exclusions are quiet, stuck, far from the others, and both of
a disagreeing pair: far from the others needs others, and stuck needs the value to hold. A room with
this as its only sensor holds 127.68 as its temperature and never heats, or falls to the stuck rule
and reads as a room with no reading at all.

## Where the helper is the lighting engine's own, every row of the seed lands right

This house's dropdown is `input_select.house_presence`, offering Home, Away, Sleeping and Guests. The
vocabulary classifies them as everyday, away, night and guest, which is what each one means, and the
bar is met with four distinct states.

Four of four against three of five, and the reason is the source: the vocabulary was copied from the
lighting engine and this is the lighting engine's own helper, so the words match by construction. A
helper written without that vocabulary in mind is the case the settings page exists for.

## The Supervisor's own path spends no refusal while other addresses spend theirs

Every read of this house went through the Supervisor's path, which needs no token and cannot earn a
ban, so the visit spent none of the five. Three refusals were spent against the house meanwhile by
other addresses: a browser requesting a media player proxy URL with a stale signature three times in
one second, and an external address requesting `/api/`. The counter is per address and a stale
signature spends one as surely as a wrong password.

## Two differences from the cabin worth knowing before a visit

**Docker is reachable from the shell here**, so an add-on's own persistent directory can be read
without the page. The cabin's terminal add-on runs in protection mode and refuses it.

**No thermostat lost its target across the restart.** All eight climate entities held the value
recorded beforehand, where a restart at the cabin knocks two rooms to the temperature written in their
configuration.

## The manifest carries no `image` key

The store's own `build` field now reads true without any on-box edit: `adaptive_heating/config.yaml`
never names an image to pull. A store install builds the add-on on the box the way the by-hand
install above always has, so the line a box used to carry commented out is gone from the procedure,
not just from the file.
