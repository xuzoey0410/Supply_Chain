"""Run: streamlit run 'Supply Chain/Agent_App.py'."""
import hashlib
import json
import os
import uuid
from pathlib import Path
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
import planning_core as core
from file_inputs import read_attachment, suggested_role, SHEETS
from planning_service import PlanningSession
from conversation_agent import run_turn, RunFailed, Budget
from storage import LocalStore
from api_client import APITransport, RemotePlanningSession
from api_config import service_token
from app_runtime import AppSettings, visitor_store_path, claim_host_run
from demo_data import demo_workbook, run_demo
from presentation import theme, hero, intro, comparison_chart, assessment_view, result_view, trace_view, architecture_view, footer, executive_snapshot


load_dotenv(Path(__file__).parent / '.env')
load_dotenv(Path(__file__).parent.parent / '.env')
st.set_page_config(page_title='Supply Studio · 智能供应链决策工作台', page_icon='◈', layout='wide')
try:
    server_secrets=dict(st.secrets)
except FileNotFoundError:
    server_secrets={}
settings=AppSettings.load(server_secrets)
public=settings.mode=='public'
api_url=str(server_secrets.get('SUPPLY_API_URL',os.getenv('SUPPLY_API_URL',''))).strip()
remote=bool(api_url)
transport=None
if remote:
    public=True
    supplied=str(server_secrets.get('SUPPLY_API_SERVICE_TOKEN',os.getenv('SUPPLY_API_SERVICE_TOKEN',''))).strip()
    transport=APITransport(api_url,supplied or service_token())
