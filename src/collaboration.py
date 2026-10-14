from datetime import datetime, timezone
from uuid import uuid4
import sqlite3, hashlib, secrets, os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from src.auth import get_accounts

FEATURES = {'question_optimize','answer_evaluate','presentation_questions'}
router = APIRouter(prefix='/api/collaboration', tags=['collaboration'])
def now(): return datetime.now(timezone.utc).isoformat()
def expire(c, round_id):
    row=c.execute('SELECT created_at,state FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()
    if not row or row['state']!='open': return row
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds()
    if age > int(os.getenv('COLLABORATION_TIMEOUT_SECONDS','900')):
        t=now(); c.execute("UPDATE collaboration_rounds SET state='expired',updated_at=? WHERE round_id=? AND state='open'",(t,round_id)); c.execute("UPDATE collaboration_claims SET state='released',updated_at=? WHERE round_id=? AND state IN ('pending','accepted')",(t,round_id)); c.commit(); return {'state':'expired'}
    return row
def con(request):
    c=sqlite3.connect(get_accounts(request).db_path); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def teacher(request, class_id, session_id):
    c=con(request); r=c.execute('SELECT s.session_id,s.status,c.course_id,c.class_id FROM classroom_sessions s JOIN classes c ON c.class_id=s.class_id WHERE s.session_id=? AND c.class_id=?',(session_id,class_id)).fetchone(); c.close()
    if not r or not get_accounts(request).owns(request.state.account['account_id'],r['course_id']): raise HTTPException(404,'班级或课堂不存在。')
    if r['status']!='active': raise HTTPException(409,'课堂已结束。')
    return r
class RoundIn(BaseModel): class_id:str; session_id:str; feature_type:str; question_snapshot:str|None=None
class ClaimIn(BaseModel): round_id:str
class EntryIn(BaseModel): text:str=''; answer:str=''
@router.post('/rounds')
def create_round(p:RoundIn, request:Request):
    if p.feature_type not in FEATURES: raise HTTPException(400,'协作功能类型无效。')
    snapshot=(p.question_snapshot or '').strip()
    r=teacher(request,p.class_id,p.session_id); c=con(request); rid=str(uuid4()); t=now()
    try:
        token=secrets.token_urlsafe(24)
        with c: c.execute('INSERT INTO collaboration_rounds VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,r['course_id'],p.class_id,p.session_id,p.feature_type,'open',hashlib.sha256(token.encode()).hexdigest(),snapshot or None,t,t))
    finally:c.close()
    return {'question_snapshot':snapshot,'round_id':rid,'round_token':token,'course_id':r['course_id'],'class_id':p.class_id,'session_id':p.session_id,'feature_type':p.feature_type,'state':'open'}
@router.post('/rounds/{round_id}/claim')
def claim(round_id:str,p:ClaimIn,request:Request):
    token=request.headers.get('X-Student-Session',''); c=con(request); row=c.execute("SELECT r.*,cs.session_student_id,cs.status AS student_status FROM collaboration_rounds r JOIN classroom_students cs ON cs.session_id=r.session_id WHERE r.round_id=? AND cs.student_token_hash=?",(round_id,__import__('hashlib').sha256(token.encode()).hexdigest())).fetchone()
    if not row: c.close(); raise HTTPException(403,'学生会话与协作课堂不匹配。')
    if row['student_status']!='confirmed': c.close(); raise HTTPException(403,'学生尚未被教师确认。')
    expired=expire(c, round_id)
    if expired and expired['state']!='open': c.close(); raise HTTPException(409,'协作轮次已关闭或已过期。')
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            active=c.execute("SELECT 1 FROM collaboration_claims WHERE round_id=? AND state IN ('pending','accepted')",(round_id,)).fetchone()
            if active: raise HTTPException(409,'当前功能已有学生申请或占用。')
            cid=str(uuid4()); t=now(); c.execute('INSERT INTO collaboration_claims VALUES (?,?,?,?,?,?)',(cid,round_id,row['session_student_id'],'pending',t,t))
    finally:c.close()
    return {'claim_id':cid,'state':'pending'}
@router.get('/rounds/{round_id}/student-state')
def student_state(round_id:str, request:Request):
    token=request.headers.get('X-Student-Session',''); c=con(request)
    row=c.execute("SELECT r.state AS round_state,r.feature_type,r.question_snapshot,cc.claim_id,cc.state AS claim_state,e.original_text,e.answer_text FROM collaboration_rounds r JOIN classroom_students cs ON cs.session_id=r.session_id LEFT JOIN collaboration_claims cc ON cc.round_id=r.round_id AND cc.session_student_id=cs.session_student_id LEFT JOIN collaboration_entries e ON e.claim_id=cc.claim_id WHERE r.round_id=? AND cs.student_token_hash=? ORDER BY cc.requested_at DESC,e.updated_at DESC LIMIT 1",(round_id,hashlib.sha256(token.encode()).hexdigest())).fetchone()
    if not row: c.close(); raise HTTPException(403,'学生会话与协作轮次不匹配。')
    expire(c,round_id)
    row=c.execute("SELECT r.state AS round_state,r.feature_type,r.question_snapshot,cc.claim_id,cc.state AS claim_state,e.original_text,e.answer_text FROM collaboration_rounds r JOIN classroom_students cs ON cs.session_id=r.session_id LEFT JOIN collaboration_claims cc ON cc.round_id=r.round_id AND cc.session_student_id=cs.session_student_id LEFT JOIN collaboration_entries e ON e.claim_id=cc.claim_id WHERE r.round_id=? AND cs.student_token_hash=? ORDER BY cc.requested_at DESC,e.updated_at DESC LIMIT 1",(round_id,hashlib.sha256(token.encode()).hexdigest())).fetchone()
    c.close(); return dict(row)
@router.post('/claims/{claim_id}/complete')
def complete_claim(claim_id:str, request:Request):
    token=request.headers.get('X-Student-Session',''); c=con(request)
    row=c.execute("SELECT cc.*,r.class_id,r.session_id FROM collaboration_claims cc JOIN collaboration_rounds r ON r.round_id=cc.round_id JOIN classroom_students cs ON cs.session_student_id=cc.session_student_id WHERE cc.claim_id=? AND cs.student_token_hash=?",(claim_id,hashlib.sha256(token.encode()).hexdigest())).fetchone()
    if not row: c.close(); raise HTTPException(403,'无权完成该协作申请。')
    expire(c,row['round_id']); cur=c.execute("UPDATE collaboration_claims SET state='completed',updated_at=? WHERE claim_id=? AND state='accepted'",(now(),claim_id));
    if cur.rowcount!=1: c.close(); raise HTTPException(409,'协作申请未被接受或已结束。')
    c.commit(); c.close(); return {'claim_id':claim_id,'state':'completed'}
@router.patch('/claims/{claim_id}/entry')
def save_entry(claim_id:str,p:EntryIn,request:Request):
    token=request.headers.get('X-Student-Session',''); c=con(request)
    row=c.execute("SELECT cc.*,r.state AS round_state,r.feature_type,r.round_id,r.question_snapshot FROM collaboration_claims cc JOIN collaboration_rounds r ON r.round_id=cc.round_id JOIN classroom_students cs ON cs.session_student_id=cc.session_student_id WHERE cc.claim_id=? AND cs.student_token_hash=?",(claim_id,hashlib.sha256(token.encode()).hexdigest())).fetchone()
    if not row: c.close(); raise HTTPException(403,'无权同步该协作内容。')
    current=expire(c,row['round_id'])
    if current['state']!='open' or row['state']!='accepted': c.close(); raise HTTPException(409,'协作申请未处于可编辑状态。')
    question_text=row['question_snapshot'] if row['feature_type']=='answer_evaluate' else p.text
    if row['feature_type']=='answer_evaluate' and not question_text: c.close(); raise HTTPException(409,'答案评价题目快照为空。')
    t=now(); eid=str(uuid4()); c.execute("INSERT INTO collaboration_entries(entry_id,round_id,claim_id,student_id,original_text,final_text,answer_text,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(round_id,claim_id) DO UPDATE SET original_text=excluded.original_text,final_text=excluded.final_text,answer_text=excluded.answer_text,updated_at=excluded.updated_at",(eid,row['round_id'],claim_id,None,question_text,question_text,p.answer,t,t)); c.commit(); c.close(); return {'claim_id':claim_id,'text':question_text,'answer':p.answer,'updated_at':t}
@router.get('/rounds/{round_id}/entry')
def get_entry(round_id:str,request:Request):
    c=con(request); r=c.execute('SELECT class_id,session_id,state,feature_type FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作轮次不存在。')
    teacher(request,r['class_id'],r['session_id']); expire(c,round_id); r=c.execute('SELECT state,feature_type FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone(); row=c.execute('SELECT e.*,cs.requested_name,st.name FROM collaboration_entries e JOIN collaboration_claims cc ON cc.claim_id=e.claim_id JOIN classroom_students cs ON cs.session_student_id=cc.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE e.round_id=? ORDER BY e.updated_at DESC LIMIT 1',(round_id,)).fetchone(); c.close(); return {**(dict(row) if row else {'round_id':round_id,'text':'','answer':''}),'round_state':r['state'],'feature_type':r['feature_type']}
@router.patch('/rounds/{round_id}/teacher-entry')
def teacher_entry(round_id:str,p:EntryIn,request:Request):
    c=con(request); r=c.execute('SELECT class_id,session_id FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作轮次不存在。')
    teacher(request,r['class_id'],r['session_id']); row=c.execute('SELECT e.entry_id,r.feature_type,r.question_snapshot FROM collaboration_entries e JOIN collaboration_rounds r ON r.round_id=e.round_id WHERE e.round_id=? ORDER BY e.updated_at DESC LIMIT 1',(round_id,)).fetchone()
    if not row: c.close(); raise HTTPException(409,'当前没有学生协作内容。')
    final_text=row['question_snapshot'] if row['feature_type']=='answer_evaluate' else p.text
    c.execute('UPDATE collaboration_entries SET final_text=?,answer_text=?,updated_at=? WHERE entry_id=?',(final_text,p.answer,now(),row['entry_id'])); c.commit(); c.close(); return {'round_id':round_id,'text':final_text,'answer':p.answer}
@router.post('/rounds/{round_id}/submit')
def submit_round(round_id:str,request:Request):
    c=con(request); r=c.execute('SELECT * FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone(); e=c.execute('SELECT e.*,cc.session_student_id,cc.state AS claim_state,cs.student_id AS bound_student_id FROM collaboration_entries e JOIN collaboration_claims cc ON cc.claim_id=e.claim_id JOIN classroom_students cs ON cs.session_student_id=cc.session_student_id WHERE e.round_id=? ORDER BY e.updated_at DESC LIMIT 1',(round_id,)).fetchone()
    if not r or not e: c.close(); raise HTTPException(404,'协作内容不存在。')
    teacher(request,r['class_id'],r['session_id']); current=expire(c,round_id); c.close()
    if current['state'] != 'open' or e['claim_state'] in ('released','rejected','cancelled'): raise HTTPException(409,'协作轮次或申请已关闭。')
    from src.course_data import CourseStore
    from src import web_api
    store=CourseStore(get_accounts(request).db_path); runtime=web_api._get_course_runtime(r['course_id'],store)
    text=e['final_text'] or e['original_text']; answer=e['answer_text']
    try:
        if r['feature_type']=='question_optimize':
            result=runtime.service.question_optimize(text,runtime.settings.default_top_k); payload=web_api.QuestionOptimizeResponse.model_validate(runtime.source_mapper.sanitize_value(web_api._add_optimized_question_levels(result.data))).model_dump(); task='question_optimize'; inp={'question':text}
        elif r['feature_type']=='answer_evaluate':
            question_text=r['question_snapshot']
            if not question_text: raise HTTPException(409,'题目快照为空。')
            result=runtime.service.answer_evaluate(question_text,answer,runtime.settings.default_top_k); payload=web_api.AnswerEvaluateResponse.model_validate(runtime.source_mapper.sanitize_value(result.data)).model_dump(); task='answer_evaluate'; inp={'question':question_text,'student_answer':answer}
        else: raise HTTPException(400,'该轮次需要使用材料提问接口。')
    except HTTPException: raise
    except Exception as error: raise web_api._safe_service_error(error) from None
    from src.teaching_history import get_history_store
    get_history_store(store).add(course_id=r['course_id'],task_type=task,student_id=e['bound_student_id'],class_id=r['class_id'],session_id=r['session_id'],round_id=round_id,input_data=inp,output_data=payload)
    c=con(request)
    c.execute("UPDATE collaboration_claims SET state='completed',updated_at=? WHERE claim_id=? AND state='accepted'",(now(),e['claim_id']))
    c.commit(); c.close()
    return payload
@router.post('/tokens/{round_token}/claim')
def claim_token(round_token:str, request:Request):
    c=con(request); row=c.execute('SELECT round_id FROM collaboration_rounds WHERE round_token_hash=?',(hashlib.sha256(round_token.encode()).hexdigest(),)).fetchone(); c.close()
    if not row: raise HTTPException(403,'协作二维码无效或已过期。')
    return claim(row['round_id'], ClaimIn(round_id=row['round_id']), request)
@router.get('/rounds/{round_id}/claims')
def claims(round_id:str,request:Request):
    c=con(request); r=c.execute('SELECT class_id,session_id FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作轮次不存在。')
    teacher(request,r['class_id'],r['session_id']); expire(c,round_id)
    state=c.execute('SELECT state FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()['state']
    rows=c.execute('SELECT cc.claim_id,cc.state,cc.requested_at,cc.session_student_id,cs.requested_name,st.name FROM collaboration_claims cc JOIN classroom_students cs ON cs.session_student_id=cc.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE cc.round_id=? ORDER BY cc.requested_at',(round_id,)).fetchall(); c.close()
    return [{**dict(x),'round_state':state} for x in rows]
def set_claim(claim_id, state, request):
    c=con(request); r=c.execute('SELECT cc.*,cr.class_id,cr.session_id FROM collaboration_claims cc JOIN collaboration_rounds cr ON cr.round_id=cc.round_id WHERE cc.claim_id=?',(claim_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作申请不存在。')
    teacher(request,r['class_id'],r['session_id']); current=expire(c,r['round_id'])
    if current['state']!='open': c.close(); raise HTTPException(409,'轮次已关闭。')
    c.execute('UPDATE collaboration_claims SET state=?,updated_at=? WHERE claim_id=? AND state IN (\'pending\',\'accepted\')',(state,now(),claim_id));
    if c.total_changes != 1: c.close(); raise HTTPException(409,'协作申请已处理或已释放。')
    c.commit(); c.close(); return {'claim_id':claim_id,'state':state}
@router.post('/claims/{claim_id}/accept')
def accept(claim_id,request:Request): return set_claim(claim_id,'accepted',request)
@router.post('/claims/{claim_id}/reject')
def reject(claim_id,request:Request): return set_claim(claim_id,'rejected',request)
@router.post('/claims/{claim_id}/release')
def release(claim_id,request:Request): return set_claim(claim_id,'released',request)
@router.post('/claims/{claim_id}/return')
def return_for_edit(claim_id,request:Request):
    """让教师把已完成的学生内容退回编辑，保留原草稿和历史上下文。"""
    c=con(request); r=c.execute('SELECT cc.*,cr.class_id,cr.session_id,cr.state AS round_state FROM collaboration_claims cc JOIN collaboration_rounds cr ON cr.round_id=cc.round_id WHERE cc.claim_id=?',(claim_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作申请不存在。')
    teacher(request,r['class_id'],r['session_id'])
    if expire(c,r['round_id'])['state']!='open': c.close(); raise HTTPException(409,'轮次已关闭。')
    cur=c.execute("UPDATE collaboration_claims SET state='accepted',updated_at=? WHERE claim_id=? AND state='completed'",(now(),claim_id))
    if cur.rowcount != 1: c.close(); raise HTTPException(409,'仅已完成的协作内容可以退回编辑。')
    c.commit(); c.close(); return {'claim_id':claim_id,'state':'accepted'}
@router.post('/claims/{claim_id}/cancel')
def cancel_claim(claim_id,request:Request):
    c=con(request); r=c.execute('SELECT cc.*,cr.class_id,cr.session_id FROM collaboration_claims cc JOIN collaboration_rounds cr ON cr.round_id=cc.round_id WHERE cc.claim_id=?',(claim_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作申请不存在。')
    teacher(request,r['class_id'],r['session_id'])
    cur=c.execute("UPDATE collaboration_claims SET state='released',updated_at=? WHERE claim_id=? AND state IN ('pending','accepted','completed')",(now(),claim_id))
    if cur.rowcount != 1: c.close(); raise HTTPException(409,'协作申请已取消。')
    c.commit(); c.close(); return {'claim_id':claim_id,'state':'released'}
@router.post('/rounds/{round_id}/cancel')
def cancel_round(round_id:str,request:Request):
    c=con(request); r=c.execute('SELECT class_id,session_id FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作轮次不存在。')
    teacher(request,r['class_id'],r['session_id']); t=now()
    cur=c.execute("UPDATE collaboration_rounds SET state='cancelled',updated_at=? WHERE round_id=? AND state='open'",(t,round_id))
    if cur.rowcount != 1: c.close(); raise HTTPException(409,'协作轮次已关闭。')
    c.execute("UPDATE collaboration_claims SET state='released',updated_at=? WHERE round_id=? AND state IN ('pending','accepted')",(t,round_id)); c.commit(); c.close(); return {'round_id':round_id,'state':'cancelled'}
@router.post('/rounds/{round_id}/complete')
def complete_round(round_id:str,request:Request):
    c=con(request); r=c.execute('SELECT class_id,session_id FROM collaboration_rounds WHERE round_id=?',(round_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'协作轮次不存在。')
    teacher(request,r['class_id'],r['session_id']); c.execute("UPDATE collaboration_rounds SET state='completed',updated_at=? WHERE round_id=? AND state='open'",(now(),round_id)); c.execute("UPDATE collaboration_claims SET state='completed',updated_at=? WHERE round_id=? AND state IN ('pending','accepted')",(now(),round_id)); c.commit(); c.close(); return {'round_id':round_id,'state':'completed'}
