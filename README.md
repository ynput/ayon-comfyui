# ComfyUI addon
ComfyUI integration for AYON.

#### Migrating settings to ayon_comfyui 0.19 from earlier.
Tooling is included in `additional_tooling/migrate_json.py`<br>
Save your data from AYON with the low level settings editor, e.g. <br>
in Studio Settings / Project settings -> Addons -> ComfyUI (right click) -> `Low-level editor` -> Copy

Then save the contents to a json file.

Then run `python additional_tooling/migration_json.py "path/to/json/ayon_comfyui_settings.json"`<br>
The console will then fix it for you, and display: `Migrated settings here: path/to/json/ayon_comfyui_settings_migrated.json`,<br>
which you can then copy into the low level editor once more.

#### A note on https:
The planned control flow is as follows:

```
[AYON]--> WebSocket Server(WSRPC) <---> [AYON HTTP server w/ <iframe>]
  |                                                    ^ Continuous polling for WebUI buttons to function.
  | heartbeat (WebSocket Client)                       | 
  V                                                    V postMessage "Ayon API" requests
[ComfyUI Backend] -> Nefarious Middleware -> [ComfyUI Frontend]
```

This requires, that said Nefarious Middleware respects the \<iframe> specifications for embedding
pages of cross origin. This is done through headers.

If your comfyui server is just being forwarded without:
- X-Frame-Options
- Content-Security-Policy

being injected into the headers, you have nothing to worry about,<br>
except that you may want to follow the advice to put a Content-Security-Policy header in place.

```
Content-Security-Policy: frame-ancestors http://localhost:<port_that_iframe_is_hosted_on>;
```
### NOTE THAT THIS IS EXPLICITLY ALLOWING MIXED SECURITY AND (LIMITED; ASSUMING Content-Security-Policy) CROSS ORIGIN REMOTE SCRIPTING.

### More information (including header settings and further security issues) is provided [Here](./client/ayon_comfyui/api/iframe/README.md).