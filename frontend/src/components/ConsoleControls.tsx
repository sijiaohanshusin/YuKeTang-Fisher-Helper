import { useState } from 'react'
import type { CourseItem } from '../types'
import { api, type AISettings, type Health, type Runtime } from '../consoleApi'

export function CoursePicker({ courses, selected, onChange }: { courses: CourseItem[]; selected: string[]; onChange: (ids: string[]) => void }) {
  const [query, setQuery] = useState('')
  const visible = courses.filter(c => `${c.name} ${c.teacher_name || ''} ${c.classroom_id}`.toLowerCase().includes(query.toLowerCase()))
  return <div>
    <div className="control-toolbar"><input className="console-input search-input" aria-label="搜索课程" placeholder="搜索课程名称、教师或班级编号" value={query} onChange={e => setQuery(e.target.value)} /><span className="count-tag">已选 {selected.length} / {courses.length}</span></div>
    <div className="inline-actions"><button onClick={() => onChange(courses.map(c => c.classroom_id))}>全选</button><button onClick={() => onChange(courses.filter(c => c.active).map(c => c.classroom_id))}>仅选正在上课</button><button onClick={() => onChange([])}>清空</button><span>{visible.length} 门匹配课程</span></div>
    <div className="course-picker">{visible.map(course => <label className={`course-choice ${selected.includes(course.classroom_id) ? 'is-selected' : ''}`} key={course.classroom_id}>
      <input type="checkbox" checked={selected.includes(course.classroom_id)} onChange={e => onChange(e.target.checked ? [...selected, course.classroom_id] : selected.filter(id => id !== course.classroom_id))} />
      <span><strong>{course.name}</strong><small>{course.teacher_name || '已加入班级'} · {course.classroom_id}</small></span>{course.active && <em>上课中</em>}
    </label>)}</div>
    {!visible.length && <div className="console-empty">{courses.length ? '没有匹配的课程，试试其他关键词。' : '完成扫码登录后，账号已加入的班级会显示在这里。'}</div>}
  </div>
}

const MODES = [
  { id: 'observe', title: '先观察', subtitle: '仅发现开课', description: '不签到，不进入课堂，不提交答案。' },
  { id: 'trial', title: 'AI 试答', subtitle: '看答案再决定', description: '进入课堂后生成答案，始终不自动提交。' },
  { id: 'auto', title: '自动运行', subtitle: '持续监听与作答', description: '按下方独立开关执行签到和有效答案提交。' },
] as const

export function ModeControl({ value, onChange }: { value: Runtime; onChange: (value: Runtime) => void }) {
  return <div><div className="mode-grid">{MODES.map(mode => <label key={mode.id} className={`mode-choice ${value.mode === mode.id ? 'is-selected' : ''}`}>
    <input type="radio" name="run-mode" value={mode.id} checked={value.mode === mode.id} onChange={() => onChange({ ...value, mode: mode.id, auto_signin: false, submit_answers: false })} />
    <span className="mode-heading">{mode.title}</span><small>{mode.subtitle}</small><p>{mode.description}</p>
  </label>)}</div>
    <label className="switch-row"><span><strong>自动进入课堂并签到</strong><small>对选中班级生效，会产生真实考勤；取题需要课堂令牌。</small></span><input className="console-switch" type="checkbox" checked={value.auto_signin} disabled={value.mode === 'observe'} onChange={e => onChange({ ...value, auto_signin: e.target.checked })} /></label>
    <label className="switch-row"><span><strong>自动提交有效 AI 答案</strong><small>只在自动运行模式生效；AI 失败、无效或超时会跳过。</small></span><input className="console-switch" type="checkbox" checked={value.submit_answers} disabled={value.mode !== 'auto'} onChange={e => onChange({ ...value, submit_answers: e.target.checked })} /></label>
  </div>
}

