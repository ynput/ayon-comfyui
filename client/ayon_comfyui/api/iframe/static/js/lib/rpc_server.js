export class RPCServer {
    constructor(remoteWindow, remoteOrigin) {
        this.remoteWindow = remoteWindow; 
        this.remoteOrigin = remoteOrigin;   
        this.methods = {};
        this.pending = new Map();

        // Listen for incoming messages
        window.addEventListener("message", async (event) => {
            if (event.origin !== this.remoteOrigin) return;
            const msg = event.data;
            if (!msg.rpc || !msg.id) return;

            // Incoming request from remote
            if (msg.method) {
                const fn = this.methods[msg.method];
                if (!fn) {
                    event.source.postMessage({
                        rpc: true,
                        id: msg.id,
                        error: "Method not found"
                    }, event.origin);
                    return;
                }

                try {
                    const result = await fn(msg.params);
                    event.source.postMessage({
                        rpc: true,
                        id: msg.id,
                        result
                    }, event.origin);
                } catch (err) {
                    event.source.postMessage({
                        rpc: true,
                        id: msg.id,
                        error: err.toString()
                    }, event.origin);
                }
            }

            else if (msg.result !== undefined || msg.error !== undefined) {
                const pending = this.pending.get(msg.id);
                if (!pending) return;
                this.pending.delete(msg.id);
                if (msg.error) pending.reject(new Error(msg.error));
                else pending.resolve(msg.result);
            }
        });
    }

    register(name, fn) {
        this.methods[name] = fn;
    }

    call(method, params) {
        const id = crypto.randomUUID();
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject });
            this.remoteWindow.postMessage({
                rpc: true,
                id,
                method,
                params
            }, this.remoteOrigin);
        });
    }
}