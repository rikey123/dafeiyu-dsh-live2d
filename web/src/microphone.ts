/** Keep the browser's error code: device failures never reach the speech server. */
export function microphoneError(error: unknown): string {
  const detail = error as { name?: string; message?: string } | null
  const name = detail?.name || 'Error'
  const hints: Record<string, string> = {
    NotFoundError: '浏览器未找到可用麦克风。请接入麦克风，在 Windows“设置 → 系统 → 声音 → 输入”中确认设备已启用，然后刷新设备列表。',
    DevicesNotFoundError: '浏览器未找到可用麦克风。请接入并启用录音设备，然后刷新设备列表。',
    NotAllowedError: '麦克风访问被拒绝。请允许当前网站使用麦克风，并检查 Windows“隐私和安全性 → 麦克风”的访问权限。',
    PermissionDeniedError: '麦克风访问被拒绝。请允许当前网站使用麦克风，并检查 Windows 的麦克风权限。',
    NotReadableError: '无法打开麦克风。请关闭可能独占设备的录音、会议软件，检查设备连接后重试，也可在设置中选择其他麦克风。',
    TrackStartError: '无法打开麦克风。请检查设备连接，并关闭可能独占设备的程序后重试。',
    OverconstrainedError: '所选麦克风已不可用或不支持录音要求。请刷新设备列表，重新选择麦克风或“系统默认”后重试。',
    AbortError: '麦克风启动被中断。请检查设备连接后重试。',
    SecurityError: '浏览器禁止此页面采音。请通过本机 localhost / 127.0.0.1 或 HTTPS 打开，并检查网站权限。',
  }
  const hint = hints[name]
  return hint ? `${hint}（${name}）` : detail?.message || String(error)
}

/** Enumeration does not open the microphone or ask for recording permission. */
export async function audioInputs(): Promise<MediaDeviceInfo[]> {
  if (!navigator.mediaDevices?.enumerateDevices) {
    throw new DOMException('当前页面无法访问音频设备，请使用本机 localhost / 127.0.0.1 或 HTTPS。', 'SecurityError')
  }
  return (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'audioinput')
}
