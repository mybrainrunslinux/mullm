"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let worker, timer, ready = false;
  const categories = ["code","research","creative","conversation","deploy","note","lookup","vision"];
  function stop(message="Model unloaded.") { clearTimeout(timer);worker?.terminate();worker=null;ready=false;$("load").disabled=false;$("classify").disabled=true;$("status").textContent=message; }
  $("stop").onclick=()=>stop();
  $("load").onclick=()=>{
    stop();$("status").textContent="Loading local model…";$("load").disabled=true;
    worker=new Worker("/static/kev-worker.js",{type:"module"});
    worker.onerror=()=>stop("Could not load the browser runtime. Check the optional installation and browser support.");
    worker.onmessage=({data})=>{
      clearTimeout(timer);
      if(data.type==="ready"){ready=true;$("classify").disabled=false;$("status").textContent="Ready · classification stays in this browser.";}
      else if(data.type==="result"){
        $("classify").disabled=false;
        const a=data.response?.answers, intent=a?.intent, complexity=a?.complexity;
        const level=Number(complexity?.choice), confidence=Math.min(Number(intent?.confidence),Number(complexity?.confidence));
        if(!categories.includes(intent?.choice)||!Number.isInteger(level)||level<1||level>5||!Number.isFinite(confidence)||confidence<0||confidence>1){$("status").textContent="Invalid classifier output. Server routing is unchanged.";return;}
        $("result").textContent=JSON.stringify({category:intent.choice,complexity:level,confidence},null,2);
        $("status").textContent=confidence<.8?"Low confidence · treat this as a suggestion.":"Classified locally · preview only.";
      } else stop("Classifier unavailable: "+data.message);
    };
    worker.postMessage({type:"load",device:$("device").value});
    timer=setTimeout(()=>stop("Loading timed out. Check model files or choose another device."),120000);
  };
  $("classify").onclick=()=>{
    if(!ready||!$("query").value.trim())return;
    $("classify").disabled=true;$("status").textContent="Classifying…";
    worker.postMessage({type:"classify",request:{state:$("query").value.slice(0,4000),questions:{
      intent:{type:"choice",instructions:"Select the primary intent of the user request.",criteria:Object.fromEntries(categories.map(c=>[c,c]))},
      complexity:{type:"choice",instructions:"Rate the difficulty of completing the request.",criteria:{"1":"Trivial lookup","2":"Simple single-step task","3":"Moderate multistep task","4":"Complex expert task","5":"Demanding research or architecture"}}
    }}});
    timer=setTimeout(()=>stop("Classification timed out. Server routing is unchanged."),30000);
  };
})();
