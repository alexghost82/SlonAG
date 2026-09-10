(() => {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const stage = document.getElementById("stage");
  const clock = document.getElementById("clock");
  const form = document.getElementById("command-form");
  const input = document.getElementById("command-input");
  const mic = document.getElementById("mic");
  const overlay = document.getElementById("overlay");
  const drawer = document.getElementById("drawer");
  const drawerTitle = document.getElementById("drawer-title");
  const drawerBody = document.getElementById("drawer-body");
  const toast = document.getElementById("toast");
  const stars = document.getElementById("stars");
  const orbFx = document.getElementById("orb-fx");
  const sctx = stars.getContext("2d", { alpha: true });

  const state = {
    listening: true,
    processing: false,
    chat: [
      { role: "user", text: "What's on my schedule?" },
      { role: "ghost", text: "One review remains at 23:55. The rest of the night is clear." },
    ],
    reminders: [
      { title: "Call Alex", body: "23:43 · Today" },
      { title: "Evening review", body: "23:55 · Today" },
    ],
    notes: [{ title: "Project Ghost", body: "Keep the workspace local-first.", time: "23:41" }],
  };
  const titles = { chat: "New Chat", reminders: "Reminders", notes: "Notes", settings: "Settings", add: "Add Action" };
  const voice = { energy: 0.14, bass: 0.1, mid: 0.1, high: 0.08, wave: null };
  const view = { stageW: 0, stageH: 0 };

  let lastFocus = null;
  let toastTimer = 0;
  let analyser = null;
  let freqData = null;
  let waveData = null;
  let audioCtx = null;
  let frameN = 0;

  const starField = Array.from({ length: 70 }, () => ({
    x: Math.random(), y: Math.random(), r: Math.random() * 1.1 + 0.2, a: Math.random(), s: 0.002 + Math.random() * 0.008,
  }));
  const orbWave = [];
  const sideWaves = [];

  function createOrb(canvas) {
    const gl = canvas.getContext("webgl", {
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
    });
    if (!gl) {
      const ctx = canvas.getContext("2d");
      return {
        resize(w, h) {
          const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
          canvas.width = Math.round(w * dpr);
          canvas.height = Math.round(h * dpr);
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        },
        render(t) {
          const w = canvas.getBoundingClientRect().width;
          const h = canvas.getBoundingClientRect().height;
          ctx.clearRect(0, 0, w, h);
          const e = voice.energy;
          ctx.globalCompositeOperation = "lighter";
          [[0.32, 0.28, "#00e5ff"], [0.62, 0.4, "#b44cff"], [0.7, 0.58, "#ffb347"]].forEach((blob, i) => {
            const a = t * 0.00025 + i * 2.1;
            const x = w * (0.5 + Math.cos(a) * 0.12);
            const y = h * (0.5 + Math.sin(a * 0.9) * 0.1);
            const g = ctx.createRadialGradient(x, y, 0, x, y, w * (0.22 + e * 0.08));
            g.addColorStop(0, blob[2]);
            g.addColorStop(1, "rgba(0,0,0,0)");
            ctx.fillStyle = g;
            ctx.globalAlpha = 0.22 + e * 0.2;
            ctx.beginPath();
            ctx.arc(x, y, w * 0.34, 0, Math.PI * 2);
            ctx.fill();
          });
          ctx.globalAlpha = 1;
          ctx.globalCompositeOperation = "source-over";
        },
      };
    }

    const vs = `
      attribute vec2 a;
      void main(){ gl_Position = vec4(a,0.0,1.0); }
    `;
    const fs = `
      precision mediump float;
      uniform vec2 uRes;
      uniform float uTime, uEnergy, uBass, uLive;
      float hash(vec3 p){
        p = fract(p*0.3183 + vec3(.11,.17,.23));
        p *= 17.0;
        return fract(p.x*p.y*p.z*(p.x+p.y+p.z));
      }
      float n3(vec3 x){
        vec3 i=floor(x), f=fract(x);
        f=f*f*(3.0-2.0*f);
        return mix(
          mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x), mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
          mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x), mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),
          f.z);
      }
      float fbm(vec3 p){
        float s=0.0, a=0.52;
        for(int i=0;i<4;i++){ s+=a*n3(p); p=p*2.07+1.7; a*=0.5; }
        return s;
      }
      mat2 rot(float a){ float c=cos(a),s=sin(a); return mat2(c,-s,s,c); }
      void main(){
        vec2 uv=(gl_FragCoord.xy-0.5*uRes)/min(uRes.x,uRes.y);
        float fall=smoothstep(0.78,0.16,length(uv));
        vec3 ro=vec3(0.0,0.0,2.55);
        vec3 rd=normalize(vec3(uv,-1.35));
        vec3 col=vec3(0.0);
        float t=1.15;
        float e=uEnergy;
        for(int i=0;i<22;i++){
          vec3 p=ro+rd*t;
          p.xy*=rot(uTime*0.11+uBass*0.15);
          p.xz*=rot(uTime*0.07);
          float r=length(p);
          float shell=smoothstep(1.18,0.70,r)*smoothstep(0.18,0.46,r);
          float field=fbm(p*2.15 + vec3(uTime*0.16, uTime*0.09, -uTime*0.05));
          float threads=pow(abs(sin(field*6.4 + p.y*3.2)*sin(field*5.1 + p.x*4.0)), 2.6);
          float dens=shell*(0.28+field*0.85+threads*1.55)*(0.72+e*0.85);
          vec3 pal=mix(vec3(0.62,0.16,1.0), vec3(0.0,0.92,1.0), clamp(field+p.x*0.38,0.0,1.0));
          pal=mix(pal, vec3(1.0,0.64,0.24), smoothstep(0.22,0.92,p.x+field*0.2));
          col+=pal*dens*0.086;
          t+=0.062;
        }
        col+=vec3(0.05,0.75,1.0)*smoothstep(0.26,0.0,length(uv))*(0.12+e*0.32);
        col*=fall*mix(0.35,1.0,uLive);
        float a=clamp(length(col)*1.15,0.0,1.0)*fall;
        gl_FragColor=vec4(col*a,a);
      }
    `;

    function compile(type, src) {
      const sh = gl.createShader(type);
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.error(gl.getShaderInfoLog(sh));
        return null;
      }
      return sh;
    }

    const prog = gl.createProgram();
    const vsh = compile(gl.VERTEX_SHADER, vs);
    const fsh = compile(gl.FRAGMENT_SHADER, fs);
    if (!vsh || !fsh) return null;
    gl.attachShader(prog, vsh);
    gl.attachShader(prog, fsh);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const uRes = gl.getUniformLocation(prog, "uRes");
    const uTime = gl.getUniformLocation(prog, "uTime");
    const uEnergy = gl.getUniformLocation(prog, "uEnergy");
    const uBass = gl.getUniformLocation(prog, "uBass");
    const uLive = gl.getUniformLocation(prog, "uLive");
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    return {
      resize(w, h) {
        const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
        const pw = Math.max(2, Math.round(w * dpr));
        const ph = Math.max(2, Math.round(h * dpr));
        if (canvas.width === pw && canvas.height === ph) return;
        canvas.width = pw;
        canvas.height = ph;
        gl.viewport(0, 0, pw, ph);
      },
      render(t) {
        gl.uniform2f(uRes, canvas.width, canvas.height);
        gl.uniform1f(uTime, t * 0.001);
        gl.uniform1f(uEnergy, voice.energy);
        gl.uniform1f(uBass, voice.bass);
        gl.uniform1f(uLive, state.listening ? 1 : 0.38);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      },
    };
  }

  const orb = createOrb(orbFx);

  function fillWave(el, count, bucket) {
    el.innerHTML = "";
    for (let i = 0; i < count; i += 1) {
      const bar = document.createElement("i");
      bar.style.height = `${20 + ((i * 37) % 64)}%`;
      el.append(bar);
      bucket.push(bar);
    }
  }

  function fillOrbWave() {
    const el = document.getElementById("orb-wave");
    el.innerHTML = "";
    [22, 38, 58, 78, 100, 76, 52, 34, 20].forEach((h) => {
      const bar = document.createElement("i");
      bar.style.height = `${h}%`;
      el.append(bar);
      orbWave.push(bar);
    });
  }

  function pad(n) { return String(n).padStart(2, "0"); }
  function nowStamp() {
    const d = new Date();
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function tickClock() {
    const d = new Date();
    clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    clock.dateTime = d.toISOString();
  }
  function showToast(message) {
    toast.hidden = false;
    toast.textContent = message;
    requestAnimationFrame(() => toast.classList.add("is-open"));
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toast.classList.remove("is-open");
      window.setTimeout(() => { toast.hidden = true; }, 180);
    }, 2400);
  }
  function replyFor(command) {
    const text = command.toLowerCase();
    if (text.includes("schedule")) return "Tonight is clear after 23:55. One review remains.";
    if (text.includes("alex") || text.includes("remind")) return "Reminder set. I will keep it local.";
    if (text.includes("message")) return "3 unread threads. One needs a reply.";
    if (text.includes("project") || text.includes("ghost")) return "Opening project Ghost.";
    if (text.includes("search")) return "Local search is ready. Cloud search stays off.";
    return `Heard: “${command}”. Keeping this on-device.`;
  }
  function setTask(name) {
    document.querySelectorAll("#tasks li").forEach((item) => {
      item.dataset.on = String(item.dataset.task === name);
    });
  }
  function addRecent(command) {
    const li = document.createElement("li");
    li.innerHTML = "<span></span><time></time>";
    li.querySelector("span").textContent = command;
    li.querySelector("time").textContent = nowStamp();
    const list = document.getElementById("recent");
    list.prepend(li);
    while (list.children.length > 4) list.lastElementChild.remove();
  }
  function runCommand(command) {
    const value = command.trim();
    if (!value) { showToast("Type or speak a command first."); input.focus(); return; }
    if (state.processing) return;
    state.processing = true;
    input.disabled = true;
    input.value = "";
    addRecent(value);
    state.chat.push({ role: "user", text: value });
    ["understand", "process", "search", "generate"].forEach((step, i) => {
      window.setTimeout(() => setTask(step), i * 180);
    });
    window.setTimeout(() => {
      const answer = replyFor(value);
      state.chat.push({ role: "ghost", text: answer });
      setTask("");
      state.processing = false;
      input.disabled = false;
      showToast(answer);
    }, 820);
  }
  function setListening(on) {
    state.listening = on;
    stage.dataset.listening = String(on);
    mic.setAttribute("aria-pressed", String(on));
    document.getElementById("status-chip").innerHTML = on ? "<i></i>Active" : "Standby";
    document.getElementById("voice-chip").textContent = on ? "Enabled" : "Paused";
    document.getElementById("listen-text").textContent = on ? "Listening" : "Standby";
  }
  async function enableMic() {
    if (!navigator.mediaDevices?.getUserMedia) return false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, echoCancellation: true, noiseSuppression: true });
      audioCtx = audioCtx || new AudioContext();
      if (audioCtx.state === "suspended") await audioCtx.resume();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.86;
      freqData = new Uint8Array(analyser.frequencyBinCount);
      waveData = new Uint8Array(analyser.fftSize);
      audioCtx.createMediaStreamSource(stream).connect(analyser);
      return true;
    } catch {
      analyser = null;
      return false;
    }
  }
  function sampleVoice(t) {
    if (analyser && freqData && waveData) {
      analyser.getByteFrequencyData(freqData);
      analyser.getByteTimeDomainData(waveData);
      let sum = 0;
      let bass = 0;
      let mid = 0;
      let high = 0;
      const n = freqData.length;
      for (let i = 0; i < n; i += 1) {
        const v = freqData[i] / 255;
        sum += v;
        if (i < n * 0.12) bass += v;
        else if (i < n * 0.45) mid += v;
        else high += v;
      }
      const target = Math.min(1, (sum / n) * 2.15);
      voice.energy += (target - voice.energy) * 0.07;
      voice.bass += (bass / Math.max(1, n * 0.12) - voice.bass) * 0.06;
      voice.mid += (mid / Math.max(1, n * 0.33) - voice.mid) * 0.06;
      voice.high += (high / Math.max(1, n * 0.55) - voice.high) * 0.06;
      voice.wave = waveData;
      return;
    }
    const breath = 0.13 + Math.sin(t * 0.00115) * 0.035;
    voice.energy += (breath - voice.energy) * 0.035;
    voice.bass = 0.09 + Math.sin(t * 0.0009) * 0.025;
    voice.mid = 0.1 + Math.sin(t * 0.0013 + 1.1) * 0.02;
    voice.high = 0.07 + Math.sin(t * 0.0017 + 2.2) * 0.02;
  }
  function setBar(bar, i, total) {
    let amp = 0.28 + voice.energy * 0.55;
    if (voice.wave && voice.wave.length) {
      const idx = Math.floor((i / total) * voice.wave.length);
      amp = Math.abs(voice.wave[idx] - 128) / 128;
    }
    const y = Math.max(0.2, Math.min(1.25, 0.3 + amp * (0.5 + voice.energy * 0.55)));
    bar.style.transform = `scaleY(${y})`;
  }
  function driveWaves() {
    orbWave.forEach((bar, i) => setBar(bar, i, orbWave.length));
    if (frameN % 2 === 0) {
      sideWaves.forEach((bar, i) => setBar(bar, i, sideWaves.length));
    }
  }
  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }
  function renderPanel(id) {
    if (id === "chat") {
      return state.chat.map((item) => `<article class="card"><h3>${item.role === "ghost" ? "Ghost" : "You"}</h3><p></p></article>`).join("");
    }
    if (id === "reminders") {
      if (!state.reminders.length) return `<div class="empty"><p>No reminders.</p></div>`;
      return state.reminders.map((item, i) => `<article class="card"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p><button type="button" class="primary" data-done="${i}">Mark done</button></article>`).join("");
    }
    if (id === "notes") {
      return state.notes.map((note) => `<article class="card"><h3>${escapeHtml(note.title)}</h3><p>${escapeHtml(note.body)}</p></article>`).join("");
    }
    if (id === "settings") {
      return `<div class="field toggle"><div><label>Voice input</label><p class="help">Pause listening without leaving Ghost.</p></div><button type="button" class="switch" id="set-voice" role="switch" aria-checked="${state.listening}"></button></div><div class="field"><label>Privacy</label><p class="help">Secure. Private. Local first.</p></div>`;
    }
    return `<form class="field" id="add-form"><label for="new-action">Custom action</label><input id="new-action" name="action" required /><button type="submit" class="primary">Add</button></form>`;
  }
  function bindPanel(id) {
    if (id === "chat") [...drawerBody.querySelectorAll("p")].forEach((p, i) => { p.textContent = state.chat[i].text; });
    if (id === "reminders") {
      drawerBody.querySelectorAll("[data-done]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const i = Number(btn.dataset.done);
          showToast(`Cleared: ${state.reminders[i].title}`);
          state.reminders.splice(i, 1);
          openDrawer("reminders");
        });
      });
    }
    if (id === "settings") {
      document.getElementById("set-voice").addEventListener("click", () => {
        setListening(!state.listening);
        document.getElementById("set-voice").setAttribute("aria-checked", String(state.listening));
      });
    }
    if (id === "add") {
      document.getElementById("add-form").addEventListener("submit", (event) => {
        event.preventDefault();
        const value = event.target.action.value.trim();
        closeDrawer();
        if (value) runCommand(value);
      });
    }
  }
  function openDrawer(id) {
    lastFocus = document.activeElement;
    drawerTitle.textContent = titles[id];
    drawerBody.innerHTML = renderPanel(id);
    bindPanel(id);
    overlay.hidden = false;
    drawer.hidden = false;
    requestAnimationFrame(() => drawer.classList.add("is-open"));
    document.getElementById("drawer-close").focus();
  }
  function closeDrawer() {
    drawer.classList.remove("is-open");
    window.setTimeout(() => {
      drawer.hidden = true;
      overlay.hidden = true;
      lastFocus?.focus?.();
    }, 200);
  }
  function resizeAll() {
    const stageBox = stage.getBoundingClientRect();
    const orbBox = document.getElementById("orb").getBoundingClientRect();
    view.stageW = stageBox.width;
    view.stageH = stageBox.height;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
    stars.width = Math.max(2, Math.round(stageBox.width * dpr));
    stars.height = Math.max(2, Math.round(stageBox.height * dpr));
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (orb) orb.resize(orbBox.width, orbBox.height);
  }
  function drawStars(t) {
    if (frameN % 2) return;
    sctx.clearRect(0, 0, view.stageW, view.stageH);
    starField.forEach((star) => {
      const tw = 0.28 + Math.abs(Math.sin(t * star.s + star.a * 6)) * 0.6;
      sctx.fillStyle = `rgba(210,240,255,${tw * 0.55})`;
      sctx.fillRect(star.x * view.stageW, star.y * view.stageH, star.r, star.r);
    });
  }
  function frame(t) {
    frameN += 1;
    sampleVoice(t);
    driveWaves();
    drawStars(t);
    if (orb) orb.render(t);
    if (!reduced) requestAnimationFrame(frame);
  }

  fillWave(document.getElementById("wave-listen"), 16, sideWaves);
  fillWave(document.getElementById("wave-activity"), 14, sideWaves);
  fillWave(document.getElementById("wave-voice"), 18, sideWaves);
  fillOrbWave();
  resizeAll();
  tickClock();
  window.setInterval(tickClock, 1000);
  window.addEventListener("resize", resizeAll);
  enableMic();
  if (!reduced) requestAnimationFrame(frame);
  else if (orb) orb.render(0);

  form.addEventListener("submit", (event) => { event.preventDefault(); runCommand(input.value); });
  mic.addEventListener("click", async () => {
    const next = !state.listening;
    setListening(next);
    if (next) {
      const ok = await enableMic();
      showToast(ok ? "Listening." : "Microphone blocked. Sphere stays in idle motion.");
    } else showToast("Standby.");
  });
  document.getElementById("orb").addEventListener("click", async () => {
    if (!analyser) {
      const ok = await enableMic();
      setListening(true);
      showToast(ok ? "Voice linked to the sphere." : "Allow the microphone to make it react.");
    }
  });
  document.querySelectorAll("[data-panel]").forEach((btn) => btn.addEventListener("click", () => openDrawer(btn.dataset.panel)));
  document.querySelectorAll("[data-command]").forEach((btn) => btn.addEventListener("click", () => runCommand(btn.dataset.command)));
  document.querySelectorAll("[data-range]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-range]").forEach((el) => el.classList.toggle("is-on", el === btn));
      showToast(`Voice range: ${btn.dataset.range}`);
    });
  });
  overlay.addEventListener("click", closeDrawer);
  document.getElementById("drawer-close").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !drawer.hidden) closeDrawer(); });
})();
