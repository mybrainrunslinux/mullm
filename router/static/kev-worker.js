let kev;
self.onmessage = async ({data}) => {
  try {
    if (data.type === "load") {
      const {loadKev, ort} = await import("/kev-assets/runtime.js");
      ort.env.wasm.wasmPaths = "/kev-assets/";
      ort.env.wasm.numThreads = 1;
      kev = await loadKev("/kev-model", {ort, variant:"q8f32", executionProviders:[data.device]});
      self.postMessage({type:"ready"});
    } else if (data.type === "classify") {
      if (!kev) throw new Error("Load a model first");
      const response = await kev.systemOne(data.request);
      self.postMessage({type:"result",response});
    }
  } catch (error) {
    self.postMessage({type:"error", message: error.message});
  }
};
