# CarrierComm Plugin for Elite Dangerous Market Connector (EDMC)

The **CarrierComm** plugin tracks your Fleet Carrier’s movements, fuel levels, and other relevant stats in Elite Dangerous, and notifies users via a Discord webhook.
The **CarrierComm** plugin tracks your Fleet Carrier’s movements, fuel levels, and relevant stats in Elite Dangerous, and notifies you or your squadron via a Discord webhook.

## Features

- **Track Fleet Carrier Data**: Keep an eye on your carrier's fuel levels, jump range, and location.
- **Discord Notifications**: Automatically send notifications to your Discord channel through a webhook when your Fleet Carrier jumps, arrives, or cancels a jump.
- **Carrier Image**: Configure a custom image to be displayed with Discord notifications.
  
- **Track Fleet Carrier Data**: Automatically synchronizes your carrier's fuel levels, jump range, and location from Frontier CAPI, journal entries, and EDSM.
- **Discord Notifications**: Sends rich Discord embeds when your Fleet Carrier starts jump prep, arrives at its destination, or cancels a jump.
- **Dynamic Discord Timestamps**: Jump and lockdown times use native Discord timestamps (`<t:ts:T> (<t:ts:R>)`) for real-time countdowns rendered in each viewer's local timezone.
- **Non-Blocking / Asynchronous**: All Discord notifications, EDSM lookups, and network calls run on a dedicated background worker thread so EDMC never freezes or stutters.
- **Carrier Image Customization**: Configure a custom image for notifications, or use the built-in Drake-class default.
- **Test Webhook Button**: Test your Discord webhook connectivity directly from the EDMC settings dialog.
- **Full EDMC Theme Support**: Seamlessly matches EDMC light and dark themes.

## Installation

1. **Download the Plugin**: Download the `CarrierComm` plugin folder or clone the repository.
   
2. **Place in EDMC Plugins Folder**:
   Move or copy the plugin folder into your EDMC `plugins` directory, typically found at:
   Move or copy the plugin folder into your EDMC `plugins` directory:
      - Windows: `%LOCALAPPDATA%\EDMarketConnector\plugins`
      - Mac: `~/Library/Application Support/EDMarketConnector/plugins`
      - Linux: `$XDG_DATA_HOME/EDMarketConnector/plugins`, or
          `~/.local/share/EDMarketConnector/plugins` if `$XDG_DATA_HOME` is unset.
      - Linux: `$XDG_DATA_HOME/EDMarketConnector/plugins` (or `~/.local/share/EDMarketConnector/plugins`)
   
3. **Restart EDMC**: After placing the plugin in the directory, restart EDMC. The plugin should now be loaded and visible under the EDMC settings.
3. **Restart EDMC**: After placing the plugin in the directory, restart EDMC. CarrierComm will appear in the EDMC main window and settings.

## Configuration

### Plugin Settings in EDMC

1. Open EDMC and go to the **Plugins** tab in the top menu.
2. Find **CarrierComm** in the plugin list and click **Configure**.
3. Enter the required information:
   - **Discord Webhook URL**: The URL of your Discord webhook, where notifications will be sent.
   - **Carrier Image URL**: (Optional) The URL of an image to display with the Discord notifications.
1. In EDMC, open **File** > **Settings** (or **Preferences** on Mac) and navigate to the **CarrierComm** tab.
2. Configure your options:
   - **Notification Toggles**: Choose which events to notify (Departure, Arrival, Cancelled).
   - **Discord Webhook URL**: Enter your Discord channel webhook URL.
   - **Carrier Image URL**: (Optional) Enter the direct URL of an image to display in notifications, or click **Default**.
   - **Test Discord Webhook**: Click this button to verify your webhook configuration instantly.
3. Click **OK** to save settings.

4. Click **Save** to store the settings.

## Usage
### How to Store Carrier Location
To make the plugin save or store your carrier location:

1. **Carrier Manage and dock:** Open the carrier management tab in Elite Dangerous and dock at your carrier. This will automatically save the carrier’s current location in the plugin.
### Storing Carrier Location

2. **EDSM Detection:** If your carrier's location is detected via EDSM, the plugin will store the location automatically based on EDSM data.
The plugin tracks and stores your carrier location through multiple methods:

3. **Outdated Location:** If the carrier's location in the plugin becomes outdated (EDSM), simply dock at your carrier again to update and save its current location.
1. **Carrier Management & Docking**: Open the carrier management tab or dock at your carrier.
2. **Frontier CAPI Synchronization**: If EDMC is linked with Frontier CAPI, carrier details and system updates sync automatically.
3. **EDSM Integration**: If the carrier's system is unknown, CarrierComm queries EDSM asynchronously to retrieve its current system.

Notifications
Once configured, the plugin will monitor and notify the following events through Discord:
- Carrier Jump Request: When your Fleet Carrier starts preparing for a jump.
- Carrier Jump: When your Fleet Carrier arrives at the destination system.
 - Carrier Jump Cancelled: When a Fleet Carrier jump is canceled.
### Notifications

The notifications include details such as the current system, destination system, estimated jump time, and an optional carrier image.
- **Carrier Jump Request**: Fired when your Fleet Carrier initiates jump preparations. Includes departure system, destination system/body, estimated departure countdown, and lockdown time.
- **Carrier Jump**: Fired upon arrival at the destination system and orbit.
- **Carrier Jump Cancelled**: Fired when a pending jump is aborted, displaying the current holding position.

## LICENSE
This plugin is distributed under the MIT License.
## License

This plugin is distributed under the [MIT License](LICENSE).
