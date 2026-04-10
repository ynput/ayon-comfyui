Ayon ComfyUI Setup Guide
---
Setting up ComfyUI for Ayon can be a bit of a hassle,<br>
but with this guide, hopefully, step by step you'll get it going!

#### Assuming ayon_comfyui is already in an active bundle;

### 1. Getting ComfyUI
Download a release of ComfyUI from ComfyOrg on GitHub: [**Over here!**](https://github.com/Comfy-Org/ComfyUI/releases)

#### Note: The plugin has been tested with ComfyUI Windows Standalone 0.18.1

### 2. Setup AYON Applications
Add an entry for ComfyUI as an application in the webui settings for `Applications / Additional Applications`
<details>
<summary>Setup for Ayon Applications settings</summary>
In the AYON web interface, navigate to either Studio or Project settings, and choose the Applications plugin.<br>
We need to add an entry for ComfyUI.

Please note that the `Name` and `Host name` entries need to be lowercase.

<img src="./images/applications.png" width="650" height="auto">

</details>

### 3. Setting up basic profiles

The plugin for ComfyUI works on profiles, divided into local and remote profiles.

<details>
<summary>Setting up a basic local launch profile:</summary>

Local launch profiles focus on launching ComfyUI locally, and then connecting to that locally launched instance.<br>
The only thing you need to change to get a local profile going, is to
1. Add a name
2. Point to the ComfyUI path in the ComfyUI folder (not the root windows portable folder, if using.)

Like this example:

<img src="./images/basiclocalprofile.png" width="1000" height="auto">

Do not worry about the rest of the options for now.

</details>
<details>
<summary>Setting up a basic remote launch profile:</summary>

Remote launch profiles' only function is to connect to a ComfyUI server that is already running,<br>
and that has the included plugin in the custom nodes folder so that it can use AYON functionality.

To set one up;
1. Add a name
2. Point to the right URL.

Like this example:

<img src="./images/basicremoteprofile.png" width="850" height="auto">

</details>