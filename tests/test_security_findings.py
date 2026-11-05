import shutil
import ssl
import subprocess
import wave
from pathlib import Path

import pytest
import uvicorn
from fastapi import HTTPException

from router.server_tls import tls_options


@pytest.fixture
def certificate(tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('OpenSSL is required for TLS handshake checks')
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run([
        'openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
        '-keyout', str(key), '-out', str(cert), '-days', '1', '-nodes',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
    ], check=True, capture_output=True)
    return str(cert), str(key)


def handshake(server_context, client_context):
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    server = server_context.wrap_bio(incoming, outgoing, server_side=True)
    client = client_context.wrap_bio(client_in, client_out, server_hostname='localhost')
    done = [False, False]
    for _ in range(50):
        for i, endpoint in enumerate((client, server)):
            try:
                endpoint.do_handshake()
                done[i] = True
            except ssl.SSLWantReadError:
                pass
            if i == 0:
                incoming.write(client_out.read())
            else:
                client_in.write(outgoing.read())
        if all(done):
            return client.version()
    raise AssertionError('TLS handshake did not finish')


@pytest.mark.parametrize('mtls', [False, True])
def test_uvicorn_uses_tls13_context_and_enforces_client_certificates(certificate, mtls):
    cert, key = certificate
    async def app(scope, receive, send):
        pass
    config = uvicorn.Config(app, **tls_options(cert, key, mtls=mtls, ca_certs=cert))
    config.load()
    client = ssl.create_default_context(cafile=cert)
    if mtls:
        with pytest.raises(ssl.SSLError):
            handshake(config.ssl, client)
        client.load_cert_chain(cert, key)
    assert handshake(config.ssl, client) == 'TLSv1.3'
    client.maximum_version = ssl.TLSVersion.TLSv1_2
    with pytest.raises(ssl.SSLError):
        handshake(config.ssl, client)


def test_mtls_requires_explicit_ca():
    with pytest.raises(ValueError, match='client CA'):
        tls_options('server.pem', 'server.key', mtls=True)


@pytest.fixture
def audio_source(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for audio integration checks')
    source = tmp_path / 'track; echo injected.wav'
    with wave.open(str(source), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b'\0\0' * 4000)
    return source


@pytest.mark.parametrize('format', ['mp3_128', 'mp3_256', 'wav_16', 'wav_24', 'opus_32'])
def test_audio_fixed_command_transcodes_supported_outputs(audio_source, format):
    from router.main import _musaic_format, _musaic_transcode
    extension, _ = _musaic_format(format)
    dest = audio_source.parent / ('result' + extension)
    _musaic_transcode(audio_source, dest, format, [])
    assert dest.stat().st_size > 40
    assert not (audio_source.parent / 'injected.wav').exists()


def test_audio_rejects_command_options_and_disguised_playlists(audio_source):
    from router.main import _musaic_format, _musaic_transcode
    with pytest.raises(HTTPException) as error:
        _musaic_format('mp3_128 -i https://example.org/input')
    assert error.value.status_code == 400
    # The .wav extension must not let ffmpeg parse a playlist or open its references.
    audio_source.write_text('ffconcat version 1.0\nfile /etc/passwd\n')
    dest = audio_source.parent / 'result.mp3'
    with pytest.raises(HTTPException) as error:
        _musaic_transcode(audio_source, dest, 'mp3_128', [])
    assert error.value.status_code == 502
    assert not dest.exists()


def test_audio_process_argv_contains_only_server_owned_paths(audio_source, monkeypatch):
    from router import main
    actual = subprocess.run
    def inspect(args, **kwargs):
        assert str(audio_source) not in args
        assert args[args.index('-i') + 1] == 'input'
        assert args[-1] == 'output'
        assert args[args.index('-protocol_whitelist') + 1] == 'file'
        assert Path(kwargs['cwd'], 'input').read_bytes() == audio_source.read_bytes()
        assert not kwargs.get('shell', False)
        return actual(args, **kwargs)
    monkeypatch.setattr(main.subprocess, 'run', inspect)
    main._musaic_transcode(audio_source, audio_source.parent / 'result.wav', 'wav_16', [])


@pytest.mark.parametrize('extension,codec', [
    ('mp3', 'libmp3lame'), ('wav', 'pcm_s16le'), ('webm', 'libopus'),
    ('ogg', 'libvorbis'), ('opus', 'libopus'), ('m4a', 'aac'), ('aac', 'aac'),
])
def test_audio_accepts_advertised_input_containers(audio_source, extension, codec):
    from router.main import _musaic_transcode
    encoded = audio_source.parent / ('encoded.' + extension)
    subprocess.run(['ffmpeg', '-hide_banner', '-y', '-i', str(audio_source),
                    '-codec:a', codec, str(encoded)], check=True, capture_output=True)
    output = audio_source.parent / 'decoded.wav'
    _musaic_transcode(encoded, output, 'wav_16', [])
    with wave.open(str(output)) as decoded:
        assert decoded.getnframes() > 0


async def test_audio_processing_does_not_block_api_event_loop(audio_source, monkeypatch):
    import threading
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from router import main
    monkeypatch.setattr(main.settings, 'asset_root', str(audio_source.parent))
    source = main._musaic_path('raw', 'example.wav')
    shutil.copyfile(audio_source, source)
    thread_id = threading.get_ident()
    def transcode(source, dest, format, filters):
        assert threading.get_ident() != thread_id
        shutil.copyfile(source, dest)
    monkeypatch.setattr(main, '_musaic_transcode', transcode)
    request = SimpleNamespace(json=AsyncMock(return_value={
        'asset_id': 'raw:example.wav', 'format': 'wav_16',
    }))
    result = await main.musaic_process(request)
    assert result['bucket'] == 'processed'
