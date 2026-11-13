# ComfyUI addon
ComfyUI integration for AYON.

To learn more about configuration and user guides, please visit [AYON ComfyUi - AYON Help Center](https://help.ayon.app/en/help/collections/4847305-comfyui).

## How AYON talks to ComfyUI

```
[AYON session (Qt tools)] --websocket--> [ComfyUI server + AYON plugin] <--websocket-- [ComfyUI tab in the browser]
                                          /ayon/ws relays requests between
                                          an AYON session and its paired tab
```

The AYON ComfyUI plugin (a custom node package shipped with this addon) adds a
few routes to ComfyUI's own server:

- `GET /ayon/info`: lets AYON check the plugin is installed and compatible,
  and which addon version it is from.
- `GET /ayon/pair`: the page AYON opens in the browser to pair a tab.
- `GET /ayon/ws` (also `/api/ayon/ws`): a websocket relay between an AYON
  session and the ComfyUI tab paired with it.

AYON is only a client: it doesn't listen on any port, and the browser only
talks to its own ComfyUI server. That works the same for a local ComfyUI
(`http://127.0.0.1:8188`) and for a shared one behind HTTPS
(`https://comfyui.example.com`, sub-paths work too).

When AYON starts, it opens `<comfyui>/ayon/pair#code=...` in the browser. That
one-time code pairs the tab with this AYON session; the tab keeps a credential
in its session storage so it reconnects after reloads or a ComfyUI restart.
The AYON panel in ComfyUI's sidebar shows what the tab is connected to, and
accepts a pairing code by hand (e.g. when a login page dropped it from the
link). When no tab is connected, AYON shows a small "AYON - ComfyUI" window
to reopen the tab or quit the session.

### Shared / remote ComfyUI servers

- Install the AYON ComfyUI plugin on the server, from the same addon version
  the artists use: copy the custom node folder
  `client/ayon_comfyui/_comfyui_plugin/ayon_menu` into ComfyUI's
  `custom_nodes` folder. (A ComfyUI that AYON launches locally gets
  `_comfyui_plugin` as an extra custom nodes folder instead.) The plugin
  reports its version at `/ayon/info`. AYON refuses to connect to a plugin
  with another bridge protocol, and logs a warning for a plugin from another
  addon version.
- A reverse proxy in front of ComfyUI must pass websocket upgrades for
  `/ayon/ws` and `/api/ayon/ws`, like it does for ComfyUI's own `/ws`, and
  should not time out idle websockets in less than a minute (the bridge
  pings every 30 seconds).
- Use HTTPS for anything that isn't on the artist's machine. AYON verifies
  the certificate with the system's trusted certificates (and
  `SSL_CERT_FILE`, if set).
- A reverse proxy that requires a login or extra headers for every request
  (SSO, Cloudflare Access, mTLS) isn't supported for the AYON connection yet.

### Upgrading a shared ComfyUI server

Update the plugin on a shared ComfyUI server together with the AYON ComfyUI
addon in the AYON bundle of everyone who uses that server, so they all switch
at once:

- AYON ComfyUI addon versions from before this bridge showed ComfyUI inside a
  page that AYON served itself (on `http://127.0.0.1:5454`). Their sessions
  can't use a ComfyUI that has the new plugin: ComfyUI shows them "AYON:
  update the AYON ComfyUI addon" instead. The other way around (the old
  plugin on the server, the new addon in AYON), AYON reports that ComfyUI
  doesn't have the AYON plugin or has an older one.
- After that, a plugin and an addon of different versions still connect when
  they share a bridge protocol (AYON logs a warning). Otherwise AYON refuses
  to connect and names both versions.

### Security

ComfyUI itself has no authentication: anyone who can reach it can queue
prompts and read its user data. The bridge doesn't change that, but it makes
sure that nobody without the session's secret, pairing code or tab credential
can drive an AYON session (open tools, save, read what AYON asks the tab), and
that AYON sessions sharing one ComfyUI server never reach each other's tabs.
Restrict access to a shared ComfyUI with a reverse proxy or the network.

## Caveats

- **One tab per AYON session:** AYON drives one ComfyUI browser tab. Opening
  the same session in another tab (e.g. "Duplicate tab") moves AYON to that
  tab; the other one offers "Use this tab for AYON" to move it back.
- **Active workflow:** inside that tab, AYON works on the active ComfyUI
  workflow (the selected workflow tab).
