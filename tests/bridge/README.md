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
python tests/bridge/test_version.py
```

Each prints a `PASS`/`FAIL` line per check and exits non-zero on failure.
They also run under pytest, one test per file:

```shell
pytest tests
```

- `test_relay.py`: the plugin version in `/ayon/info`, the welcomes and
  protocol rejections, pairing codes and tab credentials, newest tab wins,
  isolation between AYON sessions, relaying requests and responses (and
  refusing injected or late ones), failing in-flight requests when a peer
  leaves, large messages, hello timeout, pairing code expiry.
- `test_client.py`: the AYON side against the relay served under a
  sub-path: `check_plugin()` errors naming the plugin and addon versions, a
  warning for a plugin from another addon version, calls in both
  directions, timeouts, handler errors, a relay restart (the session
  registers again and the tab rejoins), protocol rejection, handshake
  timeout.
- `test_version.py`: the plugin's `version.py` has the addon version of
  `package.py`, like the addon's own `version.py`, and `create_package.py`
  writes both.
