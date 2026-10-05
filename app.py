# app.py
import streamlit as st
import os
import time
from core.log_aligner import LogAligner
from core.workflow_agents import run_rca_pipeline

# 1. 页面基本配置
st.set_page_config(
    page_title="车联网日志溯源专家",
    page_icon="🚗",
    layout="wide"
)

# 自定义一点样式让报告更好看
st.markdown("""
<style>
    .report-box { padding: 20px; border-radius: 10px; background-color: #f0f2f6; color: #1e1e1e;}
</style>
""", unsafe_allow_html=True)

BASE_DIR = os.path.dirname(__file__)

# 2. 侧边栏：控制面板
with st.sidebar:
    st.title("🎛️ 测开控制台")
    st.markdown("---")
    
    # 下拉框：选择我们造好的那 3 个混沌案件
    case_selector = st.selectbox(
        "📂 选择要分析的实车故障数据：",
        options=["case_1_can_congestion", "case_2_network_offline", "case_3_hardware_fault"],
        format_func=lambda x: {
            "case_1_can_congestion": "案件 1: 疑似底层网络拥堵",
            "case_2_network_offline": "案件 2: 疑似车端弱网断连",
            "case_3_hardware_fault": "案件 3: 疑似执行器机械故障"
        }[x]
    )
    
    CASE_DIR = os.path.join(BASE_DIR, 'data_output', case_selector)
    MERGED_FILE_PATH = os.path.join(CASE_DIR, 'merged_timeline.txt')

    st.subheader("第一步：预处理")
    if st.button("🔄 异构日志时钟对齐", use_container_width=True):
        with st.spinner("正在清洗过滤数千行异构噪音..."):
            aligner = LogAligner(CASE_DIR)
            # 调用我们在命令行测试过的粗筛逻辑
            merged_logs = aligner.get_aligned_logs(limit=15000) 
            with open(MERGED_FILE_PATH, 'w', encoding='utf-8') as f:
                f.write(merged_logs)
            st.success(f"✅ 日志对齐与降噪完成！")

    st.markdown("---")
    st.subheader("第二步：大模型诊断")
    start_diagnosis = st.button("🚀 启动 Multi-Agent 溯源", type="primary", use_container_width=True)

# 3. 主界面
st.title("🚗 车联网异构日志 Multi-Agent 溯源系统")
st.markdown("> **项目定位**：解决跨域排障难、日志海量且异构、依靠人工扒日志耗时极长的问题。")
st.markdown(f"**当前加载数据集**：`{case_selector}`")

# 核心诊断逻辑
if start_diagnosis:
    if not os.path.exists(MERGED_FILE_PATH):
        st.error("⚠️ 请先点击左侧按钮进行『异构日志时钟对齐』！")
        st.stop()
        
    with open(MERGED_FILE_PATH, 'r', encoding='utf-8') as f:
        logs_content = f.read()

    # 创建动态UI容器
    status_container = st.empty()
    progress_bar = st.progress(0)
    
    with st.spinner("AI 专家团协同推理中，这可能需要几十秒..."):
        # 调用核心引擎
        final_report, steps = run_rca_pipeline(logs_content)
        
        # 为了演示效果，逐条显示 Agent 的执行进度
        status_text = ""
        for i, step in enumerate(steps):
            status_text += f"{step}\n"
            status_container.code(status_text, language="shell")
            progress_bar.progress((i + 1) / len(steps))
            time.sleep(0.5) # 给一点视觉停留时间

    st.success("✅ 诊断完成！终极 RCA 报告如下：")
    
    # 渲染 Markdown 报告
    st.markdown("<div class='report-box'>", unsafe_allow_html=True)
    st.markdown(final_report)
    st.markdown("</div>", unsafe_allow_html=True)