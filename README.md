# CarrierComm Plugin for Elite Dangerous Market Connector (EDMC)

The **CarrierComm** plugin tracks your Fleet Carrier’s movements, fuel levels, and other relevant stats in Elite Dangerous, and notifies users via a Discord webhook.

## Features

- **Track Fleet Carrier Data**: Keep an eye on your carrier's fuel levels, jump range, and location.
- **Discord Notifications**: Automatically send notifications to your Discord channel through a webhook when your Fleet Carrier jumps, arrives, or cancels a jump.
- **Carrier Image**: Configure a custom image to be displayed with Discord notifications.
  
## Installation

1. **Download the Plugin**: Download the `CarrierComm` plugin folder or clone the repository.
   
2. **Place in EDMC Plugins Folder**:
   - Move or copy the plugin folder into your EDMC `plugins` directory, typically found at:
     - Windows: `C:\Users\<YourName>\AppData\Local\EDMarketConnector\plugins`
     - MacOS: `~/Library/Application Support/EDMarketConnector/plugins`
   
3. **Restart EDMC**: After placing the plugin in the directory, restart EDMC. The plugin should now be loaded and visible under the EDMC settings.

## Configuration

### Plugin Settings in EDMC

1. Open EDMC and go to the **Plugins** tab in the top menu.
2. Find **CarrierComm** in the plugin list and click **Configure**.
3. Enter the required information:
   - **Discord Webhook URL**: The URL of your Discord webhook, where notifications will be sent.
   - **Carrier Image URL**: (Optional) The URL of an image to display with the Discord notifications.

4. Click **Save** to store the settings.

## Usage
### How to Store Carrier Location
To make the plugin save or store your carrier location:

1. **Dock at Your Carrier:** Open the carrier management tab in Elite Dangerous and dock at your carrier. This will automatically save the carrier’s current location in the plugin.

2. **EDSM Detection:** If your carrier's location is detected via EDSM, the plugin will store the location automatically based on EDSM data.

3. **Outdated Location:** If the carrier's location in the plugin becomes outdated, simply dock at your carrier again to update and save its current location.

Notifications
Once configured, the plugin will monitor and notify the following events through Discord:
- Carrier Jump Request: When your Fleet Carrier starts preparing for a jump.
- Carrier Jump: When your Fleet Carrier arrives at the destination system.
 - Carrier Jump Cancelled: When a Fleet Carrier jump is canceled.

The notifications include details such as the current system, destination system, estimated jump time, and an optional carrier image.

## LICENSE
This plugin is distributed under the MIT License.
