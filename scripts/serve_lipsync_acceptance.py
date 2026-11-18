"""Equal-RMS vowel PCM through the production Pipecat/browser/Live2D path.

Uses controlled TTS fixtures; never writes primary settings or captures a mic.
Start this with .venv-voice Python, then run check_vowel_shapes.cjs.
"""
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import wave

import httpx
import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/vowel-acceptance'
app = FastAPI()
pcm = b''


@app.post('/v1/audio/speech/stream')
async def speak():
    async def chunks():
        for offset in range(0, len(pcm), 3200):
            yield pcm[offset:offset+3200]
            await asyncio.sleep(.001)
    return StreamingResponse(chunks(), media_type='audio/pcm', headers={'X-Audio-Sample-Rate':'16000','X-Audio-Channels':'1','X-Audio-Format':'pcm_s16le'})


@app.get('/health')
def health():
    return {'asr': {'ready': True}, 'tts': {'ready': True}}


async def main():
    global pcm
    OUT.mkdir(parents=True, exist_ok=True)
    sequence, buffers, offset = [], [], 0
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for label, text in [('A','阿阿阿阿阿阿。'),('I','衣衣衣衣衣衣。'),('U','乌乌乌乌乌乌。'),('E','鹅鹅鹅鹅鹅鹅。'),('O','哦哦哦哦哦哦。')]:
            response = await client.post('http://127.0.0.1:8766/v1/audio/speech', json={'input': text})
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content), 'rb') as source:
                assert source.getnchannels()==1 and source.getsampwidth()==2 and source.getframerate()==16000
                samples = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(float)
            active = np.flatnonzero(np.abs(samples)>500)
            assert len(active)>100, label
            # Fixed duration, equal total RMS. No phoneme labels enter the app.
            samples = samples[active[0]:active[-1]+1]
            samples = np.tile(samples, int(np.ceil(24000/len(samples))))[:24000]
            samples *= 2800 / np.sqrt(np.mean(samples*samples))
            assert np.max(np.abs(samples))<32767
            samples = np.round(samples).astype('<i2')
            sequence.append({'label':label,'start':offset/16000,'end':(offset+len(samples))/16000,'rms':float(np.sqrt(np.mean(samples.astype(float)**2)))})
            buffers.extend([samples.tobytes(), bytes(12800)])
            offset += len(samples)+6400
    pcm=b''.join(buffers)+bytes(32000)
    (OUT/'sequence.json').write_text(json.dumps(sequence,indent=2),encoding='utf-8')
    with wave.open(str(OUT/'equal-rms-vowels.wav'),'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed')); wav.writeframes(pcm)
    process=subprocess.Popen([str(ROOT/'.venv-voice/Scripts/python.exe'),'scripts/serve_voice_acceptance.py','--port','8895','--provider-port','8894','--speech-url','http://127.0.0.1:8896'],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        await uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8896,log_level='warning')).serve()
    finally:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)


if __name__=='__main__':
    asyncio.run(main())
