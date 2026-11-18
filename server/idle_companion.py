"""One local, connection-scoped idle clock; no conversation memory or capture cache."""
import asyncio
import random
import time


class IdleCompanion:
    def __init__(self, settings, screen, native_context, *, notify, clock=time.monotonic,
                 jitter=lambda: random.uniform(0, 5)):
        self.settings, self.screen, self.native_context = settings, screen, native_context
        self.notify, self.clock, self.jitter = notify, clock, jitter
        self.enabled = bool(settings.get('idle_companion_enabled') and
                            settings.get('conversation_mode', 'duplex') != 'moss_live')
        self.closed = False
        self.pending = False
        self.generation = 0
        self.deadline = float('-inf')
        self.last_activity = clock()
        self.next_attempt = self.last_activity + settings.get('idle_companion_after_s', 120) + max(0, jitter())
        self.task = None
        self.last_status = None

    async def status(self, status, reason):
        pair = (status, reason)
        if pair != self.last_status:
            self.last_status = pair
            await self.notify({'type': 'voice.idle', 'status': status, 'reason': reason})

    def activity(self, invalidate=True):
        if invalidate:
            self.generation += 1
        self.last_activity = self.clock()
        self.next_attempt = self.last_activity + self.settings.get('idle_companion_after_s', 120) + max(0, self.jitter())
        if invalidate:
            self.screen.request.cancel_tool('activity', purpose='idle')

    def invalidate(self):
        self.generation += 1
        self.screen.request.cancel_tool('activity', purpose='idle')

    def current(self, generation, stream_id=None):
        return (not self.closed and self.enabled and generation == self.generation
                and (stream_id is None or self.screen.control.stream_id == stream_id))

    def valid(self, generation, stream_id=None):
        return self.current(generation, stream_id) and self.clock() <= self.deadline

    def busy(self, *, ignore_pending=False):
        s = self.screen
        return (s.user_speaking or s.bot_speaking or s.generating or (s.pending_reply and not ignore_pending)
                or s.playback_busy() or s.external_busy() or s.request.busy
                or s.request.tool_pending is not None or s.control.task is not None)

    async def tick(self):
        now = self.clock()
        if self.closed or not self.enabled:
            return False
        if now < self.next_attempt or self.pending:
            return False
        # No backlog, including after long busy periods and failed attempts.
        self.next_attempt = now + max(5, min(30, self.settings.get('idle_companion_after_s', 120))) + max(0, self.jitter())
        budget = self.screen.control.budget
        for queue in (budget.idle, budget.replies, budget.judgments):
            while queue and now - queue[0] >= 3600:
                queue.popleft()
        if self.busy():
            await self.status('waiting', 'busy')
            return False
        if len(budget.idle) >= self.settings.get('idle_companion_max_per_hour', 6):
            await self.status('waiting', 'budget')
            return False
        if len(budget.replies) >= self.settings.get('screen_companion_max_replies_per_hour', 12):
            await self.status('waiting', 'budget')
            return False
        if now - budget.last_reply < max(self.settings.get('idle_companion_cooldown_s', 180),
                                          self.settings.get('screen_companion_cooldown_s', 30)):
            await self.status('waiting', 'cooldown')
            return False
        self.pending = True
        generation = self.generation
        self.deadline = now + max(5, (self.settings.get('screen_companion_timeout_ms', 3000)
                                      + self.settings.get('screen_request_timeout_ms', 2000)) / 1000 + 3)
        try:
            native = await self.native_context()
            if not self.valid(generation):
                return False
            if native is None or native.get('busy') is not False:
                await self.status('waiting', 'busy')
                return False
            if self.busy():
                return False
            image = None
            stream_id = None
            if self.settings.get('idle_companion_include_screen', True):
                result = await self.screen.request.snapshot(purpose='idle')
                if not self.valid(generation):
                    return False
                if result.get('available'):
                    image, stream_id = result['image'], result['stream_id']
                elif result.get('reason') in {'activity', 'sharing_changed', 'no_connection'}:
                    return False
            if not self.valid(generation, stream_id) or self.busy():
                return False
            # Recheck the native agent after capture, which can take seconds.
            native = await self.native_context()
            if not self.valid(generation, stream_id) or self.busy():
                return False
            if native is None or native.get('busy') is not False:
                await self.status('waiting', 'busy')
                return False
            now = self.clock()
            budget.idle.append(now)
            budget.replies.append(now)
            budget.mark_reply(now)
            await self.status('accepted', 'idle')
            if not self.valid(generation, stream_id) or self.busy():
                return False
            await self.screen.offer_idle(image, generation, stream_id)
            return True
        finally:
            self.pending = False

    async def run(self):
        await self.status('waiting' if self.enabled else 'unavailable', 'inactivity' if self.enabled else 'disabled')
        while not self.closed and self.enabled:
            await asyncio.sleep(max(.1, min(5, self.next_attempt - self.clock())))
            try:
                await self.tick()
            except Exception:
                await self.status('unavailable', 'error')

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run(), name='idle-companion')

    async def close(self):
        self.closed = True
        self.invalidate()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
