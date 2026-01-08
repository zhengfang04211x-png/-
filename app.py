import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.figure_factory as ff
import io

# ==============================================================================
# 1. 🎨 页面基本设置与 CSS (修复侧边栏可见性)
# ==============================================================================
st.set_page_config(
    page_title="套期保值稳定性回测系统",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

# 修复：删除了隐藏 header 的 CSS，确保左上角箭头可见
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {display: none;}
    #stDecoration {display:none;}
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 🎛️ 侧边栏参数 (严格展开)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")
multiplier = st.sidebar.number_input("合约乘数 (吨/手)", value=10, step=1)
lots = st.sidebar.number_input("下单手数", value=3, step=1)
quantity = lots * multiplier 

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (完全复刻 app (2).py)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    df['Basis'] = df['Spot'] - df['Futures']
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
    
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset
    return df

# ==============================================================================
# 4. 📊 交互式看板 (带全量动作标记与分布曲线)
# ==============================================================================
if uploaded_file:
    try: raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except: raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if any(k in c for k in ['时间', 'Date'])), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        min_d, max_d = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("分析时段", value=(min_d, max_d))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df = process_data(raw_df[(raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 1. Metric 指标区 ---
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            max_loss_no = df['Value_Change_NoHedge'].min() / 10000
            max_loss_hedge = df['Value_Change_Hedged'].min() / 10000
            loss_saved = max_loss_hedge - max_loss_no 

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现货波动风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余波动", f"{std_hedge:.2f} 万", delta=f"下降 {stability_boost:.1f}%")
            c3.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
            c4.metric("最大亏损修复额", f"{loss_saved:.2f} 万")

            # --- 2. 交互 Tab 区 ---
            t1, t2, t3, t4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with t1:
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货', line=dict(color='blue')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货', line=dict(color='orange', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis'], name='基差', fill='tozeroy', yaxis='y2', opacity=0.3, fillcolor='gray', line=dict(width=0)))
                fig1.update_layout(hovermode="x unified", height=450, yaxis2=dict(overlaying='y', side='right', showgrid=False))
                st.plotly_chart(fig1, use_container_width=True)

            with t2:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保', line=dict(color='red', width=1), opacity=0.3))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='已套保', line=dict(color='green', width=2.5)))
                fig2.update_layout(hovermode="x unified", height=450, yaxis_title="万元")
                st.plotly_chart(fig2, use_container_width=True)

            with t3:
                # 🛠️ 修复：模拟原版 KDE 曲线分布图
                hist_data = [df['Cycle_PnL_NoHedge'].dropna()/10000, df['Cycle_PnL_Hedge'].dropna()/10000]
                group_labels = ['未套保盈亏', '套保后盈亏']
                fig3 = ff.create_distplot(hist_data, group_labels, show_hist=True, show_rug=False, colors=['red', 'green'])
                fig3.update_layout(height=450, xaxis_title="万元", barmode='overlay')
                st.plotly_chart(fig3, use_container_width=True)

            with t4:
                # 🛠️ 修复：恢复资金动作点标记
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈线', line=dict(color='rgba(0,0,255,0.1)', dash='dot')))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(color='rgba(255,0,0,0.1)', dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.05)'))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='账户权益', line=dict(color='black', width=1.5)))
                
                # 动作点
                inj_ev = df[df['Cash_Injection']>0]
                wit_ev = df[df['Cash_Withdrawal']>0]
                fig4.add_trace(go.Scatter(x=inj_ev['Date'], y=inj_ev['Account_Equity']/10000, mode='markers', name='追加资金', marker=dict(color='red', symbol='triangle-up', size=12)))
                fig4.add_trace(go.Scatter(x=wit_ev['Date'], y=wit_ev['Account_Equity']/10000, mode='markers', name='提取盈余', marker=dict(color='blue', symbol='triangle-down', size=12)))
                fig4.update_layout(hovermode="x unified", height=450, yaxis_title="万元")
                st.plotly_chart(fig4, use_container_width=True)

            # --- 3. 摘要分析结论 (完全复刻原版文字) ---
            st.markdown("---")
            st.subheader("📝 稳定性分析结论")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.write(f"✅ **风险对冲质量**：通过套保，资产净值的波动幅度被压制在了现货波动的 **{100-stability_boost:.1f}%** 范围内。")
                st.write(f"✅ **极端生存能力**：在回测期内最不利的价格波动下，套保方案成功挽救了约 **{loss_saved:.2f} 万元** 的潜在损失。")
            with sc2:
                st.write(f"✅ **资金运营频率**：系统平均每 **{len(df)/(len(inj_ev)+len(wit_ev)+1):.1f}** 天触发一次资金调度。")
                st.write(f"✅ **收益确定性**：套保后的盈亏分布（见标签3）明显向中心靠拢，大幅降低了“意外”风险。")

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 导出回测详情", data=output.getvalue(), file_name='Backtest_Report.xlsx')






