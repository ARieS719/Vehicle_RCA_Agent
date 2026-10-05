# core/workflow_agents.py
import os
from dotenv import load_dotenv
from typing import TypedDict
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
import chromadb.config

# 加载环境变量
load_dotenv()

# ==========================================
# 1. 定义全局状态 (新增了 rag_context 字段)
# ==========================================
class RCAState(TypedDict):
    raw_logs: str          
    filtered_logs: str     
    decoded_clues: str 
    rag_context: str       # 【新增】Agent C 从向量库搜到的历史经验    

# ==========================================
# 2. 初始化大模型与向量模型 (接入硅基流动)
# ==========================================
llm = ChatOpenAI(
    model="deepseek-ai/DeepSeek-V3", 
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url=os.getenv("SILICONFLOW_BASE_URL"),
    max_tokens=2048,
    temperature=0.1 
)

# 【新增】初始化向量模型 (用于 RAG 将文本转为数字向量)
embeddings = OpenAIEmbeddings(
    model="BAAI/bge-m3", # 硅基流动支持的高级开源向量模型
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url=os.getenv("SILICONFLOW_BASE_URL")
)

# ==========================================
# 3. 工具与 Agent A, B
# ==========================================
@tool
def decode_can_protocol(can_id: str) -> str:
    """
    当发现未知的 CAN ID（例如 0x3F2 或 0x0C1 等）时，调用此工具查询该 ID 对应的真实物理含义。
    参数 can_id 必须是十六进制字符串。
    """
    print(f"   ⚙️ [系统日志] 工具调用: 查询 CAN 字典 -> {can_id}")
    dbc_mock_db = {
        "0X3F2": "车门控制模块(BCM) - 远程解锁指令 (优先级: 中)",
        "0X0C1": "发动机控制模块(ECM) - 动力总成高优心跳包 (优先级: 极高)",
        "0X3F3": "车门控制模块(BCM) - 解锁执行状态反馈 (包含状态码)" # 【新增】
    }
    upper_id = can_id.upper().strip()
    return dbc_mock_db.get(upper_id, "未知报文 ID，字典中未定义")

llm_with_tools = llm.bind_tools([decode_can_protocol])

