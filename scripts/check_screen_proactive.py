"""Bounded, explicitly opted-in live screen decisions using synthetic images.

No real desktop, DSH credentials, model generation, TTS or settings writes.
The default is a no-op. --live makes exactly four System One requests.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def picture(lines):
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new('RGB', (960, 540), '#182638')
    draw = ImageDraw.Draw(canvas)
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    font = ImageFont.truetype(str(font_path), 30) if font_path.is_file() else ImageFont.load_default(size=30)
    for index, line in enumerate(lines):
        draw.text((50, 80 + 110 * index), line, fill='#f9d162' if index == 0 else '#eeeeee', font=font)
    output = io.BytesIO()
    canvas.save(output, format='JPEG')
    return base64.b64encode(output.getvalue()).decode('ascii')


async def run(output, style=None):
    from server.storage import DEFAULTS
    from server.systemone import SystemOneClient
    keys = ['systemone_provider', 'systemone_ark_model', 'systemone_ark_api_key', 'systemone_api_key',
            'systemone_timeout_ms', 'systemone_confidence', 'screen_companion_timeout_ms',
            'screen_companion_speak_threshold', 'screen_companion_wait_threshold', 'screen_companion_style']
    database = sqlite3.connect((ROOT / 'data/companion.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        rows = database.execute('SELECT key,value FROM settings WHERE key IN (' + ','.join('?' for _ in keys) + ')', keys).fetchall()
    finally:
        database.close()
    settings = {**DEFAULTS, **{key: json.loads(value) for key, value in rows}}
    if style is not None:
        settings['screen_companion_style'] = style
    victory = ['VICTORY!', 'Game finished - 10 : 0', 'Synthetic game screen']
    cases = [
        ('victory_without_dialogue', victory, []),
        ('visible_build_error', ['Build failed', 'Error: Cannot find module ./config', 'Process exited with code 1'], []),
        ('victory_after_invitation', victory, [{'role': 'user', 'text':
            'I have lost many times. I hope to win this game. Please keep me company.'}]),
        ('explicit_quiet_request', victory, [{'role': 'user', 'text':
            '请保持安静，不要主动评论我的屏幕；等我明确提问再说话。'}]),
    ]
    report = {'method': 'Four live System One decisions on generated images, not live desktop/DSH/TTS acceptance',
        'real_desktop_captured': False, 'settings_modified': False, 'real_dsh_generation': False, 'tts_called': False,
        'style': settings['screen_companion_style'],
        'speak_threshold': settings['screen_companion_speak_threshold'],
        'wait_threshold': settings['screen_companion_wait_threshold'],
        'intent_confidence_threshold': settings['systemone_confidence'], 'cases': []}
    client = SystemOneClient(settings)
    try:
        report.update(provider=client.provider.name, model=client.model)
        for name, lines, context in cases:
            started = time.monotonic()
            decision = await client.decide(picture(lines), context, settings['screen_companion_timeout_ms'] / 1000,
                                           settings['screen_companion_style'])
            item = {'name': name, 'reason': client.last_reason,
                    'elapsed_ms': round((time.monotonic() - started) * 1000), 'eligible': False, 'decision': None}
            if decision is not None:
                item['decision'] = {key: getattr(decision, key) for key in
                    ('desire', 'must_wait', 'intent', 'intent_confidence', 'intent_probability', 'non_wait_probability')}
                item['eligible'] = (decision.desire >= settings['screen_companion_speak_threshold']
                    and decision.must_wait <= settings['screen_companion_wait_threshold']
                    and decision.intent not in (None, 'wait'))
            report['cases'].append(item)
    finally:
        await client.close()
    by_name = {case['name']: case for case in report['cases']}
    report['checks'] = {
        'all_decisions_available': all(case['decision'] is not None for case in report['cases']),
        'invited_victory_eligible': by_name['victory_after_invitation']['eligible'],
        'explicit_quiet_respected': (by_name['explicit_quiet_request']['decision'] is not None
                                    and not by_name['explicit_quiet_request']['eligible']),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if not all(report['checks'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--style', choices=('quiet', 'balanced', 'lively'), help='Temporary synthetic-test policy; does not save settings')
    parser.add_argument('--output', type=Path, default=Path('E:/Dafeiyu/verification/screen-proactive/assessment.json'))
    args = parser.parse_args()
    if args.live:
        asyncio.run(run(args.output, args.style))
    else:
        print('Not run: --live enables exactly four synthetic-image judgments; no real screen, DSH generation or TTS.')
