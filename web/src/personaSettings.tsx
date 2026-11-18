export function PersonaSetting({ embedded, value, onChange }: { embedded: boolean; value: string; onChange: (value: string) => void }) {
  return embedded
    ? <div className="service-status">人格由 DSH 人格插件管理</div>
    : <label>角色设定<textarea rows={4} value={value} onChange={e => onChange(e.target.value)} placeholder="描述角色的性格和说话方式"/></label>
}
