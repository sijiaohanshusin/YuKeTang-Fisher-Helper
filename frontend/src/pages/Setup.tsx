import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, DEFAULT_RUNTIME, modeName, useConsoleData, type Runtime } from '../consoleApi'
import { CoursePicker, ModelPanel, ModeControl } from '../components/ConsoleControls'
import Login from './Login'

const STEPS = [ ['账号登录', '连接你的雨课堂主站账号'], ['模型连接', '配置密钥并验证图片输入'], ['选择课程', '限定需要自动处理的班级'], ['运行方式', '独立控制签到与答案提交'], ['完成确认', '保存后开始持续监听'] ]

export default function Setup({ onAuthChange }: { onAuthChange: () => void }) {
  const { health, courses, ai, loading, error, refresh } = useConsoleData()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [runtime, setRuntime] = useState<Runtime>(DEFAULT_RUNTIME)
  const [initialized, setInitialized] = useState(false)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [skipModel, setSkipModel] = useState(false)
  useEffect(() => {
    if (health && !initialized) { setRuntime(health.runtime); setInitialized(true) }
  }, [health, initialized])
  const modelReady = !!(ai.keys[ai.active_key] && health?.vision_validation?.correct && health.vision_validation.current_config)
  const next = () => { setMessage(''); setStep(value => Math.min(4, value + 1)) }
  const finish = async () => {
    setBusy(true)
    try {
      const value = skipModel && !modelReady ? { ...runtime, mode: 'observe', auto_signin: false, submit_answers: false } : runtime
      const result = await api<{ ok: boolean; error?: string }>('/api/runtime', value, 'PUT')
      if (!result.ok) throw new Error(result.error || '设置未保存')
      await api('/api/setup/complete', {})
      sessionStorage.removeItem('setup-snoozed')
      navigate('/experiment', { replace: true })
    } catch (e) { setMessage(e instanceof Error ? e.message : '配置尚未保存') }
    finally { setBusy(false) }
  }
  const later = () => { sessionStorage.setItem('setup-snoozed', 'true'); navigate('/experiment') }
  if (loading) return <div className="console-empty">正在读取本机配置…</div>
  return <div className="setup-page">
    <div className="console-eyebrow">开始使用 · 首次配置</div><div className="setup-heading"><div><h1>让课堂助手准备就绪</h1><p>按步骤完成连接，随后选择适合你的运行方式。</p></div><button className="console-button ghost" onClick={later}>稍后配置，先看运行台</button></div>
    <div className="setup-layout"><aside className="setup-steps" aria-label="配置进度">{STEPS.map(([title, text], index) => <button key={title} disabled={index > step} className={`setup-step ${index === step ? 'current' : ''} ${index < step ? 'complete' : ''}`} onClick={() => setStep(index)}><span>{index < step ? '✓' : index + 1}</span><div><strong>{title}</strong><small>{text}</small></div></button>)}<p className="setup-local-note">凭据保存在本机。新用户默认不会产生考勤或答案提交。</p></aside>
      <section className="console-panel setup-content"><div className="panel-heading"><span className="step-number">步骤 {step + 1} / 5</span><h2>{STEPS[step][0]}</h2><p>{STEPS[step][1]}</p></div>
        {error && <div className="console-notice error">{error}</div>}
        {step === 0 && <>{health?.login_verified ? <div className="connected-message"><span>✓</span><h3>账号已通过服务器验证</h3><p>已读取 {courses.length} 个已加入班级。微信登录二维码只用于账号登录，无需逐节上传课堂二维码。</p></div> : <><p className="panel-description">普通雨课堂请选择“雨课堂”。用微信扫描程序生成的二维码，账号信息校验成功后即可继续。</p><Login embedded onSuccess={() => { onAuthChange(); refresh() }} /></>}</>}
        {step === 1 && <><p className="panel-description">课程可能包含公式和题图，请使用支持图片输入的模型。保存密钥后，点击识图验证。</p><ModelPanel health={health} ai={ai} onChanged={refresh} notify={setMessage} />{modelReady && <div className="console-notice success">当前模型已通过图片输入验证，可以继续。</div>}<button className="text-button skip-model" onClick={() => { setSkipModel(true); setRuntime({ ...runtime, mode: 'observe', auto_signin: false, submit_answers: false }); next() }}>暂时跳过模型，先使用观察模式</button></>}
        {step === 2 && <><p className="panel-description">只有选中班级会在允许时自动进入。可以选择全部，也可以只选正在上课的班级。</p><CoursePicker courses={courses} selected={runtime.course_ids} onChange={ids => setRuntime({ ...runtime, course_ids: ids })} /><button className="text-button" onClick={async () => { await api('/api/courses/refresh', {}); refresh() }}>重新读取账号课程</button></>}
        {step === 3 && <>{!modelReady && <div className="console-notice">模型尚未通过验证。可以保存观察模式；准备自动作答时再完成模型配置。</div>}<ModeControl value={runtime} onChange={value => { setRuntime(value); if (value.mode !== 'observe') setSkipModel(false) }} /></>}
        {step === 4 && <><div className="setup-summary"><div><span>雨课堂服务器</span><strong>{health?.domain}</strong></div><div><span>课程范围</span><strong>{runtime.course_ids.length} 个班级</strong></div><div><span>模型</span><strong>{ai.keys[ai.active_key]?.model || '暂未配置'}</strong></div><div><span>运行方式</span><strong>{modeName(runtime.mode)}</strong></div><div><span>自动签到</span><strong>{runtime.auto_signin ? '开启 · 产生真实考勤' : '关闭'}</strong></div><div><span>自动提交</span><strong>{runtime.submit_answers ? '开启 · 提交有效 AI 答案' : '关闭'}</strong></div></div><div className="console-notice">保存后按这些设置持续运行。没有课程时等待，下课后继续发现下一节；失败或无效的 AI 答案始终跳过。</div></>}
        {message && <div className="console-notice" role="status">{message}</div>}
        <footer className="setup-footer"><button className="console-button secondary" disabled={step === 0 || busy} onClick={() => { setMessage(''); setStep(step - 1) }}>上一步</button><span>{STEPS[step][0]}</span>{step < 4 ? <button className="console-button" disabled={(step === 0 && !health?.login_verified) || (step === 1 && !modelReady) || (step === 2 && !runtime.course_ids.length) || (step === 3 && runtime.mode !== 'observe' && !modelReady)} onClick={next}>下一步 <span aria-hidden="true">→</span></button> : <button className="console-button" disabled={busy || (runtime.mode !== 'observe' && !modelReady)} onClick={finish}>{busy ? '正在保存…' : '保存并进入运行台'}</button>}</footer>
      </section></div>
  </div>
}
