"""Templates html page for injection of JS stuff ComfyUI needs to know."""

HTML_TMP = """<!DOCTYPE html>
<script lang="text/javascript" type="module" src="../static/js/proxy.js">
</script>
<script lang="text/javascript">
window.rpc_port = {{port}};
</script>
<style>
html, body {
  margin: 0;
  height: 100%;
}

iframe {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border: none;
}
</style>
<body>
    <iframe id="server_iframe" src="{{source}}"></iframe><br>
</body>"""


def template_html(
    webui_port: int = 55056, comfy_url: str = "http://127.0.0.1:8188"
) -> str:
    """Returns templated HTML page ready for RPC.

    webui_port is the port used for websocket comms.
    comfy_url has to contain the
    """
    return HTML_TMP.replace("{{source}}", comfy_url).replace(
        "{{port}}", str(webui_port)
    )
