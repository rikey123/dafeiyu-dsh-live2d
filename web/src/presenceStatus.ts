/** Local scheduling diagnostics, never a claim that any speech was played. */
export function presenceStatus(data: unknown): string | undefined {
 if (!data || typeof data !== 'object') return
 const value = data as Record<string, unknown>
 if (value.type !== 'voice.idle' || !['waiting','accepted','unavailable'].includes(String(value.status))) return
 const reasons: Record<string,string> = { inactivity:'还未到无互动时间', cooldown:'主动搭话冷却中', budget:'已达到每小时主动搭话限额', busy:'对话或任务正在进行', requested:'已请求主动搭话，不代表已经播放', stale:'本次机会已过期', cancelled:'本次机会已取消', not_ready:'等待 DSH 就绪', no_screen:'未共享画面，可仅按话题交流', disabled:'未开启安静后主动搭话' }
 return value.status === 'accepted' ? '已请求主动搭话，不代表已经播放' : value.status === 'unavailable' ? '主动搭话暂不可用，正常对话不受影响' : typeof value.reason === 'string' && Object.hasOwn(reasons,value.reason) ? reasons[value.reason] : '等待合适的搭话机会'
}
