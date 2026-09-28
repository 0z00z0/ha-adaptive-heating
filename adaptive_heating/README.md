# Adaptive heating — the add-on

Planning, learning and the settings page. The thermostat each room appears as comes from the integration in
`custom_components/adaptive_heating/`, which is installed separately and works on its own.

## What it serves

One page, reached from Home Assistant's sidebar. Home Assistant's own sign-in guards it, so the page carries
no login of its own and maps no port: there is no address of the add-on's own to reach on the box.

## Installing

Add this repository under **Settings → Apps → Install app → ⋮ → Repositories**, then install
**Adaptive heating**. The Supervisor builds the add-on on the box rather than pulling a published
image, so the install is not instant. The repository's own `README.md` walks every step.

Supported boards are `aarch64` and `amd64`. A 32-bit board is not covered.

## Building the image

Off the box, with the repository root as the build context:

```bash
docker buildx build -f adaptive_heating/Dockerfile --platform linux/arm64,linux/amd64 \
  -t ghcr.io/0z00z0/adaptive-heating:0.1.0-preview.1 --push .
```

The publish carries no runtime identifier, so one compile serves every board and only the runtime base
differs. `version` in `config.yaml` and the image tag are the same string; a mismatch is what makes an
install fail with nothing to pull.

## What survives an update

`/data` is the add-on's own persistent directory. The encryption key ring lives there, so replacing the image
does not log every open page out.

## Looking at the page without Home Assistant

`addon/tools/pagehost` renders the same components against the same stylesheet with a cabin made up. See its
own README.