export function ModelPanel({ ai, health, onChanged, notify }: { ai: AISettings; health: Health | null; onChanged: () => void; notify: (message: string) => void }) {
  const [preset, setPreset] = useState('deepseek')
  const [key, setKey] = useState('')
  const [base, setBase] = useState('https://api.deepseek.com/v1')
  const [model, setModel] = useState('deepseek-flash')
  const [busy, setBusy] = useState('')
  const active = ai.keys[ai.active_key]
  const verified = health?.vision_validation?.correct && health.vision_validation.current_config
  const selectPreset = (id: string) => {
    setPreset(id)
    setBase(id === 'deepseek' ? 'https://api.deepseek.com/v1' : '')
    setModel(id === 'deepseek' ? 'deepseek-flash' : '')
  }
  const save = async () => {
    if (!key.trim() || !model.trim() || (preset !== 'google' && !base.trim())) { notify('请填写密钥、模型名称和接口地址。'); return }
    setBusy('save')
    try {
      const result = await api<{ ok: boolean; index: number }>('/api/ai/keys', { name: preset === 'deepseek' ? 'DeepSeek 官方视觉接口' : model, provider: preset === 'google' ? 'google' : 'openai_compat', key: key.trim(), model: model.trim(), base_url: base.trim() })
      if (!result.ok) throw new Error('模型保存未完成')
      await api('/api/ai/active', { active_key: result.index }, 'PUT')
      await api('/api/ai/fallback', { fallback_keys: false }, 'PUT')
      setKey(''); notify('模型已保存并设为当前模型，请继续验证图片输入。'); onChanged()
    } catch (error) { notify(error instanceof Error ? error.message : '模型保存失败') }
    finally { setBusy('') }
  }
  const test = async () => {
    setBusy('test')
    try {
      const result = await api<{ ok: boolean; correct?: boolean; answers?: string[]; elapsed_seconds?: number; error?: string }>('/api/experiment/vision-test', {})
      notify(result.ok && result.correct ? `识图验证通过：答案 ${result.answers?.join(', ')}，耗时 ${result.elapsed_seconds} 秒。` : result.error || '接口可达，但图片示例答案不符，请检查视觉模型。')
      onChanged()
    } catch { notify('识图请求未完成，请检查网络或查看日志。') }
    finally { setBusy('') }
  }
  return <div>
    {active && <div className="model-current"><span className={`status-dot ${verified ? 'green' : 'amber'}`} /><div><strong>{active.name || active.model}</strong><small>{active.model} · {active.key}</small></div><span className={`console-pill ${verified ? 'green' : 'amber'}`}>{verified ? '图片输入已验证' : '待识图验证'}</span></div>}
    <div className="form-grid"><label>接口提供商<select className="console-input" value={preset} onChange={e => selectPreset(e.target.value)}><option value="deepseek">DeepSeek 官方视觉模型</option><option value="custom">自定义 OpenAI 兼容接口</option><option value="google">Google Gemini</option></select></label><label>API Key<input className="console-input" type="password" autoComplete="off" placeholder={active ? '填写新密钥以新增配置' : '仅保存在这台电脑'} value={key} onChange={e => setKey(e.target.value)} /></label>
      {preset !== 'google' && <label className="span-2">接口地址 Base URL<input className="console-input" placeholder="https://服务商域名/v1" value={base} onChange={e => setBase(e.target.value)} /></label>}
      <label className="span-2">视觉模型名称<input className="console-input" placeholder={preset === 'google' ? '填写 Gemini 模型 ID' : '必须支持图片输入'} value={model} onChange={e => setModel(e.target.value)} /></label>
    </div>
    <div className="panel-actions"><button className="console-button secondary" disabled={!!busy} onClick={save}>{busy === 'save' ? '保存中…' : '保存模型配置'}</button><button className="console-button" disabled={!!busy || !active} onClick={test}>{busy === 'test' ? '正在调用模型…' : '验证图片输入'}</button></div>
    <details className="help-details"><summary>识图验证会做什么？</summary><p>读取下面的电路图，使用当前模型生成并解析答案 B（2A）。此操作会调用你的模型接口，始终不提交课堂答案。</p><img src="/api/experiment/sample.png" alt="12V 电源与 6Ω 电阻的识图验证电路" /></details>
  </div>
}
