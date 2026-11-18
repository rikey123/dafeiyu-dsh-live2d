"""One fresh, consent-bound screen input for an ordinary completed user turn.

No screenshots are cached, no capture permissions are acquired here, and no
independent response/history is created. The normal DSH turn owns the answer.
"""
from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timezone

from .screen_companion import image_from_frame


class RequestedScreen:
    def __init__(self, client, settings, control, context, notify):
        self.client, self.settings, self.control = client, settings, control
        self.context, self.notify = context, notify
        self.generation = 0
        self.closed = False
        self.busy = False
        self.assessment = None
        self.pending = None
        self.tool_pending = None
        self.requests = self.attached = 0

    def current(self, generation):
        return not self.closed and generation == self.generation

    def invalidate(self):
        """New user input/stop/disconnect retires the entire pending turn."""
        self.generation += 1
        if self.assessment:
            self.assessment.cancel()
        if self.pending and not self.pending['future'].done():
            self.pending['future'].set_result(None)

    def sharing_changed(self):
        """Screen-off resolves a waiter, but does not discard the user's question."""
        if self.pending and not self.pending['future'].done():
            self.pending['future'].set_result(None)
        self.cancel_tool('sharing_changed')

    def cancel_tool(self, reason, *, purpose=None):
        pending = self.tool_pending
        if pending and (purpose is None or pending.get('purpose') == purpose) and not pending['future'].done():
            pending['future'].set_result({'available': False, 'reason': reason})

    async def close(self):
        self.closed = True
        self.cancel_tool('no_connection')
        self.invalidate()
        if self.assessment:
            await asyncio.gather(self.assessment, return_exceptions=True)

    async def status(self, reason, *, probability=None):
        event = {'type': 'voice.screen.status', 'mode': 'requested',
            'status': 'observing' if reason == 'request_attached' else 'waiting',
            'reason': reason, 'source': self.client.source, 'model': self.client.model,
            'requests': self.requests, 'attached': self.attached,
            **self.control.counters()}
        if probability is not None:
            event['desire'] = probability
        await self.notify(event)
        self.control.log_status(event)

    async def answer(self, data):
        """An unsolicited, expired or wrong-stream snapshot is never accepted."""
        pending = self.tool_pending
        if pending and isinstance(data, dict) and data.get('request_id') == pending['request_id']:
            if (set(data) != {'request_id', 'stream_id', 'seq', 'width', 'height', 'mime_type', 'data'}
                    or data.get('stream_id') != pending['stream_id']
                    or self.control.stream_id != pending['stream_id']
                    or pending['future'].done() or type(data.get('seq')) is not int
                    or data['seq'] <= max(pending['min_seq'], self.control.seq)):
                return False
            try:
                image, _ = image_from_frame({k: v for k, v in data.items() if k != 'request_id'})
            except ValueError:
                return False
            self.control.seq = data['seq']
            pending['future'].set_result({'available': True, 'image': image,
                'captured_at': datetime.now(timezone.utc).isoformat(), 'stream_id': pending['stream_id']})
            return True
        pending = self.pending
        if (self.closed or pending is None or not isinstance(data, dict)
                or set(data) != {'request_id', 'stream_id', 'seq', 'width', 'height', 'mime_type', 'data'}
                or data['request_id'] != pending['request_id']
                or data['stream_id'] != pending['stream_id']
                or self.control.stream_id != pending['stream_id']
                or not self.current(pending['generation']) or pending['future'].done()
                or type(data['seq']) is not int or data['seq'] <= max(pending['min_seq'], self.control.seq)):
            return False
        try:
            image, _ = image_from_frame({k: v for k, v in data.items() if k != 'request_id'})
        except ValueError:
            return False
        self.control.seq = max(self.control.seq, data['seq'])
        pending['future'].set_result(image)
        return True

    async def snapshot(self, purpose="tool"):
        if purpose not in {"tool", "idle"}:
            raise ValueError("invalid snapshot purpose")
        if self.closed:
            return {'available': False, 'reason': 'no_connection'}
        if not self.control.enabled:
            return {'available': False, 'reason': 'disabled'}
        stream_id = self.control.stream_id
        if stream_id is None:
            return {'available': False, 'reason': 'not_shared'}
        if self.tool_pending is not None:
            return {'available': False, 'reason': 'busy'}
        future = asyncio.get_running_loop().create_future()
        pending = {'stream_id': stream_id, 'request_id': str(uuid.uuid4()),
                   'min_seq': self.control.seq, 'future': future, 'purpose': purpose}
        self.tool_pending = pending
        try:
            async with asyncio.timeout(self.settings.get('screen_request_timeout_ms', 2000) / 1000):
                await self.notify({'type': 'voice.screen.request', 'stream_id': stream_id,
                                   'request_id': pending['request_id'], 'purpose': purpose})
                result = await future
                if result.get('available') and (self.closed or self.control.stream_id != stream_id):
                    return {'available': False, 'reason': 'no_connection' if self.closed else 'sharing_changed'}
                return result
        except TimeoutError:
            return {'available': False, 'reason': 'timeout'}
        finally:
            if not future.done():
                future.cancel()
            if self.tool_pending is pending:
                self.tool_pending = None

    async def prepare(self, frame):
        """Return false only if newer input has retired this whole normal turn."""
        generation = self.generation
        shared = lambda: self.control.stream_id is not None and self.control.enabled
        frame.metadata['dafeiyu_screen_state'] = 'shared_not_requested' if shared() else 'not_shared'
        frame.metadata['dafeiyu_request_current'] = lambda: self.current(generation)
        if not self.settings.get('systemone_enabled') or not self.settings.get('screen_request_enabled', True):
            if shared():
                frame.metadata['dafeiyu_screen_state'] = 'request_disabled'
            return True
        messages = frame.context.messages
        if not messages or messages[-1].get('role') != 'user' or not isinstance(messages[-1].get('content'), str):
            return True
        self.busy = True
        self.requests += 1
        probability = None
        try:
            self.assessment = asyncio.create_task(self.client.screen_request(messages[-1]['content'], self.context()))
            try:
                async with asyncio.timeout(self.settings.get('systemone_timeout_ms', 1200) / 1000):
                    probability = await self.assessment
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                return False
            except Exception:
                probability = None
            finally:
                self.assessment = None
            if not self.current(generation):
                return False
            frame.metadata['dafeiyu_screen_state'] = 'shared_not_requested' if shared() else 'not_shared'
            if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
                probability = None
            if probability is None:
                frame.metadata['dafeiyu_screen_state'] = 'intent_unavailable' if shared() else 'not_shared'
                await self.status('request_intent_unavailable')
                return self.current(generation)
            if probability < self.settings.get('screen_request_threshold', .75):
                await self.status('request_low_intent', probability=probability)
                return self.current(generation)
            if not shared():
                frame.metadata['dafeiyu_screen_state'] = 'not_shared'
                await self.status('request_not_shared', probability=probability)
                return self.current(generation)
            stream_id = self.control.stream_id
            request_id = str(uuid.uuid4())
            future = asyncio.get_running_loop().create_future()
            pending = {'stream_id': stream_id, 'request_id': request_id, 'future': future,
                'generation': generation, 'min_seq': self.control.seq}
            self.pending = pending
            try:
                await self.notify({'type': 'voice.screen.request', 'stream_id': stream_id, 'request_id': request_id})
                async with asyncio.timeout(self.settings.get('screen_request_timeout_ms', 2000) / 1000):
                    image = await future
            except TimeoutError:
                image = None
            finally:
                if not future.done():
                    future.cancel()
                if self.pending is pending:
                    self.pending = None
            if not self.current(generation):
                return False
            if image is None or self.control.stream_id != stream_id:
                frame.metadata['dafeiyu_screen_state'] = 'snapshot_timeout' if shared() else 'not_shared'
                await self.status('request_snapshot_timeout' if shared() else 'request_not_shared')
                return self.current(generation)
            frame.metadata['dafeiyu_requested_screen'] = image
            frame.metadata['dafeiyu_requested_screen_valid'] = lambda: self.current(generation) and self.control.stream_id == stream_id
            frame.metadata['dafeiyu_screen_state'] = 'attached'
            self.attached += 1
            await self.status('request_attached', probability=probability)
            return self.current(generation)
        finally:
            self.busy = False
