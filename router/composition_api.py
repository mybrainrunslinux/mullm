"""Deterministic composition exports for game-audio prototyping.

The endpoint intentionally does not call an LLM or a cloud service. It turns a
small, reviewable note specification into interoperable notation, playback and
instrument-animation artifacts.
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave
import zipfile
from html import escape

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/composition", tags=["composition"])

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
DULCIMER_18 = (
    "G3", "A3", "B3", "C4", "D4", "E4", "F4", "G4",
    "D4", "E4", "F#4", "G4", "A4", "B4", "C5", "D5", "E5", "F#5",
)


class CompositionNote(BaseModel):
    pitch: str = Field(pattern=r"^[A-G](?:#|b)?[2-7]$")
    beats: float = Field(default=1.0, gt=0, le=16)
    velocity: int = Field(default=88, ge=1, le=127)


class CompositionRequest(BaseModel):
    title: str = Field(default="Untitled motif", min_length=1, max_length=100)
    bpm: int = Field(default=96, ge=30, le=240)
    notes: list[CompositionNote] = Field(min_length=1, max_length=512)
    instrument: str = Field(default="hammered_dulcimer_18")

    @field_validator("instrument")
    @classmethod
    def supported_instrument(cls, value: str) -> str:
        if value != "hammered_dulcimer_18":
            raise ValueError("supported instrument: hammered_dulcimer_18")
        return value


def _midi_number(pitch: str) -> int:
    match = __import__("re").fullmatch(r"([A-G])([#b]?)([2-7])", pitch)
    if not match:
        raise ValueError(f"invalid pitch: {pitch}")
    letter, accidental, octave_text = match.groups()
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter]
    semitone += 1 if accidental == "#" else -1 if accidental == "b" else 0
    return (int(octave_text) + 1) * 12 + semitone


def _canonical_pitch(pitch: str) -> str:
    midi = _midi_number(pitch)
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def _varlen(value: int) -> bytes:
    parts = [value & 0x7F]
    while value >> 7:
        value >>= 7
        parts.append((value & 0x7F) | 0x80)
    return bytes(reversed(parts))


def _midi_bytes(body: CompositionRequest) -> bytes:
    ticks = 480
    tempo = round(60_000_000 / body.bpm)
    track = bytearray(b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big"))
    # GM dulcimer program 15 (zero-based 15 = Dulcimer).
    track += b"\x00\xc0\x0f"
    for item in body.notes:
        note = _midi_number(item.pitch)
        duration = max(1, round(item.beats * ticks))
        track += b"\x00\x90" + bytes((note, item.velocity))
        track += _varlen(duration) + b"\x80" + bytes((note, 0))
    track += b"\x00\xff\x2f\x00"
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, ticks)
    return header + b"MTrk" + struct.pack(">I", len(track)) + track


def _musicxml(body: CompositionRequest) -> bytes:
    divisions = 4
    measures: list[str] = []
    current: list[str] = []
    used = 0
    number = 1
    for item in body.notes:
        canonical = _canonical_pitch(item.pitch)
        pitch_name, octave = canonical[:-1], canonical[-1]
        step = pitch_name[0]
        alter = "<alter>1</alter>" if "#" in pitch_name else ""
        duration = max(1, round(item.beats * divisions))
        if used and used + duration > divisions * 4:
            measures.append(f'<measure number="{number}">' + "".join(current) + "</measure>")
            number += 1
            current, used = [], 0
        current.append(
            f"<note><pitch><step>{step}</step>{alter}<octave>{octave}</octave></pitch>"
            f"<duration>{duration}</duration><voice>1</voice><type>quarter</type>"
            f"<velocity>{item.velocity}</velocity></note>"
        )
        used += duration
    if current:
        measures.append(f'<measure number="{number}">' + "".join(current) + "</measure>")
    first = measures[0].replace(
        ">", f"><attributes><divisions>{divisions}</divisions><key><fifths>0</fifths></key>"
        "<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef>"
        f"</attributes><direction><sound tempo=\"{body.bpm}\"/></direction>", 1
    )
    measures[0] = first
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<score-partwise version="4.0"><work><work-title>' + escape(body.title) +
        '</work-title></work><part-list><score-part id="P1"><part-name>Hammered Dulcimer</part-name>'
        '</score-part></part-list><part id="P1">' + "".join(measures) + '</part></score-partwise>'
    )
    return xml.encode()


def _course_map(body: CompositionRequest) -> bytes:
    courses: dict[str, list[int]] = {}
    for index, pitch in enumerate(DULCIMER_18):
        courses.setdefault(pitch, []).append(index)
    beat = 0.0
    strikes = []
    hand = "R"
    for item in body.notes:
        pitch = _canonical_pitch(item.pitch)
        choices = courses.get(pitch)
        if not choices:
            raise HTTPException(status_code=422, detail=f"{item.pitch} is outside hammered_dulcimer_18 range")
        strikes.append({"beat": beat, "pitch": pitch, "course": choices[0], "hand": hand, "velocity": item.velocity})
        beat += item.beats
        hand = "L" if hand == "R" else "R"
    return json.dumps({"instrument": body.instrument, "bpm": body.bpm, "courses": DULCIMER_18, "strikes": strikes}, indent=2).encode()


def _preview_wav(body: CompositionRequest) -> bytes:
    rate = 44100
    seconds_per_beat = 60 / body.bpm
    total = sum(item.beats for item in body.notes) * seconds_per_beat + 2.5
    samples = [0.0] * math.ceil(total * rate)
    cursor = 0
    for item in body.notes:
        duration = item.beats * seconds_per_beat
        start = cursor
        freq = 440 * (2 ** ((_midi_number(item.pitch) - 69) / 12))
        ring = min(3.0, max(0.65, duration + 1.35))
        amplitude = item.velocity / 127 * 0.28
        for offset in range(min(len(samples) - start, round(ring * rate))):
            t = offset / rate
            strike = math.exp(-t * 2.35)
            transient = math.exp(-t * 52) * math.sin(2 * math.pi * freq * 3.07 * t)
            value = (math.sin(2 * math.pi * freq * t) * 0.64 +
                     math.sin(2 * math.pi * freq * 2.002 * t) * 0.23 +
                     math.sin(2 * math.pi * freq * 3.01 * t) * 0.09 + transient * 0.28)
            samples[start + offset] += value * strike * amplitude
        cursor += round(duration * rate)
    peak = max(1.0, max(abs(sample) for sample in samples) * 1.05)
    pcm = b"".join(struct.pack("<h", max(-32767, min(32767, round(sample / peak * 32767)))) for sample in samples)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return output.getvalue()


@router.get("/status")
async def composition_status():
    return {"ok": True, "instruments": ["hammered_dulcimer_18"], "exports": ["musicxml", "midi", "course_map", "wav"]}


@router.post("/render")
async def composition_render(body: CompositionRequest):
    """Render notation, MIDI, dulcimer strikes, and preview audio as a ZIP."""
    course_map = _course_map(body)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("score.musicxml", _musicxml(body))
        archive.writestr("performance.mid", _midi_bytes(body))
        archive.writestr("dulcimer-courses.json", course_map)
        archive.writestr("preview.wav", _preview_wav(body))
        archive.writestr("request.json", body.model_dump_json(indent=2))
    safe_title = __import__("re").sub(r"[^a-z0-9-]+", "", "-".join(body.title.lower().split()))[:60] or "composition"
    return Response(output.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{safe_title}.zip"'})
