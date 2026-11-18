"""Explicit, bounded paid evaluation; dry run by default, never tunes thresholds.

Reports probability calibration/coverage on caller-labelled examples. The bundled
text examples are a smoke set, not evidence of real microphone performance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def binary_metrics(samples, bins=5):
    if not samples:
        return {'n': 0, 'brier': None, 'ece': None, 'accuracy_at_half': None, 'bins': []}
    groups = [[] for _ in range(bins)]
    for probability, label in samples:
        if type(label) is not bool or type(probability) not in (float, int) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('Invalid probability or label')
        groups[min(int(probability * bins), bins - 1)].append((probability, label))
    reliability = [{'lower': i / bins, 'upper': (i + 1) / bins, 'n': len(group),
                    'mean_probability': sum(p for p, _ in group) / len(group),
                    'positive_fraction': sum(y for _, y in group) / len(group)} for i, group in enumerate(groups) if group]
    return {'n': len(samples), 'brier': sum((p - y) ** 2 for p, y in samples) / len(samples),
            'ece': sum(g['n'] * abs(g['mean_probability'] - g['positive_fraction']) for g in reliability) / len(samples),
            'accuracy_at_half': sum((p >= .5) == y for p, y in samples) / len(samples), 'bins': reliability}


def load_cases(path, allow_audio=False):
    if path.stat().st_size > 1_000_000:
        raise ValueError('Dataset is too large')
    cases = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError('Supply 1-100 labelled examples')
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'] or len(case['id']) > 80 or case['id'] in ids:
            raise ValueError('Examples need unique short IDs')
        ids.add(case['id'])
        if not isinstance(case.get('text'), str) or len(case['text']) > 2000 or type(case.get('overlap')) is not bool:
            raise ValueError('Expected bounded text and boolean overlap')
        if any(type(case.get('labels', {}).get(name)) is not bool for name in ('interrupt', 'backchannel')):
            raise ValueError('Both binary ground-truth labels are required')
        if case['labels']['interrupt'] and case['labels']['backchannel']:
            raise ValueError('An interruption cannot also be a backchannel')
        case['_pcm'] = None
        if case.get('audio_wav'):
            if not allow_audio:
                raise ValueError('Audio examples require --allow-audio-upload')
            audio = (path.parent / case['audio_wav']).resolve()
            if audio.stat().st_size > 8_000_000:
                raise ValueError('Audio file too large')
            with wave.open(str(audio), 'rb') as wav:
                if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth(), wav.getcomptype()) != (1, 16000, 2, 'NONE'):
                    raise ValueError('Audio must be 16kHz mono PCM16 WAV')
                if not 0 < wav.getnframes() <= 64000:
                    raise ValueError('Audio examples must be at most 4 seconds')
                case['_pcm'] = wav.readframes(wav.getnframes())
    return cases


async def evaluate(settings, cases):
    from server.systemone import SystemOneClient, TURN_QUESTIONS
    client = SystemOneClient(settings)
    records = []
    try:
        for case in cases:
            started = time.monotonic()
            answer = await client.assess({'user_text': case['text'], 'assistant_speaking': case['overlap'], 'recent_dialogue': []}, TURN_QUESTIONS, case['_pcm'])
            record = {'id': case['id'], 'input': 'text+audio' if case['_pcm'] else 'text',
                      'labels': case['labels'], 'reason': client.last_reason, 'elapsed_ms': round((time.monotonic() - started) * 1000)}
            if answer:
                record['probabilities'] = {name: answer[name]['noul'] for name in ('interrupt', 'backchannel')}
                record['would_interrupt'] = answer['interrupt']['noul'] >= client.threshold and answer['backchannel']['noul'] < .5
            records.append(record)
            # A permanent account/config failure is not a reason to spend the
            # rest of the batch; uncertainty is never automatically re-posted.
            if client.last_reason in {'authentication', 'permission_denied', 'region_restricted', 'model_not_open', 'endpoint_not_found', 'billing', 'invalid_request', 'circuit_open'}:
                break
    finally:
        await client.close()
    valid = [r for r in records if 'probabilities' in r]
    negatives = [r for r in valid if not r['labels']['interrupt']]
    positives = [r for r in valid if r['labels']['interrupt']]
    return {'provider': client.provider.name, 'model': client.model, 'threshold': client.threshold,
            'requested_examples': len(cases), 'attempted_examples': len(records), 'valid_examples': len(valid),
            'coverage': len(valid) / len(cases), 'calibration_bins': 5,
            'binary': {name: binary_metrics([(r['probabilities'][name], r['labels'][name]) for r in valid]) for name in ('interrupt', 'backchannel')},
            'false_interrupt_rate': sum(r['would_interrupt'] for r in negatives) / len(negatives) if negatives else None,
            'missed_interrupt_rate': sum(not r['would_interrupt'] for r in positives) / len(positives) if positives else None,
            'limitation': 'Caller-labelled examples only; text smoke labels are not validated acoustic ground truth. No automatic threshold tuning.',
            'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT / 'scripts/fixtures/systemone-labels.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute-paid-requests', action='store_true', help='Actually send dataset examples to the saved provider (billable)')
    parser.add_argument('--allow-audio-upload', action='store_true', help='Explicitly permit uploading WAVs referenced by the dataset')
    args = parser.parse_args()
    try:
        cases = load_cases(args.dataset, args.allow_audio_upload)
    except (ValueError, OSError, wave.Error, TypeError, AttributeError):
        parser.error('Invalid dataset/audio: check the documented fields, limits and audio permission flag.')
    if not args.execute_paid_requests:
        print(json.dumps({'dry_run': True, 'examples': len(cases), 'audio_examples': sum(bool(c['_pcm']) for c in cases), 'cloud_requests': 0}))
        return
    if not args.output:
        parser.error('--output is required for a paid evaluation; prefer an E-drive path')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    from server.storage import Store
    from server.systemone_providers import provider_for
    store = Store()
    try:
        settings = store.settings(private=True)
    finally:
        store.db.close()
    if not provider_for(settings).key:
        parser.error('Save the selected provider API key first; no cloud requests were made.')
    if any(c['_pcm'] for c in cases) and not settings['systemone_audio_enabled']:
        parser.error('Saved audio judgments are disabled; no cloud requests were made.')
    # Check the output destination before spending on remote calls.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        report = asyncio.run(evaluate(settings, cases))
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({k: report[k] for k in ('provider', 'attempted_examples', 'valid_examples', 'coverage')}))


if __name__ == '__main__':
    main()
