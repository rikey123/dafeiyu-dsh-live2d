export const presenceDefaults = { companion_interests: '', idle_companion_enabled: false, idle_companion_after_s: 120, idle_companion_cooldown_s: 180, idle_companion_max_per_hour: 6, idle_companion_include_screen: true, idle_companion_max_reply_chars: 64 }
export type PresenceSettings = typeof presenceDefaults
export const idleFields = [
 ['idle_companion_after_s','无互动多久后主动说话（秒）',30,3600],
 ['idle_companion_cooldown_s','主动说话冷却（秒）',30,3600],
 ['idle_companion_max_per_hour','每小时最多主动说话次数',1,60],
 ['idle_companion_max_reply_chars','建议回复长度（字符）',8,240],
] as const
export function PresencePreferences({settings,onChange,native,runtime,dsh=true}: {settings: PresenceSettings; onChange:(patch:Partial<PresenceSettings>)=>void; native:boolean; runtime?:string; dsh?:boolean}) {
 return <section className="group presence-parameters"><h3>陪伴与兴趣</h3>
 <label>共同兴趣<textarea aria-label="共同兴趣" maxLength={2000} rows={3} value={settings.companion_interests} onChange={e=>onChange({companion_interests:e.target.value})}/></label>
 <small>填写喜欢的话题、游戏或其他兴趣，Jev 和 DSH 可在陪伴交流中参考。</small>
 <label className="motion-setting"><input aria-label="空闲时主动聊天" type="checkbox" checked={settings.idle_companion_enabled} disabled={(native || !dsh) && !settings.idle_companion_enabled} onChange={e=>onChange({idle_companion_enabled:e.target.checked})}/>空闲时主动聊天</label>
 {!dsh && <small>安静后主动搭话需要使用 DSH 插件模式。</small>}
 <small>没有有意义的互动一段时间后，助手可以主动找话题；这与用户说话时主动接话是独立功能。无需开启屏幕陪玩或分享屏幕。MOSS-Live 不支持；保存设置后语音会话重新连接。</small>
 {runtime && settings.idle_companion_enabled && <small role="status">安静后主动搭话：{runtime}</small>}
 <label className="motion-setting"><input type="checkbox" checked={settings.idle_companion_include_screen} onChange={e=>onChange({idle_companion_include_screen:e.target.checked})}/>空闲聊天时可参考当前分享画面</label>
 <small>仅在当前已有手动授权的屏幕分享时获取新画面，不会自动开始或重新授权分享。</small>
 {idleFields.map(([key,label,min,max])=><label key={key}>{label}<input aria-label={label} type="number" required min={min} max={max} step={1} value={Number.isFinite(settings[key]) ? settings[key] : ''} onChange={e=>onChange({[key]:e.target.valueAsNumber})}/><small>默认 {presenceDefaults[key]}，范围 {min}–{max}。</small></label>)}
 </section>
}
