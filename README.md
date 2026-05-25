# ComfyUI addon
ComfyUI integration for AYON.

To learn more about configuration and user guides, please visit [AYON ComfyUi - AYON Help Center](https://help.ayon.app/en/help/collections/4847305-comfyui).

#### A note on https:

The planned control flow is as follows:

```
[AYON]--> WebSocket Server(WSRPC) <---> [AYON HTTP server w/ <iframe>]
  |                                                    ^ Continuous polling for WebUI buttons to function.
  | heartbeat (WebSocket Client)                       | 
  V                                                    V postMessage "Ayon API" requests
[ComfyUI Backend] -> Middleware -> [ComfyUI Frontend]
```

This requires, that said _Middleware_ respects the `<iframe>` specifications for embedding
pages of cross-origin. This is done through headers.

If your comfyui server is just being forwarded without:
- X-Frame-Options
- Content-Security-Policy

being injected into the headers, you have nothing to worry about,<br>
except that you may want to follow the advice to put a Content-Security-Policy header in place.

```
Content-Security-Policy: frame-ancestors http://localhost:<port_that_iframe_is_hosted_on>;
```

### Security notice

> [!WARNING]  
> This explicitly allows mixed security and (limited; ASSUMING `Content-Security-Policy`) cross-origin remote scripting.

More information (including header settings and further security issues) is provided [here](https://github.com/ynput/ayon-comfyui/blob/develop/client/ayon_comfyui/api/iframe/README.md).
