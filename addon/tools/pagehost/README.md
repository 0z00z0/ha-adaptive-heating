# pagehost — a host for the settings page, so a change can be looked at

`AdaptiveHeating.Page` is a Razor Class Library and has no host of its own, so a change to the settings page
could only ever be reasoned about. This runs the real components against the real stylesheet, with a cabin
made up in `HouseSeed.cs`.

```bash
dotnet run --project addon/tools/pagehost
# http://localhost:5299
```

`--port 5300` moves it, so two worktrees can render at once. `--port 0` takes any free port and prints it as
`pagehost listening on …`. **A port that is already taken fails the start rather than quietly moving**, because
a host that lands somewhere unannounced points the next screenshot run at another worktree's page.

## Photographing both themes

The theme is held in the browser under `heating-theme`, so a headless run seeds it and reloads rather than
clicking the picker:

```js
localStorage.setItem('heating-theme', 'light');   // or 'dark'
location.reload();
```

Nothing stored means *follow the device*, which resolves to dark or light from `prefers-color-scheme`.

The sizes to photograph are 1280×900 and 390×844, in both themes.

## The seeded cabin

Four rooms, chosen so every state the page draws is on screen at once: one standing off the plan after a hand
change, one borrowing its neighbour's reading, one learnt number nobody has measured, and one a person has
locked. Change `HouseSeed.cs` to reproduce another state.

## Not in the solution

`AdaptiveHeating.slnx` does not include this project on purpose — a build server should not build or package a
developer tool.

## Two things that are not obvious, and each looks like broken UI

- **`builder.WebHost.UseStaticWebAssets()`.** Static web assets are wired up automatically only in
  Development. Without it the library's `_content/**` 404s and the page renders unstyled.
- **`app.MapStaticAssets()`.** It serves both `_content/**` and `_framework/blazor.web.js`. Without it every
  page server-renders once and no circuit ever opens, so nothing on the page responds.
