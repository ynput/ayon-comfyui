import {RPCServer} from "./lib/rpc_server.js"
import "./lib/wsrpc.js"
const IFRAME = document.getElementById("server_iframe")

window.onload = async (e) => {

  const IFRAME_RPC = new RPCServer(IFRAME.contentWindow, new URL(IFRAME.src).origin);
  let url = window.location.protocol.replace("http","ws") + "//"+ window.location.hostname + `:${window.rpc_port}` + "/ws/"
  
  const RPC = new WSRPC(url);

  // reroute RPC calls to IFRAME_RPC
  RPC.addRoute('getPublishNodes', async (data) => {
    return await IFRAME_RPC.call('getPublishNodes', data)
  })

  RPC.addRoute('getWorkfile', async (data) => {
    return await IFRAME_RPC.call('getWorkfile', data)
  })

  RPC.addRoute('addPublishNode', async (data) => {
    return await IFRAME_RPC.call('addPublishNode', data)
  })

  RPC.addRoute('removePublishNodes', async (data) => {
    return await IFRAME_RPC.call('removePublishNodes', data)
  })

  RPC.addRoute('getPublishNodeImages', async (data) => {
    console.log("getPublishnodeImages", data)
    let result = await IFRAME_RPC.call('getPublishNodeImages', data)
    console.log("image result in IFRAME", result)
    return result
  })

  RPC.addRoute('setImprintContext', async (data) => {
    return await IFRAME_RPC.call('setImprintContext', data)
  })

  RPC.addRoute('getImprintContext', async (data) => {
    return await IFRAME_RPC.call('getImprintContext', data)
  })

  RPC.addRoute('loadWorkfile', async (data) => {
    
    return await IFRAME_RPC.call('loadWorkfile', data)
  })

  RPC.connect()

  // pop stuff from the stack and pass through to RPC
  async function poll_rpc() {
      let result = await IFRAME_RPC.call("pop_process", {})
      if (result !== null){
        console.log(result)
        await RPC.call(result.function,result.args)
      }
  }

  // spam the polling endpoint.
  const PollProc = setInterval(poll_rpc, 100);

}