"""Screen decision controller; the caller owns transport, replies and playback."""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import logging
import math
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

from .systemone import SCREEN_INTENTS

MAX_BYTES = 256 * 1024


@dataclass
class ScreenBudget:
    """Share this object across reconnects and call mark_reply for initiative."""
    judgments: deque = field(default_factory=deque)
    replies: deque = field(default_factory=deque)
    last_reply: float = float('-inf')
    idle: deque = field(default_factory=deque)

    def mark_reply(self, now):
        self.last_reply = now


def image_from_frame(frame):
    """Validate and normalize JPEG without copying metadata to the output."""
    if not isinstance(frame, dict) or set(frame) != {'stream_id', 'seq', 'width', 'height', 'mime_type', 'data'}:
        raise ValueError('invalid_frame')
    if (type(frame['seq']) is not int or frame['seq'] < 1
            or any(type(frame[k]) is not int for k in ('width', 'height'))
            or not 1 <= frame['width'] <= 960 or not 1 <= frame['height'] <= 540
            or frame['mime_type'] != 'image/jpeg'):
        raise ValueError('invalid_frame')
    encoded = frame['data']
    if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
        raise ValueError('invalid_frame')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_BYTES or base64.b64encode(raw).decode('ascii') != encoded:
            raise ValueError('invalid_frame')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'JPEG' or image.size != (frame['width'], frame['height']):
                raise ValueError('invalid_frame')
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            # A new RGB image and a fresh encoder discard EXIF and other metadata.
            clean = Image.new('RGB', image.size)
            clean.paste(image.convert('RGB'))
        thumb = clean.resize((32, 18), Image.Resampling.BILINEAR).convert('RGB')
        output = io.BytesIO()
        clean.save(output, format='JPEG', quality=85, optimize=True)
        normalized = output.getvalue()
        if len(normalized) > MAX_BYTES:
            raise ValueError('invalid_frame')
        return ({'mime_type': 'image/jpeg', 'data': base64.b64encode(normalized).decode('ascii'),
                 'width': frame['width'], 'height': frame['height']}, thumb)
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('invalid_frame') from None


