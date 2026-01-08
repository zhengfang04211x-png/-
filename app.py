import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.figure_factory as ff
import io

# ==============================================================================
# 1. 🎨 页面配置 (图表放大 + 侧边栏常驻)
# ==============================================================================
st.set_page_config(
    page_title="套期保值稳定性回测系统",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {display: none;}
    #stDecoration {display:none;}
    .block-container {padding-top: 1rem; padding-bottom: 1rem; max-width: 95%;}
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 🎛️ 侧边栏参数面板
# ==============================================================================
with st.sidebar:
    st.header("🛠️ 参数配置")
    uploaded_file = st.file_uploader("1. 上传 CSV 文件", type=['csv'])
    
    st.subheader("🏭 2. 规模设定")
    multiplier = st.number_input("合约乘数 (单位/手)", value=10, step=1)
    lots = st.number_input("下单手数", value=3, step=1)
    quantity = lots * multiplier 
    
    hedge_ratio = st.slider("套保比例", 0.0, 1.2, 1.0, 0.1)
    margin_rate = st.number_input("保证金率", value=0.12, step=0.01)
    
    st.subheader("💰 3. 风控线")
    inject_ratio = st.number_input("补金警戒线", value=1.2, step=0.05)
    withdraw_ratio = st.number_input("提盈触发线", value=1.5, step=0.05)
    
    st.subheader("⏳ 4. 周期")
    holding_days = st.slider("持仓天数", 7, 90, 30)

# ==============================================================================
# 3. 🧠 计算核心 (增加强制数据转换)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    
    # --- 💡 核心修复：确保数据全是数字，处理逗号和空值 ---
    for col in ['Spot', 'Futures']:
        if df[col].dtype == 'object':
            df[col] = df[col].str.replace(',', '').str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 填充空值防止计算中断
    df = df.ffill().bfill()

    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, margin_req_list, cash_in_list, cash_out_list = [], [], [], []
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0: current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio
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
        cash_in_list.append(in_amt); cash_out_list.append(out_amt); equity_list.append(current_equity)

    df['Account_Equity'] = equity_list
    df['Cash_Injection'], df['Cash_Withdrawal'] = cash_in_list, cash_out_list
    df['Line_Inject'], df['Line_Withdraw'] = np.array(margin_req_list) * inject_r, np.array(margin_req_list) * withdraw_r
    
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash - base_asset
    return df

# ==============================================================================
# 4. 📊 展示区 (图表放大版)
# ==============================================================================
st.title("📊 企业套期保值风险回测看板")

if uploaded_file:
    try: raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except: raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if any(k in c for k in ['时间', 'Date'])), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if '期货' in c or '主力' in c), None)

    if col_time and col_spot and col_fut:
        # 重命名并初步清洗列名
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)
        
        # 执行计算
        df = process_data(raw_df, quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

        # 1. 核心指标
        c1, c2, c3, c4 = st.columns(4)
        std_raw, std_hedge = df['Value_Change_NoHedge'].std()/10000, df['Value_Change_Hedged'].std()/10000
        c1.metric("现货风险 (Std)", f"{std_raw:.2f}万")
        c2.metric("套保后风险", f"{std_hedge:.2f}万", delta=f"降低{(1-std_hedge/std_raw)*100:.1f}%")
        c3.metric("调仓净额", f"{(df['Cash_Withdrawal'].sum()-df['Cash_Injection'].sum())/10000:.2f}万")
        c4.metric("风险挽回", f"{(df['Value_Change_Hedged'].min()-df['Value_Change_NoHedge'].min())/10000:.2f}万")

        # 2. 放大版图表 (Height=650)
        CHART_HEIGHT = 650 
        t1, t2, t3, t4 = st.tabs(["📉 价格基差", "🛡️ 对冲波动", "📊 密度分布", "🏦 资金监控"])

        with t1:
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货', line=dict(color='blue')))
            fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货', line=dict(color='orange', dash='dash')))
            fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis'], name='基差', fill='tozeroy', yaxis='y2', opacity=0.2, fillcolor='gray'))
            fig1.update_layout(height=CHART_HEIGHT, hovermode="x unified", yaxis2=dict(overlaying='y', side='right', showgrid=False))
            st.plotly_chart(fig1, use_container_width=True)

        with t2:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保', line=dict(color='red'), opacity=0.3))
            fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='已套保', line=dict(color='green', width=3)))
            fig2.update_layout(height=CHART_HEIGHT, hovermode="x unified", yaxis_title="万元")
            st.plotly_chart(fig2, use_container_width=True)

        with t3:
            d1 = df['Cycle_PnL_NoHedge'].dropna()/10000
            d2 = df['Cycle_PnL_Hedge'].dropna()/10000
            fig3 = ff.create_distplot([d1, d2], ['未套保', '套保后'], show_rug=False, colors=['red', 'green'], bin_size=0.5)
            fig3.update_layout(height=CHART_HEIGHT, xaxis_title="万元", title_text="盈亏分布密度曲线 (KDE)")
            st.plotly_chart(fig3, use_container_width=True)

        with t4:
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈线', line=dict(dash='dot', color='blue'), opacity=0.2))
            fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(dash='dot', color='red'), opacity=0.2))
            fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='权益', line=dict(color='black', width=2)))
            inj, wit = df[df['Cash_Injection']>0], df[df['Cash_Withdrawal']>0]
            fig4.add_trace(go.Scatter(x=inj['Date'], y=inj['Account_Equity']/10000, mode='markers', name='补仓', marker=dict(color='red', symbol='triangle-up', size=14)))
            fig4.add_trace(go.Scatter(x=wit['Date'], y=wit['Account_Equity']/10000, mode='markers', name='出金', marker=dict(color='blue', symbol='triangle-down', size=14)))
            fig4.update_layout(height=CHART_HEIGHT, hovermode="x unified")
            st.plotly_chart(fig4, use_container_width=True)

        # 3. 结论输出
        st.markdown("---")
        st.subheader("📝 稳定性分析结论")
        sc1, sc2 = st.columns(2)
        with sc1:
            st.write(f"✅ **对冲质量**：波动压制在原始风险的 **{100-stability_boost:.1f}%** 范围内。")
            st.write(f"✅ **生存能力**：极端情况下挽救了约 **{loss_saved:.2f} 万元**。")
        with sc2:
            st.write(f"✅ **调仓频率**：平均每 **{len(df)/(len(inj)+len(wit)+1):.1f}** 天操作一次。")
            st.write(f"✅ **确定性**：套保后盈亏分布显著向中心轴收拢。")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        st.download_button("📥 导出报表", data=output.getvalue(), file_name='Backtest_Report.xlsx')
    else:
        st.error("数据表头缺失：请确保包含‘时间’、‘现货’、‘期货’字样")
else:
    st.info("👋 请在左侧上传 CSV 文件开启深度分析。")







