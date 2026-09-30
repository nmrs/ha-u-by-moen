# U by Moen Home Assistant Integration

A custom Home Assistant integration for U by Moen smart shower systems (Alexa/Android version, not HomeKit).

**This is a fork of [WeaveHubHQ/ha-u-by-moen](https://github.com/WeaveHubHQ/ha-u-by-moen) by Jason Lazerus (@WeaveHubHQ) — all credit for the original integration goes there.** This fork adds an **optional fully-local control transport**: the shower's TS3304 controller runs a native HomeKit accessory server on your LAN, and this integration can pair with it directly — commands and state stay on your network, with no cloud round-trip. Cloud control (presets, Pusher real-time updates) continues to work unchanged.

## Features

- **Climate Control**: Control your shower temperature and power through Home Assistant's climate entity
- **Preset Activation**: Buttons to activate your configured shower presets (cloud transport)
- **Outlet Control**: Individual switches for each water outlet (shower head, body sprayers, etc.)
- **Real-time Updates**: Device-reported state via Pusher WebSocket, plus **local HAP push events** when the optional local transport is paired — physical button presses on the shower's own console appear in Home Assistant within ~300 ms
- **Cloud-identical local semantics**: local commands mirror the official app's behavior — valve switches are no-ops while the shower is off (the app hides them), temperature changes while off are ignored, and power-on behaves like the cloud's `shower_on` (opens the default outlet)
- **Safe write handling**: all local HomeKit writes are serialized and paced; the device's HAP server is sensitive to concurrent sessions

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nmrs&repository=ha-u-by-moen)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL (`https://github.com/nmrs/ha-u-by-moen`) and select "Integration" as the category
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/u_by_moen` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "U by Moen"
4. Enter your U by Moen account credentials (email and password)
5. Click Submit

Your devices will be automatically discovered and added to Home Assistant. That's all that's required for the **cloud integration** — the local transport below is optional.

## Optional: fully-local control (pair by IP)

The TS3304 controller (firmware 3.3.0 verified) runs a HomeKit accessory server on your LAN (`_hap._tcp`, port 80). If a file named `u_by_moen_hap.json` exists in your Home Assistant `config/` directory at integration setup, the integration pairs with the shower directly and routes all valve/power/temperature commands — and state updates — over the local transport. Presets and anything not represented in the shower's HomeKit model still use the cloud.

**Why pair by IP?** Home Assistant running in a Docker bridge network can't hear LAN mDNS, so the integration looks for the pairing file instead of using discovery. Pairing is done once with aiohomekit and the resulting keys are stored in the file.

### Pairing procedure

1. **Free the HomeKit slot.** If the shower is paired to Apple Home (or another controller), remove it there first — the shower only accepts one controller. Verify the mDNS TXT record shows `sf=1` (`dns-sd -L "U by Moen" _hap._tcp local.`).
2. **Get the setup code** from the QR on the shower touchscreen (HomeKit section of the local menu). Format it as `XXX-XX-XXX` for aiohomekit.
   ⚠️ **The setup code rotates on controller reboot** — grab it fresh from the screen right before pairing, and never reuse a stale one.
3. **Pair by IP** with aiohomekit. The pairing JSON this integration expects contains:
   ```json
   {
     "AccessoryPairingID": "AA:BB:CC:DD:EE:FF",
     "AccessoryLTPK": "<hex>",
     "iOSDeviceLTPK": "<hex>",
     "iOSDeviceLTSK": "<hex>",
     "AccessoryIP": "192.168.x.x",
     "AccessoryPort": 80
   }
   ```
   The first five fields are exactly what aiohomekit's IP pairing produces —
   drive `IpDiscovery` (`custom_components/homekit_controller` uses the same
   machinery): fabricate discovery info for the shower's IP + port, call
   `async_start_pairing()`, then `finish("<setup code>")` — the returned
   pairing data is the file above. See aiohomekit's
   `controller/ip/discovery.py` for the exact API.
4. **DHCP-reserve the shower's IP address** — the pairing file pins it.
5. Save the file as `u_by_moen_hap.json` in your HA `config/` directory (keep it out of git) and restart Home Assistant. The log will show `Local HAP transport enabled (u_by_moen_hap.json found)` and `HAP event stream active (local push, no cloud)`.

⚠️ **Device fragility:** a *bad or repeated pair-setup attempt* can wedge the shower's HAP server (mDNS vanishes, the screen hangs on "contacting server"). The fix is rebooting the wall controller — after which the setup code rotates. Pair carefully, once, with a fresh code.

### What local control changes

- Valve and power/temperature commands go over the LAN; state updates arrive as HomeKit push events (no cloud dependency).
- Behavior is cloud-identical by design:
  - Valve switches are **unavailable while the shower is off or paused** — the official app hides valve controls when off and the physical console ignores them; this integration matches that rather than lying about state.
  - Power-on opens the default outlet (outlet 1), like the cloud's `shower_on`.
  - Temperature changes while off are no-ops (the device would silently "arm" them otherwise; the cloud ignores them).
- A `main=on + no outlets` state is the shower's pause — reported as `paused-by-user`, shown as off, resumable.

## Entities Created

For each U by Moen shower, the integration creates:

### Climate Entity
- Control temperature and turn shower on/off
- Shows current and target temperature; pause states report as `off` (resumable)

### Switches
- **Power** — main on/off control
- **Valve 1-4** (rename to taste) — individual outlet control; only available while the shower is running

### Buttons (Presets, cloud transport)
- One button per configured preset

### Sensors
- **Mode** — `off` / `adjusting` / `ready` / `paused-by-user` / `paused-by-preset`
- **Current Temperature**, **Target Temperature**
- **Active Preset**, **Time Remaining**, **Firmware**

### Usage Examples

Turn on shower at target temperature:
```yaml
automation:
  - alias: "Morning Shower Ready"
    trigger:
      - platform: time
        at: "06:30:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.master_bathroom
        data:
          temperature: 102
          hvac_mode: heat
