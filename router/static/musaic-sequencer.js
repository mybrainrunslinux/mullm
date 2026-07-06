/* Musaic Sequencer — loop-station / step-sequencer tab for the Audio Studio.
 *
 * Everything renders through Web Audio (no external deps):
 *   - Transport: BPM, swing, 4-bar pattern, lookahead scheduler
 *   - Drum machine: 8 synthesized lanes x 16 steps x 4 bars, velocity per step
 *   - Synth tracks: bass (mono) + keys (chords) with pattern generators
 *   - Sample tracks: Musaic library assets or live recordings; trim/align/loop
 *   - WebMIDI in: GM drum map (Roland TD-27 / Steven Slate triggers) with
 *     quantized live recording into the grid
 *   - LoFi Jam: one-click chill loop (swung drums, jazzy 7ths, wow, crackle)
 *   - Bounce: OfflineAudioContext -> WAV download or save to Library
 */
(function () {
  'use strict';

  const LANES = ['kick', 'snare', 'hat', 'openhat', 'clap', 'rim', 'tom', 'shaker'];
  const LANE_LABELS = ['Kick', 'Snare', 'Hat', 'OpenHat', 'Clap', 'Rim', 'Tom', 'Shaker'];
  const GM_DRUM_MAP = {
    35: 0, 36: 0, 38: 1, 40: 1, 37: 5, 39: 4, 42: 2, 44: 2, 46: 3,
    41: 6, 43: 6, 45: 6, 47: 6, 48: 6, 50: 6, 49: 7, 51: 7, 53: 7, 55: 7, 57: 7, 59: 7,
  };
  const STEPS = 16;         // 16th notes per bar
  const BARS = 4;           // pattern length
  const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  const CHORD_SHAPES = { maj7: [0, 4, 7, 11], m7: [0, 3, 7, 10], dom7: [0, 4, 7, 10], m9: [0, 3, 7, 10, 14] };
  const PROGRESSIONS = [
    [[5, 'maj7'], [4, 'm7'], [2, 'm7'], [0, 'maj7']],   // IVmaj7 iii7 ii7 Imaj7
    [[9, 'm9'], [2, 'm7'], [7, 'dom7'], [0, 'maj7']],   // vi9 ii7 V7 Imaj7
    [[0, 'maj7'], [9, 'm7'], [5, 'maj7'], [7, 'dom7']], // I vi IV V
    [[2, 'm9'], [7, 'dom7'], [0, 'maj7'], [9, 'm7']],   // ii V I vi
  ];

  // ── State ────────────────────────────────────────────────────────────────
  const S = {
    ctx: null, playing: false, bpm: 76, swing: 0.54, bar: 0, step: 0,
    nextNoteTime: 0, timer: null, lofi: 0.35, crackle: true, midiArm: false,
    midiOk: false, loops: 4, key: 0,
    // drums[bar][lane][step] = 0 | 0.6 | 1
    drums: emptyDrums(),
    bass: emptyNotes(),          // bass[bar][step] = midi | null
    keys: emptyChords(),         // keys[bar][step] = [midi,...] | null
    mutes: { drums: false, bass: false, keys: false },
    samples: [],                 // {name,buffer,gain,offsetMs,trimStart,trimEnd,loopBars,rate,mute}
    nodes: {},                   // live audio graph
  };

  function emptyDrums() { return Array.from({ length: BARS }, () => LANES.map(() => Array(STEPS).fill(0))); }
  function emptyNotes() { return Array.from({ length: BARS }, () => Array(STEPS).fill(null)); }
  function emptyChords() { return Array.from({ length: BARS }, () => Array(STEPS).fill(null)); }

  function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

  // ── Audio graph ──────────────────────────────────────────────────────────
  function ensureCtx() {
    if (S.ctx) return S.ctx;
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    S.ctx = ctx;
    S.nodes = buildGraph(ctx, ctx.destination);
    return ctx;
  }

  function buildGraph(ctx, out) {
    const master = ctx.createGain(); master.gain.value = 0.9;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -14; comp.ratio.value = 3; comp.attack.value = 0.01; comp.release.value = 0.2;
    const lofiLP = ctx.createBiquadFilter(); lofiLP.type = 'lowpass';
    lofiLP.frequency.value = lofiCutoff(S.lofi);
    const drumBus = ctx.createGain();
    const musicBus = ctx.createGain();   // keys+bass, ducked by the kick
    const sampleBus = ctx.createGain();
    drumBus.connect(comp); musicBus.connect(comp); sampleBus.connect(comp);
    comp.connect(lofiLP); lofiLP.connect(master); master.connect(out);
    let crackleSrc = null, crackleGain = null;
    if (S.crackle) {
      crackleGain = ctx.createGain(); crackleGain.gain.value = 0.05;
      crackleSrc = ctx.createBufferSource();
      crackleSrc.buffer = vinylBuffer(ctx); crackleSrc.loop = true;
      crackleSrc.connect(crackleGain); crackleGain.connect(master);
      crackleSrc.start();
    }
    return { master, comp, lofiLP, drumBus, musicBus, sampleBus, crackleSrc, crackleGain };
  }

  function lofiCutoff(amount) { return 18000 * Math.pow(3200 / 18000, amount); }

  function vinylBuffer(ctx) {
    const len = ctx.sampleRate * 2;
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) {
      d[i] = (Math.random() * 2 - 1) * 0.012;                 // hiss bed
      if (Math.random() < 0.0004) d[i] += (Math.random() * 2 - 1) * 0.6;  // pops
    }
    return buf;
  }

  // ── Instruments (pure: ctx + destination + time) ─────────────────────────
  function trigDrum(ctx, bus, lane, t, vel) {
    const v = vel;
    if (lane === 0) { // kick
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.setValueAtTime(150, t); o.frequency.exponentialRampToValueAtTime(48, t + 0.11);
      g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.28);
      o.connect(g); g.connect(bus); o.start(t); o.stop(t + 0.3);
    } else if (lane === 1) { // snare
      noiseHit(ctx, bus, t, v * 0.7, 1800, 0.16, 'bandpass');
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.setValueAtTime(190, t);
      g.gain.setValueAtTime(v * 0.5, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.12);
      o.connect(g); g.connect(bus); o.start(t); o.stop(t + 0.13);
    } else if (lane === 2) { noiseHit(ctx, bus, t, v * 0.35, 8000, 0.05, 'highpass'); }
    else if (lane === 3) { noiseHit(ctx, bus, t, v * 0.32, 7000, 0.32, 'highpass'); }
    else if (lane === 4) { // clap: 3 quick bursts
      for (let i = 0; i < 3; i++) noiseHit(ctx, bus, t + i * 0.012, v * 0.4, 1500, 0.09, 'bandpass');
    } else if (lane === 5) { noiseHit(ctx, bus, t, v * 0.4, 3600, 0.035, 'bandpass'); }
    else if (lane === 6) { // tom
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.setValueAtTime(160, t); o.frequency.exponentialRampToValueAtTime(90, t + 0.2);
      g.gain.setValueAtTime(v * 0.8, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
      o.connect(g); g.connect(bus); o.start(t); o.stop(t + 0.32);
    } else if (lane === 7) { noiseHit(ctx, bus, t, v * 0.18, 9500, 0.08, 'highpass'); }
  }

  function noiseHit(ctx, bus, t, gain, freq, dur, type) {
    const len = Math.max(1, Math.floor(ctx.sampleRate * dur));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource(); src.buffer = buf;
    const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = 0.8;
    const g = ctx.createGain();
    g.gain.setValueAtTime(gain, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(f); f.connect(g); g.connect(bus); src.start(t); src.stop(t + dur + 0.02);
  }

  function midiHz(m) { return 440 * Math.pow(2, (m - 69) / 12); }

  function trigBass(ctx, bus, t, midi, dur) {
    const o = ctx.createOscillator(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    o.type = 'sawtooth'; o.frequency.value = midiHz(midi);
    f.type = 'lowpass'; f.frequency.setValueAtTime(900, t); f.frequency.exponentialRampToValueAtTime(200, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.5, t + 0.015);
    g.gain.setTargetAtTime(0.0001, t + dur * 0.7, 0.08);
    o.connect(f); f.connect(g); g.connect(bus); o.start(t); o.stop(t + dur + 0.3);
  }

  function trigKeys(ctx, bus, t, midis, dur, wow) {
    for (const m of midis) {
      for (const [type, det, amp] of [['sine', 0, 0.16], ['triangle', -6, 0.09], ['triangle', 7, 0.07]]) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = type; o.frequency.value = midiHz(m); o.detune.value = det;
        if (wow) { // slow tape-wobble on pitch
          const lfo = ctx.createOscillator(), lg = ctx.createGain();
          lfo.frequency.value = 0.9 + Math.random() * 0.6; lg.gain.value = 6;
          lfo.connect(lg); lg.connect(o.detune); lfo.start(t); lfo.stop(t + dur + 1);
        }
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(amp, t + 0.03);
        g.gain.setTargetAtTime(0.0001, t + dur * 0.55, 0.35);
        o.connect(g); g.connect(bus); o.start(t); o.stop(t + dur + 1.2);
      }
    }
  }

  // ── Scheduling ───────────────────────────────────────────────────────────
  function stepDur() { return 60 / S.bpm / 4; }
  function swungTime(base, step) { return base + (step % 2 === 1 ? stepDur() * (S.swing - 0.5) * 2 : 0); }

  function scheduleStep(ctx, nodes, bar, step, t, forLive) {
    if (!S.mutes.drums) {
      LANES.forEach((_, lane) => {
        const v = S.drums[bar][lane][step];
        if (v > 0) {
          trigDrum(ctx, nodes.drumBus, lane, t, v);
          if (lane === 0) { // gentle sidechain-style duck on the music bus
            nodes.musicBus.gain.cancelScheduledValues(t);
            nodes.musicBus.gain.setValueAtTime(0.72, t);
            nodes.musicBus.gain.setTargetAtTime(1.0, t + 0.02, 0.09);
          }
        }
      });
    }
    if (!S.mutes.bass) {
      const n = S.bass[bar][step];
      if (n != null) trigBass(ctx, nodes.musicBus, t, n, stepDur() * 2.6);
    }
    if (!S.mutes.keys) {
      const c = S.keys[bar][step];
      if (c) trigKeys(ctx, nodes.musicBus, t, c, stepDur() * 10, S.lofi > 0.2);
    }
    if (forLive && bar === 0 && step === 0) scheduleSamplesLive(ctx, nodes, t);
  }

  function scheduleSamplesLive(ctx, nodes, patternStart) {
    // (Re)launch each sample loop at the top of the 4-bar pattern.
    const patDur = stepDur() * STEPS * BARS;
    for (const smp of S.samples) {
      if (smp.mute || !smp.buffer) continue;
      const loopDur = stepDur() * STEPS * smp.loopBars;
      for (let k = 0; k * loopDur < patDur - 0.001; k++) {
        launchSample(ctx, nodes.sampleBus, smp, patternStart + k * loopDur, loopDur);
      }
    }
  }

  function launchSample(ctx, bus, smp, when, maxDur) {
    const src = ctx.createBufferSource();
    src.buffer = smp.buffer; src.playbackRate.value = smp.rate;
    const g = ctx.createGain(); g.gain.value = smp.gain;
    src.connect(g); g.connect(bus);
    const startInBuf = Math.max(0, smp.trimStart);
    const dur = Math.min(Math.max(0.02, smp.trimEnd - smp.trimStart), maxDur * smp.rate);
    src.start(Math.max(when + smp.offsetMs / 1000, ctx.currentTime), startInBuf, dur);
  }

  function tick() {
    const ctx = S.ctx, ahead = 0.12;
    while (S.nextNoteTime < ctx.currentTime + ahead) {
      const t = swungTime(S.nextNoteTime, S.step);
      scheduleStep(ctx, S.nodes, S.bar, S.step, t, true);
      paintPlayhead(S.bar, S.step, (S.nextNoteTime - ctx.currentTime) * 1000);
      S.nextNoteTime += stepDur();
      S.step++;
      if (S.step >= STEPS) { S.step = 0; S.bar = (S.bar + 1) % BARS; }
    }
  }

  function play() {
    const ctx = ensureCtx();
    if (ctx.state === 'suspended') ctx.resume();
    if (S.playing) return;
    S.playing = true; S.bar = 0; S.step = 0;
    S.nextNoteTime = ctx.currentTime + 0.06;
    S.timer = setInterval(tick, 25);
    ui.playBtn.textContent = '■ Stop';
  }

  function stop() {
    S.playing = false;
    if (S.timer) clearInterval(S.timer);
    ui.playBtn.textContent = '▶ Play';
    document.querySelectorAll('.sq-cell.playing').forEach(el => el.classList.remove('playing'));
  }

  // ── Generators ───────────────────────────────────────────────────────────
  function generateDrums(style, seed) {
    const r = rng(seed);
    const d = emptyDrums();
    for (let b = 0; b < BARS; b++) {
      const fill = b === BARS - 1;
      d[b][0][0] = 1;                                    // kick on the one
      d[b][0][7 + (r() < 0.5 ? 0 : 1)] = 0.6;            // pickup kick
      if (r() < 0.6) d[b][0][10] = 1;
      d[b][1][4] = 1; d[b][1][12] = 1;                   // backbeat snare
      for (let s = 0; s < STEPS; s += 2) d[b][2][s] = s % 4 === 0 ? 0.6 : 1;  // swung hats
      if (style === 'lofi') {
        for (let s = 0; s < STEPS; s++) if (r() < 0.35) d[b][7][s] = 0.6;     // shaker dust
        if (r() < 0.5) d[b][3][14] = 0.6;                                     // open hat sigh
        if (fill) { d[b][1][14] = 0.6; d[b][1][15] = r() < 0.5 ? 0.6 : 0; d[b][6][15] = 0.6; }
      } else if (fill) { d[b][1][13] = 0.6; d[b][1][14] = 0.6; d[b][1][15] = 1; }
    }
    return d;
  }

  function chordMidis(rootPc, quality, octave) {
    return CHORD_SHAPES[quality].map(iv => 12 * octave + rootPc + iv);
  }

  function generateProgression(keyPc, seed) {
    const r = rng(seed);
    const prog = PROGRESSIONS[Math.floor(r() * PROGRESSIONS.length)];
    const keys = emptyChords(), bass = emptyNotes();
    prog.forEach(([deg, quality], b) => {
      const rootPc = (keyPc + deg) % 12;
      const voicing = chordMidis(rootPc, quality, 4);
      keys[b][0] = voicing;
      if (r() < 0.7) keys[b][10 + Math.floor(r() * 2)] = voicing.slice(0, 3); // soft re-hit
      const rootMidi = 12 * 2 + rootPc;                   // bass octave 2
      bass[b][0] = rootMidi;
      bass[b][8] = r() < 0.5 ? rootMidi + 7 : rootMidi;   // fifth or repeat
      if (r() < 0.5) bass[b][14] = rootMidi + (r() < 0.5 ? -2 : 2); // approach note
    });
    return { keys, bass };
  }

  function lofiJam() {
    const seed = Math.floor(Math.random() * 1e9);
    const r = rng(seed);
    S.bpm = 72 + Math.floor(r() * 10);          // chill, consistent
    S.swing = 0.55; S.lofi = 0.55; S.crackle = true;
    S.key = Math.floor(r() * 12);
    S.drums = generateDrums('lofi', seed);
    const prog = generateProgression(S.key, seed);
    S.keys = prog.keys; S.bass = prog.bass;
    rebuildLiveGraph(); syncUI(); renderGrids(); persist();
    setStatus(`LoFi jam in ${NOTE_NAMES[S.key]} @ ${S.bpm} BPM — press Play, then Bounce for a drive-ready WAV`);
  }

  function rebuildLiveGraph() {
    if (!S.ctx) return;
    try { if (S.nodes.crackleSrc) S.nodes.crackleSrc.stop(); } catch (e) { /* already stopped */ }
    try { S.nodes.master.disconnect(); } catch (e) { /* first build */ }
    S.nodes = buildGraph(S.ctx, S.ctx.destination);
  }

  // ── Bounce (offline render → WAV) ────────────────────────────────────────
  async function bounce() {
    const patDur = stepDur() * STEPS * BARS;
    const total = patDur * S.loops + 1.5;                 // tail for release
    const off = new OfflineAudioContext(2, Math.ceil(total * 44100), 44100);
    const nodes = buildGraph(off, off.destination);
    for (let loop = 0; loop < S.loops; loop++) {
      for (let b = 0; b < BARS; b++) {
        for (let s = 0; s < STEPS; s++) {
          const base = 0.05 + loop * patDur + (b * STEPS + s) * stepDur();
          scheduleStep(off, nodes, b, s, swungTime(base, s), false);
        }
      }
      const top = 0.05 + loop * patDur;
      for (const smp of S.samples) {
        if (smp.mute || !smp.buffer) continue;
        const loopDur = stepDur() * STEPS * smp.loopBars;
        for (let k = 0; k * loopDur < patDur - 0.001; k++) {
          launchSample(off, nodes.sampleBus, smp, top + k * loopDur, loopDur);
        }
      }
    }
    setStatus('Bouncing… (offline render)');
    const rendered = await off.startRendering();
    const wav = encodeWav(rendered);
    const blob = new Blob([wav], { type: 'audio/wav' });
    const name = `musaic-jam-${NOTE_NAMES[S.key].replace('#', 's')}-${S.bpm}bpm.wav`;
    ui.bounceLink.href = URL.createObjectURL(blob);
    ui.bounceLink.download = name;
    ui.bounceLink.style.display = 'inline-block';
    ui.bounceLink.textContent = `⬇ ${name} (${(blob.size / 1e6).toFixed(1)} MB)`;
    ui.saveLibBtn.style.display = 'inline-block';
    ui.saveLibBtn.onclick = async () => {
      const fd = new FormData(); fd.append('file', blob, name);
      const resp = await fetch('/api/musaic/upload', { method: 'POST', body: fd });
      setStatus(resp.ok ? `Saved ${name} to Library` : `Library save failed (${resp.status})`);
    };
    setStatus(`Bounced ${S.loops * BARS} bars → ${name}`);
  }

  function encodeWav(buf) {
    const nCh = buf.numberOfChannels, len = buf.length * nCh * 2 + 44;
    const ab = new ArrayBuffer(len), v = new DataView(ab);
    const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    ws(0, 'RIFF'); v.setUint32(4, len - 8, true); ws(8, 'WAVE'); ws(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, nCh, true);
    v.setUint32(24, buf.sampleRate, true); v.setUint32(28, buf.sampleRate * nCh * 2, true);
    v.setUint16(32, nCh * 2, true); v.setUint16(34, 16, true); ws(36, 'data');
    v.setUint32(40, len - 44, true);
    const chans = []; for (let c = 0; c < nCh; c++) chans.push(buf.getChannelData(c));
    let o = 44;
    for (let i = 0; i < buf.length; i++) {
      for (let c = 0; c < nCh; c++) {
        const x = Math.max(-1, Math.min(1, chans[c][i]));
        v.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7FFF, true); o += 2;
      }
    }
    return ab;
  }

  // ── MIDI in (TD-27 / SSD triggers) ───────────────────────────────────────
  async function initMidi() {
    if (!navigator.requestMIDIAccess) { ui.midiChip.textContent = 'MIDI: unsupported'; return; }
    try {
      const midi = await navigator.requestMIDIAccess();
      const wire = () => {
        let n = 0;
        midi.inputs.forEach(inp => { inp.onmidimessage = onMidi; n++; });
        S.midiOk = n > 0;
        ui.midiChip.textContent = n ? `MIDI: ${n} input${n > 1 ? 's' : ''}` : 'MIDI: no inputs';
      };
      midi.onstatechange = wire; wire();
    } catch (e) { ui.midiChip.textContent = 'MIDI: denied'; }
  }

  function onMidi(msg) {
    const [st, note, vel] = msg.data;
    if ((st & 0xf0) !== 0x90 || vel === 0) return;
    const lane = GM_DRUM_MAP[note];
    if (lane === undefined) return;
    const v = vel > 90 ? 1 : 0.6;
    const ctx = ensureCtx();
    trigDrum(ctx, S.nodes.drumBus, lane, ctx.currentTime, v);   // always audition
    if (S.midiArm && S.playing) {                                // quantize-record
      const pos = S.bar * STEPS + S.step;                        // nearest current step
      const b = Math.floor(pos / STEPS), s = pos % STEPS;
      S.drums[b][LANES.indexOf(LANES[lane])][s] = Math.max(S.drums[b][lane][s], v);
      renderDrumCell(b, lane, s);
      persist();
    }
  }

  // ── Sample tracks ────────────────────────────────────────────────────────
  async function addLibrarySample(rec) {
    const ctx = ensureCtx();
    setStatus(`Loading ${rec.name}…`);
    const resp = await fetch(rec.stream_url);
    const buf = await ctx.decodeAudioData(await resp.arrayBuffer());
    S.samples.push(sampleTrack(rec.name, buf));
    renderSamples(); setStatus(`Added ${rec.name}`);
  }

  function sampleTrack(name, buffer) {
    return { name, buffer, gain: 0.9, offsetMs: 0, trimStart: 0, trimEnd: buffer.duration, loopBars: BARS, rate: 1, mute: false };
  }

  let recStream = null, recRecorder = null, recChunks = [];
  async function recordIntoTrack() {
    if (recRecorder) {  // stop path
      recRecorder.stop(); return;
    }
    recStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false },
    });
    recChunks = [];
    recRecorder = new MediaRecorder(recStream);
    recRecorder.ondataavailable = e => { if (e.data.size) recChunks.push(e.data); };
    recRecorder.onstop = async () => {
      recStream.getTracks().forEach(t => t.stop());
      const blob = new Blob(recChunks);
      recRecorder = null; ui.recBtn.textContent = '● Record into track';
      const ctx = ensureCtx();
      try {
        const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
        S.samples.push(sampleTrack(`take-${new Date().toISOString().slice(11, 19)}`, buf));
        renderSamples(); setStatus('Take added as a sample track — trim & align below');
      } catch (e) { setStatus('Could not decode recording'); }
    };
    recRecorder.start();
    ui.recBtn.textContent = '■ Stop take';
    if (!S.playing) play();   // record against the groove
    setStatus('Recording… play along, then Stop take');
  }

  // ── Persistence ──────────────────────────────────────────────────────────
  function persist() {
    try {
      localStorage.setItem('musaic-seq-v1', JSON.stringify({
        bpm: S.bpm, swing: S.swing, lofi: S.lofi, crackle: S.crackle, key: S.key,
        drums: S.drums, bass: S.bass, keys: S.keys, mutes: S.mutes, loops: S.loops,
      }));
    } catch (e) { /* storage full/blocked — non-fatal */ }
  }

  function restore() {
    try {
      const raw = localStorage.getItem('musaic-seq-v1');
      if (!raw) return;
      const d = JSON.parse(raw);
      Object.assign(S, {
        bpm: d.bpm ?? S.bpm, swing: d.swing ?? S.swing, lofi: d.lofi ?? S.lofi,
        crackle: d.crackle ?? S.crackle, key: d.key ?? 0, loops: d.loops ?? S.loops,
        drums: d.drums ?? S.drums, bass: d.bass ?? S.bass, keys: d.keys ?? S.keys,
        mutes: d.mutes ?? S.mutes,
      });
    } catch (e) { /* corrupt state — start fresh */ }
  }

  // ── UI ───────────────────────────────────────────────────────────────────
  const ui = {};

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function setStatus(msg) { ui.status.textContent = msg; }

  function init(container) {
    injectCss();
    restore();
    container.innerHTML = '';
    const root = el('div', 'sq-root');

    // Transport
    const bar = el('div', 'sq-transport');
    ui.playBtn = el('button', 'sq-btn sq-primary', '▶ Play');
    ui.playBtn.onclick = () => (S.playing ? stop() : play());
    bar.appendChild(ui.playBtn);
    bar.appendChild(labeled('BPM', numInput(50, 180, S.bpm, v => { S.bpm = v; persist(); })));
    bar.appendChild(labeled('Swing', rangeInput(50, 66, S.swing * 100, v => { S.swing = v / 100; persist(); })));
    bar.appendChild(labeled('LoFi', rangeInput(0, 100, S.lofi * 100, v => {
      S.lofi = v / 100;
      if (S.nodes.lofiLP) S.nodes.lofiLP.frequency.value = lofiCutoff(S.lofi);
      persist();
    })));
    const crk = el('button', 'sq-btn', S.crackle ? 'Crackle: on' : 'Crackle: off');
    crk.onclick = () => { S.crackle = !S.crackle; crk.textContent = S.crackle ? 'Crackle: on' : 'Crackle: off'; rebuildLiveGraph(); persist(); };
    bar.appendChild(crk);
    const jam = el('button', 'sq-btn sq-gold', '✨ LoFi Jam');
    jam.onclick = lofiJam; bar.appendChild(jam);
    ui.midiChip = el('span', 'sq-chip', 'MIDI: …'); bar.appendChild(ui.midiChip);
    const arm = el('button', 'sq-btn', 'MIDI rec: off');
    arm.onclick = () => { S.midiArm = !S.midiArm; arm.textContent = S.midiArm ? 'MIDI rec: ON' : 'MIDI rec: off'; };
    bar.appendChild(arm);
    root.appendChild(bar);

    // Bounce row
    const brow = el('div', 'sq-transport');
    brow.appendChild(labeled('Loops', numInput(1, 32, S.loops, v => { S.loops = v; persist(); })));
    const bounceBtn = el('button', 'sq-btn sq-gold', '⤓ Bounce WAV');
    bounceBtn.onclick = () => bounce().catch(e => setStatus('Bounce failed: ' + e.message));
    brow.appendChild(bounceBtn);
    ui.bounceLink = el('a', 'sq-btn'); ui.bounceLink.style.display = 'none';
    brow.appendChild(ui.bounceLink);
    ui.saveLibBtn = el('button', 'sq-btn', '↥ Save to Library'); ui.saveLibBtn.style.display = 'none';
    brow.appendChild(ui.saveLibBtn);
    root.appendChild(brow);

    ui.status = el('div', 'sq-status', 'Sequencer ready — click steps, or hit ✨ LoFi Jam.');
    root.appendChild(ui.status);

    // Grids
    ui.drumWrap = el('div'); root.appendChild(section(root, 'Drum machine', ui.drumWrap, 'drums'));
    ui.bassWrap = el('div'); root.appendChild(section(root, 'Bass', ui.bassWrap, 'bass'));
    ui.keysWrap = el('div'); root.appendChild(section(root, 'Keys (chords)', ui.keysWrap, 'keys'));

    // Samples
    const shead = el('div', 'sq-sechead');
    shead.appendChild(el('span', 'sq-sectitle', 'Sample / loop tracks'));
    ui.recBtn = el('button', 'sq-btn', '● Record into track');
    ui.recBtn.onclick = () => recordIntoTrack().catch(e => setStatus('Mic error: ' + e.message));
    shead.appendChild(ui.recBtn);
    const addBtn = el('button', 'sq-btn', '+ From Library');
    addBtn.onclick = openLibraryPicker;
    shead.appendChild(addBtn);
    root.appendChild(shead);
    ui.samplesWrap = el('div'); root.appendChild(ui.samplesWrap);
    ui.libPick = el('div', 'sq-libpick'); ui.libPick.style.display = 'none';
    root.appendChild(ui.libPick);

    container.appendChild(root);
    renderGrids(); renderSamples(); initMidi();
  }

  function section(root, title, body, muteKey) {
    const wrap = el('div', 'sq-section');
    const head = el('div', 'sq-sechead');
    head.appendChild(el('span', 'sq-sectitle', title));
    const mute = el('button', 'sq-btn sq-small', S.mutes[muteKey] ? 'Unmute' : 'Mute');
    mute.onclick = () => {
      S.mutes[muteKey] = !S.mutes[muteKey];
      mute.textContent = S.mutes[muteKey] ? 'Unmute' : 'Mute'; persist();
    };
    head.appendChild(mute);
    if (muteKey === 'drums') {
      const gen = el('button', 'sq-btn sq-small', 'Generate');
      gen.onclick = () => { S.drums = generateDrums('lofi', Date.now() & 0xffff); renderGrids(); persist(); };
      head.appendChild(gen);
      const clr = el('button', 'sq-btn sq-small', 'Clear');
      clr.onclick = () => { S.drums = emptyDrums(); renderGrids(); persist(); };
      head.appendChild(clr);
    } else if (muteKey === 'bass' || muteKey === 'keys') {
      const gen = el('button', 'sq-btn sq-small', 'Generate both');
      gen.onclick = () => {
        const p = generateProgression(S.key, Date.now() & 0xffff);
        S.keys = p.keys; S.bass = p.bass; renderGrids(); persist();
      };
      head.appendChild(gen);
    }
    wrap.appendChild(head); wrap.appendChild(body);
    return wrap;
  }

  function labeled(name, input) {
    const w = el('label', 'sq-label'); w.appendChild(el('span', null, name)); w.appendChild(input);
    return w;
  }

  function numInput(min, max, val, cb) {
    const i = el('input'); i.type = 'number'; i.min = min; i.max = max; i.value = val; i.className = 'sq-num';
    i.oninput = () => cb(Math.max(min, Math.min(max, Number(i.value) || min)));
    return i;
  }

  function rangeInput(min, max, val, cb) {
    const i = el('input'); i.type = 'range'; i.min = min; i.max = max; i.value = val; i.className = 'sq-range';
    i.oninput = () => cb(Number(i.value));
    return i;
  }

  // Drum grid: BARS blocks of 16 steps x 8 lanes
  function renderGrids() {
    ui.drumWrap.innerHTML = '';
    for (let b = 0; b < BARS; b++) {
      const g = el('div', 'sq-grid');
      g.appendChild(el('div', 'sq-barlabel', 'Bar ' + (b + 1)));
      LANES.forEach((_, lane) => {
        const row = el('div', 'sq-row');
        row.appendChild(el('span', 'sq-lane', LANE_LABELS[lane]));
        for (let s = 0; s < STEPS; s++) {
          const c = el('button', 'sq-cell');
          c.dataset.k = `${b}-${lane}-${s}`;
          styleDrumCell(c, S.drums[b][lane][s], s);
          c.onclick = () => {
            const cur = S.drums[b][lane][s];
            S.drums[b][lane][s] = cur === 0 ? 0.6 : cur === 0.6 ? 1 : 0;
            styleDrumCell(c, S.drums[b][lane][s], s); persist();
          };
          row.appendChild(c);
        }
        g.appendChild(row);
      });
      ui.drumWrap.appendChild(g);
    }
    renderPitchGrid(ui.bassWrap, S.bass, false);
    renderPitchGrid(ui.keysWrap, S.keys, true);
  }

  function renderDrumCell(b, lane, s) {
    const c = ui.drumWrap.querySelector(`[data-k="${b}-${lane}-${s}"]`);
    if (c) styleDrumCell(c, S.drums[b][lane][s], s);
  }

  function styleDrumCell(c, v, s) {
    c.classList.toggle('on-soft', v === 0.6);
    c.classList.toggle('on-hard', v === 1);
    c.classList.toggle('beat', s % 4 === 0);
  }

  function describeCell(val, isChord) {
    if (val == null) return '·';
    if (isChord) return NOTE_NAMES[val[0] % 12] + (val.length > 3 ? '7' : '');
    return NOTE_NAMES[val % 12] + Math.floor(val / 12 - 1);
  }

  function renderPitchGrid(wrap, model, isChord) {
    wrap.innerHTML = '';
    for (let b = 0; b < BARS; b++) {
      const row = el('div', 'sq-row sq-pitchrow');
      row.appendChild(el('span', 'sq-lane', 'Bar ' + (b + 1)));
      for (let s = 0; s < STEPS; s++) {
        const c = el('button', 'sq-cell sq-pitch');
        c.textContent = describeCell(model[b][s], isChord);
        c.classList.toggle('beat', s % 4 === 0);
        c.classList.toggle('on-hard', model[b][s] != null);
        c.onclick = () => {
          if (model[b][s] != null) { model[b][s] = null; }
          else if (isChord) { model[b][s] = chordMidis((S.key + [0, 5, 9, 7][b % 4]) % 12, b % 2 ? 'm7' : 'maj7', 4); }
          else { model[b][s] = 24 + ((S.key + [0, 0, 7, 5][s % 4]) % 12); }
          c.textContent = describeCell(model[b][s], isChord);
          c.classList.toggle('on-hard', model[b][s] != null);
          persist();
        };
        row.appendChild(c);
      }
      wrap.appendChild(row);
    }
  }

  function paintPlayhead(bar, step, delayMs) {
    setTimeout(() => {
      document.querySelectorAll('.sq-cell.playing').forEach(e => e.classList.remove('playing'));
      document.querySelectorAll(`[data-k^="${bar}-"][data-k$="-${step}"]`).forEach(e => e.classList.add('playing'));
    }, Math.max(0, delayMs));
  }

  function renderSamples() {
    ui.samplesWrap.innerHTML = '';
    if (!S.samples.length) {
      ui.samplesWrap.appendChild(el('div', 'sq-empty', 'No sample tracks yet — record a take or add one from the Library.'));
      return;
    }
    S.samples.forEach((smp, idx) => {
      const card = el('div', 'sq-sample');
      const head = el('div', 'sq-sechead');
      head.appendChild(el('span', 'sq-sectitle', `${smp.name} (${smp.buffer.duration.toFixed(2)}s)`));
      const mute = el('button', 'sq-btn sq-small', smp.mute ? 'Unmute' : 'Mute');
      mute.onclick = () => { smp.mute = !smp.mute; mute.textContent = smp.mute ? 'Unmute' : 'Mute'; };
      head.appendChild(mute);
      const del = el('button', 'sq-btn sq-small', '✕');
      del.onclick = () => { S.samples.splice(idx, 1); renderSamples(); };
      head.appendChild(del);
      card.appendChild(head);
      const row = el('div', 'sq-transport');
      row.appendChild(labeled('Gain', rangeInput(0, 120, smp.gain * 100, v => { smp.gain = v / 100; })));
      row.appendChild(labeled('Align ms', numInput(-500, 500, smp.offsetMs, v => { smp.offsetMs = v; })));
      row.appendChild(labeled('Trim in s', numInput(0, Math.ceil(smp.buffer.duration), smp.trimStart, v => { smp.trimStart = v; })));
      row.appendChild(labeled('Trim out s', numInput(0, Math.ceil(smp.buffer.duration), smp.trimEnd, v => { smp.trimEnd = v; })));
      row.appendChild(labeled('Loop bars', numInput(1, 8, smp.loopBars, v => { smp.loopBars = v; })));
      row.appendChild(labeled('Rate', rangeInput(50, 150, smp.rate * 100, v => { smp.rate = v / 100; })));
      card.appendChild(row);
      ui.samplesWrap.appendChild(card);
    });
  }

  async function openLibraryPicker() {
    ui.libPick.style.display = 'block';
    ui.libPick.textContent = 'Loading library…';
    try {
      const recs = await (await fetch('/api/musaic/library')).json();
      ui.libPick.innerHTML = '';
      ui.libPick.appendChild(el('div', 'sq-sectitle', 'Pick a library asset:'));
      if (!recs.length) ui.libPick.appendChild(el('div', 'sq-empty', 'Library is empty — record or upload in the other tabs.'));
      recs.slice(0, 40).forEach(rec => {
        const b = el('button', 'sq-btn sq-small', `${rec.name} (${rec.bucket})`);
        b.onclick = () => { ui.libPick.style.display = 'none'; addLibrarySample(rec).catch(e => setStatus('Load failed: ' + e.message)); };
        ui.libPick.appendChild(b);
      });
      const close = el('button', 'sq-btn sq-small', 'Close');
      close.onclick = () => { ui.libPick.style.display = 'none'; };
      ui.libPick.appendChild(close);
    } catch (e) { ui.libPick.textContent = 'Library unavailable: ' + e.message; }
  }

  function syncUI() {
    const t = ui.playBtn.closest('.sq-root');
    t.querySelectorAll('.sq-transport')[0].querySelector('.sq-num').value = S.bpm;
    const ranges = t.querySelectorAll('.sq-transport')[0].querySelectorAll('.sq-range');
    ranges[0].value = S.swing * 100; ranges[1].value = S.lofi * 100;
    if (S.nodes.lofiLP) S.nodes.lofiLP.frequency.value = lofiCutoff(S.lofi);
  }

  function injectCss() {
    if (document.getElementById('sq-css')) return;
    const css = document.createElement('style'); css.id = 'sq-css';
    css.textContent = `
.sq-root{display:flex;flex-direction:column;gap:12px}
.sq-transport{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.sq-btn{background:var(--panel,#1a2332);border:1px solid var(--border,#2a3648);color:var(--text,#e2e8f0);
  border-radius:6px;padding:6px 12px;cursor:pointer;font:12px/1.4 var(--mono,monospace);text-decoration:none}
.sq-btn:hover{border-color:var(--gold,#F59E0B)}
.sq-gold{border-color:var(--gold,#F59E0B);color:var(--gold,#F59E0B)}
.sq-primary{font-weight:700}
.sq-small{padding:3px 8px;font-size:11px}
.sq-chip{font:11px var(--mono,monospace);color:var(--text2,#94a3b8);border:1px dashed var(--border,#2a3648);
  border-radius:999px;padding:3px 10px}
.sq-label{display:flex;align-items:center;gap:6px;font:11px var(--mono,monospace);color:var(--text2,#94a3b8)}
.sq-num{width:64px;background:var(--panel,#1a2332);border:1px solid var(--border,#2a3648);color:var(--text,#e2e8f0);
  border-radius:4px;padding:4px 6px}
.sq-range{width:110px;accent-color:var(--gold,#F59E0B)}
.sq-status{font:12px var(--mono,monospace);color:var(--gold,#F59E0B);min-height:18px}
.sq-section{border:1px solid var(--border,#2a3648);border-radius:8px;padding:10px}
.sq-sechead{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
.sq-sectitle{font:600 12px var(--mono,monospace);color:var(--text,#e2e8f0)}
.sq-grid{margin-bottom:8px}
.sq-barlabel{font:10px var(--mono,monospace);color:var(--text2,#94a3b8);margin:4px 0}
.sq-row{display:flex;gap:2px;align-items:center;margin-bottom:2px}
.sq-lane{width:58px;font:10px var(--mono,monospace);color:var(--text2,#94a3b8);flex:none}
.sq-cell{width:24px;height:20px;flex:none;border:1px solid var(--border,#2a3648);border-radius:3px;
  background:transparent;cursor:pointer;padding:0;font:8px var(--mono,monospace);color:var(--text2,#94a3b8)}
.sq-cell.beat{border-color:#3a4a60}
.sq-cell.on-soft{background:#7c5f1d}
.sq-cell.on-hard{background:var(--gold,#F59E0B);color:#111}
.sq-cell.playing{outline:2px solid #22c55e}
.sq-pitch{width:42px;font-size:9px}
.sq-pitchrow{margin-bottom:3px}
.sq-sample{border:1px solid var(--border,#2a3648);border-radius:8px;padding:10px;margin-bottom:8px}
.sq-empty{font:11px var(--mono,monospace);color:var(--text2,#94a3b8);padding:8px}
.sq-libpick{border:1px solid var(--gold,#F59E0B);border-radius:8px;padding:10px;display:flex;flex-wrap:wrap;gap:6px}
@media (max-width:720px){.sq-cell{width:16px}.sq-pitch{width:30px}.sq-lane{width:44px}}`;
    document.head.appendChild(css);
  }

  window.MusaicSeq = {
    init, play, stop, lofiJam, bounce,
    _state: S,  // exposed for tests
  };
})();
