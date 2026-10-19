import { useEffect, useState } from 'react'
import type { CourseItem } from '../types'

type Runtime = { mode: string; auto_signin: boolean; submit_answers: boolean; course_ids: string[]; poll_interval: number; submit_reserve: number; ai_timeout: number }
const defaults: Runtime = { mode: 'observe', auto_signin: false, submit_answers: false, course_ids: [], poll_interval: 30, submit_reserve: 3, ai_timeout: 90 }

export default function Experiment() {
  const [runtime, setRuntime] = useState<Runtime>(defaults)
  const [dirty, setDirty] = useState(false)
  const edit = (next: Runtime) => { setDirty(true); setRuntime(next) }
  const [health, setHealth] = useState<any>(null)
  const [events, setEvents] = useState<any[]>([])
  const [courses, setCourses] = useState<CourseItem[]>([])
  const [keys, setKeys] = useState<any[]>([])
  const [key, setKey] = useState('')
  const [base, setBase] = useState('')
  const [model, setModel] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const reload = () => {
    fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => setHealth(null))
    fetch('/api/events/recent').then(r => r.json()).then(setEvents).catch(() => {})
    fetch('/api/courses/all').then(r => r.json()).then(setCourses).catch(() => {})
  }
  useEffect(() => {
    fetch('/api/runtime').then(r => r.json()).then(setRuntime)
    fetch('/api/ai/settings').then(r => r.json()).then(r => setKeys(r.keys))
    reload()
    const timer = setInterval(reload, 3000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => { if (!dirty && health?.runtime) setRuntime(health.runtime) }, [health?.runtime, dirty])
  const save = async () => {
    const value = { ...runtime, auto_signin: runtime.mode !== 'observe' && runtime.auto_signin, submit_answers: runtime.mode === 'auto' && runtime.submit_answers }
    const result = await fetch('/api/runtime', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }).then(r => r.json())
    setMessage(result.ok ? '运行设置已保存。新课将在下一轮发现时连接。' : result.error)
    if (result.ok) { setDirty(false); setRuntime(result.config) }
    reload()
  }
  const saveKey = async () => {
    if (!key || !base || !model) { setMessage('请一次填写 API Key、完整 Base URL 和视觉模型名称。'); return }
    const result = await fetch('/api/ai/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: model, provider: 'openai_compat', key, base_url: base, model }) }).then(r => r.json())
    if (result.ok) {
      await fetch('/api/ai/active', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ active_key: result.index }) })
      setKey('')
      setMessage('模型已保存并设为当前模型。请进行下面的图片试答。')
      fetch('/api/ai/settings').then(r => r.json()).then(r => setKeys(r.keys))
    }
  }
  const visionTest = async () => {
    setBusy(true); setMessage('正在获取示例电路图并调用已配置模型…')
    try {
      const result = await fetch('/api/experiment/vision-test', { method: 'POST' }).then(r => r.json())
      setMessage(JSON.stringify(result, null, 2))
    } catch { setMessage('后端不可达，请查看日志。') }
    setBusy(false)
  }
  const time = (epoch: number) => epoch ? new Date(epoch * 1000).toLocaleString() : '尚无'
  return <div>
    <h1>课堂实验控制台</h1>
    <p>首次启动为观察模式。设置保存在本机 store 中。登录扫码只验证账号；课堂签到由下面的独立开关控制。</p>
    <section className="card" style={{ padding: 20, marginBottom: 20 }}>
      <h2>运行与监听状态</h2>
      <p>后端：{health ? '可达' : '不可达'} ｜服务器：{health?.domain || '未知'} ｜登录：{health?.login_verified ? '服务器已验证' : '尚未验证，请扫码登录'}</p>
      <p>发现循环：{health?.monitor?.discovery_healthy ? '正常' : '未启动或异常'} ｜状态：{health?.monitor?.state || '等待登录'} ｜最近成功：{time(health?.monitor?.last_success)} ｜最近错误：{health?.monitor?.last_error || '无'}</p>
      <p>当前已保存模式：{health?.runtime?.mode} ｜发现开课：{health?.monitor?.discovered?.length || 0} 节</p>
      {health?.monitor?.lessons?.map((l: any) => <p key={l.lessonid}>
        {l.lessonname}（{l.lessonid}）：{l.connection_state} ｜连接{l.connected && l.last_pong && Date.now() / 1000 - l.last_pong < 45 ? '心跳正常' : '尚未确认或失联'} ｜最近 Pong：{time(l.last_pong)} ｜课件：{l.presentations}，缓存题目：{l.cached_problems}
      </p>)}
    </section>
    <section className="card" style={{ padding: 20, marginBottom: 20 }}>
      <h2>模式、课程范围和开关</h2>
      <select className="form-select" value={runtime.mode} onChange={e => edit({ ...runtime, mode: e.target.value, auto_signin: false, submit_answers: false })}>
        <option value="observe">观察模式：仅发现开课，不签到、不进入课堂、不提交</option>
        <option value="trial">AI 试答：生成答案，始终不提交</option>
        <option value="auto">自动运行：按以下开关签到与提交</option>
      </select>
      <p>读取题目需要课堂令牌。项目已知流程只能通过签到取得令牌；AI 试答如关闭签到，将仅观察开课。</p>
      <p><label><input type="checkbox" checked={runtime.auto_signin} disabled={runtime.mode === 'observe'} onChange={e => edit({ ...runtime, auto_signin: e.target.checked })} /> 允许自动进入并签到（会产生真实考勤）</label></p>
      <p><label><input type="checkbox" checked={runtime.submit_answers} disabled={runtime.mode !== 'auto'} onChange={e => edit({ ...runtime, submit_answers: e.target.checked })} /> 提交有效 AI 答案（会产生真实答题记录）</label></p>
      <p>只执行选中的班级。空列表表示不进入任何班级。下面使用课堂班级 classroom_id，不是课程名或每节 lessonId。</p>
      <button className="btn btn-secondary" onClick={() => edit({ ...runtime, course_ids: courses.map(c => c.classroom_id) })}>全选全部班级</button>{' '}
      <button className="btn btn-secondary" onClick={() => edit({ ...runtime, course_ids: [] })}>清空选择</button>
      <p>当前选择 {runtime.course_ids.length} 个班级{dirty ? '（尚未保存）' : ''}。</p>
      {courses.map(c => <p key={c.classroom_id}><label><input type="checkbox" checked={runtime.course_ids.includes(c.classroom_id)} onChange={e => edit({ ...runtime, course_ids: e.target.checked ? [...runtime.course_ids, c.classroom_id] : runtime.course_ids.filter(x => x !== c.classroom_id) })} /> {c.name}（{c.classroom_id}）</label></p>)}
      {!courses.length && <p>登录后显示账号已加入班级。</p>}
      <button className="btn btn-secondary" onClick={async () => { const r = await fetch('/api/courses/refresh', { method: 'POST' }).then(r => r.json()); setMessage(r.ok ? '课程已刷新' : r.error); reload() }}>刷新账号课程</button>
      <p>扫描间隔（秒）：<input type="number" min="10" max="120" value={runtime.poll_interval} onChange={e => edit({ ...runtime, poll_interval: +e.target.value })} /> AI 最长等待：<input type="number" min="5" max="180" value={runtime.ai_timeout} onChange={e => edit({ ...runtime, ai_timeout: +e.target.value })} /> 提交预留：<input type="number" min="2" max="15" value={runtime.submit_reserve} onChange={e => edit({ ...runtime, submit_reserve: +e.target.value })} /></p>
      <button className="btn btn-primary" onClick={save}>保存运行设置</button>
    </section>
    <section className="card" style={{ padding: 20, marginBottom: 20 }}>
      <h2>本机模型配置与识图验证</h2>
      {health?.vision_validation && <p>最近识图验证：{health.vision_validation.current_config && health.vision_validation.correct ? "当前配置已通过电路图试答" : "未通过或配置已变更，请重测"} ｜模型：{health.vision_validation.active_model} ｜耗时：{health.vision_validation.elapsed_seconds} 秒</p>}
      <p>填写支持 Chat Completions 图片输入的视觉模型。API Key 只保存在本机；不要在聊天中粘贴。Google 等其他提供商可在登录后的设置页配置。</p>
      <p><input className="form-input" type="password" placeholder="API Key" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} /></p>
      <p><input className="form-input" style={{ width: '100%' }} placeholder="Base URL，例如 https://服务商域名/v1" value={base} onChange={e => setBase(e.target.value)} /></p>
      <p><input className="form-input" style={{ width: '100%' }} placeholder="服务商支持图片输入的模型名称" value={model} onChange={e => setModel(e.target.value)} /></p>
      <button className="btn btn-secondary" onClick={saveKey}>保存并设为当前模型</button>
      {keys.map((k, i) => <p key={i}>{k.name} ｜ {k.model} ｜ {k.key}</p>)}
      <p><img src="/api/experiment/sample.png" style={{ width: '100%', maxWidth: 700 }} alt="本地电路试题" /></p>
      <p>选项 A=1A，B=2A，C=3A，D=6A。数值只在图中；正确答案 B。测试使用实际课堂相同的取图、AI 请求和严格解析流程，始终不提交。</p>
      <button className="btn btn-primary" disabled={busy} onClick={visionTest}>{busy ? '测试中…' : '调用模型验证图片试答'}</button>
    </section>
    {message && <pre style={{ whiteSpace: 'pre-wrap', padding: 16, background: '#edf2f7', color: '#1a202c' }}>{message}</pre>}
    <h2>最近事件（自动刷新）</h2>
    <p>accepted 表示服务器接受；valid 仅表示 AI 答案格式有效；sent 仅表示已发请求；unknown 需要人工核对，程序不会盲目重发。</p>
    <div style={{ maxHeight: 550, overflow: 'auto' }}>{events.slice().reverse().map((event, i) => <pre key={i} style={{ whiteSpace: 'pre-wrap', borderBottom: '1px solid #ccc', padding: 10 }}>{JSON.stringify(event, null, 2)}</pre>)}</div>
  </div>
}
