export class ReconnectBackoff {
  private timer?: ReturnType<typeof setTimeout>
  private attempt = 0
  schedule(retry: () => void) {
    if (this.timer !== undefined) return undefined
    const delay = Math.min(30000, 1000 * 2 ** Math.min(this.attempt++, 5))
    this.timer = setTimeout(() => { this.timer = undefined; retry() }, delay)
    return delay
  }
  cancel() { if (this.timer !== undefined) clearTimeout(this.timer); this.timer = undefined }
  reset() { this.cancel(); this.attempt = 0 }
}