class ScreenCompanion:
    """Single-flight controller. No history, generation, capture or disk access."""
    def __init__(self, client, settings, *, on_reply, busy, on_status, context=lambda: (),
                 budget=None, clock=time.monotonic, on_sample=None, native_context=None):
        self.client, self.settings = client, settings
        self.style = settings.get('screen_companion_style', 'balanced')
        if self.style not in {'quiet', 'balanced', 'lively'}:
            self.style = 'balanced'
        self.on_reply, self.busy, self.status, self.context = on_reply, busy, on_status, context
        self.budget, self.clock = budget or ScreenBudget(), clock
        self.enabled = bool(settings.get('screen_companion_enabled')
                            and settings.get('conversation_mode', 'duplex') != 'moss_live')
        self.stream_id = None
        self.seq = 0
        self.generation = 0
        self.deadline = float('-inf')
        self.task = None
        self.status_tasks = set()
        self.native_context = native_context
        self.on_sample = on_sample
        self.sample_task = None
        self.sample_tasks = set()
        self.closed = False
        self.thumbnail = None
        self.last_request = float('-inf')
        self.frames = self.rejected = 0
        self.last_status = None
        self.last_status_at = float('-inf')
        self.metrics = getattr(client, 'metrics', None)

    def counters(self):
        return {'judgments': len(self.budget.judgments), 'replies': len(self.budget.replies),
            'frames': self.frames, 'rejected': self.rejected, 'sharing': self.stream_id is not None}

    def count(self, name):
        if self.metrics:
            self.metrics.increment('screen_' + name)

    def log_status(self, event):
        # Content-free fixed reasons only, never user text, images or credentials.
        reason = event.get('reason', '')
        status = event.get('status', '')
        if re.fullmatch(r'[a-z_]{1,80}', reason) and re.fullmatch(r'[a-z_]{1,24}', status):
            fields = []
            if event.get('mode') in {'proactive', 'requested'}:
                fields.append('mode=' + event['mode'])
            for key in ('desire', 'must_wait', 'speak_threshold', 'wait_threshold',
                        'intent_confidence_threshold', 'intent_confidence', 'intent_probability', 'non_wait_probability'):
                value = event.get(key)
                if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1:
                    fields.append(f'{key}={value:.6f}')
            if event.get('style') in {'quiet', 'balanced', 'lively'}:
                fields.append('style=' + event['style'])
            if event.get('intent') in SCREEN_INTENTS:
                fields.append('intent=' + event['intent'])
            logging.getLogger('uvicorn.error').info('screen status=%s reason=%s judgments=%d replies=%d frames=%d %s',
                status, reason, len(self.budget.judgments), len(self.budget.replies), self.frames, ' '.join(fields))

    def current(self, generation):
        return (not self.closed and self.enabled and self.stream_id is not None
                and generation == self.generation)

    def valid(self, generation):
        return self.current(generation) and self.clock() <= self.deadline

    def _invalidate(self):
        self.generation += 1
        self.deadline = float('-inf')
        task = self.task
        if task:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if task is not current:
                task.cancel()
        self.thumbnail = None

    async def activate(self, data):
        """Change the stream; stop invalidates synchronously before returning."""
        if (self.closed or not isinstance(data, dict) or set(data) != {'active', 'stream_id'}
                or type(data['active']) is not bool or not isinstance(data['stream_id'], str)):
            return False
        stream_id = data['stream_id']
        try:
            if str(uuid.UUID(stream_id)) != stream_id:
                return False
        except (ValueError, AttributeError):
            return False
        if not data['active'] and stream_id != self.stream_id:
            return False
        self._stop_sampling()
        self._invalidate()
        self.stream_id = stream_id if data['active'] and self.enabled else None
        self.seq = 0
        self._status_soon('active' if self.stream_id else 'inactive',
                          'started' if self.stream_id else 'disabled' if data['active'] else 'stopped')
        if self.stream_id and self.on_sample and (self.settings.get('systemone_enabled') or self.settings.get('screen_companion_mode') == 'direct'):
            self.sample_task = asyncio.create_task(self._sample(self.stream_id), name='screen-sampling')
            self.sample_tasks.add(self.sample_task)
            def done(task):
                self.sample_tasks.discard(task)
                if not task.cancelled():
                    task.exception()
            self.sample_task.add_done_callback(done)
        return not data['active'] or self.enabled

    def _stop_sampling(self):
        if self.sample_task:
            self.sample_task.cancel()
            self.sample_task = None

    async def _sample(self, stream_id):
        # WebSocket-driven sampling avoids depending solely on hidden-page JS
        # intervals. This never authorizes capture or queues missed observations.
        def current():
            return (not self.closed and self.stream_id == stream_id
                    and self.sample_task is asyncio.current_task())
        while current():
            await asyncio.sleep(max(1, self.settings['screen_companion_interval_ms'] / 1000))
            if not current():
                return
            try:
                await self.on_sample({'type': 'voice.screen.sample', 'stream_id': stream_id})
            except Exception:
                self.count('sample_unavailable')

    def cancel_pending(self):
        """Invalidate pending decisions/replies on user input or interruption."""
        self._invalidate()

    async def close(self):
        self.closed = True
        self.stream_id = None
        self._stop_sampling()
        sampling = list(self.sample_tasks)
        if sampling:
            await asyncio.gather(*sampling, return_exceptions=True)
        self._invalidate()
        task = self.task
        if task and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)
        pending = list(self.status_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _status(self, status, reason, decision=None):
        event = {'type': 'voice.screen.status', 'status': status, 'reason': reason,
                 'source': self.client.source, 'model': self.client.model,
                 'mode': 'proactive', 'style': self.style, **self.counters(),
                 'speak_threshold': self.settings['screen_companion_speak_threshold'],
                 'wait_threshold': self.settings['screen_companion_wait_threshold'],
                 'intent_confidence_threshold': getattr(self.client, 'confidence', .6)}
        if decision is not None:
            event.update(desire=decision.desire, must_wait=decision.must_wait, intent=decision.intent)
            for key in ('intent_confidence', 'intent_probability', 'non_wait_probability'):
                value = getattr(decision, key, None)
                if value is not None:
                    event[key] = value
            if self.metrics is not None:
                self.metrics.record_screen_decision(event)
        await self.status(event)
        self.log_status(event)

    def _status_soon(self, status, reason):
        if (status, reason) == self.last_status and self.clock() - self.last_status_at < 5:
            return
        self.last_status, self.last_status_at = (status, reason), self.clock()
        task = asyncio.create_task(self._status(status, reason))
        self.status_tasks.add(task)
        def done(finished):
            self.status_tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()
        task.add_done_callback(done)

    def _task_done(self, task):
        if self.task is task:
            self.task = None
        if not task.cancelled():
            task.exception()

    async def offer(self, frame):
        """Admit at most one frame and schedule its decision without waiting for it."""
        if self.closed or not self.enabled or (not self.settings.get('systemone_enabled') and self.settings.get('screen_companion_mode') != 'direct') or self.stream_id is None:
            return False
        if not isinstance(frame, dict) or frame.get('stream_id') != self.stream_id:
            return False
        seq = frame.get('seq')
        if type(seq) is not int or seq <= self.seq:
            return False
        self.frames += 1
        self.count('frames')
        if self.task is not None or self.busy():
            self.rejected += 1
            self.count('busy')
            self._status_soon('waiting', 'busy')
            return False
        try:
            image, thumb = image_from_frame(frame)
        except ValueError:
            self._status_soon('waiting', 'invalid_frame')
            return False
        self.seq = seq
        now = self.clock()
        if now - self.last_request < self.settings['screen_companion_interval_ms'] / 1000:
            self._status_soon('waiting', 'interval')
            return False
        if self.thumbnail is not None:
            difference = sum(ImageStat.Stat(ImageChops.difference(thumb, self.thumbnail)).mean) / (3 * 255)
            if (difference < self.settings['screen_companion_change_threshold']
                    and now - self.last_request < self.settings.get('screen_companion_refresh_ms', 15000) / 1000):
                self._status_soon('waiting', 'unchanged')
                return False
        for queue in (self.budget.judgments, self.budget.replies):
            while queue and now - queue[0] >= 3600:
                queue.popleft()
        if (len(self.budget.judgments) >= self.settings['screen_companion_max_judgments_per_hour']
                or len(self.budget.replies) >= self.settings['screen_companion_max_replies_per_hour']):
            self._status_soon('waiting', 'budget')
            return False
        if now - self.budget.last_reply < self.settings['screen_companion_cooldown_s']:
            self._status_soon('waiting', 'cooldown')
            return False
        # Each admitted frame gets its own generation and TTL. A later frame
        # cannot make an older queued reply valid again by extending a deadline.
        self.generation += 1
        generation = self.generation
        self.deadline = now + self.settings['screen_companion_timeout_ms'] / 1000
        self.last_request = now
        self.thumbnail = thumb
        self.budget.judgments.append(now)
        self.count('probes')
        self.task = asyncio.create_task(self._assess(image, generation), name='screen-judgment')
        self.task.add_done_callback(self._task_done)
        return True

    async def _assess(self, image, generation):
        try:
            timeout = self.settings['screen_companion_timeout_ms'] / 1000
            deadline = self.deadline
            native = None
            if self.native_context is not None:
                native = await self.native_context()
                if not self.valid(generation) or self.busy():
                    return False
                if native is None or native.get('busy') is not False:
                    await self._status('waiting', 'dsh_busy_or_unavailable')
                    return False
            if self.settings.get('screen_companion_mode') == 'direct':
                if not self.valid(generation) or self.busy():
                    return False
                self.budget.replies.append(self.clock())
                self.budget.mark_reply(self.clock())
                self.count('replies')
                await self._status('accepted', 'direct')
                if not self.valid(generation) or self.busy():
                    return False
                await self.on_reply(image, 'direct', generation, self.settings['screen_companion_max_reply_chars'])
                return True
            async with asyncio.timeout(timeout):
                context = self.context()
                if native is not None:
                    context = {'recent_dialogue': context, 'persona': native['persona'],
                               'companion_interests': self.settings.get('companion_interests', '')[:2000]}
                decision = await self.client.decide(image['data'], context, timeout, self.style)
            if not self.current(generation):
                return False
            if self.clock() > deadline:
                await self._status('unavailable', 'timeout')
                return False
            if self.native_context is not None:
                native = await self.native_context()
                if not self.valid(generation) or self.busy():
                    return False
                if native is None or native.get('busy') is not False:
                    await self._status('waiting', 'dsh_busy_or_unavailable')
                    return False
            if self.busy():
                await self._status('waiting', 'busy')
                return False
            if decision is None:
                await self._status('unavailable', self.client.last_reason)
                return False
            if (decision.desire < self.settings['screen_companion_speak_threshold']
                    or decision.must_wait > self.settings['screen_companion_wait_threshold']
                    or decision.intent not in SCREEN_INTENTS or decision.intent == 'wait'):
                reason = ('low_desire' if decision.desire < self.settings['screen_companion_speak_threshold']
                    else 'must_wait' if decision.must_wait > self.settings['screen_companion_wait_threshold']
                    else 'wait_intent' if decision.intent == 'wait' else 'low_confidence')
                self.count('wait')
                self.count(reason)
                await self._status('waiting', reason, decision)
                return False
            # Reserve before yielding. The callback must check valid(generation)
            # before generation starts and honor cancellation until it completes.
            self.budget.replies.append(self.clock())
            self.budget.mark_reply(self.clock())
            self.count('replies')
            await self._status('accepted', 'strong_desire', decision)
            if not self.valid(generation) or self.busy() or self.clock() > deadline:
                return False
            await self.on_reply(image, decision.intent, generation, self.settings['screen_companion_max_reply_chars'])
            return True
        except asyncio.CancelledError:
            return False
        except TimeoutError:
            if self.current(generation):
                self.count('unavailable')
                await self._status('unavailable', 'timeout')
            return False
        except Exception:
            if self.current(generation):
                self.count('unavailable')
                await self._status('unavailable', 'error')
            return False
        finally:
            if self.task is asyncio.current_task():
                self.task = None
