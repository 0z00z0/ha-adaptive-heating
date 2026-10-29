<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/hero-dark.webp">
  <img src="docs/images/hero-light.webp" alt="Adaptive Heating for Home Assistant: warm rooms from the heaters already in the house." width="1280">
</picture>

<h3 align="center">Every room warm on time. Cooler when nobody needs the heat.</h3>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/dashboard-dark.webp">
  <img src="docs/images/dashboard-light.webp" alt="The dashboard shows the house mode, a timeline for each room and every room's temperature." width="1280">
</picture>

<table>
  <tr>
    <td width="50%" valign="top" align="center">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/room-dark.webp">
        <img src="docs/images/room-light.webp" alt="A room page shows the living room at 20.6 °C, heating to 21 °C, with a slider for each part of the day." width="100%">
      </picture>
      <br>A room's day
    </td>
    <td width="50%" valign="top" align="center">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/schedule-dark.webp">
        <img src="docs/images/schedule-light.webp" alt="The schedule shows morning from 06:30 at 20 °C, then evening and night." width="100%">
      </picture>
      <br>The schedule
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top" align="center">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/house-modes-dark.webp">
        <img src="docs/images/house-modes-light.webp" alt="The house modes page shows the drop-down option Night set to mean Sleep, with night setback on." width="100%">
      </picture>
      <br>House modes
    </td>
    <td width="50%" valign="top" align="center">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/activity-dark.webp">
        <img src="docs/images/activity-light.webp" alt="The activity page lists what happened today, such as the bedroom set to 19 °C by Alex." width="100%">
      </picture>
      <br>Plain answers
    </td>
  </tr>
</table>

## What it does

- **Warm on time.** Set 20 °C for 06:30. Each room learns when to start.
- **Cooler at night.** Warm again by morning in any room with a power meter.
- **One switch for the house.** Pick Home, Away, Sleep or Guests in Home Assistant.
- **Warm for arrivals.** A calendar arrival warms the house first.
- **A room of its own.** A thermostat preset lasts until the next part of the day.
- **Safe when something fails.** An open window stops the heating. A flat sensor battery leaves no room cold.
- **Plain answers.** Each room says why it heats or not.
- **Stays at home.** No account, no cloud.

## Install

The integration gives each room a thermostat. The app holds the schedule and settings.

1. In **Settings → Marketplace**, install **Adaptive Heating**.
2. Open **Settings → Apps → Repositories** and add `https://github.com/0z00z0/ha-adaptive-heating-app`, or [add it in one step](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2F0z00z0%2Fha-adaptive-heating-app).
3. Install the app and start it.
4. Give each room's heaters and temperature sensors the label `heating`.

Needs Home Assistant 2026.11 or newer. The app also needs the Supervisor and a 64-bit board.

[Landing page](https://0z0.xyz/adaptive-heating) · [Issues](https://github.com/0z00z0/ha-adaptive-heating/issues) · MIT licence
