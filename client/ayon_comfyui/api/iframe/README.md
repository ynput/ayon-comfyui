# IFrame RPC

The control flow is as follows:

```
[AYON]--> WebSocket Server(WSRPC) <---> [AYON HTTP server w/ <iframe>]
  |                                                    ^ Continuous polling for WebUI buttons to function.
  | heartbeat (WebSocket Client)                       | 
  V                                                    V postMessage "Ayon API" requests
[ComfyUI Backend] -> Middleware -> [ComfyUI Frontend]
```

This allows a webpage ran on http, to embed a webpage served with TLS (https),
if no headers get in the way.

Headers that could get in the way, that might be set by a reverse proxy like
NGINX or Traefik:

- X-Frame-Options (Should not be used for this to work)
- Content-Security-Policy

The `Content-Security-Policy` should always be set to something like:

```
Content-Security-Policy: frame-ancestors http://localhost:5454;
```

To explicitly allow a http server on localhost to embed the site hosted with
TLS.

`<iframe>` communication only works one way:<br>
https (from the contentWindow) -> postMessage -> https (on the https served
site w/ correct headers)

For example, when you're hosting your app
on https://comfyui.contoso-internal.com,
whatever is exposing the app to internet should either:

1. Not set X-Frame-Options nor Content-Security-Policy headers
2. Set the Content-Security-Policy to allow for localhost embedding on the port
   that is used.

## PROBLEMS WITH THIS:

This may seem nice, and it is convenient, but it still doesn't solve the root
problem. We're essentially still opening up localhost without any encryption.

Ideally, we'd serve the connection with TLS using a local certificate
authority.
This gives us the benefit of allowing https communication to happen solely
within the same machine, assuming we do not distribute the certificate
authority file.

We can then do the bare minimum and check the origin of the websocket
connection coming from the browser since setting the Origin header is outside
anyone's control, so we can verify that it actually comes from
`https://localhost:someport`

For further security we can use a secret to verify just one connection (in the
case that we are worried about our CA being stolen, and we need to strictly
verify the caller (browser / tab) identity), we should issue a token based on a
secret.
We could bootstrap the secret on `http://` but this would be effectively
meaningless, any computer in the local network can access it.

Serving it over `https://` is much better, or better yet, we can control the
launch of the browser and include the secret in our query params, to then read
it through javascript, verify, and store it somewhere as a cookie or session
data or whatever.

Just `https://` and an origin check would already harden this enough.