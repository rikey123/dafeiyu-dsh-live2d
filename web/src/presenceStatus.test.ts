import {expect,it} from 'vitest'
import {presenceStatus} from './presenceStatus'
it('only renders local idle diagnostics without echoing raw input', () => {
 expect(presenceStatus({type:'voice.idle',status:'accepted'})).toContain('不代表已经播放')
 expect(presenceStatus({type:'voice.idle',status:'waiting',reason:'busy'})).toBe('对话或任务正在进行')
 expect(presenceStatus({type:'voice.idle',status:'waiting',reason:'private transcript or key'})).toBe('等待合适的搭话机会')
 expect(presenceStatus({type:'voice.idle',status:'unavailable',reason:'private transcript or key'})).not.toContain('private')
 expect(presenceStatus({type:'voice.initiative',status:'accepted'})).toBeUndefined()
 expect(presenceStatus({type:'voice.idle',status:'arbitrary'})).toBeUndefined()
})