def agent_a_purify(state: RCAState) -> RCAState:
    print(" [Agent A] 开始进行日志提纯工作...")
    
    # 【新增】：强化版的 Prompt，指导大模型避开干扰项
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一个资深的车联网测试开发专家。
你需要从长文本异构日志中提取真正的【异常线索】。
关键规则：
1. 过滤干扰项：日志中可能包含用户多次下发的指令（包含执行成功的干扰项）。请忽略执行成功的链路，**死磕最终导致报错（Error/Timeout/Fault）的那一次操作！**
2. 提取出导致失败的指令下发、车机接收、底层 CAN 发送/反馈的关键时间节点和内容。
3. 绝不能遗漏 TBOX_LOGCAT 的任何 Timeout 报错。
4. 列出异常期间出现过的 CAN ID 列表，供后续专家解码。"""),
        ("user", "原始日志：\n{logs}")
    ])
    
    result = (prompt | llm).invoke({"logs": state["raw_logs"]})
    return {"filtered_logs": result.content}

def agent_b_decode(state: RCAState) -> RCAState:
    print(" [Agent B] 开始进行通信解码工作...")
    prompt = ChatPromptTemplate.from_messages([
        ("system", "找出所有十六进制 CAN ID 并必须调用 `decode_can_protocol` 工具查询其真实含义。"),
        ("user", "提纯线索：\n{filtered_logs}")
    ])
    response = (prompt | llm_with_tools).invoke({"filtered_logs": state["filtered_logs"]})
    
    if response.tool_calls:
        decoded_results = []
        for tool_call in response.tool_calls:
            tool_output = decode_can_protocol.invoke(tool_call["args"])
            decoded_results.append(f"ID {tool_call['args'].get('can_id')} 解码为: {tool_output}")
        return {"decoded_clues": "底层协议解码结果：\n" + "\n".join(decoded_results)}
    return {"decoded_clues": "未发现需要解码的 CAN ID。"}

# ==========================================
# 4. 【引入】Agent C (RAG 溯源功能)
# ==========================================
def agent_c_rag(state: RCAState) -> RCAState:
    print(" [Agent C] 开始RAG溯源工作，正在检索历史缺陷库...")
    
    # 第一步：读取本地历史经验文档
    base_dir = os.path.dirname(os.path.dirname(__file__))
    knowledge_path = os.path.join(base_dir, 'knowledge_base', 'history_bugs.txt')
    
    with open(knowledge_path, 'r', encoding='utf-8') as f:
        knowledge_text = f.read()
    
    # 简单切分历史文档 (按 "[Jira-" 分割出不同的 Bug)
    bug_records = knowledge_text.split("[Jira-")
    docs = [Document(page_content="[Jira-" + record) for record in bug_records if record.strip()]
    
    # 【新增】关闭 ChromaDB 的遥测功能，消除控制台警告
    client_settings = chromadb.config.Settings(anonymized_telemetry=False)
    
    # 第二步：将文档灌入 ChromaDB 向量数据库 (传入配置)
    vector_db = Chroma.from_documents(
        docs, 
        embeddings,
        client_settings=client_settings
    )
    
    # 第三步：拿着 Agent B 解码出来的线索，去向量数据库里搜最相似的记录
    search_query = state["decoded_clues"]
    similar_docs = vector_db.similarity_search(search_query, k=1) 
    
    if similar_docs:
        retrieved_info = similar_docs[0].page_content
        print("    [Agent C] 已在历史库中找到了高度相似的 Jira 记录。")
    else:
        retrieved_info = "未检索到相关的历史 Bug 记录。"
        
    return {"rag_context": retrieved_info}

# ==========================================
# 5. Agent D (RCA 裁判功能 - 结合 RAG 上下文)
# ==========================================
def agent_d_rca(state: RCAState) -> RCAState:
    print(" [Agent D] 汇总线索与历史经验，撰写最终 RCA 报告...")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一个权威的汽车测试架构师。
撰写标准 Bug 报告 (RCA Report)。
要求：
1. 故障现象描述 (What)
2. 时序链路还原 (Timeline)
3. 根因定性 (Why)：结合协议解码结果分析物理原因。
4. 【重点】历史溯源 (History)：结合检索到的历史 Bug，判断当前是否为旧病复发。
5. 责任判定与下一步建议 (Action)"""),
        ("user", "提纯线索：\n{filtered_logs}\n\n协议解码：\n{decoded_clues}\n\n【RAG 检索到的历史经验】：\n{rag_context}\n\n请输出 RCA 报告：")
    ])
    
    response = (prompt | llm).invoke({
        "filtered_logs": state["filtered_logs"],
        "decoded_clues": state["decoded_clues"],
        "rag_context": state["rag_context"] # 【新增】把 C 的成果提供给 D
    })
    
    return response.content


# ==========================================
# 6. 主函数串联 (封装为可供 Web UI 调用的函数)
# ==========================================
def run_rca_pipeline(merged_logs_content: str):
    """
    供前端 UI 调用的主入口函数。
    接收合并对齐后的日志文本，执行 A->B->C->D 流水线，并返回执行过程和最终报告。
    """
    # 初始化状态
    current_state = RCAState(raw_logs=merged_logs_content, filtered_logs="", decoded_clues="", rag_context="")
    
    # 记录执行过程，用于在 UI 上动态展示
    execution_steps = []
    
    execution_steps.append(" [Agent A] 启动：正在审阅海量异构日志，剥离无用噪音...")
    current_state.update(agent_a_purify(current_state))
    execution_steps.append(" [Agent A] 提纯完成！提取到关键时序。")
    
    execution_steps.append(" [Agent B] 启动：接手提纯线索，正在调用底层字典工具解码...")
    current_state.update(agent_b_decode(current_state))
    execution_steps.append(" [Agent B] 解码完成！十六进制物理含义已翻译。")
    
    execution_steps.append("️ [Agent C] 启动：向量检索开启，正在比对历史缺陷库...")
    current_state.update(agent_c_rag(current_state))
    execution_steps.append(" [Agent C] 溯源完成！提取到相似历史经验。")
    
    execution_steps.append(" [Agent D] 启动：汇总所有线索， RCA 报告生成中...")
    final_report = agent_d_rca(current_state)
    execution_steps.append(" [系统] 全链路排障结束！")
    
    return final_report, execution_steps