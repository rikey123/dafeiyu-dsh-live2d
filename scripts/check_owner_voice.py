"""Isolated real ERes2Net/Silero/ASR/Pipecat gate acceptance using two TTS voices.

Run with .venv-voice Python. Starts private 8884/8885/8886 services with temporary
settings and voice profile. Never enrolls a voice in the user's primary service.
Synthetic voices test plumbing; results are not human identification accuracy.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/audio-engineering'


def wav_bytes(samples):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.clip(samples, -32768, 32767).astype('<i2').tobytes())
    return buffer.getvalue()


def read_pcm(data):
    with wave.open(io.BytesIO(data), 'rb') as stream:
        assert stream.getnchannels() == 1 and stream.getsampwidth() == 2
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
        rate = stream.getframerate()
    if rate != 16000:
        samples = np.interp(np.arange(round(len(samples) * 16000 / rate)) * rate / 16000, np.arange(len(samples)), samples)
    return samples.astype('<i2')


def sapi_fixture(path):
    sys.path.insert(0, str(ROOT))
    from speech.server import Engine
    engine = Engine()
    engine.tts_kind = 'sapi'
    engine.tts_state = {'ready': True}
    data = engine.synthesize('今天我们来测试不同的声音，请不要把旁人的说话当成本人的问题。', '')
    Path(path).write_bytes(wav_bytes(read_pcm(data)))


async def run():
    import websockets
    from pipecat.frames.protobufs import frames_pb2
    from stress_pipecat_protocol import message
    OUT.mkdir(parents=True, exist_ok=True)
    processes, handles, results = [], [], {}
    speech, gateway, provider = 'http://127.0.0.1:8886', 'http://127.0.0.1:8885', 'http://127.0.0.1:8884'
    with tempfile.TemporaryDirectory(prefix='dafeiyu-owner-qa-') as directory:
        profile = Path(directory) / 'owner.json'
        environment = {**os.environ, 'DAFEIYU_SPEAKER_PROFILE': str(profile), 'DAFEIYU_ASR_DEVICE': 'CPU', 'PYTHONUTF8': '1'}
        def launch(python, args, name):
            handle = (OUT / name).open('w', encoding='utf-8'); handles.append(handle)
            process = subprocess.Popen([str(ROOT / python), *args], cwd=ROOT, env=environment, stdout=handle, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(process)
        try:
            launch('.venv/Scripts/python.exe', ['-m', 'uvicorn', 'speech.server:app', '--host', '127.0.0.1', '--port', '8886'], 'owner-speech.log')
            launch('.venv-voice/Scripts/python.exe', ['scripts/serve_voice_acceptance.py', '--port', '8885', '--provider-port', '8884', '--speech-url', speech], 'owner-gateway.log')
            async with httpx.AsyncClient(timeout=120, trust_env=False) as http:
                async def ready():
                    for _ in range(180):
                        if any(p.poll() is not None for p in processes):
                            raise RuntimeError('isolated service exited; inspect owner logs')
                        try:
                            health = (await http.get(speech + '/health')).json()
                            if health['asr']['ready'] and health['tts']['ready'] and (await http.get(gateway + '/api/health')).is_success:
                                return
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(.5)
                    raise TimeoutError('isolated services not ready')
                await ready()
                status = (await http.get(gateway + '/api/voice/owner/status')).json()
                assert status['ready'] and not status['enrolled'] and not status['enabled'], status
                assert (await http.put(gateway + '/api/settings', json={'owner_voice_only': True})).status_code == 409
                clips = []
                for text in ['你好，今天我们来讨论如何安排一个轻松愉快的周末。', '天气晴朗的时候，我喜欢在公园里面散步，听听鸟叫。', '等一下，我想换一个问题，请告诉我今天应该做些什么。']:
                    response = await http.post(speech + '/v1/audio/speech', json={'input': text})
                    response.raise_for_status(); clips.append(wav_bytes(read_pcm(response.content)))
                other_path = Path(directory) / 'other.wav'
                subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), __file__, '--sapi-fixture', str(other_path)], cwd=ROOT, env=environment, check=True, timeout=30)
                other = other_path.read_bytes()
                upload = lambda data: {'file': ('voice.wav', data, 'audio/wav')}
                missing = await http.post(speech + '/v1/audio/transcriptions', files=upload(clips[2]), data={'owner_only': 'true'})
                assert missing.status_code == 503
                response = await http.post(gateway + '/api/voice/owner/enroll', files=[('files', ('one.wav', clips[0], 'audio/wav')), ('files', ('two.wav', clips[1], 'audio/wav'))])
                response.raise_for_status()
                original = profile.read_bytes()
                assert set(json.loads(original)) == {'version', 'model', 'embedding', 'samples'}, 'raw audio stored in profile'
                mixed = await http.post(gateway + '/api/voice/owner/enroll', files=[('files', ('one.wav', clips[0], 'audio/wav')), ('files', ('other.wav', other, 'audio/wav'))])
                assert mixed.status_code == 400 and profile.read_bytes() == original
                cases = {'same_voice_new_text': clips[2], 'different_voice': other, 'silence': wav_bytes(np.zeros(16000*4)), 'noise': wav_bytes(np.random.default_rng(7).normal(0, 100, 16000*4)), 'short': wav_bytes(read_pcm(clips[0])[:16000])}
                for name, clip in cases.items():
                    at = time.perf_counter()
                    response = await http.post(speech + '/v1/audio/transcriptions', files=upload(clip), data={'owner_only': 'true'})
                    response.raise_for_status(); result = response.json()
                    assert (result['speaker']['accepted'] is True) == (name == 'same_voice_new_text'), result
                    assert bool(result['text']) == (name == 'same_voice_new_text'), result
                    results[name] = {**result, 'http_seconds': round(time.perf_counter()-at, 3)}
                assert (await http.put(gateway + '/api/settings', json={'owner_voice_only': True})).is_success
                assert (await http.get(gateway + '/api/voice/owner/status')).json()['enabled'] is True
                session = (await http.post(gateway + '/api/sessions')).json()['id']
                events, audio = [], []
                async with websockets.connect(gateway.replace('http:', 'ws:') + '/ws/voice?session_id=' + session, max_size=4000000) as ws:
                    async def collect():
                        async for packet in ws:
                            frame = frames_pb2.Frame.FromString(packet)
                            if frame.WhichOneof('frame') == 'message':
                                event = json.loads(frame.message.data); events.append(event)
                            elif frame.WhichOneof('frame') == 'audio':
                                audio.append(len(frame.audio.audio))
                    collector = asyncio.create_task(collect())
                    async def wait(predicate, timeout=60):
                        async with asyncio.timeout(timeout):
                            while not predicate():
                                await asyncio.sleep(.05)
                    async def send_audio(clip):
                        pcm = bytes(32000) + read_pcm(clip).tobytes() + bytes(48000)
                        for offset in range(0, len(pcm), 1024):
                            frame = frames_pb2.Frame(); frame.audio.audio = pcm[offset:offset+1024]
                            frame.audio.sample_rate = 16000; frame.audio.num_channels = 1
                            await ws.send(frame.SerializeToString()); await asyncio.sleep(len(frame.audio.audio)/32000)
                    try:
                        await ws.send(message('client-ready', {}, 'ready'))
                        await wait(lambda: any(e['type'] == 'bot-ready' for e in events))
                        await ws.send(message('send-text', {'content': '请慢慢介绍你自己。', 'options': {'run_immediately': True, 'audio_response': True}}, 'first'))
                        await wait(lambda: any(e['type'] == 'bot-started-speaking' for e in events))
                        index, byte_index = len(events), len(audio)
                        await send_audio(other)
                        await wait(lambda: any(e.get('data', {}).get('type') == 'voice.speaker' for e in events[index:]))
                        rejected = events[index:]
                        assert not any(e['type'] in {'bot-interrupted', 'user-transcription'} for e in rejected), rejected
                        ducks = [e['data']['active'] for e in rejected if e.get('data', {}).get('type') == 'voice.duck']
                        assert ducks and ducks[0] is True and ducks[-1] is False, ducks
                        rejection_audio_bytes = sum(audio[byte_index:])
                        assert rejection_audio_bytes > 0, 'rejected voice stopped bot audio'
                        assert len((await http.get(provider + '/test/requests')).json()) == 1
                        # The following owner PCM must still start a new real speech turn.
                        index = len(events)
                        await send_audio(clips[2])
                        await wait(lambda: len([e for e in events[index:] if e['type'] == 'bot-started-speaking']) >= 1)
                        assert len((await http.get(provider + '/test/requests')).json()) == 2
                        await wait(lambda: any(e['type'] == 'bot-stopped-speaking' for e in events[index:]))
                        errors = [e for e in events if e['type'] == 'error']
                        assert not errors, errors
                        results['pipeline'] = {'different_voice_no_interrupt': True, 'duck_reset': ducks, 'next_owner_turn': True, 'audio_bytes_during_rejection': rejection_audio_bytes, 'errors': errors}
                    finally:
                        collector.cancel()
                        await asyncio.gather(collector, return_exceptions=True)
                history = (await http.get(gateway + f'/api/sessions/{session}/messages')).json()
                assert len([m for m in history if m['role'] == 'user']) == 2, history
                results['history_user_count'] = 2
                await http.delete(gateway + '/api/sessions/' + session)
                await http.delete(gateway + '/api/voice/owner/enrollment')
                assert not profile.exists()
                assert (await http.get(gateway + '/api/settings')).json()['owner_voice_only'] is False
                assert (await http.get(gateway + '/api/voice/owner/status')).json()['enabled'] is False
                missing = await http.post(speech + '/v1/audio/transcriptions', files=upload(clips[2]), data={'owner_only': 'true'})
                assert missing.status_code == 503
                unrestricted = await http.post(speech + '/v1/audio/transcriptions', files=upload(other))
                unrestricted.raise_for_status(); assert unrestricted.json()['text']
                (OUT / 'enrollment-fixture.wav').write_bytes(wav_bytes(np.concatenate([np.zeros(16000), read_pcm(clips[0]), np.zeros(16000)])))
                browser = await asyncio.create_subprocess_exec('node', 'scripts/check_owner_ui.cjs', cwd=ROOT, env={**environment, 'VOICE_TEST_URL': gateway}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                browser_output, _ = await browser.communicate()
                print(browser_output.decode('utf-8', errors='replace'), flush=True)
                assert browser.returncode == 0, 'real owner settings browser acceptance failed'
                results.update(passed=True, method='Temporary profile/settings; real CPU ERes2Net, Silero, SenseVoice, VITS and Windows SAPI; controlled LLM and paced official protobuf. No human accuracy or physical AEC claim.')
                (OUT / 'owner.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(results, ensure_ascii=False, indent=2))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            for handle in handles:
                handle.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sapi-fixture')
    args = parser.parse_args()
    if args.sapi_fixture:
        sapi_fixture(args.sapi_fixture)
    else:
        asyncio.run(run())
