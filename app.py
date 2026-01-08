import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# ==============================================================================
# 1. 🎨 页面配置 (设置初始状态为展开，防止侧边栏“消失”)
# ==============================================================================
st.set_page_config(
    page_title="套期保值稳定性回测系统",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"  # 强制侧边栏默认展开
)

# --- 修复后的 CSS：保留了 header 以确保侧边栏开关箭头可见 ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            .viewerBadge_container__1QSob {display: none;}
            #stDecoration {display:none;}
            /* 适当调整顶部间距，补偿 header 留下的空白 */
            .block-container {padding-top: 2rem;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==============================================================================
# 2. 🎛️ 侧边栏参数面板 (始终位于最外层)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")

uploaded_file = st.sidebar.file_uploader("1. 上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 2. 业务规模")
multiplier = st.sidebar.number_input("合约乘数 (吨/手)", value=10, step=1)
lots = st.sidebar.number_input("套保手数", value=3, step=1)
quantity = lots * multiplier 
st.sidebar.info(f"👉 实际套保总量: {quantity} 单位")

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率 (如:0.12)", value=0.12, step=0.01)

st.sidebar.subheader("💰 3. 风控阈值")
inject_ratio = st.sidebar.number_input("补金警戒线 (权益/保证金)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (权益/保证金)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 4. 周期设置")
holding_days = st.sidebar.slider("库存周转周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    df['Basis'] = df['Spot'] - df['Futures']
    
    # 损益计算
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, margin_req_list, cash_in_list, cash_out_list, risk_degree_list = [], [], [], [], []
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio
        
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
        
        # 调仓逻辑
        thresh_low, thresh_high = req_margin * inject_r, req_margin * withdraw_r
        in_amt, out_amt = 0, 0
        if current_equity < thresh_low:
            in_amt = thresh_low - current_equity
            current_equity += in_amt
        elif current_equity > thresh_high:
            out_amt = current_equity - thresh_high
            current_equity -= out_amt
            
        cash_in_list.append(in_amt)
        cash_out_list.append(out_amt)
        equity_list.append(current_equity)
        risk_degree_list.append((current_equity / req_margin) if req_margin > 0 else 0)

    df['Account_Equity'], df['Margin_Required'] = equity_list, margin_req_list
    df['Cash_Injection'], df['Cash_Withdrawal'] = cash_in_list, cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'], df['Line_Withdraw'] = df['Margin_Required'] * inject_r, df['Margin_Required'] * withdraw_r
    
    # 资产净值逻辑
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset
    return df

# ==============================================================================
# 4. 📊 数据处理与交互式绘图
# ==============================================================================
st.title("📊 企业套期保值风险回测看板")

if uploaded_file:
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if any(k in c for k in ['时间', 'Date', '日期'])), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        min_d, max_d = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("5. 选择回测时间段", value=(min_d, max_d))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df = process_data(raw_df[(raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # 指标展示
            c1, c2, c3, c4 = st.columns(4)
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            loss_saved = (df['Value_Change_Hedged'].min() - df['Value_Change_NoHedge'].min()) / 10000

            c1.metric("现货风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余风险", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%")
            c3.metric("调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
            c4.metric("风险挽回额", f"{loss_saved:.2f} 万")

            # 标签页绘图
            t1, t2, t3, t4 = st.tabs(["📉 价格/基差", "🛡️ 对冲稳态对比", "📊 风险分布", "🏦 资金监控"])

            with t1:
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货', line=dict(color='blue')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货', line=dict(color='orange', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis'], name='基差', fill='tozeroy', yaxis='y2', opacity=0.3, fillcolor='gray'))
                fig1.update_layout(hovermode="x unified", height=450, yaxis2=dict(overlaying='y', side='right', showgrid=False))
                st.plotly_chart(fig1, use_container_width=True)

            with t2:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保', line=dict(color='red'), opacity=0.3))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='已套保', line=dict(color='green', width=2)))
                fig2.update_layout(hovermode="x unified", height=450, yaxis_title="万元")
                st.plotly_chart(fig2, use_container_width=True)

            with t3:
                # 🛠️ 修复：使用原生 Plotly Histogram，不再依赖 scipy
                fig3 = go.Figure()
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_NoHedge']/10000, name='未套保', marker_color='red', opacity=0.4))
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_Hedge']/10000, name='套保后', marker_color='green', opacity=0.6))
                fig3.update_layout(barmode='overlay', height=450, xaxis_title="盈亏金额 (万)")
                st.plotly_chart(fig3, use_container_width=True)

            with t4:
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='权益', line=dict(color='black')))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(color='red', dash='dot')))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈线', line=dict(color='blue', dash='dot')))
                st.plotly_chart(fig4, use_container_width=True)

            # 下载
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 导出报表", data=output.getvalue(), file_name='Hedge_Report.xlsx')
else:
    st.info("👋 请在左侧上传 CSV 数据文件开启系统分析。")






