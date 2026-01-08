import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.figure_factory as ff
import io

# 1. 页面配置 (只改了这里：让侧边栏默认展开)
st.set_page_config(page_title="套期保值稳定性回测系统", layout="wide", initial_sidebar_state="expanded")

# 2. 修复后的 CSS (删除了隐藏 header 的那一行，箭头就回来了)
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {display: none;}
    #stDecoration {display:none;}
    </style>
""", unsafe_allow_html=True)

# 3. 侧边栏 (保持你的原逻辑)
st.sidebar.header("参数配置")
uploaded_file = st.sidebar.file_uploader("上传 CSV 数据文件", type=['csv'])
multiplier = st.sidebar.number_input("合约乘数", value=10)
lots = st.sidebar.number_input("手数", value=3)
hedge_ratio = st.sidebar.slider("套保比例", 0.0, 1.2, 1.0)
margin_rate = st.sidebar.number_input("保证金率", value=0.12)
inject_ratio = st.sidebar.number_input("补金警戒线", value=1.2)
withdraw_ratio = st.sidebar.number_input("提盈触发线", value=1.5)
holding_days = st.sidebar.slider("库存周转周期 (天)", 7, 90, 30)

# 4. 核心计算 (增加了数据强制清洗，解决报错)
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy()
    # --- 修复数据报错的核心代码 ---
    for col in ['Spot', 'Futures']:
        if df[col].dtype == 'object':
            df[col] = df[col].str.replace(',', '').str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.ffill().bfill() # 补齐空值
    # ---------------------------
    
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, margin_req_list, cash_in_list, cash_out_list = [], [], [], []
    current_equity = df['Futures'].iloc[0] * q * ratio * m_rate * inject_r

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            current_equity += -(price - df['Futures'].iloc[i-1]) * q * ratio
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
        
        # 你的原版资金调度逻辑
        if current_equity < req_margin * inject_r:
            in_amt = req_margin * inject_r - current_equity
            current_equity += in_amt
            cash_in_list.append(in_amt); cash_out_list.append(0)
        elif current_equity > req_margin * withdraw_r:
            out_amt = current_equity - req_margin * withdraw_r
            current_equity -= out_amt
            cash_in_list.append(0); cash_out_list.append(out_amt)
        else:
            cash_in_list.append(0); cash_out_list.append(0)
        equity_list.append(current_equity)

    df['Account_Equity'] = equity_list
    df['Cash_Injection'], df['Cash_Withdrawal'] = cash_in_list, cash_out_list
    df['Line_Inject'] = np.array(margin_req_list) * inject_r
    df['Line_Withdraw'] = np.array(margin_req_list) * withdraw_r
    
    cum_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = (df['Spot'] * q) + df['Account_Equity'] + cum_cash - ((df['Spot'].iloc[0] * q) + (df['Futures'].iloc[0] * q * ratio * m_rate * inject_r))
    return df

# 5. 展示与绘图 (只改了 height)
if uploaded_file:
    raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    # 自动找列名
    col_time = next(c for c in raw_df.columns if '时间' in c or 'Date' in c)
    col_spot = next(c for c in raw_df.columns if '现货' in c)
    col_fut = next(c for c in raw_df.columns if '期货' in c or '主力' in c)
    raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
    raw_df['Date'] = pd.to_datetime(raw_df['Date'])
    
    df = process_data(raw_df, lots*multiplier, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

    t1, t2, t3, t4 = st.tabs(["📉 价格/基差", "🛡️ 对冲波动", "📊 盈亏分布", "🏦 资金监控"])
    # 统一度量：Height 改为 700 
    H = 700 

    with t1:
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货'))
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货'))
        fig1.update_layout(height=H, hovermode="x unified")
        st.plotly_chart(fig1, use_container_width=True)

    with t2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge'], name='未套保', line=dict(color='red', width=1)))
        fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged'], name='已套保', line=dict(color='green', width=3)))
        fig2.update_layout(height=H)
        st.plotly_chart(fig2, use_container_width=True)

    with t3:
        # 密度图增加安全过滤
        d1 = df['Cycle_PnL_NoHedge'].dropna()
        d2 = df['Cycle_PnL_Hedge'].dropna()
        fig3 = ff.create_distplot([d1, d2], ['未套保', '已套保'], show_rug=False, colors=['red', 'green'])
        fig3.update_layout(height=H)
        st.plotly_chart(fig3, use_container_width=True)
        

    with t4:
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity'], name='权益', line=dict(color='black')))
        fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject'], name='补金线', line=dict(dash='dot', color='red')))
        fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw'], name='提盈线', line=dict(dash='dot', color='blue')))
        # 你的原版标记点逻辑
        inj = df[df['Cash_Injection'] > 0]
        fig4.add_trace(go.Scatter(x=inj['Date'], y=inj['Account_Equity'], mode='markers', name='补仓', marker=dict(color='red', symbol='triangle-up', size=12)))
        fig4.update_layout(height=H)
        st.plotly_chart(fig4, use_container_width=True)
        
    st.write("✅ 分析完成，图表已拉大。左侧侧边栏若折叠，请点击左上角箭头。")
else:
    st.info("请上传数据。")






