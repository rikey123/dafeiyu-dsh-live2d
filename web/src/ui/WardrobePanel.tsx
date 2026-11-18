import { faceExpressions, gestureLabels, type Gesture, type Wardrobe } from '../avatar/wardrobe'

type Props = { wardrobe: Wardrobe; onChange: (next: Wardrobe) => void; expression: string; onExpression: (name: string) => void; enabled: boolean }

function Chip({ on, children, onClick, disabled }: { on: boolean; children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button type="button" className={`chip ${on ? 'on' : ''}`} aria-pressed={on} disabled={disabled} onClick={onClick}>{children}</button>
}

export function WardrobePanel({ wardrobe: w, onChange, expression, onExpression, enabled }: Props) {
  const set = (patch: Partial<Wardrobe>) => onChange({ ...w, ...patch })
  const toggles: [keyof Wardrobe, string][] = [['basin', '大钢盆'], ['teeth', '兔牙'], ['tail', '尾巴'], ['longSkirt', '长短裙'], ['chestCloth', '胸口衣服'], ['barefoot', '脱鞋']]
  return <div className="drawer-content wardrobe">
    {!enabled && <p className="hint-box">当前模型不是 DeepSeek-chan，以下配件参数可能不存在。</p>}
    <section className="group"><h3>表情</h3><p className="hint">手动表情会覆盖对话中的自动情绪。</p>
      <div className="chips">{faceExpressions.map(e => <Chip key={e.name || 'none'} on={expression === e.name} onClick={() => onExpression(e.name)}>{e.label}</Chip>)}</div></section>
    <section className="group"><h3>眼镜</h3>
      <div className="chips">{([['none', '不戴'], ['frame', '黑框眼镜'], ['mono', '单片眼镜']] as const).map(([value, label]) => <Chip key={value} on={w.glasses === value} onClick={() => set({ glasses: value })}>{label}</Chip>)}</div></section>
    <section className="group"><h3>配件与服装</h3>
      <div className="chips">{toggles.map(([key, label]) => <Chip key={key} on={!!w[key]} onClick={() => set({ [key]: !w[key] })}>{label}</Chip>)}</div>
      <label className="range-row">Q 版<input type="range" min="0" max="1" step="0.05" aria-label="Q 版体型" value={w.size} onChange={e => set({ size: Number(e.target.value) })}/><output>{w.size === 0 ? '标准' : `${Math.round(w.size * 100)}%`}</output></label>
      <div className="chips"><Chip on={w.size === 0} onClick={() => set({ size: 0 })}>标准身形</Chip><Chip on={w.size === 1} onClick={() => set({ size: 1 })}>Q 版小人</Chip></div></section>
    <section className="group"><h3>手势</h3>
      <div className="chips">{(Object.keys(gestureLabels) as Gesture[]).map(g => <Chip key={g} on={w.gesture === g} onClick={() => set({ gesture: g })}>{gestureLabels[g]}</Chip>)}</div></section>
    <section className="group"><h3>状态联动</h3>
      <label className="switch-row"><input type="checkbox" checked={w.reactive} onChange={e => set({ reactive: e.target.checked })}/><span>聆听时前倾，思考时竖起食指并显示加载</span></label></section>
    <p className="credit">DeepSeek-chan（大肥鱼） · 原画及拆分：神宫凉子 · Live2D 建模：霓虹猫_NeonNeko</p>
  </div>
}
