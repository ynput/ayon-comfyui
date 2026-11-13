# AYON bridge tests

Tests for the connection between the AYON host and ComfyUI (see
`client/ayon_comfyui/_comfyui_plugin/ayon_menu/bridge.py` and
`client/ayon_comfyui/api/bridge_client.py`). They run the relay of the
ComfyUI plugin in a plain aiohttp app on localhost, so they need neither
ComfyUI nor AYON: any Python 3.9+ with `aiohttp` works, e.g. ComfyUI's
embedded Python.

```shell
python tests/bridge/test_relay.py
python tests/bridge/test_client.py
```

Each prints a `PASS`/`FAIL` line per check and exits non-zero on failure.

- `test_relay.py`: pairing codes and tab credentials, newest tab wins,
  isolation between AYON sessions, relaying requests and responses (and
  refusing injected or late ones), failing in-flight requests when a peer
  leaves, large messages, hello timeout, pairing code expiry.
- `test_client.py`: the AYON side against the relay served under a
  sub-path: `check_plugin()` errors, calls in both directions, timeouts,
  handler errors, a relay restart (the session registers again and the
  tab rejoins), protocol rejection, handshake timeout.
