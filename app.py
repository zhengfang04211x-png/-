import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
import platform

# ==============================================================================
# 🚀 界面定制 (全量保留自 app (2).py)
# ==============================================================================
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .viewerBadge_container__1QSob {display: none;}
            #stDecoration {display:none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==============================================================================
# 1. 🎨 页面基本设置
# ==============================================================================
st.set_page_config(page_title="套期保值稳定性回测系统", layout="wide", page_icon="🛡️")

# ==============================================================================
# 2. 🎛️ 侧边栏参数 (强制放在最外层，确保永远可见)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")

# 步骤 1: 必须先看到上传组件
uploaded_file = st.sidebar.file_uploader("1. 上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 2. 业务场景设定")

# 合约乘数与手数逻辑
multiplier = st.sidebar.number_input("合约乘数 (每一手的数量)", value=10, step=1)

lots = st.sidebar.number_input("下单手数", value=3, step=1)

# 实时计算总量，反馈给用户
quantity = lots * multiplier 

st.sidebar.markdown(f"**当前核算总量: {quantity} 单位**")

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)

margin_rate = st.sidebar.number_input("保证金率 (如 0.12)", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 3. 资金风控阈值")

inject_ratio = st.sidebar.number_input("补金警戒线 (权益/保证金)", value=1.2, step=0.05)

withdraw_ratio = st.sidebar.number_input("提盈触发线 (权益/保证金)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 4. 模拟时间")

holding_days = st.sidebar.slider("库存周转周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (严格复刻原版公式，不改动任何计算步骤)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    
    # 基差与周期性盈亏计算
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 资金流水初始化
    equity_list = []
    margin_req_list = []
    cash_in_list = []
    cash_out_list = []
    risk_degree_list = []
    
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    # 循环模拟每日持仓变动
    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        
        if i > 0:
            current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio
        
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
        
        # 补金与出金逻辑判断
        thresh_low = req_margin * inject_r
        thresh_high = req_margin * withdraw_r
        
        in_amt = 0
        out_amt = 0
        
        if current_equity < thresh_low:
            in_amt = thresh_low - current_equity
            current_equity += in_amt
        elif current_equity > thresh_high:
            out_amt = current_equity - thresh_high
            current_equity -= out_amt
            
        cash_in_list.append(in_amt)
        cash_out_list.append(out_amt)
        equity_list.append(current_equity)
        
        # 风险度计算
        if req_margin > 0:
            risk_degree_list.append(current_equity / req_margin)
        else:
            risk_degree_list.append(0)

    # 数据回填
    df['Account_Equity'] = equity_list
    df['Margin_Required'] = margin_req_list
    df['Cash_Injection'] = cash_in_list
    df['Cash_Withdrawal'] = cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'] = df['Margin_Required'] * inject_r
    df['Line_Withdraw'] = df['Margin_Required'] * withdraw_r
    
    # 累计现金流与净值变动
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    
    curr_combined_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_Hedged'] = curr_combined_asset - base_asset
    
    return df

# ==============================================================================
# 4. 📊 数据处理与可视化展示
# ==============================================================================
st.title("📊 企业套期保值资金风控看板")

if uploaded_file is not None:
    # 尝试读取数据，处理中文编码
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    # 列名清洗
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    
    # 自动识别“时间/现货/期货”列
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        # 数据转换与预处理
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        # 时间范围选择器 (放在侧边栏)
        min_date = raw_df['Date'].min().to_pydatetime()
        max_date = raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("5. 筛选回测时段", value=(min_date, max_date))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            # 过滤数据并执行计算
            mask = (raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])
            filtered_df = raw_df.loc[mask]
            
            df = process_data(filtered_df, quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 核心指标显示 (Metric) ---
            c1, c2, c3, c4 = st.columns(4)
            
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            
            loss_saved = (df['Value_Change_Hedged'].min() - df['Value_Change_NoHedge'].min()) / 10000

            c1.metric("现货原始风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余波动", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%")
            c3.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
            c4.metric("最大亏损修复额", f"{loss_saved:.2f} 万")

            # --- 交互式 Plotly 图表 (Tab 结构) ---
            tab1, tab2, tab3, tab4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with tab1:
                # 价格与基差走势
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货价格', line=dict(color='blue')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货价格', line=dict(color='orange', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis'], name='基差(右轴)', fill='tozeroy', yaxis='y2', line=dict(width=0), opacity=0.3, fillcolor='gray'))
                fig1.update_layout(hovermode="x unified", height=500, yaxis=dict(title="单价"), yaxis2=dict(overlaying='y', side='right', showgrid=False, title="基差"))
                st.plotly_chart(fig1, use_container_width=True)

            with tab2:
                # 资产损益变动对比
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保损益(万)', line=dict(color='red', width=1), opacity=0.4))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='套保后净值(万)', line=dict(color='green', width=3)))
                fig2.update_layout(hovermode="x unified", height=500, yaxis_title="金额 (万元)")
                st.plotly_chart(fig2, use_container_width=True)

            with tab3:
                # 盈亏概率分布直方图
                fig3 = go.Figure()
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_NoHedge']/10000, name='未套保', marker_color='red', opacity=0.4))
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_Hedge']/10000, name='套保后', marker_color='green', opacity=0.6))
                fig3.update_layout(barmode='overlay', height=500, xaxis_title="盈亏金额 (万元)", yaxis_title="频数")
                st.plotly_chart(fig3, use_container_width=True)

            with tab4:
                # 资金水位监控
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='权益', line=dict(color='black', width=2)))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(color='red', dash='dot')))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈线', line=dict(color='blue', dash='dot')))
                
                # 标记补仓/提盈事件
                inj_pts = df[df['Cash_Injection'] > 0]
                wit_pts = df[df['Cash_Withdrawal'] > 0]
                fig4.add_trace(go.Scatter(x=inj_pts['Date'], y=inj_pts['Account_Equity']/10000, mode='markers', name='补仓', marker=dict(color='red', symbol='triangle-up', size=10)))
                fig4.add_trace(go.Scatter(x=wit_pts['Date'], y=wit_pts['Account_Equity']/10000, mode='markers', name='提盈', marker=dict(color='blue', symbol='triangle-down', size=10)))
                fig4.update_layout(hovermode="x unified", height=500, yaxis_title="账户资金 (万元)")
                st.plotly_chart(fig4, use_container_width=True)

            # --- 业务文字总结 ---
            st.markdown("---")
            st.subheader("📝 策略回测总结")
            col_l, col_r = st.columns(2)
            with col_l:
                st.success(f"✅ **对冲质量**：资产稳定性提升了 **{stability_boost:.1f}%**。")
            with col_r:
                st.warning(f"🏦 **运营成本**：整个周期内共触发资金调度 **{len(inj_pts) + len(wit_pts)}** 次。")

            # 下载 Excel 数据
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='回测详情')
            st.download_button("📥 导出回测运营报表", data=output.getvalue(), file_name='Hedge_Report.xlsx')
    else:
        st.error("❌ 数据格式错误：未在文件中找到包含‘现货’、‘期货’字样的价格列。")
else:
    # 当没有上传文件时显示的内容
    st.info("👋 请先在左侧边栏上传 CSV 数据文件以激活分析面板。")
    st.image("https://img.icons8.com/clouds/200/000000/upload.png")





