import { useEffect, useState } from 'react'
import { api, useConsoleData } from '../consoleApi'

const KINDS = [{ id: 1, title: '单选题', text: '必须是一个有效选项。' }, { id: 2, title: '多选题', text: '必须是非空、无重复的有效选项集合。' }, { id: 3, title: '投票题', text: '不超过课堂允许的选项数量。' }, { id: 5, title: '简答题', text: '必须是非空答案，不使用空白降级。' }]
export default function Settings() {
  const { courses, ai, refresh } = useConsoleData()
  const [course, setCourse] = useState('')
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!course && courses.length) setCourse(courses[0].classroom_id) }, [course, courses])
  useEffect(() => {
    if (course) { setConfig(null); api<Record<string, unknown>>(`/api/courses/settings/${course}`).then(setConfig).catch(() => setMessage('课程策略读取失败')) }
  }, [course])
  const save = async () => {
    if (!config) return
    setBusy(true)
    try {
      await api(`/api/courses/settings/${course}`, { ...config, type4: 'off', auto_danmu: false, auto_redpacket: false, answer_last5s: false }, 'PUT')
      setMessage('课程策略已保存。运行台的总模式与签到、提交开关仍然生效。')
    } catch { setMessage('策略保存失败，请检查服务状态。') }
    finally { setBusy(false) }
  }
  const changeKey = async (index: number, remove = false) => {
    try {
      if (remove) { const response = await fetch(`/api/ai/keys/${index}`, { method: 'DELETE' }); if (!response.ok) throw new Error() }
      else await api('/api/ai/active', { active_key: index }, 'PUT')
      setMessage(remove ? '模型配置已删除' : '当前模型已切换，请到模型连接页重新验证图片输入。'); refresh()
    } catch { setMessage('模型操作未完成，请重试。') }
  }
  return <div className="console-stack"><header className="console-hero"><div><div className="console-eyebrow">按班级细化 · 凭据管理</div><h1>高级设置</h1><p>日常开关请使用运行台。这里仅保留实际参与执行的选项。</p></div></header>{message && <div className="console-notice" role="status">{message}</div>}
    <section className="console-panel"><div className="panel-heading"><h2>班级题型策略</h2><p>关闭某种题型后，该班级对应题目会明确跳过。</p></div><label className="muted">选择班级<select className="console-input" value={course} onChange={e => setCourse(e.target.value)}>{courses.map(item => <option key={item.classroom_id} value={item.classroom_id}>{item.name} · {item.classroom_id}</option>)}</select></label>
      {config ? <><div className="policy-grid">{KINDS.map(kind => <label className="switch-row" key={kind.id}><span><strong>{kind.title}</strong><small>{kind.text}</small></span><select className="console-input compact-select" value={config[`type${kind.id}`] === 'ai' ? 'ai' : 'off'} onChange={e => setConfig({ ...config, [`type${kind.id}`]: e.target.value })}><option value="ai">AI 处理</option><option value="off">跳过</option></select></label>)}</div><div className="console-notice">填空题尚未验证提交格式，始终跳过。随机答案、空白答案、答案队列、弹幕和红包不参与本版本执行。</div><div className="form-grid"><label>最短提交延迟 / 秒<input className="console-input" type="number" min="0" max="20" value={Number(config.answer_delay_min || 0)} onChange={e => { const delay = Math.max(0, Math.floor(+e.target.value)); setConfig({ ...config, answer_delay_min: delay, answer_delay_max: delay }) }} /></label><p className="muted">通常保留默认值即可。AI 返回后尽快处理，并以题目截止和全局提交预留时间为准。</p></div><div className="panel-actions"><button className="console-button" disabled={busy} onClick={save}>{busy ? '保存中…' : '保存班级策略'}</button></div></> : <div className="console-empty">{course ? '正在读取策略…' : '请先登录并同步课程。'}</div>}
    </section><section className="console-panel"><div className="panel-heading"><h2>已有模型配置</h2><p>界面只显示密钥掩码。切换后请重新进行识图验证。</p></div>{ai.keys.map((key, index) => <div className="key-management-row" key={index}><div><strong>{key.name}</strong><small>{key.model} · {key.key}</small></div><span className={`console-pill ${index === ai.active_key ? 'green' : ''}`}>{index === ai.active_key ? '正在使用' : '备用配置'}</span><button className="text-button" disabled={index === ai.active_key} onClick={() => changeKey(index)}>设为当前</button><button className="text-button danger-text" onClick={() => changeKey(index, true)}>删除</button></div>)}{!ai.keys.length && <div className="console-empty">还没有模型配置，请通过配置向导或模型连接页添加。</div>}</section>
  </div>
}
