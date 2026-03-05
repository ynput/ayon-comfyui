# ComfyUI addon
ComfyUI integration for AYON.

#### A note on https:
To connect to TLS encrypted endpoints, generating certificates
for localhost is needed.

This is because the web frontend can be served from an https adress,
and we need it to become a client to our websocket server, for RPC.

To do this, `mkcert` is the easiest option.

Documentation is provided [Here](./client/ayon_comfyui/certs/NOTE_ON_MKCERT.md).