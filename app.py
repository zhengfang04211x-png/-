import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.figure_factory as ff
import io

# ==============================================================================
# 1. 🎨 页面基本设置 (修复侧边栏可见性)
# ==============================================================================
st.set_page_config(
    page_title="套期保值稳定性回测系统",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

# 修复：不再隐藏整个 header，确保左上角展开侧边栏的箭头按钮 (>) 永远存在
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {display: none;}
    #stDecoration {display:none;}
    /* 调整顶部空白，保持美观 */
    .block-container {padding-top: 2rem;}
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 🎛️ 侧边栏参数面板 (始终位于最外层，确保没上传文件也能调参数)
# ==============================================================================
with st.sidebar:
    st.header("🛠️ 参数配置面板")
    uploaded_file = st.file_uploader("1. 上传数据文件 (CSV)", type=['csv'])
    
    st.subheader("🏭 2. 业务规模")
    # 拆分手单与乘数
    multiplier = st.number_input("合约乘数 (吨/手)", value=10, step=1)
    lots = st.number_input("下单手数", value=3, step=1)
    quantity = lots * multiplier 
    st.info(f"👉 实际套保总量: {quantity} 单位")
    
    hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
    margin_rate = st.sidebar.number_input("保证金率 (如:0.12)", value=0.12, step=0.01, format="%.2f")
    
    st.subheader("💰 3. 资金风控阈值")
    inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
    withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)
    
    st.subheader("⏳ 4. 周期设置")
    holding_days = st.sidebar.slider("库存周转周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (严格对齐 app (2).py 源码)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    df['Basis'] = df['Spot'] - df['Futures']
    
    # 周期损益计算
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 资金管理逻辑初始化
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
    
    # 资产净值变动计算
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset
    return df

# ==============================================================================
# 4. 📊 主展示区
# ==============================================================================
st.title("📊 企业套期保值风险回测看板")

if uploaded_file:
    # 数据读取与清洗
    try: raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except: raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
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
        date_range = st.sidebar.date_input("5. 筛选回测时段", value=(min_d, max_d))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df = process_data(raw_df[(raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 指标看板 ---
            c1, c2, c3, c4 = st.columns(4)
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            loss_saved = (df['Value_Change_Hedged'].min() - df['Value_Change_NoHedge'].min()) / 10000

            c1.metric("现货风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余风险", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%")
            c3.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
            c4.metric("最大亏损修复额", f"{loss_saved:.2f} 万")

            # --- 核心图表 Tab ---
            t1, t2, t3, t4 = st.tabs(["📉 价格/基差监控", "🛡️ 对冲波动稳定性", "📊 盈亏概率分布 (KDE)", "🏦 资金通道监管"])

            with t1:
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货价格', line=dict(color='#1f77b4')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货价格', line=dict(color='#ff7f0e', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis'], name='基差(右轴)', fill='tozeroy', yaxis='y2', line=dict(width=0), opacity=0.3, fillcolor='gray'))
                fig1.update_layout(hovermode="x unified", height=500, yaxis2=dict(overlaying='y', side='right', showgrid=False))
                st.plotly_chart(fig1, use_container_width=True)

            with t2:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保风险', line=dict(color='red', width=1), opacity=0.3))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='套保后稳态', line=dict(color='green', width=2.5)))
                fig2.update_layout(hovermode="x unified", height=500, yaxis_title="金额 (万元)")
                st.plotly_chart(fig2, use_container_width=True)

            with t3:
                # 🚀 密度分布图 (KDE) 彻底复原
                # 去除空值并转换为万元
                data_no = df['Cycle_PnL_NoHedge'].dropna() / 10000
                data_hedge = df['Cycle_PnL_Hedge'].dropna() / 10000
                
                hist_data = [data_no, data_hedge]
                group_labels = ['未套保 (原始波幅)', '套保后 (风险压缩)']
                
                fig3 = ff.create_distplot(hist_data, group_labels, show_hist=True, show_rug=False, colors=['red', 'green'], bin_size=0.5)
                fig3.update_layout(height=500, xaxis_title="周期盈亏金额 (万元)", yaxis_title="发生概率密度")
                st.plotly_chart(fig3, use_container_width=True)

            with t4:
                # 🚀 资金通道标记点彻底复原
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈线', line=dict(color='blue', dash='dot', width=1), opacity=0.3))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(color='red', dash='dot', width=1), opacity=0.3))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='期货账户权益', line=dict(color='black', width=1.5)))
                
                # 找到动作点
                inj_ev = df[df['Cash_Injection'] > 0]
                wit_ev = df[df['Cash_Withdrawal'] > 0]
                
                fig4.add_trace(go.Scatter(x=inj_ev['Date'], y=inj_ev['Account_Equity']/10000, mode='markers', name='追加保证金 (补仓)', marker=dict(color='red', symbol='triangle-up', size=12)))
                fig4.add_trace(go.Scatter(x=wit_ev['Date'], y=wit_ev['Account_Equity']/10000, mode='markers', name='提取盈余 (出金)', marker=dict(color='blue', symbol='triangle-down', size=12)))
                
                fig4.update_layout(hovermode="x unified", height=500, yaxis_title="金额 (万元)")
                st.plotly_chart(fig4, use_container_width=True)

            # --- 3. 摘要分析结论 (复刻 app (2).py 原文) ---
            st.markdown("---")
            st.subheader("📝 稳定性分析结论")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.write(f"✅ **风险对冲质量**：通过套保，资产净值的波动幅度被压制在了现货波动的 **{100-stability_boost:.1f}%** 范围内。")
                st.write(f"✅ **极端生存能力**：在回测期内最不利的价格波动下，套保方案成功挽救了约 **{loss_saved:.2f} 万元** 的潜在损失。")
            with sc2:
                st.write(f"✅ **资金运营频率**：系统平均每 **{len(df)/(len(inj_ev)+len(wit_ev)+1):.1f}** 天触发一次资金调度（补仓/提盈）。")
                st.write(f"✅ **收益确定性**：套保后的盈亏密度显著向中心轴收拢，大幅降低了企业经营的系统性风险。")

            # 导出报表
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 导出回测运营详情", data=output.getvalue(), file_name='Backtest_Report.xlsx')
else:
    st.info("👋 请在左侧边栏上传 CSV 数据文件，激活系统进行深度风险分析。")
            st.download_button("📥 导出回测详情", data=output.getvalue(), file_name='Backtest_Report.xlsx')







