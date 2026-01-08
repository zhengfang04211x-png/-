import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
import platform

# ==============================================================================
# 🚀 界面定制 (保留原始样式)
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
st.set_page_config(page_title="企业套保资金风控系统", layout="wide", page_icon="📈")

# ==============================================================================
# 2. 🎛️ 侧边栏：参数配置 (保持原样，仅加入乘数联动)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")
multiplier = st.sidebar.number_input("合约乘数 (每手单位)", value=10, step=1)
lots = st.sidebar.number_input("下单手数", value=3, step=1)
quantity = lots * multiplier 
st.sidebar.info(f"计算总量: {quantity}")

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (完全保留原版计算结果，绝无变动)
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
        
        t_low, t_high = req_margin * inject_r, req_margin * withdraw_r
        in_amt, out_amt = 0, 0
        if current_equity < t_low:
            in_amt = t_low - current_equity
            current_equity += in_amt
        elif current_equity > t_high:
            out_amt = current_equity - t_high
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
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash - base_asset
    return df

# ==============================================================================
# 4. 📊 主界面展示 (全部替换为交互式图表)
# ==============================================================================
st.title("📊 企业套期保值资金风控看板")
st.markdown("---")

if uploaded_file is not None:
    try: raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except: raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        min_d, max_d = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("分析时间", value=(min_d, max_d))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            mask = (raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])
            df = process_data(raw_df.loc[mask], quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # Metrics 看板
            c1, c2, c3, c4 = st.columns(4)
            t_inj, t_wit = df['Cash_Injection'].sum()/10000, df['Cash_Withdrawal'].sum()/10000
            c1.metric("累计补入资金", f"{t_inj:.2f} 万")
            c2.metric("累计提取盈余", f"{t_wit:.2f} 万")
            c3.metric("资金净回流", f"{(t_wit - t_inj):.2f} 万")
            c4.metric("最新风险度", f"{df['Risk_Degree'].iloc[-1]*100:.1f}%")

            tab1, tab2, tab3, tab4 = st.tabs(["📉 价格与基差", "🏦 资金通道监控", "🛡️ 对冲效果对比", "📊 风险分布"])

            with tab1:
                st.subheader("期现价格走势与基差监控")
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot']/10000, name='现货 (万)', line=dict(color='blue')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures']/10000, name='期货 (万)', line=dict(color='orange', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis']/10000, name='基差 (万)', fill='tozeroy', yaxis='y2', line=dict(color='gray', width=0), opacity=0.3))
                fig1.update_layout(hovermode="x unified", yaxis=dict(title="价格 (万)"), yaxis2=dict(title="基差 (万)", overlaying='y', side='right', showgrid=False))
                st.plotly_chart(fig1, use_container_width=True)

            with tab2:
                st.subheader("资金安全通道监控")
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提金线', line=dict(color='blue', dash='dot', width=1)))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(color='red', dash='dot', width=1), fill='tonexty', fillcolor='rgba(128,128,128,0.1)'))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='权益 (万)', line=dict(color='green', width=2.5)))
                # 标注点
                inj_pts = df[df['Cash_Injection']>0]
                wit_pts = df[df['Cash_Withdrawal']>0]
                fig2.add_trace(go.Scatter(x=inj_pts['Date'], y=inj_pts['Account_Equity']/10000, mode='markers', name='补仓动作', marker=dict(color='red', symbol='triangle-up', size=10)))
                fig2.add_trace(go.Scatter(x=wit_pts['Date'], y=wit_pts['Account_Equity']/10000, mode='markers', name='提取动作', marker=dict(color='blue', symbol='triangle-down', size=10)))
                fig2.update_layout(hovermode="x unified", yaxis=dict(title="金额 (万)"))
                st.plotly_chart(fig2, use_container_width=True)

            with tab3:
                st.subheader("账面资产净值变动对比")
                fig3 = go.Figure()
                fig3.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保波动', line=dict(color='red', width=1), opacity=0.4))
                fig3.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='套保后平稳', line=dict(color='green', width=2.5)))
                fig3.update_layout(hovermode="x unified", yaxis=dict(title="价值变动 (万)"))
                st.plotly_chart(fig3, use_container_width=True)
                # 计算波动率降低
                s_raw, s_hdg = df['Value_Change_NoHedge'].std(), df['Value_Change_Hedged'].std()
                st.caption(f"📊 统计结论: 策略成功平抑了市场 **{((1-s_hdg/s_raw)*100):.1f}%** 的价格波动风险。")

            with tab4:
                st.subheader("盈亏频率分布分布 (直方图)")
                # Plotly 的 KDE 模拟
                import plotly.figure_factory as ff
                hist_data = [df['Cycle_PnL_NoHedge'].dropna()/10000, df['Cycle_PnL_Hedge'].dropna()/10000]
                group_labels = ['未套保分布', '套保后分布']
                fig4 = ff.create_distplot(hist_data, group_labels, bin_size=.5, show_hist=False, colors=['red', 'green'])
                fig4.update_layout(xaxis=dict(title="盈亏金额 (万)"))
                st.plotly_chart(fig4, use_container_width=True)

            # 下载
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 下载完整回测数据", data=output.getvalue(), file_name='Backtest_Report.xlsx')
else:
    st.info("💡 请在左侧上传数据文件开始回测。")