if 'visitor_id' not in st.session_state:st.session_state.visitor_id=uuid.uuid4().hex
state_root=Path(__file__).parent/'.local'
local_store=None if remote else LocalStore(visitor_store_path(state_root,settings.mode,st.session_state.visitor_id))
theme();hero(public)
with st.sidebar:
    st.markdown('## ◈ Supply Studio')
    st.caption('SUPPLY CHAIN DECISION WORKSPACE')
    st.divider()
    st.markdown('**你的分析工作区**')
    st.caption('API 后端 · 独立工作区' if remote else ('公开演示 · 本浏览器会话隔离' if public else '本机个人工作区 · 支持历史恢复'))
    with st.expander('模型连接设置', expanded=False):
        visitor_key=st.text_input('OpenAI API Key',type='password',value='',help='可填写自己的密钥；不会保存到分析记录。',key='visitor_api_key')
        access_code=st.text_input('演示访问码',type='password',value='') if remote or (public and settings.access_code) else ''
        key,host_funded=(visitor_key,False) if remote else settings.resolve_key(visitor_key,access_code)
        model=settings.model if (public or remote) else st.text_input('模型（需支持图片与工具调用）',value=settings.model)
        if key:st.caption('模型已连接 · '+('演示额度' if host_funded and public else '后台凭据' if host_funded else '自备密钥'))
        else:st.caption('由 API 后端校验模型连接与演示访问码' if remote else '未连接模型 · 仍可体验全部模拟和图表')
        st.caption('发送对话时，文件文字、表格预览、工具结果和图片会发送给模型服务。')
    st.subheader('数据来源')
    if remote:st.caption('资料会复制到所配置的计划后端；发送对话时再由后端调用模型。')
    default=st.checkbox('使用虚构演示数据',value=True)
    uploads=st.file_uploader('导入计划表或参考资料',type=['xlsx','xls','csv','tsv','json','txt','md','pdf','docx','png','jpg','jpeg','webp'],accept_multiple_files=True)
    st.caption('最多6个附件、总计30 MB；单个文件20 MB。扫描PDF请转换为图片。')
    st.download_button('下载演示数据模板',demo_workbook(),file_name='supply_demo.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if public:
        st.caption('刷新后若浏览器重建会话，将创建新工作区。关闭网页不会立即删除服务器临时文件。')
        if st.button('删除本次会话数据'):
            import shutil
            if remote:
                previous=st.session_state.get('planning_session')
                if isinstance(previous,RemotePlanningSession):
                    try:previous.delete()
                    except Exception as exc:st.error(str(exc));st.stop()
            else:shutil.rmtree(local_store.path.parent)
            st.session_state.clear()
            st.rerun()

sources=[]
if default:sources.append(('Supply_Demo.xlsx',demo_workbook()))
uploads=uploads or []
if len(uploads)>6 or sum(u.size for u in uploads)>30*1024*1024:
    st.error('请将附件限制为6个以内、总计30 MB以内。');st.stop()
sources.extend((u.name,u.getvalue()) for u in uploads)
fingerprint=hashlib.sha256(settings.mode.encode()+(api_url+st.session_state.visitor_id if remote else str(local_store.path)).encode()+b''.join(n.encode()+hashlib.sha256(b).digest() for n,b in sources)).hexdigest()
if st.session_state.get('source_hash') != fingerprint:
    attachments=[];errors=[]
    for name,data in sources:
        try: attachments.append(read_attachment(name,data))
        except Exception as exc: errors.append(f'{name}: {exc}')
    st.session_state.update(source_hash=fingerprint,attachments=attachments,import_errors=errors,
                            history=[],chat=[],trace=[],planning_session=None,mapping_hash=None)
for error in st.session_state.import_errors: st.error(error)
attachments=st.session_state.attachments
if st.session_state.planning_session is not None and not hasattr(st.session_state.planning_session,'current_spec'):
    st.session_state.planning_session=None

overview_tab,input_tab,chat_tab,result_tab,engineering_tab=st.tabs(['工作台','数据接入','对话设计','方案对比','工程说明'])
with input_tab:
    st.info('标准Excel会自动匹配表名；其他表格请选择业务用途并核对列名。参考资料不直接参与计划计算。')
    st.caption('需求单位为芯片，投片为晶圆，reach单位为周。空库存表或未列出的产品库存按0处理。产品级reach优先于全局参数。')
    tables={};mapping=[];wspw=core.empty_wspw_wafer_start_table();conflicts=[];wspw_seen=False
    options=['context',*SHEETS,'wspw']
    labels={'context':'仅作参考资料','flow':'工艺参数','product':'产品参数','demand':'月度需求','inventory':'初始库存','target':'全局目标','wspw':'WSPW投片（原始表布局）'}
    for ai,a in enumerate(attachments):
        with st.expander('📄 '+a.name,expanded=False):
            for warning in a.warnings: st.warning(warning)
            if a.text: st.text(a.text[:4000])
            if a.image_url: st.image(a.image_url)
            for ti,(sheet,df) in enumerate(a.tables.items()):
                st.write(sheet)
                suggestion=suggested_role(sheet)
                role=st.selectbox('表格用途',options,index=options.index(suggestion),format_func=lambda x,labels=labels:labels[x],key=f'role_{fingerprint}_{ai}_{ti}')
                raw_headers=list(map(str,df.columns))
                with st.expander('调整列名'):
                    header_map=st.data_editor(pd.DataFrame({'原列名':raw_headers,'计划字段':raw_headers}),disabled=['原列名'],hide_index=True,width='stretch',key=f'headers_{fingerprint}_{ai}_{ti}')
                headers=json.dumps(header_map['计划字段'].tolist(),ensure_ascii=False)
                try:
                    renamed=json.loads(headers)
                    if not isinstance(renamed,list) or len(renamed)!=len(raw_headers) or any(not isinstance(c,str) or not c.strip() for c in renamed) or len(set(renamed))!=len(renamed):
                        raise ValueError('列名必须是同长度、不重复的非空字符串数组')
                    data=df.copy();data.columns=renamed
                    st.dataframe(data.head(30).astype(str),width='stretch')
                    mapping.append((a.fingerprint,sheet,role,headers))
                    if role in SHEETS:
                        if role in tables: conflicts.append(labels[role])
                        tables[role]=data
                    elif role=='wspw':
                        if wspw_seen: conflicts.append('WSPW表重复')
                        wspw_seen=True
                        wspw=core.parse_wspw_wafer_start(a.raw_tables.get(sheet,data))
                        if wspw.empty: conflicts.append('WSPW原始布局无法识别，请核对表格')
                except Exception as exc:
                    conflicts.append(f'{a.name}/{sheet}: {exc}')
    digest=hashlib.sha256(json.dumps(mapping,ensure_ascii=False).encode()).hexdigest()
    if digest!=st.session_state.mapping_hash:
        st.session_state.update(mapping_hash=digest,planning_session=None,history=[],chat=[],trace=[])
    if conflicts:
        st.error('映射冲突，请将多余的表设为参考资料或关闭示例：'+'；'.join(conflicts))
        st.session_state.planning_session=None
    elif public and (len(tables.get('product',[]))>30 or
                     ('demand' in tables and len(core.demand_month_columns(tables['demand']))>12)):
        st.error('公开演示最多支持30个产品、12个月需求。更大数据请在本地运行。')
        st.session_state.planning_session=None
    elif st.session_state.planning_session is None:
        try:
            if remote:
                created=RemotePlanningSession.create(transport,tables,wspw)
                try:created.references(sources[1:] if default else sources)
                except Exception:
                    created.delete();raise
                st.session_state.planning_session=created
            else:st.session_state.planning_session=PlanningSession(tables,wspw,store=local_store)
        except Exception as exc: st.warning(f'尚不能计算：{exc}。可先通过对话澄清方案和资料。')
    session=st.session_state.planning_session
    if session:
        if remote:local_store=session.store
        st.success('计划数据校验通过，可计算方案。'+(' · 由 FastAPI 后端执行' if remote else ''))
        with st.expander('恢复已保存的分析'):
            saved=[w for w in local_store.workspaces(session.dataset_id) if w['id']!=session.workspace_id]
            st.caption('方案、对话和任务进度保存在当前工作区。仅显示本工作区内、与当前数据一致的分析；参考附件需重新上传。')
            if saved:
                choice=st.selectbox('选择历史分析',saved,format_func=lambda w:f"{w['id'][:8]} · {w['scenario_count']}个方案 · {w['updated']}")
                if st.button('恢复分析'):
                    restored=PlanningSession.restore(local_store,choice['id'],session.dataset_id)
                    conversation=local_store.conversation(restored.workspace_id)
                    st.session_state.update(planning_session=restored,history=conversation['history'],chat=conversation['chat'],trace=[])
                    st.rerun()
            else:st.caption('尚无其他已保存的分析。')
        st.subheader('快速模拟')
        st.caption('只改某项时可以继承当前方案；也可选择从最初输入开始。')
        base=st.selectbox('方案基准',['current','baseline',*session.scenarios],key='quick_base_'+session.workspace_id,format_func=lambda x:'当前方案（继承全部假设）' if x=='current' else ('最初输入' if x=='baseline' else f"{session.scenarios[x]['scenario_name']} [{x}]"))
        base_spec=session.current_spec.to_dict() if base=='current' else ({'config':session.baseline_config,'demand_multiplier':1.0} if base=='baseline' else session.scenarios[base]['spec'])
        prefix=hashlib.sha256(json.dumps({'base':base,'spec':base_spec},sort_keys=True).encode()).hexdigest()[:12]
        with st.form('quick_scenario'):
            name=st.text_input('方案名称',value='新方案')
            c1,c2,c3,c4=st.columns(4)
            tester=c1.number_input('Tester 数量',min_value=1.0,max_value=10000.0,value=float(base_spec['config']['tester_number']),step=1.0,key='quick_tester_'+prefix)
            minimum=c2.number_input('最低 Reach（周）',min_value=0.0,max_value=52.0,value=float(base_spec['config']['min_reach']),step=0.5,key='quick_minimum_'+prefix)
            target=c3.number_input('目标 Reach（周）',min_value=0.0,max_value=52.0,value=float(base_spec['config']['target_reach']),step=0.5,key='quick_target_'+prefix)
            multiplier=c4.number_input('需求倍数',min_value=0.0,max_value=100.0,value=float(base_spec['demand_multiplier']),step=0.1,key='quick_multiplier_'+prefix)
            fill=st.radio('产能分配方式',['Even Load','Capacity First'],index=0 if base_spec['config']['tester_fill_mode']=='Even Load' else 1,key='quick_fill_'+prefix,format_func=lambda x:'均匀分配' if x=='Even Load' else '优先填满最近产能',horizontal=True)
            reset_products=st.checkbox('清空继承的产品级修改',value=False)
            all_products=st.checkbox('将本次 Reach 设置应用到所有产品',value=False)
            st.caption('未勾选时，各产品已有的 Reach 目标优先于全局设置。')
            submitted=st.form_submit_button('运行模拟',type='primary',width='stretch')
        if submitted:
            try:
                overrides=[]
                if all_products:
                    for product in session.inspect()['products'].values():
                        overrides.extend([{'product':product['Product'],'field':'Min Reach Level','value':minimum},
                                          {'product':product['Product'],'field':'Target Reach Level','value':target}])
                with st.spinner('正在平衡需求、库存和产能…'):
                    evidence=session.run(name,{'tester_number':tester,'min_reach':minimum,'target_reach':target,'tester_fill_mode':fill},multiplier,overrides,base_scenario_id=None if base=='current' else base,reset_product_overrides=reset_products)
                st.success('方案已完成：'+evidence['evidence_id']+'。打开「方案对比」查看。')
            except Exception as exc: st.error(f'计划失败：{exc}')

with chat_tab:
    st.subheader('你的计划设计助手')
    st.caption('描述目标和约束，助手会读取资料、计算方案并解释取舍。')
    prompt_cols=st.columns(3)
    suggestions=['以最初输入为基准，比较8台和6台tester，其他条件相同','把所有产品最低reach改为2、目标改为4，重新计算','需求增加20%，分析产能和reach缺口']
    selected_prompt=None
    for col,prompt in zip(prompt_cols,suggestions):
        if col.button(prompt,width='stretch'): selected_prompt=prompt
    if not st.session_state.chat:
        st.info('从上方选择一个问题，或在下面输入你的设计方案。')
    if st.button('清空对话'):
        st.session_state.update(history=[],chat=[],trace=[])
        if st.session_state.planning_session:
            local_store.save_conversation(st.session_state.planning_session.workspace_id,[],[])
    for message in st.session_state.chat:
        with st.chat_message(message['role']): st.markdown(message['content'])
    session=st.session_state.planning_session
    failed=[];resume_id=None
    if session:
        failed=[r for r in local_store.runs(session.workspace_id) if r['status'] in ('failed','running')]
        if failed:
            with st.expander('有未完成任务，可继续运行',expanded=True):
                failed_choice=st.selectbox('未完成任务',failed,format_func=lambda r:r['question'][:60]+' · '+r['status'])
                if st.button('继续此任务'):resume_id=failed_choice['id']
    question=st.chat_input('例如：减少两台 tester，哪些产品的库存覆盖会受到影响？') or selected_prompt
    if resume_id:question=local_store.run(resume_id)['question']
    if question:
        if remote and not session:st.error('API 模式请先完成计划表映射，创建工作区。')
        elif not remote and not key:st.error('请先填写API Key；也可以在输入页运行本地模拟。')
        else:
            from openai import OpenAI
            with st.chat_message('user'):st.markdown(question)
            progress_box=st.status('准备任务…',expanded=True)
            stage_labels={'prepare':'读取资料与当前方案','reason':'分析问题与设计方案','tools':'执行业务工具','validate':'核对证据与指标','finish':'完成回答'}
            def show_progress(event):
                label=stage_labels.get(event['node'],'任务状态')
                progress_box.update(label=label)
                if event.get('status') in ('complete','passed','fallback','failed','retry'):
                    progress_box.write(label+' · '+event['status'])
            try:
                if not remote and public and host_funded:
                    claim_host_run(state_root/'host_quota.sqlite',st.session_state.visitor_id,settings.hourly_runs)
                if remote:
                    out=session.chat(question,visitor_key,access_code,resume_id,show_progress)
                else:
                    out=run_turn(OpenAI(api_key=key,timeout=60,max_retries=0),model,session,
                                 question,st.session_state.history,attachments,store=local_store,
                                 resume_run_id=resume_id,progress=show_progress,
                                 budget=Budget(max_rounds=5,max_tools=6,max_tokens=24000,context_chars=16000,history_turns=4) if public else None)
                st.session_state.history=out['history']
                if not any(m.get('run_id')==out['run_id'] for m in st.session_state.chat):
                    st.session_state.chat.extend([{'role':'user','content':question,'run_id':out['run_id']},
                                                 {'role':'assistant','content':out['answer'],'run_id':out['run_id']}])
                st.session_state.trace.extend(out['trace'])
                if session:local_store.save_conversation(session.workspace_id,out['history'],st.session_state.chat)
                progress_box.update(label='任务完成',state='complete',expanded=False)
                if not out['validation']['passed']:st.warning('模型回答未通过校验，已显示工具结果。')
                with st.chat_message('assistant'):st.markdown(out['answer'])
            except RunFailed as exc:
                progress_box.update(label='任务暂停，进度已保存',state='error')
                st.error(str(exc))
                st.info('本轮已完成的方案仍可查看。刷新任务列表后可继续此任务。')
                if st.button('刷新任务列表'):st.rerun()
            except Exception as exc:
                progress_box.update(label='任务未启动',state='error')
                st.error(str(exc))
    with st.expander('运行记录与校验'):
        if session:
            runs=local_store.runs(session.workspace_id)
            if runs:
                selected_run=st.selectbox('查看任务',runs,format_func=lambda r:r['question'][:50]+' · '+r['status'],key='trace_run')
                trace_view(local_store.events(selected_run['id']))
            else:st.caption('完成一次对话后可以查看步骤、耗时、token和校验记录。')
        else:st.json(st.session_state.trace)

with overview_tab:
    session=st.session_state.planning_session
    intro(session)
    st.markdown('### 三十秒体验完整决策流程')
    st.caption('基准产能、减少25%产能、增加20%需求。三个方案均从最初输入开始，使用确定性计算，不调用模型。')
    if st.button('一键生成演示方案',type='primary',disabled=session is None):
        try:
            with st.spinner('正在计算三个独立情景…'):
                st.session_state.demo_ids=session.run_demo() if remote else run_demo(session)
            st.rerun()
        except Exception as exc:st.error(f'演示计算失败：{exc}')
    if session and session.scenarios:
        st.markdown('### 当前方案快照')
        ids=list(session.scenarios)[-3:]
        executive_snapshot(session,ids)
        assessment_view(session,ids)
        st.plotly_chart(comparison_chart(session,ids),width='stretch',key='overview_capacity')
        st.caption('到「方案对比」查看产品缺口、完整假设与下载；到「对话设计」进一步修改情景。')
    else:
        st.info('不需要 API Key：先运行演示方案，再去「方案对比」查看指标与计划明细。自然语言对话需要连接模型。')
with result_tab:
    result_view(st.session_state.planning_session)
    session=st.session_state.planning_session
    if session and session.scenarios and st.button('清空方案与对话'):
        session.clear_scenarios();local_store.save_conversation(session.workspace_id,[],[])
        st.session_state.update(history=[],chat=[],trace=[]);st.rerun()
with engineering_tab:architecture_view()
footer()