```

Turn the vent on whenever the shower starts (any source — HA, voice, app, or the shower's own console), off 10 minutes after it stops:
```yaml
automation:
  - alias: "Shower vent auto"
    triggers:
      - trigger: state
        entity_id: switch.master_bathroom_shower_power
        to: "on"
        id: shower_on
      - trigger: state
        entity_id: switch.master_bathroom_shower_power
        to: "off"
        for: "00:10:00"
        id: shower_off
    actions:
      - choose:
          - conditions:
              - condition: trigger
                id: shower_on
            sequence:
              - action: switch.turn_on
                target:
                  entity_id: switch.master_bathroom_shower_vent
          - conditions:
              - condition: trigger
                id: shower_off
            sequence:
              - action: switch.turn_off
                target:
                  entity_id: switch.master_bathroom_shower_vent
    mode: restart
```

## Known Limitations

- **Presets are cloud-only** — the shower's HomeKit model exposes valves/power/temperature only, so preset buttons and preset-related sensors ride the Moen cloud. Local equivalents can be built as HA scripts/automations.
- **Local transport verified against TS3304, fw 3.3.0.** The HomeKit model exposes the four outlet Actives, main Active, and target temperature; the target-state characteristic (iid 15) is a dead read (always 0).
- **Pusher real-time updates** work for cloud-side changes; local HAP push works for device-side changes when the local transport is paired.

## Troubleshooting

### Integration not appearing
- Make sure you've restarted Home Assistant after installation
- Check the Home Assistant logs for any errors

### Authentication fails
- Verify your email and password are correct
- Make sure you're using the credentials for the Alexa/Android version of U by Moen (not HomeKit)

### Local transport not enabling
- Confirm `u_by_moen_hap.json` is in the HA `config/` directory (path `hass.config.path()`)
- Check for `Local HAP transport enabled` in the logs at INFO
- If the shower was re-paired elsewhere (or rebooted + re-paired), the keys are stale — re-pair and replace the file

### Controls not working
- Check Home Assistant logs for errors
- Valve switches unavailable while the shower is off is *by design* — turn the power on first
- Open an issue with debug logs

### Enable debug logging
Add to your `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.u_by_moen: debug
```

## API Information

This integration uses the Moen IoT API:
- **Base URL**: `https://www.moen-iot.com`
- **Authentication**: Token-based (obtained via email/password)
- **Real-time**: Pusher WebSocket (app_key: `dcc28ccb5296f18f8eae`, cluster: `us2`)

## Contributing

Contributions are welcome! Please open an issue or pull request.

### Development Setup

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Make your changes
4. Test with your Home Assistant instance

## License

MIT License - see LICENSE file for details

## Credits

**Original integration by Jason Lazerus ([@WeaveHubHQ](https://github.com/WeaveHubHQ))** — see the upstream repository: https://github.com/WeaveHubHQ/ha-u-by-moen. Come see their other apps and integrations at [WeaveHub](https://weavehub.app).

Local HomeKit transport, cloud-identical semantics, and the local push event stream added in this fork (@nmrs).

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Moen or Fortune Brands.