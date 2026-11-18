"""Generate labelled synthetic calibration WAVs from the local VITS voice.

Run with .venv-voice Python, then node scripts/calibrate_lipsync.cjs
artifacts/lip-calibration/manifest.json output-profile.json.
This creates fresh random TTS samples; benchmark on independent audio before
replacing a shipped profile. It never records a person's voice.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speech-url', default='http://127.0.0.1:8766')
    parser.add_argument('--voice', default='default')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/lip-calibration')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as client:
        health = await client.get(args.speech_url.rstrip('/') + '/health')
        health.raise_for_status()
        if 'sherpa-onnx VITS' not in health.json().get('tts', {}).get('detail', ''):
            raise RuntimeError('This calibration recipe is for the sherpa VITS voice only')
        records = []
        for name, char in [('A', '阿'), ('E', '鹅'), ('I', '衣'), ('O', '哦'), ('U', '乌'), ('S', '丝')]:
            response = await client.post(args.speech_url.rstrip('/') + '/v1/audio/speech', json={'input': char * 12 + '。', 'voice': args.voice})
            response.raise_for_status()
            target = args.output / (name + '.wav')
            target.write_bytes(response.content)
            records.append({'name': name, 'path': str(target.resolve())})
        (args.output / 'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        (args.output / 'voice.json').write_text(json.dumps({'tts': health.json()['tts'], 'voice': args.voice, 'training': '12 repeated isolated Chinese characters per AEIOUS label'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Generated synthetic calibration WAVs and manifest in', args.output)


if __name__ == '__main__':
    asyncio.run(main())
